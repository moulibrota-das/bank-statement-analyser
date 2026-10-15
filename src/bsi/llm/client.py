"""Thin provider-agnostic LLM client. Google Gemini by default; MockClient runs offline.

`complete_json` validates the reply against a pydantic model and retries once on failure."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from bsi.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMStats:
    calls: int = 0
    seconds: float = 0.0


class LLMClient(Protocol):
    name: str
    mock: bool
    stats: LLMStats

    def complete(self, system: str, user: str, task: str = "", schema: type[BaseModel] | None = None,
                 files: list[tuple[bytes, str]] | None = None) -> str: ...


class BaseClient:
    name = "base"
    mock = False

    def __init__(self) -> None:
        self.stats = LLMStats()

    def complete(self, system: str, user: str, task: str = "", schema: type[BaseModel] | None = None,
                 files: list[tuple[bytes, str]] | None = None) -> str:
        start = time.perf_counter()
        try:
            return self._complete(system, user, task, schema, files)
        finally:
            self.stats.calls += 1
            self.stats.seconds += time.perf_counter() - start

    def _complete(self, system: str, user: str, task: str, schema: type[BaseModel] | None,
                  files: list[tuple[bytes, str]] | None) -> str:  # pragma: no cover
        raise NotImplementedError


class GeminiClient(BaseClient):
    name = "gemini"

    def __init__(self, api_key: str, model: str, max_tokens: int = 4096) -> None:
        super().__init__()
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model, self.max_tokens = model, max_tokens

    def _complete(self, system: str, user: str, task: str, schema: type[BaseModel] | None,
                  files: list[tuple[bytes, str]] | None) -> str:
        from google.genai import types

        cfg: dict = {"system_instruction": system, "max_output_tokens": self.max_tokens}
        if schema is not None:  # structured output: Gemini constrains decoding to the pydantic schema
            cfg.update(response_mime_type="application/json", response_schema=schema)
        try:
            contents = user if not files else [
                *[types.Part.from_bytes(data=b, mime_type=m) for b, m in files], user]
            resp = self._client.models.generate_content(
                model=self.model, contents=contents, config=types.GenerateContentConfig(**cfg))
        except Exception as e:  # network/auth/quota: surface uniformly
            raise LLMError(f"{type(e).__name__}: {e}") from e
        return resp.text or ""


Handler = Callable[[str, str, str], str]


class MockClient(BaseClient):
    """Offline client. Pass `responses` (consumed in order, last one repeats) or a `handler(system,
    user, task)` for fixed replies in tests; with neither, a deterministic heuristic stub answers."""

    name = "mock"
    mock = True

    def __init__(self, responses: list[str] | None = None, handler: Handler | None = None) -> None:
        super().__init__()
        self._responses = list(responses) if responses else None
        self._handler = handler
        self.calls: list[tuple[str, str, str]] = []
        self.schemas: list[type[BaseModel] | None] = []
        self.files: list[list[tuple[bytes, str]] | None] = []

    def _complete(self, system: str, user: str, task: str, schema: type[BaseModel] | None,
                  files: list[tuple[bytes, str]] | None) -> str:
        self.calls.append((system, user, task))
        self.schemas.append(schema)
        self.files.append(files)
        if self._responses:
            return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if self._handler:
            return self._handler(system, user, task)
        from bsi.llm.mock import default_mock_reply

        return default_mock_reply(system, user, task)


def make_client(settings: Settings | None = None) -> BaseClient:
    s = settings or get_settings()
    if s.mock_mode:
        return MockClient()
    return GeminiClient(s.gemini_api_key, s.llm_model)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> object:
    m = _FENCE.search(text)
    body = (m.group(1) if m else text).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(body[start:end + 1])


def complete_json(client: LLMClient, system: str, user: str, model: type[T], task: str = "",
                  retries: int = 1, files: list[tuple[bytes, str]] | None = None) -> T:
    prompt, last_err = user, ""
    for _ in range(retries + 1):
        raw = client.complete(system, prompt, task, schema=model, files=files)
        try:
            return model.model_validate(extract_json(raw))
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_err = str(e)[:300]
            prompt = (f"{user}\n\nYour previous reply was invalid ({last_err}). "
                      "Reply again with ONLY valid JSON matching the requested shape.")
    raise LLMError(f"no valid JSON after {retries + 1} attempts: {last_err}")

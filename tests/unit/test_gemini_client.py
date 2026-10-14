"""GeminiClient against a fake SDK transport (no network, no key)."""
import pytest

from bsi.config import Settings
from bsi.llm.client import GeminiClient, LLMError, MockClient, make_client


class _Resp:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, outcome):
        self.outcome, self.kwargs = outcome, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return _Resp(self.outcome)


def _client(monkeypatch, outcome):
    import google.genai as genai

    models = _Models(outcome)
    monkeypatch.setattr(genai, "Client", lambda api_key: type("C", (), {"models": models})())
    return GeminiClient("k", "gemini-2.5-flash"), models


def test_sends_system_prompt_and_returns_text(monkeypatch):
    c, models = _client(monkeypatch, '{"ok": 1}')
    assert c.complete("SYS", "USER", "classify") == '{"ok": 1}'
    assert models.kwargs["model"] == "gemini-2.5-flash" and models.kwargs["contents"] == "USER"
    assert models.kwargs["config"].system_instruction == "SYS"
    assert c.stats.calls == 1 and not c.mock


def test_none_text_becomes_empty_string(monkeypatch):
    c, _ = _client(monkeypatch, None)
    assert c.complete("s", "u") == ""


def test_sdk_errors_become_llm_error(monkeypatch):
    c, _ = _client(monkeypatch, RuntimeError("quota"))
    with pytest.raises(LLMError, match="quota"):
        c.complete("s", "u")


def test_make_client_selects_by_key():
    assert isinstance(make_client(Settings(GEMINI_API_KEY="")), MockClient)
    assert Settings(GEMINI_API_KEY="k", mock=None).mock_mode is False
    assert Settings(GOOGLE_API_KEY="k", mock=None).mock_mode is False
    assert Settings(GEMINI_API_KEY="k", mock=True).mock_mode is True


def test_schema_enables_structured_output(monkeypatch):
    from bsi.classify.llm_classifier import _Response

    c, models = _client(monkeypatch, '{"results": []}')
    c.complete("s", "u", "classify", schema=_Response)
    cfg = models.kwargs["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_schema is _Response


def test_no_schema_means_plain_text(monkeypatch):
    c, models = _client(monkeypatch, "hello")
    c.complete("s", "u")
    assert models.kwargs["config"].response_mime_type is None


def test_complete_json_passes_model_as_schema():
    from pydantic import BaseModel

    from bsi.llm.client import complete_json

    class M(BaseModel):
        x: int

    mock = MockClient(responses=['{"x": 1}'])
    assert complete_json(mock, "s", "u", M).x == 1 and mock.schemas == [M]


def test_all_llm_tasks_request_a_schema_except_free_text_v1():
    from datetime import date

    from bsi.classify.llm_classifier import LLMClassifier
    from bsi.classify.rules import apply_rules
    from tests.conftest_helpers import make_many

    tx = make_many([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    apply_rules(tx)
    m = MockClient()
    LLMClassifier(m, "classify_v4").classify(tx)
    assert m.schemas[0] is not None
    tx2 = make_many([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    apply_rules(tx2)
    m2 = MockClient()
    LLMClassifier(m2, "classify_v1").classify(tx2)
    assert m2.schemas == [None]

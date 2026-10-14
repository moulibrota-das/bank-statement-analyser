"""LLM classification for rows the rules could not resolve.

Only narration, amount, direction, date and parsed channel/counterparty are sent: never account
numbers or holder names. Long digit runs are redacted, and the holder's name (if it appears in a
narration) is replaced by a placeholder."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

from bsi.classify.cache import CachedClass, LLMCache, cache_key
from bsi.classify.rules import is_unresolved
from bsi.llm.client import LLMClient, LLMError, complete_json
from bsi.llm.prompts import Prompt, load_prompt
from bsi.schema import Category, CategorySource, Transaction

CATEGORIES = [c.value for c in Category]
MIN_CONFIDENCE = 0.4
_LONG_DIGITS = re.compile(r"\d{9,}")


class _Result(BaseModel):
    id: int
    category: Category
    confidence: float = Field(0.5, ge=0, le=1)
    rationale: str = ""

    @field_validator("category", mode="before")
    @classmethod
    def _norm(cls, v):
        return v.strip().title() if isinstance(v, str) else v


class _Response(BaseModel):
    results: list[_Result]


@dataclass
class ClassifyStats:
    rows_unresolved: int = 0
    rows_sent: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    failures: int = 0


def sanitize_narration(narration: str, holder: str | None = None) -> str:
    out = _LONG_DIGITS.sub("#", narration)
    if holder:
        for tok in {holder, *[p for p in holder.split() if len(p) > 2]}:
            out = re.sub(re.escape(tok), "ACCOUNT_HOLDER", out, flags=re.IGNORECASE)
    return out


def _item(t: Transaction, prompt: Prompt, holder: str | None) -> dict:
    full = {
        "id": t.idx, "date": t.date.isoformat(), "narration": sanitize_narration(t.narration, holder),
        "amount": str(t.amount), "direction": t.direction.value, "channel": t.channel.value,
        "counterparty": sanitize_narration(t.counterparty, holder) if t.counterparty else None,
        "recurring_hint": "similar amount paid/received roughly monthly" if t.is_recurring else None,
    }
    keep = prompt.fields or list(full)
    return {k: v for k, v in full.items() if k in keep and v is not None}


def _parse_text_category(text: str) -> Category:
    low = text.lower()
    best, pos = Category.OTHER, len(low) + 1
    for c in Category:
        i = low.find(c.value.lower())
        if 0 <= i < pos:
            best, pos = c, i
    return best


class LLMClassifier:
    def __init__(self, client: LLMClient, prompt_version: str = "classify_v4", cache: LLMCache | None = None):
        self.client, self.prompt = client, load_prompt(prompt_version)
        self.cache = cache if cache is not None else LLMCache()

    def classify(self, txns: list[Transaction], holder: str | None = None,
                 only_unresolved: bool = True) -> ClassifyStats:
        stats = ClassifyStats()
        todo = [t for t in txns if (is_unresolved(t) if only_unresolved else True)]
        stats.rows_unresolved = len(todo)
        pending: dict[str | None, list[Transaction]] = {}
        order: list[Transaction] = []  # representative row per cache key (or per keyless row)
        for t in todo:
            key = cache_key(t)
            hit = self.cache.get(key)
            if hit:
                self._apply(t, hit, cached=True)
                stats.cache_hits += 1
                continue
            if key is not None and key in pending:
                pending[key].append(t)  # same counterparty in this run: share one query
                stats.cache_hits += 1
                continue
            pending.setdefault(key if key is not None else f"__row{t.idx}", []).append(t)
            order.append(t)

        size = max(1, self.prompt.batch_size)
        calls_before = self.client.stats.calls
        for i in range(0, len(order), size):
            batch = order[i:i + size]
            stats.rows_sent += len(batch)
            answers = self._ask(batch, holder)
            for t in batch:
                res = answers.get(t.idx)
                if res is None:
                    stats.failures += 1
                    res = CachedClass(Category.OTHER, 0.0, "LLM gave no valid answer")
                key = cache_key(t)
                if res.confidence > 0:
                    self.cache.put(key, res)
                for row in pending.get(key if key is not None else f"__row{t.idx}", [t]):
                    self._apply(row, res, cached=row is not t)
        stats.llm_calls = self.client.stats.calls - calls_before
        return stats

    def _ask(self, batch: list[Transaction], holder: str | None) -> dict[int, CachedClass]:
        items = [_item(t, self.prompt, holder) for t in batch]
        try:
            if self.prompt.output == "text":
                text = " | ".join(f"{it['narration']} | {it['amount']} | {it['direction']}" for it in items)
                raw = self.client.complete(self.prompt.system, self.prompt.render_user(items_text=text), "classify")
                return {batch[0].idx: CachedClass(_parse_text_category(raw), 0.5, raw.strip()[:120])}
            user = self.prompt.render_user(categories=", ".join(CATEGORIES), items_json=json.dumps(items, indent=1))
            resp = complete_json(self.client, self.prompt.system, user, _Response, task="classify")
        except LLMError:
            return {}
        valid = {t.idx for t in batch}
        return {r.id: CachedClass(r.category, r.confidence, r.rationale) for r in resp.results if r.id in valid}

    @staticmethod
    def _apply(t: Transaction, res: CachedClass, cached: bool) -> None:
        cat, conf, why = res.category, res.confidence, res.rationale
        if 0 < conf < MIN_CONFIDENCE and cat is not Category.OTHER:
            cat, why = Category.OTHER, f"low confidence ({conf:.2f}) -> Other; model said {res.category.value}"
        t.category, t.category_confidence = cat, conf
        t.category_source = CategorySource.LLM
        t.category_rationale = (why + " [cached by counterparty]") if cached and why else why or None

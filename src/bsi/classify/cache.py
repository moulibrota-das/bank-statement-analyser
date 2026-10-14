"""Cache of LLM classifications keyed by normalized counterparty (+ direction and a coarse
amount band, so a person's 18,000 rent and 500 lunch share no entry). In-memory by default;
pass a path to persist as JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from bsi.schema import Category, Transaction

BIG = Decimal("10000")


@dataclass
class CachedClass:
    category: Category
    confidence: float
    rationale: str


def cache_key(t: Transaction) -> str | None:
    if not t.counterparty_key:
        return None
    return f"{t.counterparty_key}|{t.direction.value}|{'big' if t.amount >= BIG else 'small'}"


class LLMCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._data: dict[str, CachedClass] = {}
        self.hits = 0
        self.misses = 0
        if path and path.exists():
            for k, v in json.loads(path.read_text()).items():
                self._data[k] = CachedClass(Category(v["category"]), v["confidence"], v["rationale"])

    def get(self, key: str | None) -> CachedClass | None:
        if key is None:
            return None
        hit = self._data.get(key)
        if hit:
            self.hits += 1
        else:
            self.misses += 1
        return hit

    def put(self, key: str | None, value: CachedClass) -> None:
        if key is None:
            return
        self._data[key] = value
        if self.path:
            self.path.write_text(json.dumps(
                {k: {"category": v.category.value, "confidence": v.confidence, "rationale": v.rationale}
                 for k, v in self._data.items()}, indent=2))

    def __len__(self) -> int:
        return len(self._data)

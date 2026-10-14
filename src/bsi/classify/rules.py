"""Rules-first classifier: merchant/keyword map and channel rules. Returns None when
the rules cannot resolve a row (those rows go to recurring evidence, then the LLM)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from bsi.schema import Category, CategorySource, Channel, Direction, Transaction

MERCHANTS_PATH = Path(__file__).parent / "merchants.yaml"


@dataclass
class RuleResult:
    category: Category
    confidence: float
    rationale: str


@lru_cache(maxsize=1)
def _config() -> dict:
    return yaml.safe_load(MERCHANTS_PATH.read_text())


def _has(word: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


def classify_rule(t: Transaction) -> RuleResult | None:
    cfg = _config()
    narr = t.narration.lower()
    key = t.counterparty_key or ""
    direction = "credit" if t.direction is Direction.CREDIT else "debit"

    for cat, words in cfg["keywords"].get(direction, {}).items():
        for w in words:
            if _has(w, narr):
                return RuleResult(Category(cat), 0.95 if cat in ("Salary", "Rent") else 0.9,
                                  f"narration contains '{w}'")

    if key in cfg.get("ambiguous", []):
        return None
    for cat, words in cfg["merchants"].items():
        for w in words:
            if _has(w, key) or _has(w, narr):
                return RuleResult(Category(cat), 0.95, f"known merchant '{w}'")

    rule = cfg.get("channel_rules", {}).get(t.channel.value)
    if rule and t.direction is Direction.DEBIT:
        return RuleResult(Category(rule[0]), float(rule[1]), f"{t.channel.value} channel")
    return None


def apply_rules(txns: list[Transaction]) -> list[Transaction]:
    """Fill category/source/confidence for rule-resolved rows; leave others as unresolved Other@0."""
    for t in txns:
        r = classify_rule(t)
        if r:
            t.category, t.category_confidence = r.category, r.confidence
            t.category_source, t.category_rationale = CategorySource.RULE, r.rationale
        else:
            t.category, t.category_confidence = Category.OTHER, 0.0
            t.category_source, t.category_rationale = CategorySource.RULE, "unresolved"
    return txns


def is_unresolved(t: Transaction) -> bool:
    return t.category_source is CategorySource.RULE and t.category_confidence == 0.0


__all__ = ["RuleResult", "classify_rule", "apply_rules", "is_unresolved", "Channel"]

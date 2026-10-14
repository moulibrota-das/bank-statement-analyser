"""Verify that every ₹ amount and percentage in generated text appears in the computed facts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

_AMOUNT = re.compile(r"(?:₹|Rs\.?|INR)\s?(-?\d[\d,]*(?:\.\d+)?)")
_PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s?%")
_NUM_IN_STR = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class FaithfulnessResult:
    ok: bool
    checked: int
    unsupported: list[str] = field(default_factory=list)


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def _round_to(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _walk(obj, amounts: set[Decimal], percents: set[Decimal]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("pct") or k.endswith("_pct"):
                try:
                    percents.add(Decimal(str(v)))
                except Exception:  # noqa: BLE001
                    pass
            _walk(v, amounts, percents)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, amounts, percents)
    elif isinstance(obj, str):
        for m in _AMOUNT.finditer(obj):
            amounts.add(_dec(m.group(1)))
        for m in _PERCENT.finditer(obj):
            percents.add(_dec(m.group(1)))
    elif isinstance(obj, (int, float, Decimal)) and not isinstance(obj, bool):
        pass  # raw numbers are only trusted via their display strings / pct fields


def allowed_figures(facts: dict) -> tuple[set[Decimal], set[Decimal]]:
    """Amounts come from the ₹ display strings (and amount-valued string fields) inside facts."""
    amounts: set[Decimal] = set()
    percents: set[Decimal] = set()
    _walk(facts, amounts, percents)
    for key in ("amount_values",):
        for v in facts.get(key, []):
            amounts.add(Decimal(str(v)))
    return amounts, percents


def _matches(value: Decimal, allowed: set[Decimal], places: int) -> bool:
    return any(_round_to(a, places) == _round_to(value, places) for a in allowed)


def check_faithfulness(text: str, facts: dict) -> FaithfulnessResult:
    amounts, percents = allowed_figures(facts)
    bad: list[str] = []
    checked = 0
    for m in _AMOUNT.finditer(text):
        checked += 1
        raw = m.group(1).rstrip(".")
        places = len(raw.split(".")[1]) if "." in raw else 0
        if not _matches(_dec(raw), amounts, places):
            bad.append(m.group(0).strip())
    for m in _PERCENT.finditer(text):
        checked += 1
        raw = m.group(1)
        places = len(raw.split(".")[1]) if "." in raw else 0
        if not _matches(_dec(raw), percents, places):
            bad.append(m.group(0).strip())
    return FaithfulnessResult(ok=not bad, checked=checked, unsupported=bad)


def sentence_count(text: str) -> int:
    # '₹1,23,456.00' contains dots; split only on '. ' / '! ' / '? ' followed by a capital/end
    return len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z₹\d])", text.strip()) if s])

"""Money parsing. Decimal only; handles Indian grouping (2,45,000.00), currency
markers (₹, Rs., INR), negatives (-, parentheses) and Dr/Cr suffixes."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from bsi.schema import Direction

_CURRENCY = re.compile(r"₹|\bRs\.?|\bINR\b", re.IGNORECASE)
_DRCR = re.compile(r"^(?P<pre>(?:Dr|Cr)\.?\s+)?(?P<body>.*?)(?P<post>\s*(?:Dr|Cr)\.?)?$", re.IGNORECASE)
_NUMERIC = re.compile(r"^\d+(\.\d+)?$")
_EMPTY = {"", "-", "--", "—", "nil", "na", "n/a"}
_TWO = Decimal("0.01")


def is_blank(text: str | None) -> bool:
    return text is None or text.strip().lower() in _EMPTY


def parse_amount_drcr(text: str) -> tuple[Decimal, Direction | None]:
    """Parse '1,234.50 Dr' -> (Decimal('1234.50'), DEBIT). Sign (-, parens) is folded
    into the returned magnitude's sign only when there is no Dr/Cr marker; i.e. the
    first element is the signed value, the second the explicit direction (or None)."""
    if text is None:
        raise ValueError("amount is None")
    s = text.strip()
    if s.lower() in _EMPTY:
        raise ValueError(f"empty amount: {text!r}")
    m = _DRCR.match(s)
    marker = (m.group("pre") or m.group("post") or "").strip(" .").lower()
    s = m.group("body").strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = _CURRENCY.sub("", s).strip()
    if s.startswith("-") or s.endswith("-"):
        negative, s = True, s.strip("-")
    s = s.lstrip("+").replace(",", "").replace(" ", "")
    if not _NUMERIC.match(s):
        raise ValueError(f"not a valid amount: {text!r}")
    try:
        value = Decimal(s)
    except InvalidOperation as e:  # pragma: no cover - guarded by regex
        raise ValueError(f"not a valid amount: {text!r}") from e
    if value != value.quantize(_TWO):
        raise ValueError(f"more than 2 decimal places: {text!r}")
    value = value.quantize(_TWO)
    if negative:
        value = -value
    direction = {"dr": Direction.DEBIT, "cr": Direction.CREDIT}.get(marker)
    return value, direction


def parse_money(text: str) -> Decimal:
    """Signed Decimal. A trailing 'Dr' makes the value negative (e.g. overdrawn balance)."""
    value, direction = parse_amount_drcr(text)
    if direction is Direction.DEBIT:
        return -abs(value)
    return value


def try_parse_money(text: str | None) -> Decimal | None:
    if is_blank(text):
        return None
    try:
        return parse_money(text)  # type: ignore[arg-type]
    except ValueError:
        return None


MONEY_TOKEN = re.compile(r"^(?:₹|Rs\.?|INR)?-?\(?\d[\d,]*\.\d{2}\)?-?$", re.IGNORECASE)


def looks_like_money(token: str) -> bool:
    return bool(MONEY_TOKEN.match(token.strip()))


def is_round_amount(value: Decimal, unit: int = 1000) -> bool:
    return value > 0 and value % unit == 0

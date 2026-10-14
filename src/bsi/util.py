from __future__ import annotations

from decimal import Decimal


def fmt_inr(value: Decimal | int | str) -> str:
    """Indian-grouped rupee string: Decimal('245000') -> '₹2,45,000.00'."""
    d = Decimal(value).quantize(Decimal("0.01"))
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    return f"{sign}₹{whole}.{frac}"

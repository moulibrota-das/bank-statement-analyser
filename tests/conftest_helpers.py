from __future__ import annotations

from datetime import date
from decimal import Decimal

from bsi.enrich.narration import enrich
from bsi.schema import Direction, Transaction


def make(narr: str, amount: str, direction: str = "debit", day: date | None = None, idx: int = 0,
         balance: str | None = None) -> Transaction:
    t = Transaction(idx=idx, date=day or date(2024, 3, 5), narration=narr, amount=Decimal(amount),
                    direction=Direction(direction), balance=Decimal(balance) if balance else None)
    return enrich([t])[0]


def make_many(rows: list[tuple]) -> list[Transaction]:
    """rows: (narration, amount, direction, date)"""
    out = [make(n, a, d, dt, idx=i) for i, (n, a, d, dt) in enumerate(rows)]
    return out

"""Recurring-payment detection (same counterparty, similar amount, roughly monthly) and
the evidence-based category boosts it enables."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from bsi.classify.rules import is_unresolved
from bsi.schema import Category, CategorySource, Channel, Direction, RecurringPayment, Transaction

AMOUNT_TOL = Decimal("0.05")
MIN_DAYS, MAX_DAYS = 24, 37


@dataclass
class RecurringGroup:
    key: str
    direction: Direction
    idxs: list[int]
    typical: Decimal


def detect_recurring(txns: list[Transaction]) -> list[RecurringGroup]:
    buckets: dict[tuple[str, Direction], list[Transaction]] = {}
    for t in txns:
        if t.counterparty_key and t.channel is not Channel.ATM:
            buckets.setdefault((t.counterparty_key, t.direction), []).append(t)
    groups: list[RecurringGroup] = []
    for (key, direction), items in buckets.items():
        items = sorted(items, key=lambda t: (t.date, t.idx))
        used: set[int] = set()
        for anchor in items:
            if anchor.idx in used:
                continue
            tol = anchor.amount * AMOUNT_TOL
            cluster = [t for t in items if abs(t.amount - anchor.amount) <= tol and t.idx not in used]
            chain = [cluster[0]]
            for t in cluster[1:]:
                gap = (t.date - chain[-1].date).days
                if MIN_DAYS <= gap <= MAX_DAYS:
                    chain.append(t)
            if len(chain) >= 2:
                used.update(t.idx for t in chain)
                groups.append(RecurringGroup(key, direction, [t.idx for t in chain],
                                             Decimal(str(median(t.amount for t in chain))).quantize(Decimal("0.01"))))
    return groups


def apply_recurring(txns: list[Transaction], groups: list[RecurringGroup]) -> None:
    """Mark recurring rows and strengthen Rent/Salary/Utilities for unresolved ones."""
    by_idx = {t.idx: t for t in txns}
    for g in groups:
        members = [by_idx[i] for i in g.idxs]
        for t in members:
            t.is_recurring = True
        for t in members:
            if not is_unresolved(t):
                continue
            n = len(members)
            if g.direction is Direction.CREDIT and t.amount >= 20000 and t.channel in (
                    Channel.NEFT, Channel.RTGS, Channel.IMPS, Channel.ACH):
                cat, why = Category.SALARY, f"recurring monthly credit ({n}x) of similar size"
            elif g.direction is Direction.DEBIT and t.amount >= 8000 and t.channel in (
                    Channel.UPI, Channel.NEFT, Channel.IMPS, Channel.CHQ):
                cat, why = Category.RENT, f"recurring monthly payment ({n}x) of similar size to the same payee"
            elif g.direction is Direction.DEBIT and t.channel is Channel.ACH:
                cat, why = Category.UTILITIES, f"recurring auto-debit ({n}x) of similar size"
            else:
                continue
            t.category, t.category_confidence = cat, 0.8
            t.category_source, t.category_rationale = CategorySource.RULE, why


def to_payments(txns: list[Transaction], groups: list[RecurringGroup]) -> list[RecurringPayment]:
    by_idx = {t.idx: t for t in txns}
    out = []
    for g in groups:
        first = by_idx[g.idxs[0]]
        out.append(RecurringPayment(counterparty=first.counterparty or g.key, typical_amount=g.typical,
                                    occurrences=len(g.idxs), direction=g.direction, category=first.category))
    return sorted(out, key=lambda r: r.typical_amount, reverse=True)

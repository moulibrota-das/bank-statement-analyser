"""Balance reconciliation. Mismatches are reported, never hidden or auto-corrected."""
from __future__ import annotations

from decimal import Decimal

from bsi.schema import (
    Direction,
    ReconciliationIssue,
    ReconciliationResult,
    StatementMeta,
    Transaction,
)

ZERO = Decimal("0.00")


def _signed(t: Transaction) -> Decimal:
    return t.amount if t.direction is Direction.CREDIT else -t.amount


def reconcile(meta: StatementMeta, txns: list[Transaction]) -> ReconciliationResult:
    credits = sum((t.amount for t in txns if t.direction is Direction.CREDIT), ZERO)
    debits = sum((t.amount for t in txns if t.direction is Direction.DEBIT), ZERO)
    issues: list[ReconciliationIssue] = []
    rows_checked = 0

    opening = meta.opening_balance
    if opening is None and txns and txns[0].balance is not None:
        opening = txns[0].balance - _signed(txns[0])  # derived; first row then trivially ok

    prev = opening
    for t in txns:
        if t.balance is None:
            if any(x.balance is not None for x in txns):
                issues.append(ReconciliationIssue(
                    idx=t.idx, kind="missing_balance",
                    message=f"row {t.idx} has no running balance"))
            if prev is not None:
                prev = prev + _signed(t)  # carry its amount, so the next printed balance is still checkable
            continue
        if prev is not None:
            expected = prev + _signed(t)
            rows_checked += 1
            if expected != t.balance:
                issues.append(ReconciliationIssue(
                    idx=t.idx, kind="running_balance", expected=expected, actual=t.balance,
                    message=(f"row {t.idx} ({t.date}): previous balance {prev} "
                             f"{'+' if t.direction is Direction.CREDIT else '-'} {t.amount} "
                             f"= {expected}, but statement shows {t.balance}")))
        prev = t.balance  # compare against the *printed* balance so one bad row is one issue

    expected_closing = opening + credits - debits if opening is not None else None
    if expected_closing is not None and meta.closing_balance is not None \
            and expected_closing != meta.closing_balance:
        issues.append(ReconciliationIssue(
            kind="total_mismatch", expected=expected_closing, actual=meta.closing_balance,
            message=(f"opening {opening} + credits {credits} - debits {debits} = "
                     f"{expected_closing}, but statement closing balance is {meta.closing_balance}")))

    return ReconciliationResult(
        passed=not issues, opening=opening, total_credits=credits, total_debits=debits,
        expected_closing=expected_closing, stated_closing=meta.closing_balance,
        rows_checked=rows_checked, issues=issues,
    )

"""Rule-based anomaly detectors. Each returns AnomalyFlag(code, severity, reason).
Thresholds live in `Thresholds` so they are explicit and testable."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from bsi.schema import AnomalyCode, AnomalyFlag, Category, Channel, Direction, Severity, Transaction
from bsi.util import fmt_inr

BOUNCE_RE = re.compile(
    r"(CHQ|CHEQUE|ECS|NACH|ACH|INWARD)[^/]*\b(RTN|RETURN|RET)\b|BOUNCE|DISHON|INSUFFICIENT|PENALTY|MIN(IMUM)? BAL",
    re.IGNORECASE)


@dataclass
class Thresholds:
    large_amount: Decimal = Decimal("25000")      # "large" for new-payee / round / pass-through checks
    round_unit: int = 5000                        # multiple that counts as a round number
    outlier_multiple: Decimal = Decimal("3")      # x category median
    outlier_z: float = 3.5                        # robust (MAD) z-score
    outlier_min_amount: Decimal = Decimal("5000")
    outlier_min_samples: int = 5
    duplicate_window_days: int = 2
    pass_through_days: int = 3
    pass_through_ratio: Decimal = Decimal("0.95")  # debit >= 95% of the credit
    low_balance: Decimal = Decimal("1000")
    cash_window_days: int = 7
    cash_window_total: Decimal = Decimal("20000")


def _exempt(t: Transaction) -> bool:
    """Expected-large payments: recurring, salary/rent, and ACH auto-debits (standing instructions)."""
    return t.is_recurring or t.category in (Category.SALARY, Category.RENT) or t.channel is Channel.ACH


def detect_amount_outliers(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    by_cat: dict[Category, list[Transaction]] = defaultdict(list)
    for t in txns:
        if t.direction is Direction.DEBIT:
            by_cat[t.category].append(t)
    flags = []
    for cat, items in by_cat.items():
        if cat in (Category.SALARY, Category.RENT, Category.OTHER) or len(items) < th.outlier_min_samples:
            continue
        amounts = [float(t.amount) for t in items]
        med = median(amounts)
        mad = median(abs(a - med) for a in amounts)
        for t in items:
            if _exempt(t) or t.amount < th.outlier_min_amount:
                continue
            z = 0.6745 * (float(t.amount) - med) / mad if mad else float("inf")
            if float(t.amount) >= float(th.outlier_multiple) * med and z > th.outlier_z:
                flags.append(AnomalyFlag(
                    code=AnomalyCode.AMOUNT_OUTLIER, severity=Severity.MEDIUM, txn_idx=[t.idx],
                    reason=(f"{fmt_inr(t.amount)} to {t.counterparty or 'unknown'} is {float(t.amount) / med:.1f}x "
                            f"the usual {cat.value} payment (median {fmt_inr(Decimal(str(med)))})")))
    return flags


def detect_new_payee_large(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    seen: set[str] = set()
    flags = []
    for t in txns:  # chronological
        key = t.counterparty_key
        if t.direction is Direction.DEBIT and key and key not in seen and t.amount >= th.large_amount \
                and not _exempt(t) and t.channel is not Channel.ATM:
            flags.append(AnomalyFlag(
                code=AnomalyCode.NEW_PAYEE_LARGE, severity=Severity.HIGH, txn_idx=[t.idx],
                reason=f"{fmt_inr(t.amount)} paid to {t.counterparty}, a payee not seen earlier in this statement"))
        if key:
            seen.add(key)
    return flags


def detect_round_large(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    return [
        AnomalyFlag(code=AnomalyCode.ROUND_NUMBER_LARGE, severity=Severity.MEDIUM, txn_idx=[t.idx],
                    reason=f"Large round-number payment of {fmt_inr(t.amount)} to {t.counterparty or 'unknown'}")
        for t in txns
        if t.direction is Direction.DEBIT and t.amount >= th.large_amount
        and t.amount % th.round_unit == 0 and not _exempt(t)
    ]


def detect_duplicates(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    flags = []
    last: dict[tuple, Transaction] = {}
    for t in txns:
        if t.direction is not Direction.DEBIT or t.channel is Channel.ATM or not t.counterparty_key:
            continue
        k = (t.counterparty_key, t.amount)
        prev = last.get(k)
        if prev and (t.date - prev.date).days <= th.duplicate_window_days and not t.is_recurring:
            flags.append(AnomalyFlag(
                code=AnomalyCode.DUPLICATE, severity=Severity.MEDIUM, txn_idx=[prev.idx, t.idx],
                reason=(f"{fmt_inr(t.amount)} to {t.counterparty} charged twice within "
                        f"{max((t.date - prev.date).days, 0)} day(s) ({prev.date} and {t.date})")))
        last[k] = t
    return flags


def detect_pass_through(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    flags = []
    for c in txns:
        if c.direction is not Direction.CREDIT or c.amount < th.large_amount or _exempt(c):
            continue
        for d in txns:
            gap = (d.date - c.date).days
            if d.direction is Direction.DEBIT and 0 <= gap <= th.pass_through_days and d.idx > c.idx \
                    and th.pass_through_ratio * c.amount <= d.amount <= c.amount * Decimal("1.02"):
                flags.append(AnomalyFlag(
                    code=AnomalyCode.PASS_THROUGH, severity=Severity.HIGH, txn_idx=[c.idx, d.idx],
                    reason=(f"{fmt_inr(c.amount)} credited on {c.date} and {fmt_inr(d.amount)} sent out "
                            f"{gap} day(s) later: money passing straight through")))
                break
    return flags


def detect_low_balance(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    flags, in_dip = [], False
    for t in txns:
        if t.balance is None:
            continue
        low = t.balance < th.low_balance
        if low and not in_dip:
            neg = t.balance < 0
            flags.append(AnomalyFlag(
                code=AnomalyCode.LOW_BALANCE, severity=Severity.HIGH if neg else Severity.MEDIUM, txn_idx=[t.idx],
                reason=f"Balance fell to {fmt_inr(t.balance)} on {t.date}" + (" (overdrawn)" if neg else "")))
        in_dip = low
    return flags


def detect_bounce(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    return [
        AnomalyFlag(code=AnomalyCode.BOUNCE_PENALTY, severity=Severity.HIGH, txn_idx=[t.idx],
                    reason=f"Bounce/penalty charge of {fmt_inr(t.amount)} on {t.date}: '{t.narration[:50]}'")
        for t in txns if t.direction is Direction.DEBIT and BOUNCE_RE.search(t.narration)
    ]


def detect_cash_spike(txns: list[Transaction], th: Thresholds) -> list[AnomalyFlag]:
    atm = [t for t in txns if t.channel is Channel.ATM and t.direction is Direction.DEBIT]
    flags, i = [], 0
    while i < len(atm):
        window = [t for t in atm[i:] if (t.date - atm[i].date).days <= th.cash_window_days]
        total = sum((t.amount for t in window), Decimal(0))
        if total >= th.cash_window_total and len(window) >= 2:
            flags.append(AnomalyFlag(
                code=AnomalyCode.CASH_SPIKE, severity=Severity.MEDIUM, txn_idx=[t.idx for t in window],
                reason=f"{len(window)} ATM withdrawals totalling {fmt_inr(total)} within {th.cash_window_days} days"))
            i += len(window)
        else:
            i += 1
    return flags


DETECTORS = [detect_amount_outliers, detect_new_payee_large, detect_round_large, detect_duplicates,
             detect_pass_through, detect_low_balance, detect_bounce, detect_cash_spike]


def detect_all(txns: list[Transaction], th: Thresholds | None = None) -> list[AnomalyFlag]:
    th = th or Thresholds()
    txns = sorted(txns, key=lambda t: (t.date, t.idx))
    flags = [f for d in DETECTORS for f in d(txns, th)]
    return sorted(flags, key=lambda f: (f.txn_idx[0], f.code.value))

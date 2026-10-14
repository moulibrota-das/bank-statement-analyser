"""Turn raw string cells (from PDF or tabular sources) into typed Transactions."""
from __future__ import annotations

from decimal import Decimal

from bsi.ingest.layouts import Layout
from bsi.parse.amounts import is_blank, parse_amount_drcr, parse_money
from bsi.parse.dates import parse_date
from bsi.schema import Direction, Transaction


def _resolve_amount(row: dict[str, str], layout: Layout) -> tuple[Decimal, Direction] | None:
    style = layout.amount_style
    if style == "split":
        d, c = row.get("debit"), row.get("credit")
        has_d, has_c = not is_blank(d), not is_blank(c)
        if has_d and has_c:
            dv, cv = parse_money(d), parse_money(c)  # type: ignore[arg-type]
            if dv == 0:
                return cv, Direction.CREDIT
            if cv == 0:
                return dv, Direction.DEBIT
            raise ValueError("both debit and credit populated")
        if has_d:
            return abs(parse_money(d)), Direction.DEBIT  # type: ignore[arg-type]
        if has_c:
            return abs(parse_money(c)), Direction.CREDIT  # type: ignore[arg-type]
        return None
    amount = row.get("amount")
    if is_blank(amount):
        return None
    value, direction = parse_amount_drcr(amount)  # type: ignore[arg-type]
    if style == "suffix":
        marker = direction
        if marker is None and not is_blank(row.get("drcr")):
            marker = {"dr": Direction.DEBIT, "cr": Direction.CREDIT}.get(
                row["drcr"].strip(" .").lower())
        if marker is None:
            raise ValueError(f"missing Dr/Cr marker: {amount!r}")
        return abs(value), marker
    # signed
    credit_positive = layout.signed_credit_positive
    is_credit = (value > 0) == credit_positive
    return abs(value), Direction.CREDIT if is_credit else Direction.DEBIT


def build_transactions(rows: list[dict[str, str]], layout: Layout) -> tuple[list[Transaction], list[str]]:
    txns: list[Transaction] = []
    warnings: list[str] = []
    for n, row in enumerate(rows, start=1):
        try:
            when = parse_date(row["date"], layout.date_formats)
            resolved = _resolve_amount(row, layout)
            if resolved is None:
                warnings.append(f"row {n}: no amount (date {row['date']}); skipped")
                continue
            amount, direction = resolved
            balance = None
            if not is_blank(row.get("balance")):
                balance = parse_money(row["balance"])
            ref = (row.get("ref") or "").strip() or None
            txns.append(Transaction(
                idx=len(txns), date=when, narration=" ".join(row.get("narration", "").split()),
                amount=amount, direction=direction, balance=balance, reference=ref))
        except (ValueError, KeyError) as e:
            warnings.append(f"row {n}: could not parse ({e}); skipped")
    return txns, warnings

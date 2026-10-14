from datetime import date
from decimal import Decimal as D

from bsi.schema import Direction, StatementMeta, Transaction
from bsi.validate.reconciliation import reconcile


def tx(i, amt, direction, bal):
    return Transaction(idx=i, date=date(2024, 1, i + 1), narration="x", amount=D(amt),
                       direction=direction, balance=D(bal))


def good():
    return [tx(0, "1000", Direction.CREDIT, "11000"), tx(1, "400", Direction.DEBIT, "10600"),
            tx(2, "100", Direction.DEBIT, "10500")]


META = StatementMeta(opening_balance=D("10000"), closing_balance=D("10500"))


def test_clean_statement_passes():
    r = reconcile(META, good())
    assert r.passed and r.issues == [] and r.rows_checked == 3
    assert r.total_credits == D("1000") and r.total_debits == D("500")
    assert r.expected_closing == D("10500")


def test_corrupted_row_is_reported_not_hidden():
    rows = good()
    rows[1] = tx(1, "450", Direction.DEBIT, "10600")  # amount corrupted, balance untouched
    r = reconcile(META, rows)
    assert not r.passed
    kinds = {(i.kind, i.idx) for i in r.issues}
    assert ("running_balance", 1) in kinds and ("total_mismatch", None) in kinds
    bad = next(i for i in r.issues if i.idx == 1)
    assert bad.expected == D("10550") and bad.actual == D("10600")
    assert len([i for i in r.issues if i.kind == "running_balance"]) == 1  # no cascade


def test_wrong_closing_balance():
    r = reconcile(StatementMeta(opening_balance=D("10000"), closing_balance=D("9999")), good())
    assert not r.passed and r.issues[0].kind == "total_mismatch"


def test_opening_derived_from_first_row_when_missing():
    r = reconcile(StatementMeta(closing_balance=D("10500")), good())
    assert r.passed and r.opening == D("10000")


def test_missing_running_balance_flagged():
    rows = good()
    rows[1] = Transaction(**{**rows[1].model_dump(), "balance": None})
    r = reconcile(META, rows)
    assert any(i.kind == "missing_balance" and i.idx == 1 for i in r.issues)

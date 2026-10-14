import json
from decimal import Decimal

import pytest

from bsi.analytics.summaries import compute_analytics
from bsi.classify.recurring import apply_recurring, detect_recurring, to_payments
from bsi.classify.rules import apply_rules
from bsi.enrich.narration import enrich
from bsi.ingest.loader import load_statement
from tests.conftest import SAMPLES


@pytest.mark.parametrize("name", ["nimbus_a_2024_q1", "nimbus_a_2024_03"])
def test_totals_match_ground_truth(name):
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    path = SAMPLES / f"{name}.pdf"
    tx = enrich(load_statement(path.read_bytes(), path.name).transactions)
    apply_rules(tx)
    groups = detect_recurring(tx)
    apply_recurring(tx, groups)
    a = compute_analytics(tx, to_payments(tx, groups))
    assert str(a.total_credits) == labels["totals"]["total_credits"]
    assert str(a.total_debits) == labels["totals"]["total_debits"]
    assert str(a.net) == labels["totals"]["net"]
    assert sum(m.debits for m in a.monthly) == a.total_debits
    assert sum(c.total for c in a.spend_by_category) == a.total_debits
    assert all(isinstance(c.total, Decimal) for c in a.spend_by_category)


def test_two_month_statement_detects_salary_and_rent_recurring():
    path = SAMPLES / "nimbus_a_2024_q1.pdf"
    tx = enrich(load_statement(path.read_bytes(), path.name).transactions)
    apply_rules(tx)
    groups = detect_recurring(tx)
    apply_recurring(tx, groups)
    names = {p.counterparty for p in to_payments(tx, groups)}
    assert {"TECHNOVA SOLUTIONS PVT LTD", "RAMESH KUMAR"} <= names
    a = compute_analytics(tx, to_payments(tx, groups))
    assert [m.month for m in a.monthly] == ["2024-01", "2024-02"]
    assert a.largest_transactions[0].amount == max(t.amount for t in tx)
    assert a.spend_by_category == sorted(a.spend_by_category, key=lambda c: c.total, reverse=True)
    assert abs(sum(c.pct_of_debits for c in a.spend_by_category) - 100) < 0.5

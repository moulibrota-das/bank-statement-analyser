from datetime import date
from decimal import Decimal

from bsi.classify.recurring import apply_recurring, detect_recurring, to_payments
from bsi.classify.rules import apply_rules
from bsi.schema import Category, CategorySource
from tests.conftest_helpers import make_many

RENT = "UPI/{}/SURESH PATEL/suresh@ybl/Payment from phone"


def rows(days_amounts, narr=RENT, direction="debit"):
    return make_many([(narr.format(f"4000000000{i:02d}"), a, direction, d) for i, (d, a) in enumerate(days_amounts)])


def test_monthly_same_payee_is_recurring():
    tx = rows([(date(2024, 1, 5), "18000"), (date(2024, 2, 5), "18000"), (date(2024, 3, 5), "18000")])
    groups = detect_recurring(tx)
    assert len(groups) == 1 and groups[0].idxs == [0, 1, 2] and groups[0].typical == Decimal("18000.00")


def test_similar_amount_within_5_percent_counts():
    tx = rows([(date(2024, 1, 5), "1000"), (date(2024, 2, 5), "1040")])
    assert len(detect_recurring(tx)) == 1


def test_different_amounts_or_gaps_are_not_recurring():
    assert detect_recurring(rows([(date(2024, 1, 5), "1000"), (date(2024, 2, 5), "2500")])) == []
    assert detect_recurring(rows([(date(2024, 1, 5), "1000"), (date(2024, 1, 20), "1000")])) == []
    assert detect_recurring(rows([(date(2024, 1, 5), "1000")])) == []


def test_recurring_person_payment_becomes_rent():
    tx = rows([(date(2024, 1, 5), "18000"), (date(2024, 2, 5), "18000")])
    apply_rules(tx)
    apply_recurring(tx, detect_recurring(tx))
    assert all(t.category is Category.RENT and t.is_recurring and t.category_source is CategorySource.RULE
               for t in tx)
    assert "recurring" in tx[0].category_rationale


def test_recurring_unfamiliar_employer_credit_becomes_salary():
    tx = rows([(date(2024, 1, 1), "72000"), (date(2024, 2, 1), "72000")],
              narr="NEFT-X{}-ZENITH ANALYTICS LLP-PAY", direction="credit")
    apply_rules(tx)
    apply_recurring(tx, detect_recurring(tx))
    assert all(t.category is Category.SALARY for t in tx)


def test_single_month_is_not_boosted():
    tx = rows([(date(2024, 1, 5), "18000")])
    apply_rules(tx)
    apply_recurring(tx, detect_recurring(tx))
    assert tx[0].category is Category.OTHER and not tx[0].is_recurring


def test_to_payments():
    tx = rows([(date(2024, 1, 5), "18000"), (date(2024, 2, 5), "18000")])
    apply_rules(tx)
    groups = detect_recurring(tx)
    apply_recurring(tx, groups)
    p = to_payments(tx, groups)[0]
    assert p.counterparty == "SURESH PATEL" and p.occurrences == 2 and p.category is Category.RENT

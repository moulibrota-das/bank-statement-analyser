import pytest

from bsi.classify.rules import apply_rules, classify_rule, is_unresolved
from bsi.schema import Category, CategorySource
from tests.conftest_helpers import make


@pytest.mark.parametrize("narr,amount,direction,expected", [
    ("NEFT-NIMBN24010186172-TECHNOVA SOLUTIONS PVT LTD-SALARY JAN24", "85000", "credit", Category.SALARY),
    ("UPI/412345678901/RAMESH KUMAR/ramesh@okicici/Rent JAN", "22000", "debit", Category.RENT),
    ("UPI/412345678901/SWIGGY/swiggy@icici/Order", "452", "debit", Category.FOOD),
    ("UPI/412345678901/ZOMATO/zomato@hdfcbank/Order", "380", "debit", Category.FOOD),
    ("ACH D-BESCOM BANGALORE-48291034", "1450", "debit", Category.UTILITIES),
    ("UPI/412345678901/AIRTEL/airtel@icici/Broadband bill", "1099", "debit", Category.UTILITIES),
    ("UPI/412345678901/RELIANCE JIO/jio@axisbank/Recharge", "349", "debit", Category.UTILITIES),
    ("UPI/412345678901/IRCTC/irctc@sbi/Ticket", "1250", "debit", Category.TRAVEL),
    ("UPI/412345678901/UBER INDIA/uber@axisbank/Ride", "310", "debit", Category.TRAVEL),
    ("POS 4821 MAKEMYTRIP INDIA MUMBAI", "6400", "debit", Category.TRAVEL),
    ("UPI/412345678901/FLIPKART/flipkart@axb/Purchase", "2199", "debit", Category.SHOPPING),
    ("UPI/412345678901/MYNTRA/myntra@ybl/Purchase", "1799", "debit", Category.SHOPPING),
    ("UPI/412345678901/AMAZON PAY/amazonpay@apl/Purchase", "999", "debit", Category.SHOPPING),
    ("ATM-CASH WDL/BENGALURU ATM 1234/556677", "5000", "debit", Category.TRANSFERS),
    ("CHQ RTN CHG-INSUFFICIENT FUNDS-214279", "590", "debit", Category.OTHER),
])
def test_rules_resolve_clear_cases(narr, amount, direction, expected):
    t = make(narr, amount, direction)
    r = classify_rule(t)
    assert r is not None and r.category is expected and r.confidence >= 0.8 and r.rationale


def test_refund_and_reversal_follow_the_merchant():
    assert classify_rule(make("UPI/412345678901/AMAZON PAY/amazonpay@apl/REFUND", "1299", "credit")).category \
        is Category.SHOPPING
    assert classify_rule(make("REV-UPI/412345678901/SWIGGY/swiggy@icici", "540", "credit")).category is Category.FOOD


def test_word_boundary_rent_does_not_match_current():
    assert classify_rule(make("UPI/412345678901/CURRENT ACCOUNT FEE/x@ybl/fee", "100")) is None


def test_salary_keyword_only_applies_to_credits():
    assert classify_rule(make("NEFT-X123-ACME-SALARY ADVANCE REPAY", "5000", "debit")) is None


def test_apply_rules_sets_source_and_confidence():
    t = apply_rules([make("UPI/412345678901/SWIGGY/swiggy@icici/Order", "452")])[0]
    assert t.category_source is CategorySource.RULE and t.category_confidence == 0.95
    assert not is_unresolved(t)


def test_unknown_rows_are_left_unresolved_for_the_llm():
    t = apply_rules([make("NEFT-X1-XYZ ENTERPRISES-INV 2231", "8400")])[0]
    assert is_unresolved(t) and t.category is Category.OTHER and t.category_confidence == 0.0


def test_plain_amazon_is_left_ambiguous():
    assert classify_rule(make("UPI/412345678901/AMAZON/amazon@apl/Purchase", "2310")) is None

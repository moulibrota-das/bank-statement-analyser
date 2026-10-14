from datetime import date
from decimal import Decimal

import pytest

from bsi.parse.amounts import (
    is_round_amount,
    looks_like_money,
    parse_amount_drcr,
    parse_money,
    try_parse_money,
)
from bsi.parse.dates import parse_date, try_parse_date
from bsi.schema import Direction


@pytest.mark.parametrize("text,expected", [
    ("₹2,45,000.00", "245000.00"),
    ("Rs. 1,23,45,678.50", "12345678.50"),
    ("INR 999", "999.00"),
    ("1,234.5", "1234.50"),
    ("(1,500.00)", "-1500.00"),
    ("-250.75", "-250.75"),
    ("250.75-", "-250.75"),
    ("  42 ", "42.00"),
    ("12,500.00 Cr", "12500.00"),
    ("12,500.00 Dr", "-12500.00"),
])
def test_parse_money(text, expected):
    value = parse_money(text)
    assert isinstance(value, Decimal)
    assert value == Decimal(expected)


def test_money_is_never_float_imprecise():
    assert parse_money("0.10") + parse_money("0.20") == Decimal("0.30")


@pytest.mark.parametrize("text", ["abc", "12.345", "1.2.3", "", "-", "₹"])
def test_parse_money_rejects(text):
    with pytest.raises(ValueError):
        parse_money(text)


def test_try_parse_money_blank():
    assert try_parse_money("") is None
    assert try_parse_money("--") is None
    assert try_parse_money(None) is None
    assert try_parse_money("1,000.00") == Decimal("1000.00")


def test_drcr_direction():
    assert parse_amount_drcr("500.00 Dr") == (Decimal("500.00"), Direction.DEBIT)
    assert parse_amount_drcr("500.00 CR") == (Decimal("500.00"), Direction.CREDIT)
    assert parse_amount_drcr("500.00") == (Decimal("500.00"), None)


def test_looks_like_money():
    assert looks_like_money("1,23,456.00")
    assert looks_like_money("₹500.00")
    assert not looks_like_money("412345678901")
    assert not looks_like_money("05/03/24")


def test_round_amount():
    assert is_round_amount(Decimal("100000.00"))
    assert not is_round_amount(Decimal("74500.00"))


@pytest.mark.parametrize("text,expected", [
    ("05/03/24", date(2024, 3, 5)),
    ("05/03/2024", date(2024, 3, 5)),
    ("5-Mar-2024", date(2024, 3, 5)),
    ("05 Mar 24", date(2024, 3, 5)),
    ("2024-03-05", date(2024, 3, 5)),
    ("05.03.2024", date(2024, 3, 5)),
    ("05/03/2024 14:22:10", date(2024, 3, 5)),
    ("Mar 5, 2024", date(2024, 3, 5)),
    ("5 Sept 2024", date(2024, 9, 5)),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_date_is_day_first():
    assert parse_date("01/02/2024") == date(2024, 2, 1)


def test_date_rejects_garbage():
    with pytest.raises(ValueError):
        parse_date("not a date")
    assert try_parse_date("31/02/2024") is None

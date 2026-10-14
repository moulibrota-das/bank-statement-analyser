from datetime import date
from decimal import Decimal

from bsi.parse.metadata import extract_metadata, mask_account

TEXT = """Nimbus Bank
Account Holder: AARAV MEHTA
Account Number: 50100234567890
IFSC: NIMB0001669
Branch: Indiranagar, Bengaluru
Statement Period: 01/01/2024 to 29/02/2024
Opening Balance: Rs. 60,000.00
Closing Balance: Rs. 9,147.00
"""


def test_extract_all_fields():
    m = extract_metadata(TEXT)
    assert m.account_holder == "AARAV MEHTA"
    assert m.ifsc == "NIMB0001669"
    assert m.branch == "Indiranagar, Bengaluru"
    assert m.period_start == date(2024, 1, 1) and m.period_end == date(2024, 2, 29)
    assert m.opening_balance == Decimal("60000.00")
    assert m.closing_balance == Decimal("9147.00")


def test_account_number_is_masked_everywhere():
    m = extract_metadata(TEXT)
    assert m.account_number_masked == "XXXXXXXXXX7890"
    assert "50100234567890" not in m.model_dump_json()
    assert "5010023456" not in m.model_dump_json()


def test_mask_account_variants():
    assert mask_account("1234") == "XXXX"
    assert mask_account("1234 5678 9012") == "XXXXXXXX9012"
    assert mask_account("XXXXXX1234") == "XXXXXX1234"


def test_missing_fields_are_none():
    m = extract_metadata("nothing useful here")
    assert m.account_number_masked is None and m.opening_balance is None


def test_overdrawn_closing_balance():
    m = extract_metadata("Closing Balance: 1,200.00 Dr")
    assert m.closing_balance == Decimal("-1200.00")

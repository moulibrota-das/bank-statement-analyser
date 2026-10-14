import pytest

from bsi.enrich.narration import normalize_key, parse_narration
from bsi.schema import Channel


def test_upi():
    i = parse_narration("UPI/412345678901/SWIGGY/swiggy@icici/Order")
    assert (i.channel, i.counterparty, i.handle, i.reference, i.key) == (
        Channel.UPI, "SWIGGY", "swiggy@icici", "412345678901", "swiggy")


def test_upi_person():
    i = parse_narration("UPI/088982673821/SURESH PATEL/suresh@ybl/Payment from phone")
    assert i.counterparty == "SURESH PATEL" and i.key == "suresh patel" and i.handle == "suresh@ybl"


def test_neft():
    i = parse_narration("NEFT-NIMBN24010186172-TECHNOVA SOLUTIONS PVT LTD-SALARY JAN24")
    assert i.channel is Channel.NEFT and i.counterparty == "TECHNOVA SOLUTIONS PVT LTD"
    assert i.reference == "NIMBN24010186172" and i.key == "technova"


def test_imps():
    i = parse_narration("IMPS/402312345678/NEHA SHARMA/FUND TRANSFER")
    assert i.channel is Channel.IMPS and i.counterparty == "NEHA SHARMA" and i.reference == "402312345678"


def test_rtgs():
    assert parse_narration("RTGS-HDFCR52024-ACME TRADERS-INV").channel is Channel.RTGS


def test_atm():
    i = parse_narration("ATM-CASH WDL/BENGALURU ATM 1234/556677")
    assert i.channel is Channel.ATM and i.key == "atm cash" and i.reference == "556677"


def test_pos_strips_card_and_city():
    i = parse_narration("POS 4821 MAKEMYTRIP INDIA MUMBAI")
    assert i.channel is Channel.POS and i.counterparty == "MAKEMYTRIP INDIA"


def test_ach():
    i = parse_narration("ACH D-BESCOM BANGALORE-48291034")
    assert i.channel is Channel.ACH and i.counterparty == "BESCOM BANGALORE" and i.reference == "48291034"


def test_chq_return_charge():
    i = parse_narration("CHQ RTN CHG-INSUFFICIENT FUNDS-214279")
    assert i.channel is Channel.CHQ and i.counterparty == "CHQ RETURN CHARGES"


def test_unknown_falls_back_to_other():
    assert parse_narration("INT.PD 01-01-24").channel is Channel.OTHER


def test_reversal_flag():
    i = parse_narration("REV-UPI/123456789012/SWIGGY/swiggy@icici")
    assert i.is_reversal and i.channel is Channel.UPI and i.key == "swiggy"


@pytest.mark.parametrize("raw,key", [
    ("XYZ ENTERPRISES", "xyz enterprises"), ("Zenith Analytics LLP", "zenith analytics"),
    ("ACME PVT LTD 12345", "acme"), (None, None), ("", None)])
def test_normalize_key(raw, key):
    assert normalize_key(raw) == key

"""Regex-based statement metadata extraction. Account numbers are masked at the
source: the unmasked value never leaves this module."""
from __future__ import annotations

import re
from datetime import date

from bsi.parse.amounts import try_parse_money
from bsi.parse.dates import try_parse_date
from bsi.schema import StatementMeta

_STOP = (r"(?=\s+(?:IFSC|Branch|A/c|Account\s*(?:No|Number|Holder|Name)|Statement|Period"
         r"|Customer|Opening|Closing|MICR)\b|\s*$)")
_DATE = r"\d{1,2}[-/. ](?:\d{1,2}|[A-Za-z]{3,9})[-/. ]\d{2,4}"

_HOLDER = re.compile(
    r"(?:Account\s*Holder(?:\s*Name)?|Account\s*Name|Customer\s*Name|A/c\s*Name)\s*[:\-]\s*(.+?)" + _STOP,
    re.IGNORECASE | re.MULTILINE,
)
_ACCOUNT = re.compile(
    r"(?:Account\s*(?:No\.?|Number)|A/c\.?\s*(?:No\.?|Number)?)\s*[:\-]?\s*([Xx*\d][Xx*\d \-]{4,}\d)",
    re.IGNORECASE,
)
_IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
_BRANCH = re.compile(r"Branch(?:\s*Name)?\s*[:\-]\s*(.+?)" + _STOP, re.IGNORECASE | re.MULTILINE)
_PERIOD = re.compile(
    rf"(?:Statement\s*Period|Period|Statement\s*From|From)\s*[:\-]?\s*({_DATE})\s*(?:to|-|–|till)\s*({_DATE})",
    re.IGNORECASE,
)
_BAL = r"\s*(?:\(.*?\))?\s*[:\-]?\s*((?:₹|Rs\.?|INR)?\s*-?\d[\d,]*(?:\.\d{1,2})?\s*(?:Dr|Cr)?)"
_OPENING = re.compile(r"Opening\s*Bal(?:ance)?" + _BAL, re.IGNORECASE)
_CLOSING = re.compile(r"Closing\s*Bal(?:ance)?" + _BAL, re.IGNORECASE)


def mask_account(number: str) -> str:
    """Keep only the last 4 digits: '50100234567890' -> 'XXXXXXXXXX7890'."""
    cleaned = re.sub(r"[\s\-]", "", number)
    if len(cleaned) <= 4:
        return "X" * 4
    tail = cleaned[-4:]
    return "X" * (len(cleaned) - 4) + tail


def _first(rx: re.Pattern[str], text: str) -> str | None:
    m = rx.search(text)
    return m.group(1).strip() if m else None


def extract_metadata(text: str, date_formats: list[str] | None = None) -> StatementMeta:
    holder = _first(_HOLDER, text)
    acct = _first(_ACCOUNT, text)
    period_start: date | None = None
    period_end: date | None = None
    pm = _PERIOD.search(text)
    if pm:
        period_start = try_parse_date(pm.group(1), date_formats)
        period_end = try_parse_date(pm.group(2), date_formats)
    opening = _first(_OPENING, text)
    closing = _first(_CLOSING, text)
    return StatementMeta(
        account_holder=holder,
        account_number_masked=mask_account(acct) if acct else None,
        ifsc=_first(_IFSC, text),
        branch=_first(_BRANCH, text),
        period_start=period_start,
        period_end=period_end,
        opening_balance=try_parse_money(opening) if opening else None,
        closing_balance=try_parse_money(closing) if closing else None,
    )

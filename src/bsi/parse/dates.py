"""Date parsing. Indian statements are day-first; several formats may coexist."""
from __future__ import annotations

import re
from datetime import date, datetime

DEFAULT_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%d %B %Y", "%d-%B-%Y",
    "%b %d, %Y", "%Y-%m-%d", "%Y/%m/%d",
]
_TIME_TAIL = re.compile(r"[ T]\d{1,2}:\d{2}(:\d{2})?(\s*[AP]M)?$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{1,2}[-/. ](?:\d{1,2}|[A-Za-z]{3,9})[-/. ,]+\d{2,4}$|^\d{4}[-/]\d{2}[-/]\d{2}$")


def parse_date(text: str, formats: list[str] | None = None) -> date:
    s = _TIME_TAIL.sub("", text.strip()).replace("Sept", "Sep")
    for fmt in [*(formats or []), *DEFAULT_FORMATS]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {text!r}")


def try_parse_date(text: str | None, formats: list[str] | None = None) -> date | None:
    if not text or not text.strip():
        return None
    try:
        return parse_date(text, formats)
    except ValueError:
        return None

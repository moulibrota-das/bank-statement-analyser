"""Redaction applied to document text before it is sent to an LLM (images cannot be redacted)."""
from __future__ import annotations

import re

from bsi.parse.metadata import extract_metadata, find_account_numbers


def redact_text(text: str) -> str:
    """Mask account numbers to their last 4 digits and replace the account holder's name."""
    for number in find_account_numbers(text):
        spaced = r"[\s\-]?".join(re.escape(c) for c in number)
        text = re.sub(spaced, "X" * (len(number) - 4) + number[-4:], text)
    holder = extract_metadata(text).account_holder
    if holder:
        for tok in {holder, *[p for p in holder.split() if len(p) > 2]}:
            text = re.sub(re.escape(tok), "ACCOUNT_HOLDER", text, flags=re.IGNORECASE)
    return text

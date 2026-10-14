"""Deterministic narration parsing: channel, counterparty, UPI handle, reference,
and a normalized counterparty key used for caching and recurring detection."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bsi.schema import Channel, Transaction

CITIES = {"BENGALURU", "BANGALORE", "MUMBAI", "CHENNAI", "HYDERABAD", "PUNE", "DELHI", "KOLKATA", "GURGAON"}
_SUFFIXES = {"pvt", "ltd", "llp", "limited", "private", "inc", "india", "co", "corp", "services", "solutions"}
_HANDLE = re.compile(r"[\w.\-]+@[a-z]{2,}", re.IGNORECASE)
_DIGITS = re.compile(r"\d{6,}")


@dataclass
class NarrationInfo:
    channel: Channel
    counterparty: str | None
    handle: str | None
    reference: str | None
    key: str | None
    is_reversal: bool = False


def normalize_key(name: str | None) -> str | None:
    if not name:
        return None
    s = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    toks = [t for t in s.split() if not t.isdigit() and t not in _SUFFIXES]
    if not toks:  # name was only suffix words, e.g. "SERVICES"
        toks = [t for t in s.split() if not t.isdigit()]
    return " ".join(toks) or None


def _clean(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"\s+", " ", name).strip(" -/")
    return name or None


def _first_ref(text: str) -> str | None:
    m = _DIGITS.search(text)
    return m.group(0) if m else None


def parse_narration(narration: str) -> NarrationInfo:
    n = " ".join(narration.split())
    up = n.upper()
    reversal = bool(re.match(r"^(REV|REVERSAL)[-/ ]", up))
    if reversal:
        n = re.sub(r"^(REV|REVERSAL)[-/ ]", "", n, flags=re.IGNORECASE)
        up = n.upper()

    def info(ch: Channel, cp: str | None, handle: str | None = None, ref: str | None = None) -> NarrationInfo:
        cp = _clean(cp)
        return NarrationInfo(ch, cp, handle, ref, normalize_key(cp), reversal)

    if up.startswith("UPI"):
        parts = [p.strip() for p in re.split(r"[/]", n)]
        parts = [p for p in parts if p][1:] if parts and parts[0].upper() == "UPI" else parts
        handle = next((m.group(0) for p in parts if (m := _HANDLE.fullmatch(p))), None)
        if handle is None:
            m = _HANDLE.search(n)
            handle = m.group(0) if m else None
        ref = next((p for p in parts if re.fullmatch(r"\d{9,}", p)), None)
        name = next((p for p in parts if p != ref and not _HANDLE.fullmatch(p)), None)
        return info(Channel.UPI, name, handle, ref)
    for ch in (Channel.NEFT, Channel.RTGS):
        if up.startswith(ch.value):
            parts = [p.strip() for p in re.split(r"[-/]", n, maxsplit=3)]
            ref = parts[1] if len(parts) > 1 else None
            return info(ch, parts[2] if len(parts) > 2 else None, None, ref)
    if up.startswith("IMPS"):
        parts = [p.strip() for p in re.split(r"[-/]", n)]
        ref = next((p for p in parts if re.fullmatch(r"\d{9,}", p)), None)
        rest = [p for p in parts[1:] if p != ref]
        return info(Channel.IMPS, rest[0] if rest else None, None, ref)
    if up.startswith("ATM"):
        return info(Channel.ATM, "ATM CASH", None, _first_ref(n))
    if up.startswith("POS"):
        body = re.sub(r"^POS\s+(?:\d{4}\s+)?", "", n, flags=re.IGNORECASE).split()
        while body and body[-1].upper() in CITIES:
            body.pop()
        return info(Channel.POS, " ".join(body), None, None)
    if up.startswith("ACH"):
        m = re.match(r"ACH\s+[DC]?\s*-\s*(.+?)(?:-(\w*\d\w*))?$", n, re.IGNORECASE)
        if m:
            return info(Channel.ACH, m.group(1), None, m.group(2))
        return info(Channel.ACH, re.sub(r"^ACH\s*", "", n, flags=re.IGNORECASE), None, None)
    if up.startswith(("CHQ", "CHEQUE", "CLG")):
        m = re.match(r"CHQ\s+(?:RTN|RETURN)\s+CHG", up)
        if m:
            return info(Channel.CHQ, "CHQ RETURN CHARGES", None, _first_ref(n))
        return info(Channel.CHQ, re.sub(r"^(CHQ|CHEQUE|CLG)\s*(NO\.?\s*\d+)?\s*", "", n, flags=re.IGNORECASE),
                    None, _first_ref(n))
    return info(Channel.OTHER, _DIGITS.sub("", n), None, _first_ref(n))


def enrich(txns: list[Transaction]) -> list[Transaction]:
    for t in txns:
        i = parse_narration(t.narration)
        t.channel, t.counterparty, t.counterparty_key = i.channel, i.counterparty, i.key
        t.upi_handle = i.handle
        t.reference = i.reference or t.reference
    return txns

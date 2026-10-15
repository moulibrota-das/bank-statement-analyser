"""Layout-free fallback for PDFs with no recognisable table header.

A row is any line that starts with a date and carries at least one money token. The last money
token is the running balance, the one before it the amount; direction comes from an explicit
Dr/Cr marker, else from how the balance moved (which is also what reconciliation checks), else
from narration keywords. Unlike the layout parsers this cannot tell a debit column from a
credit column, so everything it infers is flagged for the user and reconciliation still runs."""
from __future__ import annotations

import io
import re
from decimal import Decimal

import pdfplumber

from bsi.parse.amounts import looks_like_money, parse_money
from bsi.parse.dates import DATE_RE, try_parse_date
from bsi.parse.pdf import WRAP_GAP, _join_wrapped, _lines
from bsi.schema import Direction, Transaction

_CREDIT_WORDS = re.compile(
    r"\b(salary|sal cr|refund|reversal|interest|int\.?\s?cr|credit|deposit|cashback|dividend)\b", re.I)
_REF = re.compile(r"^\d{8,}$")


def _date_prefix(tokens: list[str]):
    for n in (3, 1):
        cand = " ".join(tokens[:n])
        if len(tokens) >= n and DATE_RE.match(cand) and try_parse_date(cand):
            return try_parse_date(cand), n
    return None, 0


def _money(tokens: list[str]):
    """-> [(value, marker, index_of_first_token)] merging a trailing Dr/Cr word into its amount."""
    out, i = [], 0
    while i < len(tokens):
        if looks_like_money(tokens[i]):
            marker = None
            if i + 1 < len(tokens) and tokens[i + 1].lower().rstrip(".") in ("dr", "cr"):
                marker = tokens[i + 1].lower().rstrip(".")
                i += 1
            out.append((tokens[i - (1 if marker else 0)], marker))
        i += 1
    return out


def extract_generic(data: bytes, opening: Decimal | None = None) -> tuple[list[Transaction], list[str]]:
    rows: list[dict] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            last_top = None
            for line in _lines(page):
                tokens = [w.text for w in line]
                when, n = _date_prefix(tokens)
                if when is None:
                    if rows and last_top is not None and line[0].top - last_top <= WRAP_GAP \
                            and not any(looks_like_money(t) for t in tokens):
                        rows[-1]["narr"] = _join_wrapped(rows[-1]["narr"], " ".join(tokens))
                        last_top = line[0].top
                    continue
                rest = tokens[n:]
                if rest and DATE_RE.match(rest[0]) and try_parse_date(rest[0]):  # value date
                    rest = rest[1:]
                first_money = next((i for i, t in enumerate(rest) if looks_like_money(t)), None)
                if first_money is None:
                    last_top = None
                    continue
                money = _money(rest[first_money:])
                narr = " ".join(rest[:first_money])
                ref = None
                parts = narr.split()
                if parts and _REF.match(parts[-1]):
                    ref, narr = parts[-1], " ".join(parts[:-1])
                rows.append({"date": when, "narr": narr, "ref": ref, "money": money})
                last_top = line[0].top
    txns: list[Transaction] = []
    warnings: list[str] = []
    prev: Decimal | None = opening
    guessed = 0
    for r in rows:
        money = r["money"]
        bal = parse_money(f"{money[-1][0]} {money[-1][1] or ''}".strip()) if len(money) >= 2 else None
        amt_raw, marker = money[-2] if len(money) >= 2 else money[-1]
        amount = abs(parse_money(amt_raw))
        if amount == 0:
            continue
        direction = None
        if marker:
            direction = Direction.DEBIT if marker == "dr" else Direction.CREDIT
        elif bal is not None and prev is not None:
            if prev + amount == bal:
                direction = Direction.CREDIT
            elif prev - amount == bal:
                direction = Direction.DEBIT
        if direction is None:
            guessed += 1
            direction = Direction.CREDIT if _CREDIT_WORDS.search(r["narr"]) else Direction.DEBIT
        if bal is not None:
            prev = bal
        txns.append(Transaction(idx=len(txns), date=r["date"], narration=" ".join(r["narr"].split()),
                                amount=amount, direction=direction, balance=bal, reference=r["ref"]))
    if guessed:
        warnings.append(f"{guessed} transaction direction(s) were guessed from the narration because the balance "
                        "trail could not decide them.")
    return txns, warnings

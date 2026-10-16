"""Statements that are images (or scanned PDFs) have no text layer, so a vision model transcribes them
into the same unified structure the parsers produce. The model only transcribes strings; code parses and
normalises every date and amount, masks the account number, and reconciliation then checks the result."""
from __future__ import annotations

import re

from pydantic import BaseModel

from bsi.ingest.loader_types import ParsedStatement, UnreadableFile
from bsi.llm.client import LLMClient, LLMError, complete_json
from bsi.llm.prompts import load_prompt
from bsi.parse.amounts import is_blank, parse_amount_drcr, parse_money
from bsi.parse.dates import parse_date
from bsi.parse.metadata import mask_account
from bsi.schema import Direction, StatementMeta, Transaction


class ExtractedRow(BaseModel):
    date: str
    narration: str
    debit: str | None = None
    credit: str | None = None
    amount: str | None = None
    drcr: str | None = None
    balance: str | None = None


class ExtractedStatement(BaseModel):
    bank_name: str | None = None
    account_holder: str | None = None
    account_last4: str | None = None
    ifsc: str | None = None
    branch: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    opening_balance: str | None = None
    closing_balance: str | None = None
    rows: list[ExtractedRow]


def _money(s: str | None):
    return None if is_blank(s) else parse_money(s)  # type: ignore[arg-type]


def _date(s: str | None):
    try:
        return parse_date(s) if s and s.strip() else None
    except ValueError:
        return None


def _row_amount(r: ExtractedRow) -> tuple | None:
    if not is_blank(r.debit) and not is_blank(r.credit):
        d, c = abs(parse_money(r.debit)), abs(parse_money(r.credit))  # type: ignore[arg-type]
        return (c, Direction.CREDIT) if d == 0 else (d, Direction.DEBIT)
    if not is_blank(r.debit):
        return abs(parse_money(r.debit)), Direction.DEBIT  # type: ignore[arg-type]
    if not is_blank(r.credit):
        return abs(parse_money(r.credit)), Direction.CREDIT  # type: ignore[arg-type]
    if not is_blank(r.amount):
        value, marker = parse_amount_drcr(r.amount)  # type: ignore[arg-type]
        marker = marker or {"dr": Direction.DEBIT, "cr": Direction.CREDIT}.get((r.drcr or "").strip(" .").lower())
        if marker is None:
            marker = Direction.CREDIT if value > 0 else Direction.DEBIT
        return abs(value), marker
    return None


CHUNK_CHARS = 20000


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Split on line boundaries so each LLM call stays well inside the output limit."""
    chunks, cur, size = [], [], 0
    for line in text.splitlines():
        if size + len(line) + 1 > max_chars and cur:
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [""]


def _ask(client: LLMClient, user_suffix: str = "", files=None) -> ExtractedStatement:
    prompt = load_prompt("extract_v1")
    try:
        return complete_json(client, prompt.system, prompt.render_user() + user_suffix, ExtractedStatement,
                             task="extract", files=files)
    except LLMError as e:
        raise UnreadableFile(f"could not read this document with the AI model: {e}") from e


def extract_with_vision(data: bytes, mime: str, client: LLMClient | None) -> ParsedStatement:
    """Images and scanned PDFs: the file itself goes to the model."""
    if client is None:
        raise UnreadableFile("this file has no text layer and needs AI extraction, which is switched off")
    return _to_parsed([_ask(client, files=[(data, mime)])],
                      "Read from an image by an AI model: figures were transcribed, not parsed from text. "
                      "The whole image was sent to the model. Check the figures.")


def extract_text_with_llm(text: str, client: LLMClient, layout_name: str = "ai-text") -> ParsedStatement:
    """Text documents (any bank, any layout): the redacted text goes to the model in chunks."""
    parts = [_ask(client, "\n\nDocument text:\n```text\n" + chunk + "\n```") for chunk in chunk_text(text)]
    return _to_parsed(parts, "Layout not recognised: rows were extracted from the document text by an AI model "
                             "(account number masked and holder name removed first). Check the figures.",
                      layout=layout_name, source=None)


def _to_parsed(parts: list[ExtractedStatement], warning: str, layout: str = "ai-vision",
               source: str | None = "image") -> ParsedStatement:
    ex = parts[0]
    rows = [r for p in parts for r in p.rows]
    txns: list[Transaction] = []
    warnings = [warning]
    for n, r in enumerate(rows, start=1):
        try:
            when, resolved = _date(r.date), _row_amount(r)
            if when is None or resolved is None:
                warnings.append(f"row {n}: unreadable date or amount; skipped")
                continue
            txns.append(Transaction(idx=len(txns), date=when, narration=" ".join(r.narration.split()),
                                    amount=resolved[0], direction=resolved[1], balance=_money(r.balance)))
        except ValueError as e:
            warnings.append(f"row {n}: could not parse ({e}); skipped")
    if not txns:
        raise UnreadableFile("no transactions could be read from this document (is it a bank statement?)")

    digits = re.sub(r"\D", "", ex.account_last4 or "")
    masked = None
    if digits:  # the prompt asks for the last 4 only; mask anything longer the model returns anyway
        masked = "X" * 8 + digits if len(digits) <= 4 else mask_account(digits)
    meta = StatementMeta(
        bank_name=ex.bank_name, account_holder=ex.account_holder, ifsc=ex.ifsc, branch=ex.branch,
        account_number_masked=masked,
        period_start=_date(ex.period_start), period_end=_date(ex.period_end),
        opening_balance=_money_safe(ex.opening_balance), closing_balance=_money_safe(ex.closing_balance),
        layout=layout, source_type=source)  # type: ignore[arg-type]
    return ParsedStatement(meta, txns, warnings)


def _money_safe(s: str | None):
    try:
        return _money(s)
    except ValueError:
        return None

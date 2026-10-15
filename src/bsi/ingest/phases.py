"""Document intake in phases.

  Phase 1  document check   LLM: is this a bank statement at all?
  Phase 2  extraction       unified structure: exact parser when a known layout matches, else the LLM
                            (text or vision), cross-checked against a heuristic parse by reconciliation
  Phase 3  analysis         classification, analytics, anomalies, summary (see pipeline.py)

This module owns phases 1 and 2. Every route ends in the same ParsedStatement."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from bsi.ingest.gate import check_document, should_reject
from bsi.ingest.layouts import Layout, detect_layout, get_layout
from bsi.ingest.loader import (
    IMAGE_MIMES,
    detect_file_type,
    load_statement,
    sniff_image,
)
from bsi.ingest.loader_types import (
    NotAStatement,
    ParsedStatement,
    UnknownLayout,
    UnreadableFile,
)
from bsi.ingest.redact import redact_text
from bsi.ingest.vision import extract_text_with_llm, extract_with_vision
from bsi.llm.client import LLMClient
from bsi.parse.metadata import extract_metadata
from bsi.schema import DocumentCheck, PhaseInfo
from bsi.validate.reconciliation import reconcile


@dataclass
class Ingested:
    parsed: ParsedStatement
    check: DocumentCheck
    phases: list[PhaseInfo] = field(default_factory=list)


def document_text(data: bytes, kind: str) -> str | None:
    """Local text view of the document (None for images). Raises UnreadableFile on corrupt files."""
    try:
        if kind == "pdf":
            from bsi.parse.pdf import extract_text
            return extract_text(data)
        if kind in ("csv", "xlsx"):
            from bsi.parse.tabular import read_grid
            lines = []
            for row in read_grid(data, kind):
                cells = [c for c in row if c]
                if len(cells) == 2:  # "label, value" preamble rows -> "label: value" so field regexes apply
                    lines.append(f"{cells[0]}: {cells[1]}")
                elif cells:
                    lines.append(", ".join(cells))
            return "\n".join(lines)
    except Exception as e:  # pdfminer/openpyxl raise many types on corrupt files
        raise UnreadableFile(f"could not read {kind.upper()} file: {type(e).__name__}") from e
    return None


def _known_layout(data: bytes, kind: str, layout: str | None) -> Layout | None:
    if layout:
        return get_layout(layout)
    try:
        if kind == "pdf":
            from bsi.parse.pdf import detect_pdf_layout
            return detect_pdf_layout(data)
        from bsi.parse.tabular import read_grid
        for row in read_grid(data, kind)[:80]:
            lay = detect_layout([c for c in row if c], kind)
            if lay:
                return lay
    except Exception:  # noqa: BLE001 - unreadable files are reported by document_text
        return None
    return None


def _issues(parsed: ParsedStatement) -> int:
    return len(reconcile(parsed.meta, parsed.transactions).issues)


def _timed(phases: list[PhaseInfo], name: str, method: str, client: LLMClient | None, start: float,
           calls0: int, detail: str = "") -> None:
    phases.append(PhaseInfo(name=name, method=method, detail=detail, seconds=round(time.perf_counter() - start, 3),
                            llm_calls=(client.stats.calls - calls0) if client else 0))


def ingest_document(data: bytes, filename: str = "", layout: str | None = None,
                    client: LLMClient | None = None) -> Ingested:
    kind = detect_file_type(data, filename)  # raises UnsupportedFileType
    phases: list[PhaseInfo] = []
    text = document_text(data, kind)
    scanned = kind == "image" or (kind == "pdf" and not (text or "").strip())
    mime = IMAGE_MIMES[sniff_image(data)] if kind == "image" else "application/pdf"  # type: ignore[index]
    safe_text = redact_text(text) if text and not scanned else None

    # ---- Phase 1: is it a bank statement?
    t0, c0 = time.perf_counter(), client.stats.calls if client else 0
    if client is None:
        check = DocumentCheck(is_bank_statement=True, confidence=0.0, document_type="unknown",
                              reason="AI is switched off; no document check was run", method="skipped")
    else:
        check = check_document(client, safe_text, (data, mime) if scanned else None)
    _timed(phases, "document_check", check.method, client, t0, c0,
           f"{check.document_type} ({check.confidence:.0%}): {check.reason}")
    if should_reject(check):
        raise NotAStatement(f"This doesn't look like a bank statement. It looks like: "
                            f"{check.document_type.replace('_', ' ')}. {check.reason}")

    # ---- Phase 2: extraction into the unified structure
    t0, c0 = time.perf_counter(), client.stats.calls if client else 0
    warnings: list[str] = []
    if check.method == "unavailable":
        warnings.append("The document check was unavailable; continuing without it.")
    elif check.confidence < 0.6 and check.method != "skipped" and check.is_bank_statement:
        warnings.append(f"The document check was unsure ({check.confidence:.0%}): {check.reason}")

    known = None if scanned else _known_layout(data, kind, layout)
    if known is not None:
        parsed, method = load_statement(data, filename, known.name), f"parser · {known.name}"
    elif scanned:
        parsed = extract_with_vision(data, mime, client)
        method = "vision model"
    else:
        parsed, method = _extract_unknown_layout(data, filename, kind, safe_text or "", client, warnings)
    balances = "balances reconcile" if _issues(parsed) == 0 else "balances do NOT reconcile"
    _timed(phases, "extraction", method, client, t0, c0, f"{len(parsed.transactions)} transactions · {balances}")
    parsed.warnings = warnings + parsed.warnings
    return Ingested(parsed, check, phases)


def _extract_unknown_layout(data: bytes, filename: str, kind: str, safe_text: str, client: LLMClient | None,
                            warnings: list[str]) -> tuple[ParsedStatement, str]:
    """Unknown layout: the LLM extracts; a heuristic parse is the offline fallback and a cross-check."""
    heuristic: ParsedStatement | None = None
    try:
        heuristic = load_statement(data, filename, None, client=None)
    except (UnknownLayout, UnreadableFile):
        pass
    llm_parsed: ParsedStatement | None = None
    if client is not None:
        try:
            llm_parsed = extract_text_with_llm(safe_text, client)
            local = extract_metadata(safe_text)  # local regex fills / overrides what the model reported
            m = llm_parsed.meta
            src = heuristic.meta if heuristic else local  # holder/account were redacted before sending
            m.account_holder = src.account_holder
            m.account_number_masked = src.account_number_masked or m.account_number_masked
            m.ifsc, m.branch = src.ifsc or m.ifsc, src.branch or m.branch
            m.opening_balance = src.opening_balance if src.opening_balance is not None else m.opening_balance
            m.closing_balance = src.closing_balance if src.closing_balance is not None else m.closing_balance
            m.period_start, m.period_end = src.period_start or m.period_start, src.period_end or m.period_end
            m.source_type = kind  # type: ignore[assignment]
        except UnreadableFile as e:
            warnings.append(f"AI extraction failed ({e}); used the heuristic parser instead.")
    if llm_parsed and heuristic:
        if _issues(heuristic) < _issues(llm_parsed):
            warnings.append("The AI extraction did not reconcile but the heuristic parse did; "
                            "using the heuristic parse.")
            return heuristic, "heuristic parser (cross-checked)"
        return llm_parsed, "LLM text extraction"
    if llm_parsed:
        return llm_parsed, "LLM text extraction"
    if heuristic:
        return heuristic, "heuristic parser"
    raise UnknownLayout("no transactions could be extracted from this document")

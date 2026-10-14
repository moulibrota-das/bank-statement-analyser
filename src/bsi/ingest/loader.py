"""File-type detection and top-level parsing into a ParsedStatement."""
from __future__ import annotations

from dataclasses import dataclass, field

from bsi.ingest.layouts import Layout, detect_layout, get_layout, load_layouts, match_header
from bsi.ingest.mapping import infer_layout, looks_like_header
from bsi.parse.metadata import extract_metadata
from bsi.parse.rows import build_transactions
from bsi.parse.tabular import extract_rows, grid_to_text, read_grid
from bsi.schema import StatementMeta, Transaction


class UnsupportedFileType(ValueError):
    pass


class UnknownLayout(ValueError):
    pass


class UnreadableFile(ValueError):
    pass


@dataclass
class ParsedStatement:
    meta: StatementMeta
    transactions: list[Transaction]
    warnings: list[str] = field(default_factory=list)


def detect_file_type(data: bytes, filename: str = "") -> str:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "xlsx"
    name = filename.lower()
    if name.endswith(".csv") or _looks_like_text(data):
        return "csv"
    raise UnsupportedFileType("file is not a PDF, CSV or XLSX")


def _looks_like_text(data: bytes) -> bool:
    try:
        data[:4096].decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in data[:4096] and b"," in data[:4096]


def load_statement(data: bytes, filename: str = "", layout: str | None = None, client=None) -> ParsedStatement:
    source = detect_file_type(data, filename)
    if source == "pdf":
        return _load_pdf(data, layout, client)
    return _load_tabular(data, source, layout, client)


def _finish(meta: StatementMeta, lay: Layout, source: str, rows, warnings: list[str], how: str | None):
    txns, w = build_transactions(rows, lay)
    if how and lay.amount_style == "signed":
        # sign convention can't be read from a header: keep whichever one reconciles better
        from bsi.validate.reconciliation import reconcile

        flipped = lay.model_copy(update={"signed_credit_positive": not lay.signed_credit_positive})
        alt, alt_w = build_transactions(rows, flipped)
        if len(reconcile(meta, alt).issues) < len(reconcile(meta, txns).issues):
            txns, w, lay = alt, alt_w, flipped
    meta.layout, meta.source_type = lay.name, source  # type: ignore[assignment]
    meta.bank_name = meta.bank_name or lay.bank_name
    if how:
        warnings.append(f"Unknown layout: column mapping inferred by {how}; verify the reconciliation result.")
    return ParsedStatement(meta, txns, warnings + w)


def _load_pdf(data: bytes, layout: str | None, client) -> ParsedStatement:
    from bsi.parse import pdf as pdfmod

    try:
        lay: Layout | None = get_layout(layout) if layout else pdfmod.detect_pdf_layout(data)
    except Exception as e:  # pdfminer raises a zoo of exception types on corrupt files
        raise UnreadableFile(f"could not read PDF: {type(e).__name__}") from e
    how = None
    if lay is None:
        headers = pdfmod.guess_header_labels(data)
        if headers is None:
            raise UnknownLayout("no layout profile matches this PDF and no transaction table header was found")
        lay, how = infer_layout(headers, "pdf", client)
    meta = extract_metadata(pdfmod.extract_text(data), lay.date_formats)
    rows = pdfmod.extract_rows(data, lay)
    if not rows:
        raise UnknownLayout("a transaction table header was found but no transaction rows could be read")
    return _finish(meta, lay, "pdf", rows, [], how)


def _load_tabular(data: bytes, source: str, layout: str | None, client) -> ParsedStatement:
    try:
        grid = read_grid(data, source)
    except Exception as e:  # corrupt zip / bad encoding
        raise UnreadableFile(f"could not read {source.upper()} file: {type(e).__name__}") from e
    lay: Layout | None = None
    hdr = None
    how = None
    if layout:
        lay = get_layout(layout)
        hdr = next((i for i, r in enumerate(grid) if match_header(r, lay)), None)
    else:
        for i, r in enumerate(grid[:80]):
            lay = detect_layout([c for c in r if c], source)
            if lay:
                hdr = i
                break
    if lay is None or hdr is None:
        hdr = next((i for i, r in enumerate(grid[:80]) if looks_like_header(r)), None)
        if hdr is None:
            raise UnknownLayout("could not find a transaction table header in this file")
        labels = [c for c in grid[hdr] if c]
        grid[hdr] = [c if c in labels else "" for c in grid[hdr]]
        lay, how = infer_layout(labels, source, client)
    try:
        rows, other = extract_rows(grid, hdr, lay)
    except ValueError as e:
        raise UnknownLayout(str(e)) from e
    if not rows:
        raise UnknownLayout("a table header was found but no transaction rows could be read")
    meta = extract_metadata(grid_to_text(other), lay.date_formats)
    return _finish(meta, lay, source, rows, [], how)


__all__ = ["ParsedStatement", "load_statement", "detect_file_type", "load_layouts", "UnsupportedFileType",
           "UnknownLayout", "UnreadableFile"]

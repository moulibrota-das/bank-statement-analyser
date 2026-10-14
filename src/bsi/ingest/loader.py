"""File-type detection and top-level parsing into a ParsedStatement."""
from __future__ import annotations

from dataclasses import dataclass, field

from bsi.ingest.layouts import Layout, get_layout, load_layouts
from bsi.parse.metadata import extract_metadata
from bsi.parse.rows import build_transactions
from bsi.schema import StatementMeta, Transaction


class UnsupportedFileType(ValueError):
    pass


class UnknownLayout(ValueError):
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
        from bsi.parse import pdf as pdfmod

        lay: Layout | None = get_layout(layout) if layout else pdfmod.detect_pdf_layout(data)
        if lay is None:
            raise UnknownLayout("no layout profile matches this PDF")
        text = pdfmod.extract_text(data)
        meta = extract_metadata(text, lay.date_formats)
        rows = pdfmod.extract_rows(data, lay)
        txns, warnings = build_transactions(rows, lay)
        meta.layout, meta.bank_name, meta.source_type = lay.name, lay.bank_name, "pdf"
        return ParsedStatement(meta, txns, warnings)
    raise NotImplementedError(f"{source} parsing arrives in phase 4")


__all__ = ["ParsedStatement", "load_statement", "detect_file_type", "load_layouts"]

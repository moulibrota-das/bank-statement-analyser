"""CSV / XLSX reading into a grid of strings, header-row location, and row extraction."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from bsi.ingest.layouts import Layout, _norm
from bsi.parse.dates import try_parse_date


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{Decimal(repr(v)):.2f}"
    return str(v).strip()


def read_grid(data: bytes, source: str) -> list[list[str]]:
    if source == "csv":
        text = data.decode("utf-8-sig", errors="replace")
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    return [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]


def grid_to_text(rows: list[list[str]]) -> str:
    """Preamble/footer rows -> 'label: value' lines for the regex metadata extractor."""
    lines = []
    for r in rows:
        cells = [c for c in r if c]
        if len(cells) >= 2:
            lines.append(f"{cells[0]}: {' '.join(cells[1:])}")
        elif cells:
            lines.append(cells[0])
    return "\n".join(lines)


def extract_rows(grid: list[list[str]], header_idx: int,
                 layout: Layout) -> tuple[list[dict[str, str]], list[list[str]]]:
    """Returns (data rows as field->text, non-data rows (preamble/footer) for metadata)."""
    header = [_norm(c) for c in grid[header_idx]]
    index: dict[str, int] = {}
    for col in layout.columns:
        try:
            index[col.field] = header.index(_norm(col.header))
        except ValueError as e:
            raise ValueError(f"header {col.header!r} not found") from e
    rows: list[dict[str, str]] = []
    other: list[list[str]] = [r for r in grid[:header_idx]]
    for r in grid[header_idx + 1:]:
        if not any(r):
            continue
        cells = {f: (r[i] if i < len(r) else "") for f, i in index.items()}
        if try_parse_date(cells.get("date"), layout.date_formats):
            rows.append(cells)
        else:
            other.append(r)
    return rows, other

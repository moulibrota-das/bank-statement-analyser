"""Layout-driven PDF table extraction using word coordinates.

Columns are located from the header row on each page (so repeated headers and
column drift between pages are handled). Text columns are claimed by left edge,
money columns by right edge. Lines without a date are wrapped narration
continuations when they sit close to the previous line."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber

from bsi.ingest.layouts import ColumnSpec, Layout, load_layouts
from bsi.parse.amounts import looks_like_money
from bsi.parse.dates import DATE_RE, try_parse_date

Y_TOL = 3.0
MONEY_X_TOL = 28.0  # wide enough for a trailing 'Dr'/'Cr' marker; money columns are far apart


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float


@dataclass
class Anchor:
    col: ColumnSpec
    x0: float
    x1: float


def _lines(page) -> list[list[Word]]:
    words = [Word(w["text"], w["x0"], w["x1"], w["top"])
             for w in page.extract_words(x_tolerance=1.5, y_tolerance=2)]
    words.sort(key=lambda w: (w.top, w.x0))
    lines: list[list[Word]] = []
    for w in words:
        if lines and abs(lines[-1][0].top - w.top) <= Y_TOL:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w.x0)
    return lines


def _text(line: list[Word]) -> str:
    return " ".join(w.text for w in line)


def _find_anchors(line: list[Word], layout: Layout) -> list[Anchor] | None:
    texts = [w.text.lower() for w in line]
    anchors: list[Anchor] = []
    pos = 0
    for col in layout.columns:
        toks = col.header.lower().split()
        for start in range(pos, len(texts) - len(toks) + 1):
            if texts[start:start + len(toks)] == toks:
                anchors.append(Anchor(col, line[start].x0, line[start + len(toks) - 1].x1))
                pos = start + len(toks)
                break
        else:
            return None
    return anchors


def _assign(line: list[Word], anchors: list[Anchor]) -> dict[str, str]:
    cells: dict[str, list[str]] = {}
    text_anchors = [a for a in anchors if a.col.kind == "text"]
    money_anchors = [a for a in anchors if a.col.kind == "money"]
    for w in line:
        target: Anchor | None = None
        if money_anchors and looks_like_money(w.text):
            best = min(money_anchors, key=lambda a: abs(a.x1 - w.x1))
            if abs(best.x1 - w.x1) <= MONEY_X_TOL:
                target = best
        if target is None and money_anchors and w.text.lower().rstrip(".") in {"dr", "cr"}:
            left = [a for a in money_anchors if a.x1 <= w.x1 + 1]
            target = max(left, key=lambda a: a.x1, default=None)
        if target is None:
            eligible = [a for a in text_anchors if a.x0 - 3 <= w.x0]
            target = max(eligible, key=lambda a: a.x0, default=text_anchors[0] if text_anchors else None)
        if target is not None:
            cells.setdefault(target.col.field, []).append(w.text)
    return {k: " ".join(v) for k, v in cells.items()}


def _join_wrapped(prev: str, cont: str) -> str:
    if not prev:
        return cont
    return prev + cont if prev.endswith(("/", "-")) else f"{prev} {cont}"


def extract_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(_text(ln) for page in pdf.pages for ln in _lines(page))


def detect_pdf_layout(data: bytes, layouts: list[Layout] | None = None) -> Layout | None:
    candidates = [lay for lay in (layouts or load_layouts()) if "pdf" in lay.sources]
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for ln in _lines(page):
                hits = [lay for lay in candidates if _find_anchors(ln, lay)]
                if hits:
                    return max(hits, key=lambda lay: len(lay.signature))
    return None


def extract_rows(data: bytes, layout: Layout) -> list[dict[str, str]]:
    noise = [re.compile(p, re.IGNORECASE) for p in layout.noise_patterns]
    rows: list[dict[str, str]] = []
    anchors: list[Anchor] | None = None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            in_table = anchors is not None
            ended = False
            last_top: float | None = None
            for line in _lines(page):
                found = _find_anchors(line, layout)
                if found:
                    anchors, in_table, ended, last_top = found, True, False, None
                    continue
                if not in_table or ended or anchors is None:
                    continue
                if any(n.search(_text(line)) for n in noise):
                    continue
                cells = _assign(line, anchors)
                date_txt = cells.get("date", "")
                if date_txt and DATE_RE.match(date_txt) and try_parse_date(date_txt, layout.date_formats):
                    rows.append(cells)
                    last_top = line[0].top
                    continue
                money_present = any(k in cells for k in ("debit", "credit", "amount", "balance"))
                if money_present:  # totals / closing-balance lines: table is over for this page
                    ended = True
                    continue
                if rows and last_top is not None and line[0].top - last_top <= layout.wrap_gap:
                    for field in ("narration", "ref"):
                        if cells.get(field):
                            rows[-1][field] = _join_wrapped(rows[-1].get(field, ""), cells[field])
                    last_top = line[0].top
    return rows


_HEADER_HINTS = [re.compile(p, re.IGNORECASE) for p in
                 (r"date", r"narration|description|particulars|details|remarks",
                  r"debit|credit|amount|withdraw|deposit", r"balance")]


def guess_header_labels(data: bytes) -> list[str] | None:
    """Find a table-header line in an unknown PDF and split it into column labels (by x-gaps)."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for ln in _lines(page):
                labels: list[list[str]] = [[ln[0].text]]
                for prev, w in zip(ln, ln[1:], strict=False):
                    if w.x0 - prev.x1 > 6:
                        labels.append([w.text])
                    else:
                        labels[-1].append(w.text)
                names = [" ".join(g) for g in labels]
                if sum(1 for rx in _HEADER_HINTS if any(rx.search(n) for n in names)) >= 3:
                    return names
    return None

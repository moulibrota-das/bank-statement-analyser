"""Layout C: amount + Dr/Cr suffix, narrations hard-wrapped over several lines, multi-page PDF."""
from __future__ import annotations

import io
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEAD = ["Txn Date", "Particulars", "Ref", "Amount (INR)", "Balance (INR)"]
WIDTHS = [60, 140, 78, 120, 130]
WRAP = 24


def _fmt(d):
    from generate_statements import indian
    return indian(d)


def wrap_narration(text: str, width: int = WRAP) -> str:
    """Hard-wrap like a core-banking print job: break after '/' or '-' (no space) or at spaces."""
    tokens = re.findall(r"[^/\- ]+[/\-]?|\s+", text)
    lines, cur = [], ""
    for tok in tokens:
        if tok.isspace():
            if cur and len(cur) + 1 > width:
                lines.append(cur)
                cur = ""
            elif cur:
                cur += " "
            continue
        if cur and len(cur) + len(tok.rstrip()) > width:
            lines.append(cur.rstrip() if cur.endswith(" ") else cur)
            cur = ""
        cur += tok
    if cur:
        lines.append(cur.rstrip())
    return "\n".join(lines)


def _build(st: dict, buf, total_pages: int | None) -> int:
    meta, items = st["meta"], st["items"]
    ss = getSampleStyleSheet()
    info = ParagraphStyle("info", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    rows = [HEAD]
    for it in items:
        sfx = "Dr" if it.direction == "debit" else "Cr"
        bal = f"{_fmt(abs(it.balance))} {'Cr' if it.balance >= 0 else 'Dr'}"
        rows.append([f"{it.date:%d %b %Y}", wrap_narration(it.narration), it.ref[:10],
                     f"{_fmt(it.amount)} {sfx}", bal])
    table = Table(rows, colWidths=WIDTHS, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("LEADING", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF3E8")),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey), ("LINEBELOW", (0, 1), (-1, -1), 0.2, colors.lightgrey),
    ]))

    def deco(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(28, A4[1] - 30, f"{meta['bank_name']}")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 28, A4[1] - 30, "Account Statement")
        canvas.drawRightString(A4[0] - 28, A4[1] - 41, f"Page {doc.page}/{total_pages or '?'}")
        canvas.drawString(28, 18, "This is a computer generated statement (fictional bank, synthetic data).")
        canvas.restoreState()

    story = [
        Paragraph(f"Customer Name: {meta['account_holder']}", info),
        Paragraph(f"A/c No.: {meta['account_number']}", info),
        Paragraph(f"IFSC Code: {meta['ifsc']}", info),
        Paragraph(f"Branch Name: {meta['branch']}", info),
        Paragraph(f"Statement Period: {meta['period_start']:%d %b %Y} to {meta['period_end']:%d %b %Y}", info),
        Paragraph(f"Opening Balance: INR {_fmt(meta['opening_balance'])} Cr", info),
        Paragraph(f"Closing Balance: INR {_fmt(abs(meta['closing_balance']))} "
                  f"{'Cr' if meta['closing_balance'] >= 0 else 'Dr'}", info),
        Spacer(1, 8 * mm), table,
    ]
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=28, rightMargin=28, topMargin=56, bottomMargin=40,
                            title="Account Statement", author="synthetic")
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return doc.page


def render_c(st: dict, out: Path) -> Path:
    pages = _build(st, io.BytesIO(), None)
    path = out / f"{st['spec']['name']}.pdf"
    with open(path, "wb") as f:
        _build(st, f, pages)
    return path

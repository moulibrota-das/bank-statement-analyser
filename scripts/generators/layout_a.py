"""Layout A: separate Debit/Credit columns, PDF, repeated page header/footer + table header."""
from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEAD = ["Date", "Narration", "Chq/Ref No", "Debit", "Credit", "Balance"]
WIDTHS = [48, 215, 72, 62, 62, 70]


def _fmt(d):
    from generate_statements import indian
    return indian(d)


def _build(st: dict, buf, total_pages: int | None):
    meta, items = st["meta"], st["items"]
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontName="Helvetica", fontSize=7.5, leading=9)
    info = ParagraphStyle("info", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    rows = [HEAD]
    for it in items:
        rows.append([
            f"{it.date:%d/%m/%y}", Paragraph(it.narration, small), it.ref,
            _fmt(it.amount) if it.direction == "debit" else "",
            _fmt(it.amount) if it.direction == "credit" else "",
            _fmt(it.balance)])
    table = Table(rows, colWidths=WIDTHS, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, colors.lightgrey),
    ]))

    def deco(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(28, A4[1] - 30, meta["bank_name"])
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 28, A4[1] - 30, "Statement of Account")
        pg = f"Page {doc.page} of {total_pages}" if total_pages else f"Page {doc.page}"
        canvas.drawRightString(A4[0] - 28, A4[1] - 41, pg)
        canvas.drawString(28, 24, "This is a computer generated statement and does not require a signature.")
        canvas.drawString(28, 14, f"{meta['bank_name']} Ltd. (fictional bank - synthetic data)")
        canvas.restoreState()

    story = [
        Paragraph(f"Account Holder: {meta['account_holder']}", info),
        Paragraph(f"Account Number: {meta['account_number']}", info),
        Paragraph(f"IFSC: {meta['ifsc']}", info),
        Paragraph(f"Branch: {meta['branch']}", info),
        Paragraph(f"Statement Period: {meta['period_start']:%d/%m/%Y} to {meta['period_end']:%d/%m/%Y}", info),
        Paragraph(f"Opening Balance: Rs. {_fmt(meta['opening_balance'])}", info),
        Paragraph(f"Closing Balance: Rs. {_fmt(meta['closing_balance'])}", info),
        Spacer(1, 8 * mm), table,
    ]
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=28, rightMargin=28, topMargin=56, bottomMargin=40,
                            title="Statement of Account", author="synthetic")
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return doc.page


def render_a(st: dict, out: Path) -> Path:
    pages = _build(st, io.BytesIO(), None)
    path = out / f"{st['spec']['name']}.pdf"
    with open(path, "wb") as f:
        _build(st, f, pages)
    return path

"""PDFs with no recognisable header are parsed by date + amount tokens instead of being rejected."""
import io
import json

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from bsi.ingest.loader import UnknownLayout, UnreadableFile, load_statement
from bsi.parse.generic import extract_generic
from bsi.parse.metadata import extract_metadata
from bsi.parse.pdf import extract_text
from bsi.pipeline import analyze_bytes
from bsi.validate.reconciliation import reconcile
from tests.conftest import SAMPLES


def headerless_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)
    y = 800
    for ln in lines:
        c.drawString(40, y, ln)
        y -= 14
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize("name", ["nimbus_a_2024_q1", "nimbus_a_2024_03", "velocity_c_2024_q3", "velocity_c_2024_10"])
def test_generic_parser_alone_matches_ground_truth_on_layouts_a_and_c(name):
    data = (SAMPLES / f"{name}.pdf").read_bytes()
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    meta = extract_metadata(extract_text(data))
    txns, _ = extract_generic(data, meta.opening_balance)
    assert len(txns) == labels["totals"]["count"]
    for t, lab in zip(txns, labels["transactions"], strict=True):
        assert (t.date.isoformat(), str(t.amount), t.direction.value, str(t.balance), t.narration) == (
            lab["date"], lab["amount"], lab["direction"], lab["balance"], lab["narration"])
    assert reconcile(meta, txns).passed


LINES = [
    "Some Bank - Account Summary",
    "Opening Balance 1,000.00",
    "05/03/2024 UPI/412345678901/SWIGGY/swiggy@icici/Order 200.00 800.00",
    "06/03/2024 NEFT-X1-ACME PVT LTD-SALARY MAR 600.00 1,400.00",
    "07/03/2024 ATM WDL SALT LAKE 400.00 1,000.00",
    "Closing Balance 1,000.00",
]


def test_header_free_document_is_parsed_not_rejected():
    parsed = load_statement(headerless_pdf(LINES), "x.pdf")
    assert parsed.meta.layout == "generic"
    assert [(str(t.amount), t.direction.value) for t in parsed.transactions] == [
        ("200.00", "debit"), ("600.00", "credit"), ("400.00", "debit")]
    assert any("Layout not recognised" in w for w in parsed.warnings)
    assert reconcile(parsed.meta, parsed.transactions).passed


def test_full_pipeline_on_headerless_pdf_surfaces_the_warning():
    rep = analyze_bytes(headerless_pdf(LINES), "x.pdf", use_llm=False)
    assert len(rep.transactions) == 3 and rep.reconciliation.passed
    assert any("Layout not recognised" in w for w in rep.warnings)


def test_direction_guessed_from_narration_is_reported_when_balance_cannot_decide():
    lines = ["05/03/2024 SALARY FROM ACME 5,000.00", "06/03/2024 COFFEE SHOP 150.00"]
    parsed = load_statement(headerless_pdf(lines), "x.pdf")
    assert [t.direction.value for t in parsed.transactions] == ["credit", "debit"]
    assert any("guessed" in w for w in parsed.warnings)


def test_dr_cr_markers_and_value_dates():
    lines = ["05/03/2024 05/03/2024 CARD PURCHASE 250.00 Dr 750.00 Cr",
             "06/03/2024 06/03/2024 REFUND 50.00 Cr 800.00 Cr"]
    parsed = load_statement(headerless_pdf(lines), "x.pdf")
    assert [(str(t.amount), t.direction.value, str(t.balance)) for t in parsed.transactions] == [
        ("250.00", "debit", "750.00"), ("50.00", "credit", "800.00")]


def test_document_with_no_transactions_still_fails_clearly():
    with pytest.raises(UnknownLayout, match="no transactions could be extracted"):
        load_statement(headerless_pdf(["Hello", "This is a letter, not a statement."]), "x.pdf")


def test_scanned_pdf_without_text_layer_is_rejected_with_a_reason():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(50, 50, 200, 100)
    c.save()
    with pytest.raises(UnreadableFile, match="no text layer"):
        load_statement(buf.getvalue(), "x.pdf")

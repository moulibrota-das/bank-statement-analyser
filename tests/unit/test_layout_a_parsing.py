import json

import pytest

from bsi.ingest.loader import UnknownLayout, UnsupportedFileType, detect_file_type, load_statement
from bsi.validate.reconciliation import reconcile
from tests.conftest import SAMPLES

NAMES = ["nimbus_a_2024_q1", "nimbus_a_2024_03"]


@pytest.mark.parametrize("name", NAMES)
def test_layout_a_matches_labels(name):
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    path = SAMPLES / f"{name}.pdf"
    parsed = load_statement(path.read_bytes(), path.name)
    assert parsed.meta.layout == "layout_a_nimbus" and parsed.warnings == []
    assert len(parsed.transactions) == labels["totals"]["count"]
    for t, lab in zip(parsed.transactions, labels["transactions"], strict=True):
        assert (t.date.isoformat(), str(t.amount), t.direction.value, str(t.balance)) == (
            lab["date"], lab["amount"], lab["direction"], lab["balance"])
        assert t.narration == lab["narration"]
    m = labels["meta"]
    assert parsed.meta.account_number_masked == m["account_number_masked"]
    assert parsed.meta.ifsc == m["ifsc"] and parsed.meta.account_holder == m["account_holder"]
    assert str(parsed.meta.opening_balance) == m["opening_balance"]
    assert reconcile(parsed.meta, parsed.transactions).passed


def test_multi_page_with_repeated_headers_has_no_phantom_rows():
    # the 2-month statement spans several pages: header/footer repeat on each
    path = SAMPLES / "nimbus_a_2024_q1.pdf"
    parsed = load_statement(path.read_bytes(), path.name)
    assert all(t.narration and "Statement of Account" not in t.narration for t in parsed.transactions)
    assert all("computer generated" not in t.narration for t in parsed.transactions)


def test_unmasked_account_number_absent_from_parse_result():
    path = SAMPLES / "nimbus_a_2024_q1.pdf"
    parsed = load_statement(path.read_bytes(), path.name)
    assert parsed.meta.account_number_masked.startswith("XXXXXXXXXX")
    assert len(parsed.meta.account_number_masked) == 14


def test_file_type_detection():
    assert detect_file_type(b"%PDF-1.4 ...") == "pdf"
    assert detect_file_type(b"PK\x03\x04rest") == "xlsx"
    assert detect_file_type(b"a,b\n1,2\n", "x.csv") == "csv"
    with pytest.raises(UnsupportedFileType):
        detect_file_type(b"\x89PNG\x00\x00\x01", "x.png")


def test_unknown_pdf_layout_raises():
    import io

    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "Some Random Document")
    c.save()
    with pytest.raises(UnknownLayout):
        load_statement(buf.getvalue(), "x.pdf")

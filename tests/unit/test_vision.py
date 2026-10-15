"""Image / scanned-PDF statements: a vision model transcribes, code parses, reconciliation checks."""
import io
import json

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from bsi.ingest.loader import UnreadableFile, detect_file_type, load_statement, sniff_image
from bsi.llm.client import MockClient
from bsi.pipeline import analyze_bytes
from bsi.validate.reconciliation import reconcile

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
JPG = b"\xff\xd8\xff\xe0" + b"0" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 200

EXTRACTION = {
    "bank_name": "Test Bank", "account_holder": "TEST PERSON", "account_last4": "4821", "ifsc": "TEST0001234",
    "period_start": "01/03/2024", "period_end": "31/03/2024", "opening_balance": "1,000.00",
    "closing_balance": "1,400.00",
    "rows": [
        {"date": "05/03/2024", "narration": "UPI/412345678901/SWIGGY/swiggy@icici/Order", "debit": "200.00",
         "balance": "800.00"},
        {"date": "06 Mar 2024", "narration": "NEFT-X1-ACME PVT LTD-SALARY MAR", "credit": "₹1,600.00",
         "balance": "2,400.00"},
        {"date": "07-Mar-2024", "narration": "ATM WDL", "amount": "1,000.00", "drcr": "Dr", "balance": "1,400.00"},
    ]}


def fake(extraction=EXTRACTION):
    return MockClient(responses=[json.dumps(extraction)])


def test_image_types_are_detected_by_content():
    assert sniff_image(PNG) == "png" and sniff_image(JPG) == "jpeg" and sniff_image(WEBP) == "webp"
    assert detect_file_type(PNG) == detect_file_type(JPG) == detect_file_type(WEBP) == "image"


def test_image_becomes_the_same_unified_structure_as_any_other_source():
    c = fake()
    parsed = load_statement(PNG, "scan.png", client=c)
    assert [(t.date.isoformat(), str(t.amount), t.direction.value, str(t.balance)) for t in parsed.transactions] == [
        ("2024-03-05", "200.00", "debit", "800.00"), ("2024-03-06", "1600.00", "credit", "2400.00"),
        ("2024-03-07", "1000.00", "debit", "1400.00")]
    assert parsed.meta.layout == "ai-vision" and parsed.meta.source_type == "image"
    assert parsed.meta.account_number_masked == "XXXXXXXX4821" and str(parsed.meta.opening_balance) == "1000.00"
    assert reconcile(parsed.meta, parsed.transactions).passed
    assert any("sent to the model" in w for w in parsed.warnings)
    assert c.files[0] == [(PNG, "image/png")] and c.calls[0][2] == "extract"
    assert c.schemas[0].__name__ == "ExtractedStatement"


def test_transcription_errors_are_caught_by_reconciliation_not_hidden():
    bad = json.loads(json.dumps(EXTRACTION))
    bad["rows"][1]["credit"] = "1,500.00"  # model misread a digit; the printed balance still says 2,400.00
    parsed = load_statement(JPG, "scan.jpg", client=fake(bad))
    rec = reconcile(parsed.meta, parsed.transactions)
    assert not rec.passed and any(i.kind == "running_balance" for i in rec.issues)


def test_full_account_number_from_the_model_is_still_masked():
    leaked = {**EXTRACTION, "account_last4": "50100234567890"}
    parsed = load_statement(PNG, "scan.png", client=fake(leaked))
    assert parsed.meta.account_number_masked == "XXXXXXXXXX7890"
    assert "5010023456" not in parsed.meta.model_dump_json()


def test_unreadable_rows_are_skipped_with_a_warning():
    bad = {**EXTRACTION, "rows": [*EXTRACTION["rows"], {"date": "??", "narration": "smudge", "debit": "5.00"}]}
    parsed = load_statement(PNG, "scan.png", client=fake(bad))
    assert len(parsed.transactions) == 3 and any("unreadable" in w for w in parsed.warnings)


def test_not_a_statement_means_no_rows_and_a_clear_error():
    with pytest.raises(UnreadableFile, match="no transactions could be read"):
        load_statement(PNG, "cat.png", client=fake({"rows": []}))


def test_ai_off_or_mock_mode_explains_why_images_cannot_be_read():
    with pytest.raises(UnreadableFile, match="switched off"):
        load_statement(PNG, "scan.png", client=None)
    with pytest.raises(UnreadableFile, match="offline mock cannot read images"):
        load_statement(PNG, "scan.png", client=MockClient())


def test_scanned_pdf_goes_through_vision_with_the_pdf_attached():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(50, 50, 200, 100)
    c.save()
    client = fake()
    parsed = load_statement(buf.getvalue(), "scan.pdf", client=client)
    assert parsed.meta.layout == "ai-vision" and client.files[0][0][1] == "application/pdf"


def test_pipeline_runs_end_to_end_on_an_image():
    def handler(system, user, task):
        if task == "extract":
            return json.dumps(EXTRACTION)
        from bsi.llm.mock import default_mock_reply
        return default_mock_reply(system, user, task)

    rep = analyze_bytes(PNG, "scan.png", client=MockClient(handler=handler))
    assert len(rep.transactions) == 3 and rep.reconciliation.passed and rep.meta.source_type == "image"
    assert rep.summary.narrative and any("image by an AI model" in w for w in rep.warnings)


def test_pipeline_gives_the_llm_client_to_unknown_layout_mapping():
    """Regression: the client used to be created after parsing, so the mapping never reached the LLM."""
    csv = (b"Posting Date,Details,Withdrawals,Deposits,Closing Bal\n"
           b"05/03/2024,SWIGGY,200.00,,800.00\n06/03/2024,SALARY,,600.00,1400.00\n")
    tasks = []

    def handler(system, user, task):
        tasks.append(task)
        if task == "mapping":
            return json.dumps({"date": "Posting Date", "narration": "Details", "debit": "Withdrawals",
                               "credit": "Deposits", "balance": "Closing Bal", "amount_style": "split"})
        from bsi.llm.mock import default_mock_reply
        return default_mock_reply(system, user, task)

    rep = analyze_bytes(csv, "x.csv", client=MockClient(handler=handler))
    assert "mapping" in tasks and any("inferred by llm" in w for w in rep.warnings)

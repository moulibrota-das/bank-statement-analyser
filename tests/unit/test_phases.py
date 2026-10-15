"""Phase 1 (is it a statement?) -> Phase 2 (unified extraction) -> Phase 3 (analysis)."""
import json

import pytest

from bsi.ingest.loader_types import NotAStatement, UnreadableFile
from bsi.ingest.phases import ingest_document
from bsi.ingest.redact import redact_text
from bsi.ingest.vision import chunk_text
from bsi.llm.client import LLMError, MockClient
from bsi.llm.mock import default_mock_reply
from bsi.pipeline import analyze_bytes
from bsi.schema import StatementReport
from tests.conftest import sample_file

UNKNOWN_CSV = (
    b"Account Holder,TEST PERSON\nAccount Number,50100234567890\nOpening Balance,1000.00\nClosing Balance,1400.00\n\n"
    b"Posting Date,Details,Withdrawals,Deposits,Closing Bal\n"
    b"05/03/2024,UPI/412345678901/SWIGGY/swiggy@icici/Order,200.00,,800.00\n"
    b"06/03/2024,NEFT-X1-ACME PVT LTD-SALARY MAR,,600.00,1400.00\n")

EXTRACTED = {"bank_name": "Test Bank", "account_last4": "7890", "opening_balance": "1000.00",
             "closing_balance": "1400.00",
             "rows": [{"date": "05/03/2024", "narration": "UPI/412345678901/SWIGGY/swiggy@icici/Order",
                       "debit": "200.00", "balance": "800.00"},
                      {"date": "06/03/2024", "narration": "NEFT-X1-ACME PVT LTD-SALARY MAR",
                       "credit": "600.00", "balance": "1400.00"}]}


def scripted(gate=None, extract=EXTRACTED):
    """MockClient whose reply depends on the task, like the real phases."""
    g = gate or {"document_type": "bank_statement", "confidence": 0.95, "reason": "dated rows with balances"}

    def handler(system, user, task):
        if task == "gate":
            return json.dumps(g)
        if task == "extract":
            if isinstance(extract, Exception):
                raise extract
            return json.dumps(extract)
        return default_mock_reply(system, user, task)

    return MockClient(handler=handler)


def tasks(client):
    return [c[2] for c in client.calls]


# ------------------------------------------------------------------ phase 1
def test_non_statement_is_rejected_before_any_extraction():
    c = scripted(gate={"document_type": "invoice_or_receipt", "confidence": 0.93, "reason": "an electricity bill"})
    with pytest.raises(NotAStatement, match="invoice or receipt.*electricity bill"):
        ingest_document(UNKNOWN_CSV, "x.csv", client=c)
    assert tasks(c) == ["gate"]  # nothing else ran


def test_credit_card_statement_is_not_accepted_as_a_bank_statement():
    c = scripted(gate={"document_type": "credit_card_statement", "confidence": 0.9, "reason": "card bill"})
    with pytest.raises(NotAStatement, match="credit card statement"):
        ingest_document(UNKNOWN_CSV, "x.csv", client=c)


def test_unsure_rejection_proceeds_with_a_warning():
    c = scripted(gate={"document_type": "other", "confidence": 0.4, "reason": "hard to tell"})
    res = ingest_document(UNKNOWN_CSV, "x.csv", client=c)
    assert res.check.is_bank_statement is False and len(res.parsed.transactions) == 2


def test_gate_failure_does_not_block_and_is_reported():
    def handler(system, user, task):
        if task == "gate":
            raise LLMError("quota")
        return default_mock_reply(system, user, task)

    res = ingest_document(sample_file("nimbus_a_2024_03").read_bytes(), "x.pdf", client=MockClient(handler=handler))
    assert res.check.method == "unavailable" and any("unavailable" in w for w in res.parsed.warnings)


def test_gate_sees_only_a_redacted_excerpt():
    c = scripted()
    ingest_document(UNKNOWN_CSV, "x.csv", client=c)
    sent = c.calls[0][0] + c.calls[0][1]
    assert "TEST PERSON" not in sent and "50100234567890" not in sent and "XXXXXXXXXX7890" in sent
    assert c.schemas[0].__name__ == "_Gate" and c.calls[0][2] == "gate"


def test_ai_off_skips_the_gate():
    res = ingest_document(sample_file("nimbus_a_2024_03").read_bytes(), "x.pdf", client=None)
    assert res.check.method == "skipped" and res.phases[0].llm_calls == 0


def test_mock_gate_accepts_every_sample_and_rejects_a_letter():
    from bsi.ingest.gate import check_document
    for name in ("nimbus_a_2024_q1", "orchid_b_2024_07", "velocity_c_2024_10", "orchid_b_2024_q2"):
        data = sample_file(name).read_bytes()
        res = ingest_document(data, sample_file(name).name, client=MockClient())
        assert res.check.is_bank_statement, name
    assert not check_document(MockClient(), "Dear customer, your policy renews next month.").is_bank_statement


# ------------------------------------------------------------------ phase 2
def test_known_layout_uses_the_exact_parser_and_never_calls_the_extraction_llm():
    c = scripted()
    res = ingest_document(sample_file("velocity_c_2024_q3").read_bytes(), "x.pdf", client=c)
    assert tasks(c) == ["gate"] and res.parsed.meta.layout == "layout_c_velocity"
    assert [p.name for p in res.phases] == ["document_check", "extraction"]
    assert res.phases[1].method.startswith("parser")


def test_unknown_layout_is_extracted_by_the_llm_from_redacted_text():
    c = scripted()
    res = ingest_document(UNKNOWN_CSV, "x.csv", client=c)
    assert tasks(c) == ["gate", "extract"] and res.phases[1].method == "LLM text extraction"
    sent = c.calls[1][0] + c.calls[1][1]
    assert "TEST PERSON" not in sent and "50100234567890" not in sent
    m = res.parsed.meta
    assert m.layout == "ai-text" and m.source_type == "csv"
    assert m.account_holder == "TEST PERSON"  # restored from the local parse, never sent
    assert m.account_number_masked == "XXXXXXXXXX7890"
    assert [(str(t.amount), t.direction.value) for t in res.parsed.transactions] == [
        ("200.00", "debit"), ("600.00", "credit")]


def test_llm_extraction_failure_falls_back_to_the_heuristic_parser():
    res = ingest_document(UNKNOWN_CSV, "x.csv", client=scripted(extract=LLMError("quota")))
    assert res.phases[1].method == "heuristic parser" and len(res.parsed.transactions) == 2
    assert any("AI extraction failed" in w for w in res.parsed.warnings)


def test_default_mock_uses_the_heuristic_path_for_text_documents():
    res = ingest_document(UNKNOWN_CSV, "x.csv", client=MockClient())
    assert res.phases[1].method == "heuristic parser" and len(res.parsed.transactions) == 2


def test_cross_check_prefers_the_heuristic_parse_when_llm_rows_do_not_reconcile():
    bad = json.loads(json.dumps(EXTRACTED))
    bad["rows"][1]["credit"] = "500.00"  # model misread; balances still say 1,400.00
    res = ingest_document(UNKNOWN_CSV, "x.csv", client=scripted(extract=bad))
    assert res.phases[1].method == "heuristic parser (cross-checked)"
    assert str(res.parsed.transactions[1].amount) == "600.00"
    assert any("did not reconcile" in w for w in res.parsed.warnings)


def test_scanned_input_cannot_be_extracted_offline():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    with pytest.raises(UnreadableFile, match="offline mock cannot read images"):
        ingest_document(png, "scan.png", client=MockClient())
    with pytest.raises(UnreadableFile, match="switched off"):
        ingest_document(png, "scan.png", client=None)


def test_chunking_keeps_lines_whole_and_covers_everything():
    text = "\n".join(f"row {i} " + "x" * 50 for i in range(1000))
    chunks = chunk_text(text, max_chars=5000)
    assert len(chunks) > 5 and "\n".join(chunks) == text
    assert all(len(c) <= 5100 for c in chunks)


def test_redaction():
    t = "Account Holder: AARAV MEHTA\nAccount Number: 5010 0234 5678 90\nUPI to AARAV MEHTA"
    out = redact_text(t)
    assert "AARAV" not in out and "MEHTA" not in out and "50100234567890" not in out.replace(" ", "")
    assert "XXXXXXXXXX7890" in out


# ------------------------------------------------------------------ phase 3 + report
def test_report_carries_all_three_phases_and_the_document_check():
    rep = analyze_bytes(sample_file("nimbus_a_2024_03").read_bytes(), "x.pdf", client=MockClient())
    StatementReport.model_validate_json(rep.model_dump_json())
    assert [p.name for p in rep.processing.phases] == ["document_check", "extraction", "analysis"]
    assert rep.document_check.is_bank_statement and rep.document_check.document_type == "bank_statement"
    assert rep.processing.phases[0].llm_calls == 1 and rep.processing.phases[2].llm_calls >= 1
    assert sum(p.llm_calls for p in rep.processing.phases) == rep.processing.llm_calls


def test_pipeline_rejects_a_non_statement_end_to_end():
    with pytest.raises(NotAStatement):
        analyze_bytes(UNKNOWN_CSV, "x.csv", client=scripted(
            gate={"document_type": "other", "confidence": 0.9, "reason": "a letter"}))

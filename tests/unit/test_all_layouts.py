import json
import re
import sys

import pytest

from bsi.ingest.loader import (
    UnknownLayout,
    UnreadableFile,
    load_statement,
)
from bsi.llm.client import MockClient
from bsi.validate.reconciliation import reconcile
from tests.conftest import SAMPLES, sample_file, sample_names

EXPECTED_LAYOUT = {"A": "layout_a_nimbus", "B": "layout_b_orchid", "C": "layout_c_velocity"}


@pytest.mark.parametrize("name", sample_names())
def test_every_layout_matches_ground_truth(name):
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    path = sample_file(name)
    parsed = load_statement(path.read_bytes(), path.name)
    assert parsed.meta.layout == EXPECTED_LAYOUT[labels["layout"]]
    assert parsed.warnings == [] and len(parsed.transactions) == labels["totals"]["count"]
    for t, lab in zip(parsed.transactions, labels["transactions"], strict=True):
        assert (t.date.isoformat(), str(t.amount), t.direction.value, str(t.balance), t.narration) == (
            lab["date"], lab["amount"], lab["direction"], lab["balance"], lab["narration"])
    assert parsed.meta.account_number_masked == labels["meta"]["account_number_masked"]
    assert str(parsed.meta.opening_balance) == labels["meta"]["opening_balance"]
    assert str(parsed.meta.closing_balance) == labels["meta"]["closing_balance"]
    assert reconcile(parsed.meta, parsed.transactions).passed


def test_at_least_six_statements_three_layouts_and_all_formats():
    names = sample_names()
    assert len(names) >= 6
    layouts = {json.loads((SAMPLES / f"{n}.labels.json").read_text())["layout"] for n in names}
    assert layouts == {"A", "B", "C"}
    assert {sample_file(n).suffix for n in names} == {".pdf", ".csv", ".xlsx"}


def test_layout_c_wrapped_narrations_are_rejoined():
    sys.path.insert(0, str(SAMPLES.parents[1] / "scripts"))
    from generators.layout_c import wrap_narration

    path = sample_file("velocity_c_2024_q3")
    parsed = load_statement(path.read_bytes(), path.name)
    long_ones = [t for t in parsed.transactions if len(t.narration) > 40]
    assert long_ones, "expected narrations long enough to wrap"
    assert all("\n" in wrap_narration(t.narration) for t in long_ones)  # these were printed on 2+ lines
    assert any(re.match(r"^UPI/\d{12}/", t.narration) for t in long_ones)  # '/'-boundary wraps rejoined w/o space


def test_layout_c_is_multipage_with_repeated_headers():
    import io

    import pdfplumber

    data = sample_file("velocity_c_2024_q3").read_bytes()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = len(pdf.pages)
        headers = sum("Particulars" in (p.extract_text() or "") for p in pdf.pages)
    assert pages >= 3 and headers == pages
    parsed = load_statement(data, "x.pdf")
    assert all("Account Statement" not in t.narration and "Page" not in t.narration for t in parsed.transactions)


def test_dr_cr_suffix_direction_and_balance_sign():
    labels = json.loads((SAMPLES / "velocity_c_2024_10.labels.json").read_text())
    parsed = load_statement(sample_file("velocity_c_2024_10").read_bytes(), "x.pdf")
    credits = {t.idx for t in parsed.transactions if t.direction.value == "credit"}
    assert credits == {t["idx"] for t in labels["transactions"] if t["direction"] == "credit"}


def test_csv_with_rupee_symbols_and_preamble():
    raw = sample_file("orchid_b_2024_q2").read_text(encoding="utf-8")
    assert "₹" in raw and raw.splitlines()[2].startswith("Account Holder")
    parsed = load_statement(raw.encode(), "x.csv")
    assert parsed.meta.account_holder == "KARTHIK IYER"


def test_xlsx_numeric_cells_and_date_cells():
    parsed = load_statement(sample_file("orchid_b_2024_07").read_bytes(), "x.xlsx")
    assert parsed.meta.source_type == "xlsx" and parsed.transactions[0].date.year == 2024


def test_forced_layout_name():
    path = sample_file("orchid_b_2024_q2")
    assert load_statement(path.read_bytes(), "x.csv", layout="layout_b_orchid").meta.layout == "layout_b_orchid"
    with pytest.raises(KeyError):
        load_statement(path.read_bytes(), "x.csv", layout="nope")


def test_corrupt_files_raise_clean_errors():
    with pytest.raises(UnreadableFile):
        load_statement(b"%PDF-1.4 this is not really a pdf", "x.pdf")
    with pytest.raises(UnreadableFile):
        load_statement(b"PK\x03\x04garbage", "x.xlsx")
    with pytest.raises(UnknownLayout):
        load_statement(b"hello,world\n1,2\n", "x.csv")


# ---------- unknown layout: LLM proposes a mapping from header labels only
UNKNOWN_CSV = """Account Holder,TEST PERSON
Opening Balance,"1,000.00"
Closing Balance,"1,400.00"

Posting Date,Details,Withdrawals,Deposits,Closing Bal
05/03/2024,UPI/412345678901/SWIGGY/swiggy@icici/Order,200.00,,800.00
06/03/2024,NEFT-X1-ACME PVT LTD-SALARY MAR,,600.00,1400.00
"""


def test_unknown_layout_uses_llm_mapping_of_headers_only_and_code_extracts_values():
    reply = json.dumps({"date": "Posting Date", "narration": "Details", "debit": "Withdrawals",
                         "credit": "Deposits", "balance": "Closing Bal", "amount_style": "split"})
    client = MockClient(responses=[reply])
    parsed = load_statement(UNKNOWN_CSV.encode(), "x.csv", client=client)
    assert [str(t.amount) for t in parsed.transactions] == ["200.00", "600.00"]
    assert [t.direction.value for t in parsed.transactions] == ["debit", "credit"]
    assert parsed.meta.layout == "inferred" and any("inferred by llm" in w for w in parsed.warnings)
    assert reconcile(parsed.meta, parsed.transactions).passed
    sent = " ".join(client.calls[0][:2])
    assert "Posting Date" in sent
    assert "SWIGGY" not in sent and "200.00" not in sent and "TEST PERSON" not in sent  # headers only, no values


def test_bad_llm_mapping_falls_back_to_heuristic():
    bad = json.dumps({"date": "Nonexistent", "narration": "Details", "amount": "Zzz"})
    parsed = load_statement(UNKNOWN_CSV.encode(), "x.csv", client=MockClient(responses=[bad]))
    assert len(parsed.transactions) == 2 and any("heuristic" in w for w in parsed.warnings)


def test_unknown_layout_without_client_uses_heuristic():
    parsed = load_statement(UNKNOWN_CSV.encode(), "x.csv")
    assert len(parsed.transactions) == 2 and parsed.meta.layout == "inferred"


def test_unknown_layout_pdf_is_inferred():
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)
    c.drawString(40, 800, "Opening Balance: 1,000.00")
    c.drawString(40, 788, "Closing Balance: 1,400.00")
    y = 750
    for x, label in ((40, "Posting Date"), (120, "Details"), (320, "Withdrawals"), (400, "Deposits")):
        c.drawString(x, y, label)
    c.drawRightString(540, y, "Closing Bal")
    rows = [("05/03/2024", "UPI/412345678901/SWIGGY/swiggy@icici/Order", "200.00", "", "800.00"),
            ("06/03/2024", "NEFT-X1-ACME PVT LTD-SALARY MAR", "", "600.00", "1,400.00")]
    for r in rows:
        y -= 14
        c.drawString(40, y, r[0])
        c.drawString(120, y, r[1][:30])
        if r[2]:
            c.drawRightString(375, y, r[2])
        if r[3]:
            c.drawRightString(455, y, r[3])
        c.drawRightString(540, y, r[4])
    c.save()
    parsed = load_statement(buf.getvalue(), "x.pdf")
    assert parsed.meta.layout == "inferred" and len(parsed.transactions) == 2
    assert [t.direction.value for t in parsed.transactions] == ["debit", "credit"]

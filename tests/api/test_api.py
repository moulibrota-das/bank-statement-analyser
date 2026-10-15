import json

import pytest
from fastapi.testclient import TestClient

from bsi.api.deps import settings_dep
from bsi.api.main import create_app
from bsi.config import Settings
from bsi.schema import ClassifiedTransaction, StatementReport
from tests.conftest import SAMPLES, sample_file, sample_names


def make_client(**kw) -> TestClient:
    app = create_app()
    settings = Settings(mock=kw.pop("mock", True), **kw)
    app.dependency_overrides[settings_dep] = lambda: settings
    return TestClient(app)


@pytest.fixture
def client():
    return make_client()


def upload(client, path, **params):
    return client.post("/analyze", params=params, files={"file": (path.name, path.read_bytes())})


@pytest.mark.parametrize("name", sample_names())
def test_upload_each_layout(client, name):
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    r = upload(client, sample_file(name))
    assert r.status_code == 200, r.text
    rep = StatementReport.model_validate(r.json())  # response conforms to the schema
    assert rep.reconciliation.passed and len(rep.transactions) == labels["totals"]["count"]
    assert rep.processing.mock_mode is True
    assert str(rep.analytics.total_debits) == labels["totals"]["total_debits"]
    assert rep.meta.account_number_masked == labels["meta"]["account_number_masked"]


def test_money_is_serialized_as_strings_not_floats(client):
    body = upload(client, sample_file("nimbus_a_2024_03")).json()
    assert isinstance(body["analytics"]["total_debits"], str)
    assert isinstance(body["transactions"][0]["amount"], str)


def test_use_llm_false(client):
    r = upload(client, sample_file("nimbus_a_2024_03"), use_llm="false").json()
    assert r["processing"]["llm_calls"] == 0 and r["summary"]["source"] == "template"


def test_layout_param(client):
    assert upload(client, sample_file("orchid_b_2024_q2"), layout="layout_b_orchid").status_code == 200
    r = upload(client, sample_file("orchid_b_2024_q2"), layout="nope")
    assert r.status_code == 400 and "Unknown layout" in r.json()["detail"]


def test_bad_extension_is_415(client):
    r = client.post("/analyze", files={"file": ("notes.txt", b"hello")})
    assert r.status_code == 415 and "PDF, CSV, XLSX or image" in r.json()["detail"]


def test_wrong_content_for_extension_is_415(client):
    r = client.post("/analyze", files={"file": ("fake.pdf", b"\x89PNG\r\n\x00\x00")})
    assert r.status_code == 415


def test_extension_content_mismatch_is_415(client):
    r = client.post("/analyze", files={"file": ("a.csv", sample_file("nimbus_a_2024_q1").read_bytes())})
    assert r.status_code == 415 and "does not match" in r.json()["detail"]


def test_oversized_upload_is_413():
    c = make_client(max_upload_mb=1)
    r = c.post("/analyze", files={"file": ("big.csv", b"a,b\n" + b"x" * (1024 * 1024 + 10))})
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]


def test_empty_file_is_400(client):
    assert client.post("/analyze", files={"file": ("e.csv", b"")}).status_code == 400


def test_corrupt_pdf_is_422(client):
    r = client.post("/analyze", files={"file": ("x.pdf", b"%PDF-1.4 garbage")})
    assert r.status_code == 422 and "Could not parse" in r.json()["detail"]


def test_unknown_layout_csv_is_422(client):
    assert client.post("/analyze", files={"file": ("x.csv", b"a,b\n1,2\n")}).status_code == 422


def test_missing_file_is_422(client):
    assert client.post("/analyze").status_code == 422


def test_full_account_number_not_in_any_response(client):
    path = sample_file("nimbus_a_2024_q1")
    import re

    from bsi.parse.pdf import extract_text
    full = re.search(r"Account Number: (\d{14})", extract_text(path.read_bytes())).group(1)
    assert full not in upload(client, path).text and full not in client.get("/samples/nimbus_a_2024_q1/analyze").text


def test_uploads_are_not_persisted(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    upload(client, sample_file("nimbus_a_2024_03"))
    assert list(tmp_path.iterdir()) == []


def test_samples_list_and_analyze(client):
    lst = client.get("/samples").json()
    assert {s["name"] for s in lst} == set(sample_names()) and len(lst) >= 6
    assert {s["layout"] for s in lst} == {"A", "B", "C"}
    r = client.get(f"/samples/{lst[0]['name']}/analyze")
    assert r.status_code == 200 and StatementReport.model_validate(r.json())


def test_unknown_sample_404_and_no_path_traversal(client):
    assert client.get("/samples/nope/analyze").status_code == 404
    assert client.get("/samples/..%2f..%2fpyproject/analyze").status_code == 404


def test_health_in_mock_mode(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["mode"] == "mock" and h["llm_configured"] is False


def test_health_reports_live_mode_when_key_configured():
    app = create_app()
    live = Settings(mock=False, GEMINI_API_KEY="test-key")
    app.dependency_overrides[settings_dep] = lambda: live
    h = TestClient(app).get("/health").json()
    assert h["llm_configured"] is True and h["mode"] == "live"


def test_classify(client):
    body = {"transactions": [
        {"date": "2024-03-05", "narration": "UPI/412345678901/SWIGGY/swiggy@icici/Order", "amount": "452.00",
         "direction": "debit"},
        {"date": "2024-03-06", "narration": "NEFT-X1-XYZ ENTERPRISES-INV 2231", "amount": "8400.00",
         "direction": "debit"}]}
    r = client.post("/classify", json=body)
    assert r.status_code == 200
    out = [ClassifiedTransaction.model_validate(x) for x in r.json()]
    assert out[0].category.value == "Food" and out[0].category_source.value == "rule"
    assert out[1].category_source.value == "llm"


def test_classify_without_llm_leaves_unresolved_rows(client):
    body = {"use_llm": False, "transactions": [
        {"date": "2024-03-06", "narration": "NEFT-X1-XYZ ENTERPRISES-INV", "amount": "8400", "direction": "debit"}]}
    out = client.post("/classify", json=body).json()
    assert out[0]["category"] == "Other" and out[0]["category_confidence"] == 0


def test_classify_validation(client):
    assert client.post("/classify", json={"transactions": []}).status_code == 400
    assert client.post("/classify", json={"transactions": [{"date": "bad"}]}).status_code == 422
    bad = {"transactions": [{"date": "2024-03-06", "narration": "x", "amount": "-5", "direction": "debit"}]}
    assert client.post("/classify", json=bad).status_code == 422


def test_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv("BSI_CORS_ORIGINS", "http://localhost:3000")
    c = make_client()
    r = c.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "http://evil.example"}).headers


def test_openapi_documents_endpoints_with_examples(client):
    spec = client.get("/openapi.json").json()
    assert {"/analyze", "/classify", "/samples", "/samples/{name}/analyze", "/health"} <= set(spec["paths"])
    assert "example" in spec["components"]["schemas"]["HealthResponse"]
    assert "StatementReport" in spec["components"]["schemas"]
    assert client.get("/docs").status_code == 200


def test_image_upload_is_accepted_but_needs_a_real_model():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    r = make_client().post("/analyze", files={"file": ("scan.png", png)})
    assert r.status_code == 422 and "GEMINI_API_KEY" in r.json()["detail"]
    r = make_client().post("/analyze", params={"use_llm": "false"}, files={"file": ("scan.png", png)})
    assert r.status_code == 422 and "switched off" in r.json()["detail"]


def test_a_document_that_is_not_a_statement_is_rejected_with_the_reason():
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 700, "Dear customer, your insurance policy renews next month.")
    c.save()
    r = make_client().post("/analyze", files={"file": ("letter.pdf", buf.getvalue())})
    assert r.status_code == 422 and "doesn't look like a bank statement" in r.json()["detail"]


def test_report_includes_document_check_and_phases(client):
    body = upload(client, sample_file("nimbus_a_2024_03")).json()
    assert body["document_check"]["is_bank_statement"] is True
    assert [p["name"] for p in body["processing"]["phases"]] == ["document_check", "extraction", "analysis"]


def test_image_extension_must_match_content():
    r = make_client().post("/analyze", files={"file": ("scan.png", sample_file("nimbus_a_2024_q1").read_bytes())})
    assert r.status_code == 415 and "does not match" in r.json()["detail"]

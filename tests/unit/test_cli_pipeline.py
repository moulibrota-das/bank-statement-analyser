import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from bsi.cli import main
from bsi.ingest.loader import load_statement
from bsi.pipeline import analyze_bytes, analyze_file
from bsi.schema import StatementReport
from bsi.validate.reconciliation import reconcile
from tests.conftest import SAMPLES, sample_file, sample_names

ROOT = Path(__file__).resolve().parents[2]


def test_cli_writes_valid_report(tmp_path, capsys):
    out = tmp_path / "report.json"
    code = main(["analyze", str(sample_file("nimbus_a_2024_03")), "--out", str(out), "--mock"])
    assert code == 0
    report = StatementReport.model_validate_json(out.read_text())
    assert report.processing.mock_mode and report.reconciliation.passed
    stdout = capsys.readouterr().out
    assert "MOCK LLM" in stdout and "Reconciliation: PASSED" in stdout


def test_cli_no_llm_makes_zero_calls(tmp_path):
    out = tmp_path / "r.json"
    assert main(["analyze", str(sample_file("nimbus_a_2024_03")), "--out", str(out), "--no-llm", "--quiet"]) == 0
    r = StatementReport.model_validate_json(out.read_text())
    assert r.processing.llm_calls == 0 and r.summary.source == "template"
    assert any("remain unclassified" in w for w in r.warnings)


def test_cli_errors_exit_2(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "missing.pdf")]) == 2
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"\x89PNG\x00\x00")
    assert main(["analyze", str(bad), "--out", str(tmp_path / "o.json")]) == 2
    assert "error:" in capsys.readouterr().err


def test_python_dash_m_entrypoint(tmp_path):
    out = tmp_path / "r.json"
    proc = subprocess.run([sys.executable, "-m", "bsi", "analyze", str(sample_file("velocity_c_2024_10")),
                           "--out", str(out), "--mock", "--quiet"], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_prompt_flag_selects_version(tmp_path):
    out = tmp_path / "r.json"
    main(["analyze", str(sample_file("nimbus_a_2024_03")), "--out", str(out), "--mock", "--prompt", "classify_v1",
          "--quiet"])
    assert StatementReport.model_validate_json(out.read_text()).processing.prompt_version == "classify_v1"


@pytest.mark.parametrize("name", sample_names())
def test_end_to_end_pipeline_on_every_sample(name):
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    report = analyze_file(sample_file(name))
    assert report.reconciliation.passed
    assert str(report.analytics.total_credits) == labels["totals"]["total_credits"]
    assert str(report.analytics.total_debits) == labels["totals"]["total_debits"]
    assert len(report.transactions) == labels["totals"]["count"]
    assert report.summary.faithfulness_passed and report.summary.narrative
    assert all(0 <= t.category_confidence <= 1 for t in report.transactions)
    assert {t.category_source.value for t in report.transactions} <= {"rule", "llm", "manual"}


@pytest.mark.parametrize("name", sample_names())
def test_full_account_number_never_appears_in_report(name):
    path = sample_file(name)
    if path.suffix == ".pdf":
        from bsi.parse.pdf import extract_text
        text = extract_text(path.read_bytes())
    else:
        text = path.read_text(encoding="utf-8") if path.suffix == ".csv" else str(
            [list(r) for r in __import__("bsi.parse.tabular", fromlist=["x"]).read_grid(path.read_bytes(), "xlsx")])
    full = re.search(r"(?:Account Number|A/c No\.)[:,'\" ]+(\d{14})", text).group(1)
    blob = analyze_file(path).model_dump_json()
    assert full not in blob and full[:10] not in blob
    assert full[-4:] in blob  # last four digits survive


def test_corrupted_row_is_reported_in_the_final_report_not_hidden():
    import csv
    import io

    rows = list(csv.reader(io.StringIO(sample_file("orchid_b_2024_q2").read_text(encoding="utf-8"))))
    h = next(n for n, r in enumerate(rows) if r and r[0] == "Txn Date")
    assert rows[h + 3][3].startswith("-")  # a debit; corrupt its amount, leave the printed balances alone
    rows[h + 3][3] = "-\u20b91.00"
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    report = analyze_bytes(buf.getvalue().encode(), "x.csv")
    assert not report.reconciliation.passed
    assert any(x.kind == "running_balance" and x.idx == 2 for x in report.reconciliation.issues)
    assert any(x.kind == "total_mismatch" for x in report.reconciliation.issues)
    assert any("Reconciliation failed" in w for w in report.warnings)


def test_use_llm_false_never_touches_a_client():
    r = analyze_file(sample_file("nimbus_a_2024_q1"), use_llm=False)
    assert r.processing.llm_calls == 0


def test_eval_script_runs_in_mock_mode_and_states_its_mode(tmp_path):
    out = tmp_path / "results.md"
    proc = subprocess.run([sys.executable, str(ROOT / "eval" / "run_eval.py"), "--mock", "--out", str(out)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert "Mode: MOCK" in text and "confusion matrix" in text and "Precision" in text
    assert "Reconciliation pass rate" in text


def test_parsed_statement_roundtrip_reconciles_for_all():
    for name in sample_names():
        p = sample_file(name)
        parsed = load_statement(p.read_bytes(), p.name)
        assert reconcile(parsed.meta, parsed.transactions).passed

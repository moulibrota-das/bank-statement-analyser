import json
from pathlib import Path

import pytest

from bsi.llm.client import MockClient
from bsi.llm.prompts import load_prompt
from bsi.pipeline import analyze_file
from bsi.summarize.faithfulness import check_faithfulness, sentence_count
from bsi.summarize.narrative import build_facts, generate_narrative, template_narrative
from tests.conftest import SAMPLES


@pytest.fixture(scope="module")
def report():
    return analyze_file(SAMPLES / "nimbus_a_2024_q1.pdf")


@pytest.fixture(scope="module")
def facts(report):
    return build_facts(report.meta, report.analytics, report.anomalies, report.reconciliation.passed)


def test_report_totals_match_labels(report):
    labels = json.loads((SAMPLES / "nimbus_a_2024_q1.labels.json").read_text())
    assert str(report.summary.total_credits) == labels["totals"]["total_credits"]
    assert str(report.summary.total_debits) == labels["totals"]["total_debits"]
    assert str(report.reconciliation.expected_closing) == labels["meta"]["closing_balance"]


def test_facts_contain_no_pii(facts, report):
    blob = json.dumps(facts, ensure_ascii=False)
    assert "AARAV" not in blob and "MEHTA" not in blob
    assert report.meta.account_number_masked not in blob and "4177" not in blob


def test_faithfulness_accepts_correct_summary(facts):
    text = template_narrative(facts)
    res = check_faithfulness(text, facts)
    assert res.ok and res.checked >= 4


def test_faithfulness_rejects_made_up_amount(facts):
    good = template_narrative(facts)
    bad = good.replace(facts["display"]["total_debits"], "₹9,99,999.00")
    res = check_faithfulness(bad, facts)
    assert not res.ok and "₹9,99,999.00" in res.unsupported


def test_faithfulness_rejects_made_up_percentage(facts):
    res = check_faithfulness("Food took 77.7% of spending.", facts)
    assert not res.ok and res.unsupported == ["77.7%"]


def test_faithfulness_accepts_amount_formatting_variants(facts):
    total = facts["display"]["total_credits"]  # e.g. ₹1,70,000.00
    plain = total.replace(",", "")
    assert check_faithfulness(f"Credits were {plain}.", facts).ok
    assert check_faithfulness(f"Credits were {plain.split('.')[0]}.", facts).ok is True


def test_faithfulness_ignores_text_without_figures(facts):
    res = check_faithfulness("Spending looked normal.", facts)
    assert res.ok and res.checked == 0


def test_sentence_count_ignores_decimal_points():
    assert sentence_count("Spent ₹1,234.50 today. Saved ₹2.50 more. Done.") == 3


def test_good_llm_summary_is_used(facts):
    good = template_narrative(facts)
    client = MockClient(responses=[json.dumps({"narrative": good})])
    text, source, ok = generate_narrative(facts, client)
    assert source == "llm" and text == good and ok and client.stats.calls == 1


def test_unfaithful_summary_regenerates_once_then_succeeds(facts):
    bad = "Spending was heavy at ₹9,99,999.00 overall. It was high. Be careful."
    good = template_narrative(facts)
    client = MockClient(responses=[json.dumps({"narrative": bad}), json.dumps({"narrative": good})])
    text, source, _ = generate_narrative(facts, client)
    assert source == "llm" and text == good and client.stats.calls == 2
    assert "9,99,999" in client.calls[1][1]  # the rejection reason is fed back


def test_unfaithful_twice_falls_back_to_template(facts):
    bad = json.dumps({"narrative": "You spent ₹9,99,999.00. That is a lot. Cut back. Really."})
    client = MockClient(responses=[bad])
    text, source, ok = generate_narrative(facts, client)
    assert source == "template" and ok and client.stats.calls == 2
    assert check_faithfulness(text, facts).ok


def test_wrong_sentence_count_is_rejected(facts):
    client = MockClient(responses=[json.dumps({"narrative": "One sentence only."})])
    _, source, _ = generate_narrative(facts, client)
    assert source == "template"


def test_no_client_uses_template(facts):
    _, source, _ = generate_narrative(facts, None)
    assert source == "template"


def test_default_mock_summary_is_faithful(report):
    assert report.summary.source == "llm" and report.summary.faithfulness_passed
    assert 3 <= sentence_count(report.summary.narrative) <= 4


@pytest.mark.parametrize(
    "name", ["summary_v1", "summary_v2", "classify_v1", "classify_v2", "classify_v3", "classify_v4"])
def test_prompts_load(name):
    p = load_prompt(name)
    assert p.name == name and p.system and p.user
    assert (p.batch_size == 20) == (name == "classify_v4")


def test_unknown_prompt_version():
    with pytest.raises(FileNotFoundError):
        load_prompt("classify_v99")


def test_prompt_changelog_has_no_invented_scores():
    text = (Path(__file__).resolve().parents[2] / "prompts" / "CHANGELOG.md").read_text()
    assert "TODO" in text

"""Narrative summary. All structured fields are deterministic. The LLM writes only the
3-4 sentence narrative from pre-computed facts, which is verified by faithfulness.py.
On failure: regenerate once, then fall back to a deterministic template."""
from __future__ import annotations

from pydantic import BaseModel

from bsi.config import get_settings
from bsi.llm.client import LLMClient, LLMError, complete_json
from bsi.llm.prompts import load_prompt
from bsi.schema import Analytics, AnomalyFlag, NarrativeSummary, StatementMeta
from bsi.summarize.faithfulness import check_faithfulness, sentence_count
from bsi.util import fmt_inr


class _Narr(BaseModel):
    narrative: str


def _period(meta: StatementMeta) -> str:
    if meta.period_start and meta.period_end:
        return f"{meta.period_start:%d %b %Y} to {meta.period_end:%d %b %Y}"
    return "the statement period"


def build_facts(meta: StatementMeta, a: Analytics, anomalies: list[AnomalyFlag], reconciled: bool) -> dict:
    """The ONLY thing the LLM sees. No account number, no holder name."""
    d = fmt_inr
    return {
        "period": _period(meta),
        "reconciliation_passed": reconciled,
        "display": {"total_credits": d(a.total_credits), "total_debits": d(a.total_debits), "net": d(a.net),
                    "net_abs": d(abs(a.net))},
        "net_direction": "increase" if a.net >= 0 else "decrease",
        "top_categories": [
            {"category": c.category.value, "display_total": d(c.total), "display_pct": f"{c.pct_of_debits}%",
             "pct": c.pct_of_debits, "count": c.count}
            for c in a.spend_by_category[:3]],
        "monthly": [{"month": m.month, "display_credits": d(m.credits), "display_debits": d(m.debits)}
                    for m in a.monthly],
        "recurring": [{"counterparty": r.counterparty, "display_amount": d(r.typical_amount),
                       "occurrences": r.occurrences} for r in a.recurring[:5]],
        "anomalies": [{"code": f.code.value, "severity": f.severity.value, "reason": f.reason}
                      for f in anomalies[:8]],
    }


def template_narrative(facts: dict) -> str:
    d = facts["display"]
    s = [f"Over {facts['period']}, the account received {d['total_credits']} and spent {d['total_debits']}, "
         f"a net {facts['net_direction']} of {d['net_abs']}."]
    cats = facts["top_categories"]
    if cats:
        parts = [f"{c['category']} ({c['display_total']}, {c['display_pct']})" for c in cats]
        s.append("Most spending went to " + ", ".join(parts) + ".")
    n = len(facts["anomalies"])
    s.append(f"{n} transaction(s) were flagged as unusual and are listed below for review." if n
             else "No unusual transactions were flagged.")
    if not facts["reconciliation_passed"]:
        s.append("Note that the statement's running balances did not fully reconcile; see the report for details.")
    return " ".join(s)


def generate_narrative(facts: dict, client: LLMClient | None,
                       prompt_version: str | None = None) -> tuple[str, str, bool]:
    """Returns (text, source 'llm'|'template', faithfulness_passed)."""
    import json

    if client is None:
        return template_narrative(facts), "template", True
    prompt = load_prompt(prompt_version or get_settings().summary_prompt)
    base_user = prompt.render_user(facts_json=json.dumps(facts, indent=1, ensure_ascii=False))
    user = base_user
    for _ in range(2):  # first try + one regeneration
        try:
            text = complete_json(client, prompt.system, user, _Narr, task="summary").narrative.strip()
        except LLMError:
            break
        res = check_faithfulness(text, facts)
        if res.ok and 3 <= sentence_count(text) <= 4:
            return text, "llm", True
        problems = (f"these figures are not in the facts: {', '.join(res.unsupported)}" if not res.ok
                    else f"it had {sentence_count(text)} sentences; write exactly 3 or 4")
        user = (f"{base_user}\n\nYour previous attempt was rejected: {problems}. "
                "Rewrite it using only figures from the facts.")
    return template_narrative(facts), "template", True


def build_summary(meta: StatementMeta, a: Analytics, anomalies: list[AnomalyFlag], reconciled: bool,
                  client: LLMClient | None, prompt_version: str | None = None) -> NarrativeSummary:
    facts = build_facts(meta, a, anomalies, reconciled)
    text, source, ok = generate_narrative(facts, client, prompt_version)
    bits = [meta.bank_name or "Bank account"]
    if meta.account_number_masked:
        bits.append(f"a/c {meta.account_number_masked}")
    if meta.account_holder:
        bits.append(meta.account_holder)
    if meta.branch:
        bits.append(meta.branch)
    return NarrativeSummary(
        account_summary=", ".join(bits), period=_period(meta),
        total_credits=a.total_credits, total_debits=a.total_debits,
        major_spending=a.spend_by_category[:3],
        unusual_transactions=[f"[{f.severity.value.upper()}] {f.code.value}: {f.reason}" for f in anomalies],
        narrative=text, source=source, faithfulness_passed=ok)


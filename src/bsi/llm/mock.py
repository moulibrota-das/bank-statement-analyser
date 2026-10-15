"""Deterministic offline stand-in for the LLM. It is a small heuristic stub, NOT a model:
mock-mode numbers verify the plumbing and say nothing about real model quality."""
from __future__ import annotations

import json
import re

from bsi.llm.client import extract_json

_COMPANY = re.compile(r"\b(llp|ltd|pvt|limited|technologies|systems|analytics|infotech|studios|solutions)\b", re.I)


def _guess(item: dict) -> tuple[str, float, str]:
    n = str(item.get("narration", "")).lower()
    amount = float(item.get("amount", 0))
    direction = item.get("direction", "debit")
    channel = str(item.get("channel", "")).upper()
    cp = str(item.get("counterparty") or "")
    if "credit card" in n or "wallet" in n:
        return "Transfers", 0.7, "card bill or wallet top-up"
    if "aws" in n or "web services" in n:
        return "Other", 0.7, "cloud/business charge"
    if "amazon" in n:
        return "Shopping", 0.6, "Amazon purchase"
    if direction == "credit" and amount >= 20000 and channel in ("NEFT", "RTGS", "ACH") and _COMPANY.search(cp):
        return "Salary", 0.7, "large credit from a company"
    if direction == "debit" and channel == "UPI" and amount >= 10000 and item.get("recurring_hint"):
        return "Rent", 0.75, "large recurring payment to an individual"
    if direction == "debit" and channel == "UPI" and amount >= 10000:
        return "Rent", 0.55, "large UPI payment to an individual"
    if direction == "debit" and channel in ("UPI", "IMPS"):
        return "Transfers", 0.6, "payment to an individual"
    return "Other", 0.3, "no clear signal"


def _mock_gate(user: str) -> dict:
    """Offline stand-in for the document check: counts dated rows that carry an amount."""
    from bsi.llm.client import LLMError

    m = re.search(r"```text\s*(.*?)```", user, re.DOTALL)
    if not m:
        raise LLMError("the offline mock cannot look at images")
    date = re.compile(r"\d{1,2}[-/ .](?:\d{1,2}|[A-Za-z]{3})[-/ .]\d{2,4}|\d{4}-\d{2}-\d{2}")
    money = re.compile(r"\d[\d,]*\.\d{2}|\b\d{3,}\b")
    rows = [ln for ln in m.group(1).splitlines() if date.search(ln) and money.search(ln)]
    ok = len(rows) >= 2
    return {"is_bank_statement": ok, "confidence": 0.8 if ok else 0.7,
            "document_type": "bank_statement" if ok else "other",
            "reason": f"{len(rows)} dated rows with amounts found" if ok else "no table of dated amounts found"}


def default_mock_reply(system: str, user: str, task: str) -> str:
    if task == "gate":
        return json.dumps(_mock_gate(user))
    if task == "extract":
        from bsi.llm.client import LLMError

        raise LLMError("the offline mock cannot read images; configure GEMINI_API_KEY to use image extraction")
    if task == "classify":
        m = re.search(r"```json\s*(.*?)```", user, re.DOTALL)
        if m:
            items = extract_json(m.group(1))
            out = []
            for it in items:  # type: ignore[union-attr]
                cat, conf, why = _guess(it)
                out.append({"id": it["id"], "category": cat, "confidence": conf, "rationale": why})
            return json.dumps({"results": out})
        line = user.split(":", 1)[-1]
        parts = [p.strip() for p in line.split("|")]
        cat, _, why = _guess({"narration": parts[0], "amount": parts[1] if len(parts) > 1 else 0,
                              "direction": parts[2] if len(parts) > 2 else "debit"})
        return f"This looks like {cat}. {why.capitalize()}."
    if task == "summary":
        m = re.search(r"```json\s*(.*?)```", user, re.DOTALL)
        facts = extract_json(m.group(1)) if m else {}
        return json.dumps({"narrative": mock_narrative(facts)})  # type: ignore[arg-type]
    if task == "mapping":
        from bsi.ingest.mapping import heuristic_mapping

        m = re.search(r"```json\s*(.*?)```", user, re.DOTALL)
        payload = extract_json(m.group(1)) if m else {}
        return json.dumps(heuristic_mapping(payload))  # type: ignore[arg-type]
    return "{}"


def mock_narrative(facts: dict) -> str:
    d = facts.get("display", {})
    s = [f"Over {facts.get('period', 'the statement period')}, the account received {d.get('total_credits')} "
         f"and spent {d.get('total_debits')}, a net change of {d.get('net')}."]
    cats = facts.get("top_categories", [])
    if cats:
        top = cats[0]
        s.append(f"The largest spending category was {top['category']} at {top['display_total']} "
                 f"({top['display_pct']} of debits).")
    n = len(facts.get("anomalies", []))
    s.append(f"{n} transaction(s) were flagged for review." if n else "No unusual transactions were flagged.")
    return " ".join(s)

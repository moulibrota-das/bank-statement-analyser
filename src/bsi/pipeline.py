"""End-to-end orchestration: parse -> enrich -> classify -> analytics -> anomalies -> summary."""
from __future__ import annotations

import time
from pathlib import Path

from bsi.analytics.summaries import compute_analytics
from bsi.anomalies.detectors import detect_all
from bsi.classify.cache import LLMCache
from bsi.classify.llm_classifier import LLMClassifier
from bsi.classify.recurring import apply_recurring, detect_recurring, to_payments
from bsi.classify.rules import apply_rules, is_unresolved
from bsi.config import Settings, get_settings
from bsi.enrich.narration import enrich
from bsi.ingest.loader import load_statement
from bsi.llm.client import BaseClient, make_client
from bsi.schema import ProcessingInfo, StatementReport
from bsi.summarize.narrative import build_summary
from bsi.validate.reconciliation import reconcile


def analyze_bytes(data: bytes, filename: str = "", *, use_llm: bool = True, layout: str | None = None,
                  settings: Settings | None = None, client: BaseClient | None = None,
                  cache: LLMCache | None = None) -> StatementReport:
    start = time.perf_counter()
    settings = settings or get_settings()
    llm: BaseClient | None = (client or make_client(settings)) if use_llm else None
    parsed = load_statement(data, filename, layout, client=llm)
    meta, txns, warnings = parsed.meta, parsed.transactions, list(parsed.warnings)
    enrich(txns)

    recon = reconcile(meta, txns)
    if not recon.passed:
        warnings.append(f"Reconciliation failed with {len(recon.issues)} issue(s); see 'reconciliation'.")

    apply_rules(txns)
    groups = detect_recurring(txns)
    apply_recurring(txns, groups)

    calls = cache_hits = 0
    if use_llm and llm is not None:
        stats = LLMClassifier(llm, settings.classify_prompt, cache).classify(txns, holder=meta.account_holder)
        calls, cache_hits = stats.llm_calls, stats.cache_hits
        if stats.failures:
            warnings.append(f"{stats.failures} row(s) could not be classified by the LLM and were left as Other.")
    else:
        for t in txns:
            if is_unresolved(t):
                t.category_rationale = "unresolved by rules (LLM disabled)"
    n_unres = sum(1 for t in txns if is_unresolved(t))
    if n_unres:
        warnings.append(f"{n_unres} row(s) remain unclassified (category Other, confidence 0).")

    analytics = compute_analytics(txns, to_payments(txns, groups))
    anomalies = detect_all(txns)
    summary = build_summary(meta, analytics, anomalies, recon.passed, llm, settings.summary_prompt)
    calls = llm.stats.calls if llm else 0

    return StatementReport(
        meta=meta, transactions=txns, reconciliation=recon, analytics=analytics, anomalies=anomalies,
        summary=summary,
        processing=ProcessingInfo(
            mock_mode=llm.mock if llm else settings.mock_mode, llm_calls=calls, cache_hits=cache_hits,
            prompt_version=settings.classify_prompt if use_llm else None,
            elapsed_ms=int((time.perf_counter() - start) * 1000)),
        warnings=warnings)


def analyze_file(path: str | Path, **kw) -> StatementReport:
    p = Path(path)
    return analyze_bytes(p.read_bytes(), p.name, **kw)

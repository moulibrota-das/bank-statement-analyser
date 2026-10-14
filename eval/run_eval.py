"""Evaluate the pipeline against synthetic ground truth and write eval/results.md.

    python eval/run_eval.py --mock          # offline; LLM numbers come from a heuristic stub
    python eval/run_eval.py --live          # real model; needs GEMINI_API_KEY
Nothing here is hard-coded: every number in results.md is computed by this run."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bsi.classify.cache import LLMCache  # noqa: E402
from bsi.classify.llm_classifier import LLMClassifier  # noqa: E402
from bsi.classify.recurring import apply_recurring, detect_recurring  # noqa: E402
from bsi.classify.rules import apply_rules  # noqa: E402
from bsi.config import Settings  # noqa: E402
from bsi.enrich.narration import enrich  # noqa: E402
from bsi.ingest.loader import load_statement  # noqa: E402
from bsi.llm.client import BaseClient, MockClient, make_client  # noqa: E402
from bsi.pipeline import analyze_bytes  # noqa: E402
from bsi.schema import Category  # noqa: E402
from bsi.validate.reconciliation import reconcile  # noqa: E402

DATA = ROOT / "data" / "synthetic"
CATS = [c.value for c in Category]


def statements() -> list[tuple[Path, dict]]:
    out = []
    for lab in sorted(DATA.glob("*.labels.json")):
        name = lab.name.removesuffix(".labels.json")
        f = next(p for p in DATA.glob(f"{name}.*") if not p.name.endswith(".labels.json"))
        out.append((f, json.loads(lab.read_text())))
    return out


# ---------- extraction
def extraction_accuracy(path: Path, labels: dict) -> tuple[int, int, bool]:
    parsed = load_statement(path.read_bytes(), path.name)
    m, lm = parsed.meta, labels["meta"]
    pairs = [
        (m.account_holder, lm["account_holder"]), (m.account_number_masked, lm["account_number_masked"]),
        (m.ifsc, lm["ifsc"]), (m.branch, lm["branch"]),
        (str(m.period_start), lm["period_start"]), (str(m.period_end), lm["period_end"]),
        (str(m.opening_balance), lm["opening_balance"]), (str(m.closing_balance), lm["closing_balance"]),
    ]
    ok = sum(a == b for a, b in pairs)
    total = len(pairs)
    by_idx = {t.idx: t for t in parsed.transactions}
    for lt in labels["transactions"]:
        t = by_idx.get(lt["idx"])
        got = (t.date.isoformat(), str(t.amount), t.direction.value, str(t.balance), t.narration) if t else None
        want = (lt["date"], lt["amount"], lt["direction"], lt["balance"], lt["narration"])
        for i in range(5):
            total += 1
            ok += bool(got and got[i] == want[i])
    return ok, total, reconcile(parsed.meta, parsed.transactions).passed


# ---------- classification
def prepare(path: Path):
    parsed = load_statement(path.read_bytes(), path.name)
    txns = enrich(parsed.transactions)
    apply_rules(txns)
    apply_recurring(txns, detect_recurring(txns))
    return parsed.meta, txns


def classify(path: Path, mode: str, client: BaseClient, prompt: str, cache: LLMCache):
    meta, txns = prepare(path)
    calls = hits = 0
    if mode != "rules":
        before = client.stats.calls
        st = LLMClassifier(client, prompt, cache).classify(txns, holder=meta.account_holder,
                                                           only_unresolved=(mode == "hybrid"))
        calls, hits = client.stats.calls - before, st.cache_hits
    return txns, calls, hits


def macro_f1(y_true: list[str], y_pred: list[str]) -> tuple[float, dict[str, tuple[float, float, float]]]:
    per = {}
    for c in sorted(set(y_true) | set(y_pred)):
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per[c] = (prec, rec, 2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(v[2] for v in per.values()) / len(per), per


@dataclass
class ModeResult:
    y_true: list[str] = field(default_factory=list)
    y_pred: list[str] = field(default_factory=list)
    ambiguous: list[bool] = field(default_factory=list)
    calls: list[int] = field(default_factory=list)
    hits: list[int] = field(default_factory=list)
    llm_rows: int = 0

    def acc(self, only_ambiguous: bool = False) -> float:
        pairs = [(t, p) for t, p, a in zip(self.y_true, self.y_pred, self.ambiguous, strict=True)
                 if a or not only_ambiguous]
        return sum(t == p for t, p in pairs) / len(pairs) if pairs else 0.0


def run_classification(sts, client: BaseClient, prompt: str, modes=("rules", "llm", "hybrid")) -> dict[str, ModeResult]:
    res = {m: ModeResult() for m in modes}
    for path, labels in sts:
        for m in modes:
            txns, calls, hits = classify(path, m, client, prompt, LLMCache())
            r = res[m]
            r.calls.append(calls)
            r.hits.append(hits)
            for t, lt in zip(txns, labels["transactions"], strict=True):
                r.y_true.append(lt["category"])
                r.y_pred.append(t.category.value)
                r.ambiguous.append(lt["ambiguous"])
    return res


def confusion(y_true, y_pred) -> str:
    cm: dict[tuple[str, str], int] = Counter(zip(y_true, y_pred, strict=True))
    head = "| true \\ pred | " + " | ".join(CATS) + " |\n|---|" + "---|" * len(CATS) + "\n"
    rows = ["| **" + t + "** | " + " | ".join(str(cm.get((t, p), 0)) or "." for p in CATS) + " |" for t in CATS]
    return head + "\n".join(rows)


# ---------- anomalies
def anomaly_scores(sts) -> tuple[float, float, list[str]]:
    tp_must = must_total = tp_flags = fp = 0
    notes = []
    for path, labels in sts:
        rep = analyze_bytes(path.read_bytes(), path.name, settings=Settings(mock=True))
        exp = labels["expected_anomalies"]
        must = [e for e in exp if not e["acceptable_extra"]]
        extra = [e for e in exp if e["acceptable_extra"]]
        hit = set()
        for f in rep.anomalies:
            def match(e, f=f):
                return e["code"] == f.code.value and set(e["txn_idx"]) & set(f.txn_idx)
            m = next((i for i, e in enumerate(must) if match(e)), None)
            if m is not None:
                hit.add(m)
                tp_flags += 1
            elif any(match(e) for e in extra):
                continue
            else:
                fp += 1
                notes.append(f"{labels['name']}: unexpected {f.code.value} on txn {f.txn_idx}")
        for i, e in enumerate(must):
            if i not in hit:
                notes.append(f"{labels['name']}: MISSED {e['code']} on txn {e['txn_idx']}")
        tp_must += len(hit)
        must_total += len(must)
    precision = tp_flags / (tp_flags + fp) if tp_flags + fp else 1.0
    return precision, tp_must / must_total if must_total else 1.0, notes


# ---------- main
def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--mock", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--prompt", default="classify_v4")
    ap.add_argument("--compare-prompts", action="store_true", help="also evaluate classify_v1..v4")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results.md")
    args = ap.parse_args()
    settings = Settings(mock=True) if args.mock or not args.live else Settings(mock=False)
    if args.live and settings.mock_mode:
        sys.exit("--live requires GEMINI_API_KEY")
    mock = settings.mock_mode
    client = make_client(settings)
    sts = statements()
    L: list[str] = []

    L.append("# Evaluation results\n")
    if mock:
        L.append("> **Mode: MOCK (offline).** LLM-dependent numbers (LLM-only, hybrid, summaries, LLM calls) come from a "
                 "deterministic heuristic *stub*, not a language model, and must not be read as model quality. "
                 "Extraction, rules-only classification, reconciliation and anomaly numbers are independent of the LLM.\n")
    else:
        L.append(f"> **Mode: LIVE** (model `{settings.llm_model}`, prompt `{args.prompt}`).\n")
    L.append(f"Generated {time.strftime('%Y-%m-%d %H:%M')} from {len(sts)} synthetic statements "
             f"({sum(len(lb['transactions']) for _, lb in sts)} transactions). Reproduce: "
             f"`python eval/run_eval.py {'--mock' if mock else '--live'}`.\n")

    # extraction
    L.append("## Extraction\n\n| Statement | Layout | Fields correct | Accuracy | Reconciles |\n|---|---|---|---|---|")
    ok_t = tot_t = rec_n = 0
    for path, lb in sts:
        ok, tot, rec = extraction_accuracy(path, lb)
        ok_t, tot_t, rec_n = ok_t + ok, tot_t + tot, rec_n + rec
        L.append(f"| {lb['name']} | {lb['layout']} ({path.suffix[1:]}) | {ok}/{tot} | {pct(ok / tot)} | {'yes' if rec else 'NO'} |")
    L.append(f"\n**Field-level accuracy: {pct(ok_t / tot_t)} ({ok_t}/{tot_t}). "
             f"Reconciliation pass rate: {pct(rec_n / len(sts))} ({rec_n}/{len(sts)}).**\n")

    # classification
    res = run_classification(sts, client, args.prompt)
    n_stm = len(sts)
    L.append(f"## Classification (prompt `{args.prompt}`)\n")
    L.append("| Mode | Accuracy (all rows) | Accuracy (ambiguous rows) | Macro-F1 | LLM calls / statement |\n|---|---|---|---|---|")
    labels_names = {"rules": "Rules only", "llm": "LLM only", "hybrid": "Hybrid (rules → LLM)"}
    for m in ("rules", "llm", "hybrid"):
        r = res[m]
        f1, _ = macro_f1(r.y_true, r.y_pred)
        L.append(f"| {labels_names[m]} | {pct(r.acc())} | {pct(r.acc(True))} | {f1:.3f} | {sum(r.calls) / n_stm:.1f} |")
    h = res["hybrid"]
    _, per = macro_f1(h.y_true, h.y_pred)
    L.append("\n**Hybrid per-class precision / recall / F1**\n\n| Category | P | R | F1 | Support |\n|---|---|---|---|---|")
    sup = Counter(h.y_true)
    for c in CATS:
        if c in per:
            p, rr, f = per[c]
            L.append(f"| {c} | {p:.2f} | {rr:.2f} | {f:.2f} | {sup.get(c, 0)} |")
    L.append("\n**Hybrid confusion matrix (rows = truth, columns = prediction)**\n\n" + confusion(h.y_true, h.y_pred))
    wrong = defaultdict(int)
    for t, p in zip(h.y_true, h.y_pred, strict=True):
        if t != p:
            wrong[(t, p)] += 1
    if wrong:
        L.append("\nMost common hybrid errors: " + ", ".join(
            f"{t}→{p} ×{n}" for (t, p), n in sorted(wrong.items(), key=lambda kv: -kv[1])[:5]) + ".")

    # anomalies
    prec, rec, notes = anomaly_scores(sts)
    L.append(f"\n## Anomalies\n\n**Precision {pct(prec)} · Recall {pct(rec)}** "
             "(matching on code + overlapping transaction; flags matching a labelled *acceptable extra* are ignored).\n")
    L += [f"- {n}" for n in notes] or ["- no misses or unexpected flags"]

    # summary + cost
    L.append("\n## Summary faithfulness, LLM usage and latency\n")
    llm_ok = latency = 0.0
    calls = hits = unresolved = 0
    for path, _lb in sts:
        c = make_client(settings)
        t0 = time.perf_counter()
        rep = analyze_bytes(path.read_bytes(), path.name, settings=settings, client=c)
        latency += time.perf_counter() - t0
        llm_ok += rep.summary.source == "llm" and rep.summary.faithfulness_passed
        calls += rep.processing.llm_calls
        hits += rep.processing.cache_hits
        unresolved += sum(1 for t in rep.transactions if t.category_source.value == "llm")
    L.append("| Metric | Value |\n|---|---|")
    L.append(f"| LLM narrative accepted (passed faithfulness; no template fallback) | {int(llm_ok)}/{n_stm} = {pct(llm_ok / n_stm)} |")
    L.append(f"| LLM calls per statement (classification + summary) | {calls / n_stm:.1f} |")
    L.append(f"| Rows classified by LLM per statement | {unresolved / n_stm:.1f} |")
    L.append(f"| Cache hits per statement | {hits / n_stm:.1f} |")
    L.append(f"| Cache hit rate within a statement (hits / rows sent to LLM path) | {pct(hits / unresolved) if unresolved else 'n/a'} |")
    L.append(f"| End-to-end latency per statement | {1000 * latency / n_stm:.0f} ms{' (mock LLM, no network)' if mock else ''} |")

    # prompt comparison
    if args.compare_prompts:
        L.append("\n## Prompt versions (hybrid mode)\n\n| Prompt | Accuracy | Ambiguous acc. | Macro-F1 | LLM calls / statement |\n|---|---|---|---|---|")
        for v in ("classify_v1", "classify_v2", "classify_v3", "classify_v4"):
            r = run_classification(sts, make_client(settings) if not mock else MockClient(), v, modes=("hybrid",))["hybrid"]
            L.append(f"| {v} | {pct(r.acc())} | {pct(r.acc(True))} | {macro_f1(r.y_true, r.y_pred)[0]:.3f} | {sum(r.calls) / n_stm:.1f} |")
        if mock:
            L.append("\n*Mock stub: its answers depend only on the fields a prompt exposes (v1/v2 omit channel and "
                     "counterparty), and it was written with knowledge of the synthetic data, so these accuracies are "
                     "optimistic and NOT evidence about prompt quality. Only the call counts (batching) are meaningful. "
                     "Run `make eval-live` for real prompt comparisons.*")

    args.out.write_text("\n".join(L) + "\n")
    print(f"wrote {args.out} ({'mock' if mock else 'live'} mode)")


if __name__ == "__main__":
    main()

# Evaluation results

> **Mode: MOCK (offline).** LLM-dependent numbers (LLM-only, hybrid, summaries, LLM calls) come from a deterministic heuristic *stub*, not a language model, and must not be read as model quality. Extraction, rules-only classification, reconciliation and anomaly numbers are independent of the LLM.

Generated 2026-10-14 12:25 from 6 synthetic statements (273 transactions). Reproduce: `python eval/run_eval.py --mock`.

## Extraction

| Statement | Layout | Fields correct | Accuracy | Reconciles |
|---|---|---|---|---|
| nimbus_a_2024_03 | A (pdf) | 158/158 | 100.0% | yes |
| nimbus_a_2024_q1 | A (pdf) | 273/273 | 100.0% | yes |
| orchid_b_2024_07 | B (xlsx) | 148/148 | 100.0% | yes |
| orchid_b_2024_q2 | B (csv) | 393/393 | 100.0% | yes |
| velocity_c_2024_10 | C (pdf) | 153/153 | 100.0% | yes |
| velocity_c_2024_q3 | C (pdf) | 288/288 | 100.0% | yes |

**Field-level accuracy: 100.0% (1413/1413). Reconciliation pass rate: 100.0% (6/6).**

## Classification (prompt `classify_v4`)

| Mode | Accuracy (all rows) | Accuracy (ambiguous rows) | Macro-F1 | LLM calls / statement |
|---|---|---|---|---|
| Rules only | 85.0% | 39.1% | 0.825 | 0.0 |
| LLM only | 25.6% | 87.0% | 0.365 | 2.0 |
| Hybrid (rules → LLM) | 98.5% | 91.3% | 0.964 | 1.0 |

**Hybrid per-class precision / recall / F1**

| Category | P | R | F1 | Support |
|---|---|---|---|---|
| Salary | 1.00 | 1.00 | 1.00 | 10 |
| Rent | 1.00 | 1.00 | 1.00 | 10 |
| Utilities | 1.00 | 1.00 | 1.00 | 30 |
| Shopping | 1.00 | 1.00 | 1.00 | 41 |
| Food | 1.00 | 1.00 | 1.00 | 71 |
| Travel | 1.00 | 1.00 | 1.00 | 46 |
| Transfers | 1.00 | 0.93 | 0.96 | 59 |
| Other | 0.60 | 1.00 | 0.75 | 6 |

**Hybrid confusion matrix (rows = truth, columns = prediction)**

| true \ pred | Salary | Rent | Utilities | Shopping | Food | Travel | Transfers | Other |
|---|---|---|---|---|---|---|---|---|
| **Salary** | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Rent** | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Utilities** | 0 | 0 | 30 | 0 | 0 | 0 | 0 | 0 |
| **Shopping** | 0 | 0 | 0 | 41 | 0 | 0 | 0 | 0 |
| **Food** | 0 | 0 | 0 | 0 | 71 | 0 | 0 | 0 |
| **Travel** | 0 | 0 | 0 | 0 | 0 | 46 | 0 | 0 |
| **Transfers** | 0 | 0 | 0 | 0 | 0 | 0 | 55 | 4 |
| **Other** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |

Most common hybrid errors: Transfers→Other ×4.

## Anomalies

**Precision 86.7% · Recall 100.0%** (matching on code + overlapping transaction; flags matching a labelled *acceptable extra* are ignored).

- orchid_b_2024_q2: unexpected AMOUNT_OUTLIER on txn [23]
- velocity_c_2024_q3: unexpected AMOUNT_OUTLIER on txn [20]

## Summary faithfulness, LLM usage and latency

| Metric | Value |
|---|---|
| LLM narrative accepted (passed faithfulness; no template fallback) | 6/6 = 100.0% |
| LLM calls per statement (classification + summary) | 2.0 |
| Rows classified by LLM per statement | 7.5 |
| Cache hits per statement | 0.0 |
| Cache hit rate within a statement (hits / rows sent to LLM path) | 0.0% |
| End-to-end latency per statement | 155 ms (mock LLM, no network) |

## Prompt versions (hybrid mode)

| Prompt | Accuracy | Ambiguous acc. | Macro-F1 | LLM calls / statement |
|---|---|---|---|---|
| classify_v1 | 87.2% | 65.2% | 0.840 | 7.5 |
| classify_v2 | 87.2% | 65.2% | 0.840 | 7.5 |
| classify_v3 | 98.5% | 91.3% | 0.964 | 7.5 |
| classify_v4 | 98.5% | 91.3% | 0.964 | 1.0 |

*Mock stub: its answers depend only on the fields a prompt exposes (v1/v2 omit channel and counterparty), and it was written with knowledge of the synthetic data, so these accuracies are optimistic and NOT evidence about prompt quality. Only the call counts (batching) are meaningful. Run `make eval-live` for real prompt comparisons.*

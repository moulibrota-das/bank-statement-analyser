# Prompt changelog

Each version records what changed, why, and the eval score. **Scores marked TODO have not been measured
live yet**; nothing here is invented. Run `make eval-live` (needs `GEMINI_API_KEY`) to fill them in,
and `make eval` for the offline mock run, whose LLM numbers come from a heuristic stub and say nothing
about model quality.

| Version | Change | Why | Classification acc. (hybrid, live) | Macro-F1 (live) | LLM calls / statement |
|---|---|---|---|---|---|
| classify_v1 | Naive "Categorize this bank transaction", free-text answer, 1 row per call | Baseline | TODO | TODO | TODO |
| classify_v2 | Fixed category list + JSON schema | v1 free text needed fuzzy parsing and could return categories outside the enum | TODO | TODO | TODO |
| classify_v3 | Few-shot examples + parsed channel/counterparty as context, rationale field | Give the model the parsed structure instead of making it re-derive it from the raw string | TODO | TODO | TODO |
| classify_v4 | Batching (20/call), recurring hints, "Other when unsure", confidence | Cut calls ~20x, use deterministic recurring evidence, make abstention explicit | TODO | TODO | TODO |

| Version | Change | Why | Faithfulness rate (live) |
|---|---|---|---|
| summary_v1 | "Write a summary in 3-4 sentences" over the facts JSON | Baseline | TODO |
| summary_v2 | Strict rules: copy amounts/percentages verbatim from `display` strings, never compute, no speculation | v1 is free to round or derive numbers, which the faithfulness check rejects | TODO |

## Mock-mode results (offline stub, for pipeline verification only)
See `eval/results.md` once generated; the header states which mode produced it.

## Extraction prompt

| Version | Change | Why | Live field accuracy |
|---|---|---|---|
| extract_v1 | Vision transcription of an image or scanned PDF into the unified structure. Copy-only rules; account number as last 4 digits only | Images have no text layer. The model only transcribes strings; code parses amounts/dates and reconciliation checks the result | TODO (no live run yet; needs real scans) |
| gate_v1 | Phase 1 document check: classify as bank statement / credit card statement / invoice or receipt / other, with confidence and reason | Reject non-statements before spending extraction effort | TODO (no live run yet) |

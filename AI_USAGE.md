# AI usage

## AI tools used to build this project

- **Claude Code (Claude Sonnet 5.5)** wrote the first implementation from a detailed specification: schema, parsers,
  synthetic data generator, classifier, anomaly detectors, prompts, API, UI, tests and docs, committed phase
  by phase with tests and lint run after each.

### In my own words (to be filled in by the author)

_TODO: which tools you used, for what, what you reviewed or changed by hand, what you verified yourself,
and what you would do differently._

## How the runtime uses an LLM

All JSON replies use Gemini **structured output**: the request carries the pydantic response model as
`response_schema` with `response_mime_type=application/json`, so decoding is constrained to the schema. The
reply is still validated with pydantic and retried once on failure.

The LLM is used in exactly three places; everything else is deterministic code.

| Use | Input sent | Output | Safeguards |
|---|---|---|---|
| Classify rows the rules could not resolve | Per row: date, narration, amount, direction, parsed channel, counterparty, optional "recurring" hint | `{id, category, confidence, rationale}` | Category constrained to the enum (pydantic); retry once on invalid JSON; confidence < 0.4 → `Other`; results cached by counterparty |
| Propose a column mapping for an unknown layout | **Header labels only** | Which header is date / narration / debit / … | Labels validated against the file; code extracts all values; falls back to a keyword heuristic |
| Write the 3–4 sentence narrative | A facts JSON of already-computed figures | `{"narrative": "..."}` | Every ₹ amount and % checked against the facts; regenerate once; else deterministic template |

### What is sent

- Narration text (with runs of 9+ digits replaced by `#`, and the account holder's name replaced by
  `ACCOUNT_HOLDER`), amount, direction, date, parsed channel and counterparty.
- For the summary: aggregate facts (period, totals, top categories, anomaly reasons, recurring payments).
- For layout inference: column header labels.

### What is never sent

- Account numbers (masked at parse time; the unmasked value is never stored in the data model).
- Account holder name, IFSC, branch, or any other statement metadata.
- Raw files, and any row the rules already classified.

Narration text can still contain third-party names (UPI payees) and merchant names; that is inherent to
classifying them. In mock mode (no API key) nothing leaves the process.

Tests assert these guarantees (`tests/ambiguous/test_llm_classification.py::test_pii_is_not_sent`,
`tests/unit/test_summary.py::test_facts_contain_no_pii`, the headers-only mapping test).

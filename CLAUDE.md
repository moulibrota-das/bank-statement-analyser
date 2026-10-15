# CLAUDE.md

## Rules
- **Deterministic first.** Parsing, normalization, reconciliation, totals, aggregations and anomaly rules are
  code. The LLM only classifies rules-unresolved rows, proposes a column mapping from header labels, and writes
  the narrative from pre-computed facts. Never let the LLM produce a number that is not verified.
- **Money is `Decimal`**, never `float`. Serialised as strings. Amounts are positive; `direction` carries sign.
- **Synthetic data only.** No real banking data, ever. Never commit `.env` or API keys.
- **Mask account numbers** to the last 4 digits at parse time; never send account numbers or holder names to
  the LLM; do not log statement content.
- **Never hide reconciliation mismatches or fabricate eval numbers.** Unmeasured live scores stay `TODO`.
- The Streamlit app talks to the API over HTTP only; it must not import `bsi`.
- Everything must run offline in mock mode (no `GEMINI_API_KEY`), including all tests.

## Commands
```
make install   make data   make test   make lint
fastapi dev main.py   # API + the web UI (web/) on :8000; root main.py re-exports the app
streamlit run app/streamlit_app.py   # legacy Streamlit UI on :8501 (optional)
node --test tests/web/   # needs REPORT_JSON; normally run via pytest
make eval      # offline -> eval/results.md      make eval-live  # needs key
python -m bsi analyze <file> --out report.json [--mock] [--no-llm] [--layout NAME] [--prompt classify_v3]
```

## Layout
`src/bsi/`: `ingest` (type + layout detection, unknown-layout mapping), `parse` (pdf, tabular, amounts, dates,
metadata, rows), `validate`, `enrich` (narration), `classify` (rules, merchants.yaml, recurring, llm, cache),
`analytics`, `anomalies`, `summarize` (narrative, faithfulness), `llm` (client, mock, prompts), `pipeline.py`,
`cli.py`, `api/`. New bank layout = a YAML in `layouts/`. Generator: `scripts/generate_statements.py`.
Labels in `data/synthetic/*.labels.json` are ground truth: if you change the generator, regenerate and re-run
tests and eval. Prompts are versioned in `prompts/`; record changes in `prompts/CHANGELOG.md`.

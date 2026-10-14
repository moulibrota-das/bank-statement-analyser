PY ?= .venv/bin/python
.PHONY: install data api ui test eval eval-live lint fmt docker-up

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev,ui]"

data:  ## regenerate the synthetic statements + labels (seeded, reproducible)
	$(PY) scripts/generate_statements.py

api:
	$(PY) -m uvicorn bsi.api.main:app --reload --port 8000

ui:
	API_BASE_URL=$${API_BASE_URL:-http://localhost:8000} $(PY) -m streamlit run app/streamlit_app.py

test:
	$(PY) -m pytest -q

eval:  ## offline mock run; writes eval/results.md
	$(PY) eval/run_eval.py --mock --compare-prompts

eval-live:  ## needs ANTHROPIC_API_KEY
	$(PY) eval/run_eval.py --live --compare-prompts

lint:
	.venv/bin/ruff check src tests scripts eval app

docker-up:
	docker compose up --build

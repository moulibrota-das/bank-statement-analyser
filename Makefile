PY ?= .venv/bin/python
.PHONY: install data api test eval eval-live lint fmt docker-up

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

data:  ## regenerate the synthetic statements + labels (seeded, reproducible)
	$(PY) scripts/generate_statements.py

api:
	$(PY) -m fastapi dev main.py --port 8000

test:
	$(PY) -m pytest -q

eval:  ## offline mock run; writes eval/results.md
	$(PY) eval/run_eval.py --mock --compare-prompts

eval-live:  ## needs GEMINI_API_KEY
	$(PY) eval/run_eval.py --live --compare-prompts

lint:
	.venv/bin/ruff check src tests scripts eval

docker-up:
	docker compose up --build

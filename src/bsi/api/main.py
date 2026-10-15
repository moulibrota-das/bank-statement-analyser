from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from bsi import __version__
from bsi.api.routes import router
from bsi.config import get_settings

WEB_DIR = Path(__file__).resolve().parents[3] / "web"

DESCRIPTION = """
Turns a bank statement (PDF/CSV/XLSX) into structured transactions, categories, spending summaries,
anomaly flags and a faithful narrative summary.

**Deterministic code** does parsing, reconciliation, totals and anomaly rules. **The LLM** only classifies
rows the rules cannot resolve and writes the narrative from pre-computed facts. Without an
`GEMINI_API_KEY` the service runs in offline **mock mode** (see `/health`).

All data is synthetic in the bundled samples. Uploads are processed in memory and never stored; account
numbers are masked to their last four digits in every response.
"""


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Bank Statement Intel", version=__version__, description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    app.include_router(router)
    if WEB_DIR.is_dir():  # the web UI is served last so it never shadows an API route
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from bsi import __version__
from bsi.api.deps import settings_dep
from bsi.api.models import ErrorResponse, HealthResponse, SampleInfo
from bsi.classify.llm_classifier import LLMClassifier
from bsi.classify.recurring import apply_recurring, detect_recurring
from bsi.classify.rules import apply_rules
from bsi.config import Settings
from bsi.enrich.narration import enrich
from bsi.ingest.layouts import load_layouts
from bsi.ingest.loader import UnknownLayout, UnreadableFile, UnsupportedFileType, detect_file_type
from bsi.llm.client import make_client
from bsi.pipeline import analyze_bytes
from bsi.schema import (
    ClassifiedTransaction,
    ClassifyRequest,
    StatementReport,
    Transaction,
)

log = logging.getLogger("bsi.api")
router = APIRouter()
ALLOWED_EXT = {".pdf", ".csv", ".xlsx"}
MAX_CLASSIFY_ROWS = 1000

ERRORS = {
    400: {"model": ErrorResponse, "description": "Bad request (empty file, unknown layout name)"},
    413: {"model": ErrorResponse, "description": "Upload too large"},
    415: {"model": ErrorResponse, "description": "Unsupported file type"},
    422: {"model": ErrorResponse, "description": "File could not be parsed"},
}


def _run(data: bytes, filename: str, use_llm: bool, layout: str | None, settings: Settings) -> StatementReport:
    try:
        return analyze_bytes(data, filename, use_llm=use_llm, layout=layout, settings=settings)
    except UnsupportedFileType as e:
        raise HTTPException(415, f"Unsupported file type: {e}") from e
    except (UnknownLayout, UnreadableFile) as e:
        raise HTTPException(422, f"Could not parse statement: {e}") from e
    except KeyError as e:
        raise HTTPException(400, f"Unknown layout {layout!r}. Available: "
                                 f"{[lay.name for lay in load_layouts(settings.layouts_dir)]}") from e
    except Exception:  # never leak internals or statement content
        log.exception("analysis failed")
        raise HTTPException(500, "Internal error while analysing the statement.") from None


@router.post("/analyze", response_model=StatementReport, responses=ERRORS, tags=["analysis"],
             summary="Analyze an uploaded statement (PDF, CSV or XLSX)")
def analyze(file: UploadFile = File(..., description="Bank statement: .pdf, .csv or .xlsx"),
            use_llm: bool = Query(True, description="Use the LLM for unresolved rows and the narrative. "
                                                    "False = deterministic rules and template only."),
            layout: str | None = Query(None, description="Force a layout profile name from layouts/"),
            settings: Settings = Depends(settings_dep)):
    """The upload is processed **in memory** and never written to disk. Account numbers are masked."""
    name = file.filename or ""
    if Path(name).suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(415, "Unsupported file type: upload a PDF, CSV or XLSX.")
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB upload limit.")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    try:
        kind = detect_file_type(data, name)
    except UnsupportedFileType:
        raise HTTPException(415, "Unsupported file type: content is not a PDF, CSV or XLSX.") from None
    if f".{kind}" != Path(name).suffix.lower():
        raise HTTPException(415, f"File extension does not match its content (looks like {kind.upper()}).")
    return _run(data, name, use_llm, layout, settings)


@router.post("/classify", response_model=list[ClassifiedTransaction], responses=ERRORS, tags=["analysis"],
             summary="Classify raw transactions")
def classify(req: ClassifyRequest, settings: Settings = Depends(settings_dep)):
    """Rules first, then recurring evidence (needs several months of rows), then the LLM for the rest."""
    if not req.transactions:
        raise HTTPException(400, "No transactions supplied.")
    if len(req.transactions) > MAX_CLASSIFY_ROWS:
        raise HTTPException(413, f"At most {MAX_CLASSIFY_ROWS} transactions per request.")
    txns = [Transaction(idx=i, date=r.date, narration=r.narration, amount=r.amount, direction=r.direction)
            for i, r in enumerate(req.transactions)]
    enrich(txns)
    apply_rules(txns)
    apply_recurring(txns, detect_recurring(txns))
    if req.use_llm:
        LLMClassifier(make_client(settings), settings.classify_prompt).classify(txns)
    return [ClassifiedTransaction(category=t.category, category_source=t.category_source,
                                  category_confidence=t.category_confidence, category_rationale=t.category_rationale)
            for t in txns]


def _samples(settings: Settings) -> dict[str, tuple[Path, dict]]:
    out = {}
    for lab in sorted(settings.samples_dir.glob("*.labels.json")):
        name = lab.name.removesuffix(".labels.json")
        f = next((p for p in settings.samples_dir.glob(f"{name}.*") if not p.name.endswith(".labels.json")), None)
        if f:
            out[name] = (f, json.loads(lab.read_text()))
    return out


@router.get("/samples", response_model=list[SampleInfo], tags=["samples"],
            summary="List bundled synthetic statements")
def list_samples(settings: Settings = Depends(settings_dep)):
    return [SampleInfo(name=n, layout=lb["layout"], format=f.suffix[1:], transactions=lb["totals"]["count"],
                       period=f"{lb['meta']['period_start']} to {lb['meta']['period_end']}")
            for n, (f, lb) in _samples(settings).items()]


@router.get("/samples/{name}/analyze", response_model=StatementReport,
            responses={**ERRORS, 404: {"model": ErrorResponse}}, tags=["samples"],
            summary="Run the pipeline on a bundled synthetic statement")
def analyze_sample(name: str, use_llm: bool = Query(True), settings: Settings = Depends(settings_dep)):
    found = _samples(settings).get(name)  # lookup by listed name only: no path traversal
    if not found:
        raise HTTPException(404, f"Unknown sample {name!r}.")
    path, _ = found
    return _run(path.read_bytes(), path.name, use_llm, None, settings)


@router.get("/health", response_model=HealthResponse, tags=["meta"], summary="Service status")
def health(settings: Settings = Depends(settings_dep)):
    return HealthResponse(status="ok", version=__version__, llm_configured=bool(settings.gemini_api_key),
                          mode="mock" if settings.mock_mode else "live", model=settings.llm_model,
                          classify_prompt=settings.classify_prompt, max_upload_mb=settings.max_upload_mb)

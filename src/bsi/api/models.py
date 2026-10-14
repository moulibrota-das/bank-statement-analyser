from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"status": "ok", "version": "0.1.0", "llm_configured": False, "mode": "mock",
                    "model": "claude-sonnet-5-5", "classify_prompt": "classify_v4"}})
    status: str
    version: str
    llm_configured: bool
    mode: str  # "live" | "mock"
    model: str
    classify_prompt: str


class SampleInfo(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"name": "nimbus_a_2024_q1", "layout": "A", "format": "pdf", "transactions": 53,
                    "period": "2024-01-01 to 2024-02-29"}})
    name: str
    layout: str
    format: str
    transactions: int
    period: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"detail": "Unsupported file type: upload a PDF, CSV or XLSX."}})
    detail: str

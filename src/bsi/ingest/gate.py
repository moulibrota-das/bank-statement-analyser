"""Phase 1: is this document a bank statement? An LLM looks at a redacted excerpt (or the image itself)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from bsi.llm.client import LLMClient, LLMError, complete_json
from bsi.llm.prompts import load_prompt
from bsi.schema import DocumentCheck

EXCERPT_CHARS = 4000
MIN_REJECT_CONFIDENCE = 0.6


class _Gate(BaseModel):
    document_type: Literal["bank_statement", "credit_card_statement", "invoice_or_receipt", "other"]
    confidence: float = Field(ge=0, le=1)
    reason: str


def check_document(client: LLMClient, text: str | None, file: tuple[bytes, str] | None = None) -> DocumentCheck:
    """`text` is an already-redacted excerpt source; `file` is (bytes, mime) for images and scanned PDFs."""
    p = load_prompt("gate_v1")
    user = p.render_user()
    files = None
    if file is not None:
        files = [file]
    else:
        user += "\n\nDocument excerpt:\n```text\n" + (text or "")[:EXCERPT_CHARS] + "\n```"
    try:
        g = complete_json(client, p.system, user, _Gate, task="gate", files=files)
    except LLMError as e:
        return DocumentCheck(is_bank_statement=True, confidence=0.0, document_type="unknown",
                             reason=f"document check unavailable ({e})", method="unavailable")
    return DocumentCheck(is_bank_statement=g.document_type == "bank_statement", confidence=g.confidence,
                         document_type=g.document_type, reason=g.reason,
                         method="heuristic" if client.mock else "llm")


def should_reject(check: DocumentCheck) -> bool:
    return not check.is_bank_statement and check.confidence >= MIN_REJECT_CONFIDENCE

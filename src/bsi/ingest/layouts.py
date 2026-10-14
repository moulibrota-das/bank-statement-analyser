"""Layout profiles (layouts/*.yaml) and header-signature matching."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from bsi.config import get_settings

Field_ = Literal["date", "narration", "ref", "debit", "credit", "amount", "balance", "drcr", "value_date"]


class ColumnSpec(BaseModel):
    field: Field_
    header: str
    kind: Literal["text", "money"] = "text"


class Layout(BaseModel):
    name: str
    bank_name: str
    sources: list[Literal["pdf", "csv", "xlsx"]]
    amount_style: Literal["split", "signed", "suffix"]
    signed_credit_positive: bool = True
    date_formats: list[str] = Field(default_factory=list)
    columns: list[ColumnSpec]
    noise_patterns: list[str] = Field(default_factory=list)
    wrap_gap: float = 11.0  # max vertical pt gap for a wrapped narration continuation line

    @property
    def signature(self) -> list[str]:
        return [c.header for c in self.columns]


def load_layouts(directory: Path | None = None) -> list[Layout]:
    directory = directory or get_settings().layouts_dir
    return [Layout(**yaml.safe_load(p.read_text())) for p in sorted(directory.glob("*.yaml"))]


def get_layout(name: str, directory: Path | None = None) -> Layout:
    for lay in load_layouts(directory):
        if lay.name == name:
            return lay
    raise KeyError(f"unknown layout: {name}")


def _norm(s: str) -> str:
    return " ".join(str(s).lower().split())


def match_header(cells: list[str], layout: Layout) -> bool:
    """True if every signature header appears, in order, among the cells."""
    pos = 0
    norm = [_norm(c) for c in cells]
    for h in layout.signature:
        try:
            pos = norm.index(_norm(h), pos) + 1
        except ValueError:
            return False
    return True


def detect_layout(cells: list[str], source: str, layouts: list[Layout] | None = None) -> Layout | None:
    candidates = [lay for lay in (layouts or load_layouts()) if source in lay.sources
                  and match_header(cells, lay)]
    return max(candidates, key=lambda lay: len(lay.signature), default=None)

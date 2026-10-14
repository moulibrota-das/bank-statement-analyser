"""Unknown-layout fallback. The LLM sees ONLY the header labels and proposes which label is which
field: never values. Code validates the proposal and extracts the values itself."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, model_validator

from bsi.ingest.layouts import ColumnSpec, Layout
from bsi.llm.client import LLMClient, LLMError, complete_json

MAPPING_SYSTEM = (
    "You map bank-statement column headers to standard fields. You see header labels only. "
    "Reply with JSON only.")
MAPPING_USER = """Standard fields: date, narration, ref, debit, credit, amount, balance, drcr.
Map each header label (copy it exactly) to a field; omit fields that are absent.
amount_style is "split" if separate debit and credit columns, "suffix" if a Dr/Cr marker is used,
otherwise "signed".

Reply: {"mapping": {"<field>": "<header label>"}, "amount_style": "split|signed|suffix"}

```json
{payload}
```"""


class ColumnMapping(BaseModel):
    mapping: dict[str, str]
    amount_style: Literal["split", "signed", "suffix"] = "signed"

    @model_validator(mode="after")
    def _check(self):
        m = self.mapping
        if "date" not in m or "narration" not in m:
            raise ValueError("mapping needs at least date and narration")
        if not ("amount" in m or ("debit" in m and "credit" in m)):
            raise ValueError("mapping needs amount or debit+credit")
        return self


_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("balance", re.compile(r"balance|bal\b", re.I)),
    ("debit", re.compile(r"debit|withdraw|paid out|\bdr\b(?!/)", re.I)),
    ("credit", re.compile(r"credit|deposit|paid in|\bcr\b(?!/)", re.I)),
    ("drcr", re.compile(r"dr\s*/\s*cr|cr\s*/\s*dr|^type$|^dr/cr$", re.I)),
    ("amount", re.compile(r"amount|amt", re.I)),
    ("ref", re.compile(r"ref|chq|cheque|utr|instrument", re.I)),
    ("narration", re.compile(r"narration|description|particulars|details|remarks", re.I)),
    ("date", re.compile(r"date", re.I)),
]


def heuristic_mapping(payload: dict) -> dict:
    """Deterministic header-keyword mapper. Also the offline stand-in for the LLM."""
    headers: list[str] = payload["headers"]
    mapping: dict[str, str] = {}
    for h in headers:
        if re.search(r"value\s*date", h, re.I) and "date" in mapping:
            continue
        for field, rx in _RULES:
            if rx.search(h) and field not in mapping:
                if field == "date" and re.search(r"value\s*date", h, re.I):
                    mapping.setdefault("_value_date", h)
                    break
                mapping[field] = h
                break
    mapping.pop("_value_date", None)
    style = "split" if "debit" in mapping and "credit" in mapping else ("suffix" if "drcr" in mapping else "signed")
    return {"mapping": mapping, "amount_style": style}


_MONEY_FIELDS = {"debit", "credit", "amount", "balance"}


def to_layout(cm: ColumnMapping, headers: list[str], source: str) -> Layout:
    valid = set(headers)
    cols = []
    for field, label in cm.mapping.items():
        if label not in valid:
            raise ValueError(f"mapped label {label!r} is not a header in this file")
        cols.append(ColumnSpec(field=field, header=label, kind="money" if field in _MONEY_FIELDS else "text"))
    order = {h: i for i, h in enumerate(headers)}
    cols.sort(key=lambda c: order[c.header])
    return Layout(name="inferred", bank_name="Unknown bank", sources=[source], amount_style=cm.amount_style,
                  columns=cols)


def infer_layout(headers: list[str], source: str, client: LLMClient | None) -> tuple[Layout, str]:
    """Returns (layout, how) where how is 'llm' or 'heuristic'."""
    import json

    payload = {"headers": headers}
    if client is not None:
        try:
            user = MAPPING_USER.replace("{payload}", json.dumps(payload))
            cm = complete_json(client, MAPPING_SYSTEM, user, ColumnMapping, task="mapping")
            return to_layout(cm, headers, source), "llm"
        except (LLMError, ValueError):
            pass  # fall through to the deterministic mapper
    cm = ColumnMapping.model_validate(heuristic_mapping(payload))
    return to_layout(cm, headers, source), "heuristic"


def looks_like_header(cells: list[str]) -> bool:
    cells = [c for c in cells if c.strip()]
    if len(cells) < 3:
        return False
    hits = sum(1 for rx in (r"date", r"narration|description|particulars|details|remarks",
                            r"debit|credit|amount|withdraw|deposit", r"balance")
               if any(re.search(rx, c, re.I) for c in cells))
    return hits >= 3

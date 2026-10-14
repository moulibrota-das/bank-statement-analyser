from __future__ import annotations

import json
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def sample_names() -> list[str]:
    return sorted(p.name.removesuffix(".labels.json") for p in SAMPLES.glob("*.labels.json"))


def sample_file(name: str) -> Path:
    return next(p for p in SAMPLES.glob(f"{name}.*") if not p.name.endswith(".labels.json"))


@pytest.fixture
def load_sample():
    def _load(name: str):
        path = sample_file(name)
        labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
        return path, labels
    return _load

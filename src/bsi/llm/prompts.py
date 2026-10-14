"""Versioned prompt loader: prompts/<name>.md with YAML frontmatter, '## system' and '## user' sections."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bsi.config import get_settings


@dataclass
class Prompt:
    name: str
    output: str  # "json" | "text"
    batch_size: int
    system: str
    user: str
    fields: list[str] = field(default_factory=list)

    def render_user(self, **vars: str) -> str:
        out = self.user
        for k, v in vars.items():
            out = out.replace("{{" + k + "}}", v)
        return out


def load_prompt(name: str, directory: Path | None = None) -> Prompt:
    path = (directory or get_settings().prompts_dir) / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"unknown prompt version: {name}")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", path.read_text(), re.DOTALL)
    if not m:
        raise ValueError(f"{path.name}: missing frontmatter")
    meta = yaml.safe_load(m.group(1))
    sections = re.split(r"^## (system|user)\s*$", m.group(2), flags=re.MULTILINE)
    parts = {sections[i]: sections[i + 1].strip() for i in range(1, len(sections) - 1, 2)}
    return Prompt(name=meta["version"], output=meta.get("output", "json"), batch_size=int(meta.get("batch_size", 1)),
                  system=parts["system"], user=parts["user"], fields=list(meta.get("fields", [])))

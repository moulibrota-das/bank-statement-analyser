"""Shared result/exception types for the ingest package."""
from __future__ import annotations

from dataclasses import dataclass, field

from bsi.schema import StatementMeta, Transaction


class UnsupportedFileType(ValueError):
    pass


class UnknownLayout(ValueError):
    pass


class UnreadableFile(ValueError):
    pass


class NotAStatement(ValueError):
    pass


@dataclass
class ParsedStatement:
    meta: StatementMeta
    transactions: list[Transaction]
    warnings: list[str] = field(default_factory=list)

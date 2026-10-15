"""CLI: python -m bsi analyze <file> --out report.json [--mock] [--no-llm] [--layout NAME] [--prompt classify_v4]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bsi.config import Settings
from bsi.ingest.loader import UnknownLayout, UnreadableFile, UnsupportedFileType
from bsi.ingest.loader_types import NotAStatement
from bsi.pipeline import analyze_bytes


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bsi", description="Bank statement analyzer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyze a PDF/CSV/XLSX statement")
    a.add_argument("file", type=Path)
    a.add_argument("--out", type=Path, default=Path("report.json"), help="where to write the JSON report")
    a.add_argument("--mock", action="store_true", help="offline mock LLM (no API key needed)")
    a.add_argument("--no-llm", action="store_true", help="rules only; skip every LLM call")
    a.add_argument("--layout", help="force a layout profile name from layouts/")
    a.add_argument("--prompt", help="classification prompt version (e.g. classify_v3)")
    a.add_argument("--quiet", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides: dict = {}
    if args.mock:
        overrides["mock"] = True
    if args.prompt:
        overrides["classify_prompt"] = args.prompt
    settings = Settings(**overrides)
    try:
        report = analyze_bytes(args.file.read_bytes(), args.file.name, use_llm=not args.no_llm,
                               layout=args.layout, settings=settings)
    except (NotAStatement, UnknownLayout, UnreadableFile, UnsupportedFileType, FileNotFoundError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    args.out.write_text(report.model_dump_json(indent=2))
    if not args.quiet:
        s, r = report.summary, report.reconciliation
        mode = "MOCK LLM" if report.processing.mock_mode else "live LLM"
        print(f"{s.account_summary}\nPeriod: {s.period}   [{mode}, {report.processing.llm_calls} LLM call(s)]")
        print(f"Total credits: {s.total_credits}   Total debits: {s.total_debits}")
        print(f"Reconciliation: {'PASSED' if r.passed else 'FAILED (' + str(len(r.issues)) + ' issue(s))'}")
        for line in s.unusual_transactions:
            print(f"  ! {line}")
        print(f"\n{s.narrative}\n\nReport written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

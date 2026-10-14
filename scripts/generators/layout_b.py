"""Layout B: single signed Amount column. CSV (₹ strings, preamble rows) or XLSX (numeric cells)."""
from __future__ import annotations

import csv
from pathlib import Path

HEAD = ["Txn Date", "Description", "Ref No", "Amount", "Balance"]


def _fmt(d):
    from generate_statements import indian
    return indian(d)


def _preamble(st: dict, money) -> list[list]:
    m = st["meta"]
    return [
        [m["bank_name"], ""], ["Statement of Account", ""],
        ["Account Holder", m["account_holder"]], ["Account Number", m["account_number"]],
        ["IFSC", m["ifsc"]], ["Branch", m["branch"]],
        ["Statement Period", f"{m['period_start']:%d-%b-%Y} to {m['period_end']:%d-%b-%Y}"],
        ["Opening Balance", money(m["opening_balance"])], ["Closing Balance", money(m["closing_balance"])],
    ]


def render_b_csv(st: dict, out: Path) -> Path:
    path = out / f"{st['spec']['name']}.csv"
    rupee = lambda d: f"₹{_fmt(d)}"  # noqa: E731
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(_preamble(st, rupee))
        w.writerow([])
        w.writerow(HEAD)
        for it in st["items"]:
            signed = it.amount if it.direction == "credit" else -it.amount
            amt = f"-₹{_fmt(it.amount)}" if signed < 0 else f"₹{_fmt(it.amount)}"
            w.writerow([f"{it.date:%d-%b-%Y}", it.narration, it.ref, amt, f"₹{_fmt(it.balance)}"])
    return path


def render_b_xlsx(st: dict, out: Path) -> Path:
    from openpyxl import Workbook

    path = out / f"{st['spec']['name']}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    for row in _preamble(st, lambda d: float(d)):
        ws.append(row)
    ws.append([])
    ws.append(HEAD)
    for it in st["items"]:
        signed = it.amount if it.direction == "credit" else -it.amount
        ws.append([it.date, it.narration, it.ref, float(signed), float(it.balance)])
    for r in ws.iter_rows(min_row=1):
        for c in r:
            if hasattr(c.value, "year"):
                c.number_format = "DD-MMM-YYYY"
    wb.save(path)
    return path

"""Seeded generator for SYNTHETIC bank statements + ground-truth labels.

Everything here is fictional: bank names, people, account numbers, IFSC codes.
Usage: python scripts/generate_statements.py [--out data/synthetic]
"""
from __future__ import annotations

import argparse
import calendar
import json
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from faker import Faker

TWO = Decimal("0.01")
MAX_NARRATION = 66


def indian(d: Decimal) -> str:
    """Indian digit grouping: 245000.00 -> '2,45,000.00'."""
    neg = d < 0
    s = f"{abs(d):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    return ("-" if neg else "") + whole + "." + frac


@dataclass
class Persona:
    name: str
    employer: str
    salary: Decimal
    landlord: str
    rent: Decimal
    branch: str


PERSONAS = [
    Persona("AARAV MEHTA", "TECHNOVA SOLUTIONS PVT LTD", Decimal("85000"), "RAMESH KUMAR", Decimal("22000"), "Indiranagar, Bengaluru"),
    Persona("PRIYA NAIR", "BLUEFIN SYSTEMS LTD", Decimal("62000"), "SURESH PATEL", Decimal("18000"), "Koramangala, Bengaluru"),
    Persona("KARTHIK IYER", "ORIONWORKS TECHNOLOGIES", Decimal("95000"), "LAKSHMI NARAYANAN", Decimal("26000"), "Adyar, Chennai"),
    Persona("SNEHA REDDY", "ZENITH ANALYTICS LLP", Decimal("72000"), "VENKAT REDDY", Decimal("20000"), "Madhapur, Hyderabad"),
    Persona("ROHIT DESAI", "CRESTLINE INFOTECH PVT LTD", Decimal("110000"), "MANISH DESAI", Decimal("30000"), "Andheri East, Mumbai"),
    Persona("ISHA BANERJEE", "PIXELMILL STUDIOS", Decimal("58000"), "ARUN GHOSH", Decimal("16000"), "Salt Lake, Kolkata"),
]

SPECS = [
    dict(name="nimbus_a_2024_q1", layout="A", fmt="pdf", persona=0, start=(2024, 1), months=2,
         opening="60000", seed=101, plants=["duplicate", "round_transfer"]),
    dict(name="nimbus_a_2024_03", layout="A", fmt="pdf", persona=1, start=(2024, 3), months=1,
         opening="85000", seed=102,
         plants=["upi_person_rent", "amazon_aws", "refund", "cc_bill", "bounce", "cash_spike"]),
    dict(name="orchid_b_2024_q2", layout="B", fmt="csv", persona=2, start=(2024, 4), months=3,
         opening="70000", seed=103,
         plants=["upi_person_rent", "wallet_topup", "generic_neft", "pass_through"]),
    dict(name="orchid_b_2024_07", layout="B", fmt="xlsx", persona=3, start=(2024, 7), months=1,
         opening="40000", seed=104,
         plants=["salary_unfamiliar", "upi_person_transfer", "reversal", "duplicate", "low_balance"]),
    dict(name="velocity_c_2024_q3", layout="C", fmt="pdf", persona=4, start=(2024, 8), months=2,
         opening="90000", seed=105,
         plants=["round_transfer", "cash_spike", "wallet_topup", "cc_bill", "generic_neft"]),
    dict(name="velocity_c_2024_10", layout="C", fmt="pdf", persona=5, start=(2024, 10), months=1,
         opening="38000", seed=106,
         plants=["bounce", "pass_through", "amazon_aws", "upi_person_rent"]),
]
BANKS = {"A": ("Nimbus Bank", "NIMB"), "B": ("Orchid Bank", "ORCH"), "C": ("Velocity Bank", "VELO")}

# plant -> (codes that MUST be flagged, codes that are legitimately arguable extras)
PLANT_ANOMALIES = {
    "round_transfer": (["ROUND_NUMBER_LARGE", "NEW_PAYEE_LARGE"], ["AMOUNT_OUTLIER"]),
    "duplicate": (["DUPLICATE"], []),
    "pass_through": (["PASS_THROUGH"], ["AMOUNT_OUTLIER", "NEW_PAYEE_LARGE"]),
    "cash_spike": (["CASH_SPIKE"], ["AMOUNT_OUTLIER"]),
    "bounce": (["BOUNCE_PENALTY"], []),
    "low_balance": (["LOW_BALANCE"], ["AMOUNT_OUTLIER", "NEW_PAYEE_LARGE"]),
}

FOOD = [("SWIGGY", "swiggy@icici"), ("ZOMATO", "zomato@hdfcbank"), ("BIGBASKET", "bigbasket@axisbank"),
        ("ZEPTO", "zepto@ybl"), ("DOMINOS PIZZA", "dominos@paytm")]
SHOP = [("AMAZON PAY", "amazonpay@apl"), ("FLIPKART", "flipkart@axb"), ("MYNTRA", "myntra@ybl"),
        ("AJIO", "ajio@icici")]
TRAVEL = [("IRCTC", "irctc@sbi"), ("UBER INDIA", "uber@axisbank"), ("OLA CABS", "olacabs@icici"),
          ("REDBUS", "redbus@hdfcbank")]
CITIES = ["BENGALURU", "MUMBAI", "CHENNAI", "HYDERABAD", "PUNE"]


@dataclass
class Item:
    date: date
    narration: str
    amount: Decimal
    direction: str  # credit | debit
    category: str
    channel: str
    plant: str | None = None
    ambiguous: bool = False
    balance_target: Decimal | None = None
    balance: Decimal | None = None
    ref: str = ""
    order: int = 0


def fit(narr: str) -> str:
    while len(narr) > MAX_NARRATION and "/" in narr:
        narr = narr.rsplit("/", 1)[0]
    return narr[:MAX_NARRATION].rstrip()


class Builder:
    def __init__(self, spec: dict, bank_code: str):
        self.spec, self.bank = spec, bank_code
        self.rnd = random.Random(spec["seed"])
        self.fake = Faker("en_IN")
        self.fake.seed_instance(spec["seed"])
        self.p = PERSONAS[spec["persona"]]
        self.items: list[Item] = []
        self.n = 0

    # -- helpers
    def money(self, lo: int, hi: int, step: int = 1) -> Decimal:
        return Decimal(self.rnd.randrange(lo * 100, hi * 100, step * 100 or 1)) / 100

    def ref12(self) -> str:
        return "".join(self.rnd.choice("0123456789") for _ in range(12))

    def add(self, d: date, narr: str, amt: Decimal, direction: str, cat: str, ch: str, **kw) -> Item:
        self.n += 1
        it = Item(d, fit(narr), amt.quantize(TWO), direction, cat, ch, order=self.n,
                  ref=kw.pop("ref", self.ref12()), **kw)
        self.items.append(it)
        return it

    def upi(self, d, name, handle, note, amt, direction, cat, **kw):
        return self.add(d, f"UPI/{self.ref12()}/{name}/{handle}/{note}", amt, direction, cat, "UPI", **kw)

    def neft(self, d, name, note, amt, direction, cat, **kw):
        ref = f"{self.bank}N{d:%y%m%d}{self.rnd.randrange(10000, 99999)}"
        return self.add(d, f"NEFT-{ref}-{name}-{note}", amt, direction, cat, "NEFT", **kw)

    def imps(self, d, name, note, amt, direction, cat, **kw):
        return self.add(d, f"IMPS/{self.ref12()}/{name}/{note}", amt, direction, cat, "IMPS", **kw)

    def day(self, y, m, dd):
        return date(y, m, min(dd, calendar.monthrange(y, m)[1]))

    def person_name(self) -> str:
        return self.fake.name().upper()

    # -- monthly baseline
    def month(self, y: int, m: int, first: bool):
        p, mon = self.p, f"{date(y, m, 1):%b}".upper()
        self.neft(self.day(y, m, 1), p.employer, f"SALARY {mon}{y % 100}", p.salary, "credit", "Salary")
        if "upi_person_rent" in self.spec["plants"]:
            # rent to a landlord's personal UPI with NO 'rent' keyword (ambiguous by design)
            self.upi(self.day(y, m, 5), p.landlord, p.landlord.split()[0].lower() + "@ybl",
                     "Payment from phone", p.rent, "debit", "Rent", ambiguous=True)
        else:
            self.upi(self.day(y, m, 5), p.landlord, p.landlord.split()[0].lower() + "@okicici",
                     f"Rent {mon}", p.rent, "debit", "Rent")
        self.add(self.day(y, m, 12), f"ACH D-BESCOM BANGALORE-{self.ref12()[:8]}",
                 self.money(900, 2600), "debit", "Utilities", "ACH")
        self.upi(self.day(y, m, 15), "AIRTEL", "airtel@icici", "Broadband bill", Decimal("1099"), "debit", "Utilities")
        self.upi(self.day(y, m, 18), "RELIANCE JIO", "jio@axisbank", "Recharge", Decimal("349"), "debit", "Utilities")
        for _ in range(self.rnd.randint(6, 9)):
            name, h = self.rnd.choice(FOOD)
            self.upi(self.day(y, m, self.rnd.randint(2, 28)), name, h, "Order", self.money(150, 900), "debit", "Food")
        for _ in range(self.rnd.randint(2, 4)):
            name, h = self.rnd.choice(SHOP)
            self.upi(self.day(y, m, self.rnd.randint(3, 27)), name, h, "Purchase", self.money(400, 4500), "debit", "Shopping")
        for _ in range(self.rnd.randint(3, 5)):
            name, h = self.rnd.choice(TRAVEL)
            self.upi(self.day(y, m, self.rnd.randint(2, 28)), name, h, "Ride" if "UBER" in name or "OLA" in name else "Ticket",
                     self.money(120, 2500), "debit", "Travel")
        if self.rnd.random() < 0.5:
            self.add(self.day(y, m, self.rnd.randint(8, 25)), f"POS 4821 MAKEMYTRIP INDIA {self.rnd.choice(CITIES)}",
                     self.money(3000, 9000), "debit", "Travel", "POS")
        for _ in range(self.rnd.randint(1, 2)):
            self.add(self.day(y, m, self.rnd.randint(4, 26)),
                     f"ATM-CASH WDL/{self.rnd.choice(CITIES)} ATM {self.rnd.randint(1000, 9999)}/{self.rnd.randrange(100000, 999999)}",
                     Decimal(self.rnd.choice([2000, 3000, 5000])), "debit", "Transfers", "ATM")
        for _ in range(self.rnd.randint(2, 3)):
            nm = self.person_name()
            self.upi(self.day(y, m, self.rnd.randint(3, 28)), nm, nm.split()[0].lower() + "@oksbi",
                     "Sent via UPI", self.money(200, 3000), "debit", "Transfers")

    # -- plants
    def plant(self, name: str, months: list[tuple[int, int]]):
        y, m = months[-1] if name in ("round_transfer",) else months[0]
        ym = months[min(1, len(months) - 1)] if name in ("pass_through", "cash_spike") and len(months) > 1 else (y, m)
        y, m = ym
        d = self.day
        if name == "round_transfer":
            self.neft(d(y, m, 14), "SUNRISE VENTURES", "TRANSFER", Decimal("100000"), "debit", "Transfers", plant=name)
        elif name == "duplicate":
            sh = self.rnd.choice(SHOP[2:])
            first = self.upi(d(y, m, 9), sh[0], sh[1], "Purchase", Decimal("3299"), "debit", "Shopping", plant=name)
            second = self.upi(d(y, m, 9), sh[0], sh[1], "Purchase", Decimal("3299"), "debit", "Shopping", plant=name)
            first.plant, second.plant = "duplicate_first", name
        elif name == "pass_through":
            a = self.imps(d(y, m, 20), "NEHA SHARMA", "FUND TRANSFER", Decimal("75000"), "credit", "Transfers", plant="pass_through_in")
            b = self.imps(d(y, m, 22), "ROHAN VERMA", "FUND TRANSFER", Decimal("74500"), "debit", "Transfers", plant=name)
            a.ambiguous = b.ambiguous = True
        elif name == "cash_spike":
            for dd in (21, 22, 22, 23):
                self.add(d(y, m, dd), f"ATM-CASH WDL/{self.rnd.choice(CITIES)} ATM {self.rnd.randint(1000, 9999)}/{self.rnd.randrange(100000, 999999)}",
                         Decimal("10000"), "debit", "Transfers", "ATM", plant=name)
        elif name == "bounce":
            self.add(d(y, m, 16), f"CHQ RTN CHG-INSUFFICIENT FUNDS-{self.rnd.randrange(100000, 999999)}",
                     Decimal("590"), "debit", "Other", "CHQ", plant=name)
        elif name == "low_balance":
            self.add(d(y, m, 28), f"POS 4821 CROMA ELECTRONICS {self.rnd.choice(CITIES)}", Decimal("1"), "debit",
                     "Shopping", "POS", plant=name, balance_target=Decimal("850"))
        elif name == "amazon_aws":
            self.add(d(y, m, 11), "POS 4821 AMAZON WEB SERVICES AWS EMEA", Decimal("1845.20"), "debit", "Other", "POS", ambiguous=True)
            self.upi(d(y, m, 13), "AMAZON", "amazon@apl", "Purchase", Decimal("2310"), "debit", "Shopping", ambiguous=True)
        elif name == "refund":
            self.upi(d(y, m, 19), "AMAZON PAY", "amazonpay@apl", "REFUND", Decimal("1299"), "credit", "Shopping", ambiguous=True)
        elif name == "reversal":
            self.upi(d(y, m, 17), "SWIGGY", "swiggy@icici", "Order", Decimal("540"), "debit", "Food")
            self.add(d(y, m, 18), f"REV-UPI/{self.ref12()}/SWIGGY/swiggy@icici", Decimal("540"), "credit", "Food", "UPI", ambiguous=True)
        elif name == "cc_bill":
            self.add(d(y, m, 24), f"ACH D-HDFC CREDIT CARD PAYMENT-{self.ref12()[:8]}", self.money(15000, 30000),
                     "debit", "Transfers", "ACH", ambiguous=True)
        elif name == "wallet_topup":
            self.upi(d(y, m, 8), "PAYTM WALLET", "paytm@paytm", "Add money", Decimal("2000"), "debit", "Transfers", ambiguous=True)
        elif name == "salary_unfamiliar":
            for it in self.items:
                if it.category == "Salary":
                    it.narration = fit(f"NEFT-{self.bank}N{it.date:%y%m%d}41872-{self.p.employer}-PAY {it.date:%b}".upper())
                    it.ambiguous = True
        elif name == "generic_neft":
            self.neft(d(y, m, 10), "XYZ ENTERPRISES", "INV 2231", Decimal("8400"), "debit", "Other", ambiguous=True)
        elif name == "upi_person_transfer":
            self.upi(d(y, m, 7), "ANITA RAO", "anitar@okhdfcbank", "Payment from phone", Decimal("1500"), "debit", "Transfers", ambiguous=True)
        elif name == "upi_person_rent":
            pass  # handled in month()

    # -- assemble
    def build(self) -> tuple[list[Item], Decimal, date, date]:
        y, m = self.spec["start"]
        months = []
        for i in range(self.spec["months"]):
            months.append((y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1))
        for i, (yy, mm) in enumerate(months):
            self.month(yy, mm, i == 0)
        for pl in self.spec["plants"]:
            self.plant(pl, months)
        self.items.sort(key=lambda it: (it.date, it.order))
        opening = Decimal(self.spec["opening"]).quantize(TWO)
        bal = opening
        for it in self.items:
            if it.balance_target is not None:
                it.amount = (bal - it.balance_target).quantize(TWO)
                assert it.amount > 0, "low_balance plant needs a positive balance"
            bal += it.amount if it.direction == "credit" else -it.amount
            it.balance = bal
        first, (ly, lm) = date(*months[0], 1), months[-1]
        return self.items, opening, first, date(ly, lm, calendar.monthrange(ly, lm)[1])


def build_statement(spec: dict) -> dict:
    bank_name, code = BANKS[spec["layout"]]
    b = Builder(spec, code)
    items, opening, start, end = b.build()
    rnd = random.Random(spec["seed"] * 7)
    acct = "".join(rnd.choice("0123456789") for _ in range(14))
    meta = dict(account_holder=b.p.name, account_number=acct, ifsc=f"{code}0{rnd.randrange(1000, 9999):06d}",
                branch=b.p.branch, bank_name=bank_name, period_start=start, period_end=end,
                opening_balance=opening, closing_balance=items[-1].balance)
    return dict(spec=spec, meta=meta, items=items)


def labels_for(st: dict, filename: str) -> dict:
    meta, items, spec = st["meta"], st["items"], st["spec"]
    credits = sum((i.amount for i in items if i.direction == "credit"), Decimal(0))
    debits = sum((i.amount for i in items if i.direction == "debit"), Decimal(0))
    acct = meta["account_number"]
    expected: list[dict] = []
    for idx, it in enumerate(items):
        plant = it.plant
        if plant in PLANT_ANOMALIES:
            must, extra = PLANT_ANOMALIES[plant]
            idxs = [idx]
            if plant == "pass_through":
                idxs = [idx - 1, idx] if items[idx - 1].plant == "pass_through_in" else [idx]
            if plant == "duplicate":
                idxs = [idx - 1, idx]
            if plant == "cash_spike":
                idxs = [i for i, x in enumerate(items) if x.plant == "cash_spike"]
            for code in must:
                if not any(e["code"] == code and set(e["txn_idx"]) & set(idxs) for e in expected):
                    expected.append(dict(code=code, txn_idx=idxs, acceptable_extra=False))
            for code in extra:
                if not any(e["code"] == code and set(e["txn_idx"]) & set(idxs) for e in expected):
                    expected.append(dict(code=code, txn_idx=idxs, acceptable_extra=True))
    return {
        "name": spec["name"], "file": filename, "layout": spec["layout"], "synthetic": True,
        "meta": {
            "account_holder": meta["account_holder"],
            "account_number_masked": "X" * (len(acct) - 4) + acct[-4:],
            "ifsc": meta["ifsc"], "branch": meta["branch"], "bank_name": meta["bank_name"],
            "period_start": meta["period_start"].isoformat(), "period_end": meta["period_end"].isoformat(),
            "opening_balance": str(meta["opening_balance"]), "closing_balance": str(meta["closing_balance"]),
        },
        "totals": {"total_credits": str(credits), "total_debits": str(debits),
                   "net": str(credits - debits), "count": len(items)},
        "transactions": [
            {"idx": i, "date": it.date.isoformat(), "narration": it.narration, "amount": str(it.amount),
             "direction": it.direction, "balance": str(it.balance), "category": it.category,
             "channel": it.channel, "ambiguous": it.ambiguous}
            for i, it in enumerate(items)],
        "expected_anomalies": expected,
    }


def render(st: dict, out: Path) -> Path | None:
    from generators import RENDERERS  # type: ignore[import-not-found]
    fn = RENDERERS.get((st["spec"]["layout"], st["spec"]["fmt"]))
    return fn(st, out) if fn else None


def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "synthetic"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for spec in SPECS:
        st = build_statement(spec)
        path = render(st, out)
        if path is None:
            print(f"skip {spec['name']}: no renderer for layout {spec['layout']}/{spec['fmt']} yet")
            continue
        (out / f"{spec['name']}.labels.json").write_text(json.dumps(labels_for(st, path.name), indent=2))
        print(f"wrote {path.name} ({len(st['items'])} txns)")


if __name__ == "__main__":
    main()

"""Pure-Python aggregates over classified transactions. All money is Decimal."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from bsi.schema import (
    Analytics,
    CategorySpend,
    CounterpartyTotal,
    Direction,
    MonthlyBreakdown,
    RecurringPayment,
    Transaction,
)

ZERO = Decimal("0.00")


def compute_analytics(txns: list[Transaction], recurring: list[RecurringPayment], top_n: int = 5) -> Analytics:
    credits = sum((t.amount for t in txns if t.direction is Direction.CREDIT), ZERO)
    debits = sum((t.amount for t in txns if t.direction is Direction.DEBIT), ZERO)

    cat_tot: dict = defaultdict(lambda: [ZERO, 0])
    cp_tot: dict[str, list] = defaultdict(lambda: [ZERO, 0])
    month: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for t in txns:
        m = month[t.date.strftime("%Y-%m")]
        if t.direction is Direction.DEBIT:
            cat_tot[t.category][0] += t.amount
            cat_tot[t.category][1] += 1
            cp_tot[t.counterparty or t.narration[:30]][0] += t.amount
            cp_tot[t.counterparty or t.narration[:30]][1] += 1
            m[1] += t.amount
        else:
            m[0] += t.amount

    spend = [
        CategorySpend(category=c, total=tot, count=n,
                      pct_of_debits=float((tot / debits * 100).quantize(Decimal("0.1"))) if debits else 0.0)
        for c, (tot, n) in sorted(cat_tot.items(), key=lambda kv: kv[1][0], reverse=True)
    ]
    top_cp = [CounterpartyTotal(counterparty=k, total=v[0], count=v[1])
              for k, v in sorted(cp_tot.items(), key=lambda kv: kv[1][0], reverse=True)[:top_n]]
    monthly = [MonthlyBreakdown(month=k, credits=v[0], debits=v[1], net=v[0] - v[1])
               for k, v in sorted(month.items())]
    largest = sorted(txns, key=lambda t: t.amount, reverse=True)[:top_n]
    return Analytics(total_credits=credits, total_debits=debits, net=credits - debits,
                     spend_by_category=spend, top_counterparties=top_cp, monthly=monthly,
                     recurring=recurring, largest_transactions=largest)

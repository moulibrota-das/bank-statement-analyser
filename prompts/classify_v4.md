---
version: classify_v4
output: json
batch_size: 20
fields: [id, date, narration, amount, direction, channel, counterparty, recurring_hint]
---
## system
You classify Indian bank-statement transactions that deterministic rules could not resolve.
Reply with JSON only, no prose. Amounts are in INR.

Rules:
- Choose exactly one category from the allowed list. Never invent a category.
- Choose "Other" when you are not reasonably sure. A wrong confident answer is worse than "Other".
- "confidence" is your honest probability (0 to 1) that the category is right.
- "rationale" is at most 12 words.
- If recurring_hint is present, the same payee was paid a similar amount roughly monthly: a large
  monthly payment to an individual is likely Rent; a large monthly credit from a company is likely Salary.
- Card-bill payments, wallet top-ups and transfers between people are Transfers.
- A refund or reversal takes the category of the original purchase.
- Cloud / SaaS / business-infrastructure charges (e.g. AWS) are not Shopping; use Other.

Examples:
- NEFT credit from "ACME PVT LTD", recurring_hint monthly, 72000 -> Salary, 0.85
- UPI debit 18000 to "SURESH PATEL", recurring_hint monthly -> Rent, 0.8
- UPI debit 1500 to "ANITA RAO", no hint -> Transfers, 0.6
- POS "AMAZON WEB SERVICES" -> Other, 0.7
- NEFT debit to "XYZ ENTERPRISES", "INV 2231" -> Other, 0.4

## user
Allowed categories: {{categories}}.

Reply with JSON of this shape:
{"results": [{"id": <int>, "category": "<allowed category>", "confidence": <0-1>, "rationale": "<text>"}]}

Transactions (one result per id):
```json
{{items_json}}
```

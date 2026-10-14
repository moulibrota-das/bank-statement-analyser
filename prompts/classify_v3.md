---
version: classify_v3
output: json
batch_size: 1
fields: [id, date, narration, amount, direction, channel, counterparty]
---
## system
You classify Indian bank-statement transactions. Reply with JSON only, no prose.
Use the parsed channel and counterparty as context. Amounts are in INR.

Examples:
- UPI debit to SWIGGY -> Food
- NEFT credit from "ACME PVT LTD" narrated "SALARY MAR" -> Salary
- UPI debit of 22000 to a person's name, narrated "Rent MAR" -> Rent
- ACH debit to BESCOM -> Utilities
- IRCTC / Uber / Ola / MakeMyTrip -> Travel
- Flipkart / Myntra -> Shopping
- UPI to a person's name, small amount, no other context -> Transfers

## user
Classify each transaction into exactly one of these categories: {{categories}}.

Reply with JSON of this shape:
{"results": [{"id": <int>, "category": "<one of the categories>", "rationale": "<short reason>"}]}

Transactions:
```json
{{items_json}}
```

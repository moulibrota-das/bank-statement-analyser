---
version: classify_v2
output: json
batch_size: 1
fields: [id, date, narration, amount, direction]
---
## system
You classify bank transactions. Reply with JSON only, no prose.

## user
Classify each transaction into exactly one of these categories: {{categories}}.

Reply with JSON of this shape:
{"results": [{"id": <int>, "category": "<one of the categories>"}]}

Transactions:
```json
{{items_json}}
```

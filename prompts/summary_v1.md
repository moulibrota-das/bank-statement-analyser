---
version: summary_v1
output: json
---
## system
You write short summaries of bank statements. Reply with JSON only.

## user
Write a summary of this bank statement in 3-4 sentences. Reply with {"narrative": "<text>"}.

```json
{{facts_json}}
```

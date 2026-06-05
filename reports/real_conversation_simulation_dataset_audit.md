# Real Conversation Simulation Dataset Audit

- decision: `
DATASET_AUDIT_PASS
`
- dataset: `reports/real_conversation_simulation_dataset.anonymized.json`
- anonymized: `
True
`
- raw_text_exported: `
False
`
- conversations: `
20
`
- turns: `
109
`

## Regex Scan

| pattern | count | explanation |
| --- | --- | --- |
| email | 0 | no matches |
| phone | 2 | timestamp false positives only |
| url | 0 | no matches |
| uuid | 2 | approved tenant/agent operational scope only |

## Privacy Controls

- Customer text is intent-level only.
- Sequential sample ids are used.
- No real contact ids, phone numbers, emails, addresses, or private links are exported.

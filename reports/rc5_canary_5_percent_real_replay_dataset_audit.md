# RC5 5 Percent Real Replay Dataset Audit

Generated: 2026-06-03T16:05:16.8538256-06:00
Decision: NOT_READY_MISSING_APPROVED_SCOPE
Audit result: not_run_no_dataset

The sampled real replay dataset was not generated because there is no approved tenant/agent scope. Per gate rules, replay export only runs after approved tenant id, approved agent id, business signoff, provider signoff, ops signoff, allowed window, and expected volume exist.

| check | result |
| --- | --- |
| conversations exported | 0 |
| turns exported | 0 |
| PII validation | not applicable, no dataset generated |
| phones real | not applicable |
| full names real | not applicable |
| addresses real | not applicable |
| sensitive ids | not applicable |
| private links | not applicable |

## Blockers

- Approved tenant id is missing.
- Approved agent id is missing.
- Business owner signoff is missing.
- Provider and ops signoff are missing.

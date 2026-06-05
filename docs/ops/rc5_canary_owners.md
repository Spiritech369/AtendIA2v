# RC5 Canary Owners

Generated: 2026-06-03T17:18:31.5306424-06:00
Gate: single_contact_live_smoke
Status: confirmed

| area | owner | status | responsibility |
| --- | --- | --- | --- |
| business | Francisco Esparza | confirmed | Approve one-contact business scope and stop/continue decision. |
| runtime | Felipe Balderas | confirmed | Own runtime readiness and P0/P1 stop decision. |
| provider | Felipe Balderas | confirmed | Own provider real usage for this smoke only. |
| db | Felipe Balderas | confirmed | Own DB/idempotency/write-error monitoring. |
| ops | Felipe Balderas | confirmed | Operate supervised window and stop conditions. |
| rollback | Felipe Balderas | confirmed | Own rollback SQL and validation. |

## Scope Limit

These owners are confirmed only for `single_contact_live_smoke`. This does not approve canary 5 percent, 10 percent, or broad production.

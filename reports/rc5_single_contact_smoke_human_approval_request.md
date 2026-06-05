# RC5 Single Contact Smoke Human Approval Request

Status: ready for final human approval. Do not start automatically.

Please approve or reject a single controlled live smoke with these limits:

| field | value |
| --- | --- |
| tenant | Dinamo Motos NL |
| tenant_id | 6ad78236-1fc9-467a-858d-90d248d57ee5 |
| agent | Francisco de Dinamo NL |
| agent_id | c169deec-226d-55b7-bd07-270f339e75a6 |
| phone | +528212889421 |
| volume | 1 conversation / 5-15 turns |
| provider real | approved for this smoke only |
| send real | approved only for +528212889421 |
| actions/workflows | off / off |
| canary 5 percent | not approved |

## Before Manual Activation

- Confirm final human approval.
- Apply the SQL manually only after approval.
- Keep monitoring active for the full smoke.
- Stop immediately if any stop condition fires.

## Verified Gate

`dinamo_agent_first_live_limited` supports tenant + phone/contact allowlisting. Focused verification passed: `3 passed, 1 skipped`.

## Stop Immediately If

- Any P0 alert fires.
- Provider fallback appears.
- A stale quote, price without snapshot, or quoted without canonical product appears.
- A duplicate side effect appears.
- A false handoff appears.
- Any unsafe customer-visible message appears.
- Any non-approved contact receives traffic.

Requested decision: approve or do not approve one single-contact live smoke. This does not approve 5 percent, 10 percent, or broad production.

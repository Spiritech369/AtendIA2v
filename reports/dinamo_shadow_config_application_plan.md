# Dinamo Shadow Config Application Plan

Decision: proposal only, `applied=false`

Generated at: `2026-06-03T22:24:52.1570446-06:00`

## Current Status

- `applied=false`
- `live_send_enabled=false`
- `actions_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `single_contact_smoke_enabled=false`

No SQL was executed.

## SQL Proposal

This is a proposal only. Do not run without explicit human approval.

```sql
-- PROPOSAL ONLY. DO NOT RUN WITHOUT HUMAN APPROVAL.
BEGIN;

-- Upsert tenant_domain_contract for tenant:
-- 6ad78236-1fc9-467a-858d-90d248d57ee5
-- agent:
-- c169deec-226d-55b7-bd07-270f339e75a6
-- payload source:
-- core/tests/agent_runtime/fixtures/tenant_domain_contracts/dinamo_motos_nl_shadow.json
-- required flags:
-- live_send_enabled=false
-- actions_enabled=false
-- workflow_side_effects_enabled=false
-- runtime_mode='v2_shadow_until_evaluated'

ROLLBACK;
```

## Rollback Proposal

Because nothing was applied, rollback is currently no-op. If applied later, rollback should restore the previous tenant config row/version and keep all send/action/workflow flags disabled.

## Human Gates Before Any Apply

1. Review fixture JSON and reports.
2. Confirm DB target is non-production or explicitly approved.
3. Confirm backup/previous config snapshot exists.
4. Confirm `live_send_enabled=false`, `actions_enabled=false`, `workflow_side_effects_enabled=false`.
5. Run E2E dry-run tests again.

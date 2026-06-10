# Controlled Single-Contact Smoke V3 Retry Activation - 2026-06-09

## Decision

`CONTROLLED_SINGLE_CONTACT_SMOKE_V3_RETRY_ACTIVE`

Activation was explicitly approved for one contact only:

- contact_id: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- phone: `+5218128889241`
- send_scope: `approved_contact_only`

No production-wide traffic was enabled.

## Preconditions

Closed gate:

- `SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX_READY`

Preflight evidence:

- Result JSON:
  `reports/controlled_single_contact_smoke_v3_preflight_after_internal_leak_fix_result_2026_06_09.json`
- Run status: `passed`
- Run decision: `TEST_LAB_PASSED`
- `15 meses` wrote `employment_seniority` and `cumple_antiguedad`.
- No final message leaked `field_not_visible`, `StateWriter`, JSON, trace, or
  internal error text.
- Every preflight turn used `send_decision=no_send`.

## Services

Started minimal services only:

- `postgres-v2`
- `redis-v2`
- `backend`
- `worker`
- `baileys-bridge`

Not started intentionally:

- workflow side-effect workers
- canary
- open production

Health:

- backend `/health`: `{"status":"ok"}`
- `baileys-bridge`: healthy
- `baileys-bridge`: connected to saved session
- `postgres-v2`: healthy
- `redis-v2`: healthy

## Global Runtime Flags

Backend:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

Worker:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

## Tenant Runtime Flags

Tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`:

- `runtime_mode=runtime_v2_controlled_single_contact_smoke_v3_retry_active`
- `send_enabled=true`
- `outbox_enabled=true`
- `live_send_enabled=true`
- `single_contact_smoke_enabled=true`
- `send_scope=approved_contact_only`
- `allowed_contact_ids=["05da6577-2647-4b79-ae24-2d233a22bbd3"]`
- `allowed_test_phones=["+5218128889241"]`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`

## DB Audit At Activation

- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`

## Post-Activation Audit

- backend env:
  - `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true`
  - `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
  - `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- worker env:
  - `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true`
  - `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
  - `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- tenant runtime:
  - `runtime_mode=runtime_v2_controlled_single_contact_smoke_v3_retry_active`
  - `send_enabled=true`
  - `outbox_enabled=true`
  - `live_send_enabled=true`
  - `single_contact_smoke_enabled=true`
  - `send_scope=approved_contact_only`
  - `allowed_contact_ids=["05da6577-2647-4b79-ae24-2d233a22bbd3"]`
  - `allowed_test_phones=["+5218128889241"]`
  - `actions_enabled=false`
  - `workflow_events_enabled=false`
  - `workflow_side_effects_enabled=false`
  - `canary_enabled=false`
  - `open_production_enabled=false`
  - `legacy_fallback_enabled=false`
  - `provider_visible_fallback_enabled=false`
  - `manual_recovery_visible_enabled=false`
- `baileys-bridge`: healthy and connected.
- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`
- Worker outbox dispatcher reported `enqueued: 0` during activation; no message
  was sent by the activation itself.

## Expected Smoke Script

Use only approved contact.

1. `hola`
2. `info porfavor`
3. `15 meses`
4. `me pagan por transferencia`
5. `vi una Skeleton`
6. `?`

Expected behavior:

- asks seniority before income,
- writes seniority and seniority eligibility,
- resolves plan from income,
- asks model after income if model is missing,
- validates model with `catalog.search`,
- quotes only with `quote.resolve`,
- no generic copy,
- no internal text,
- no actions/workflows/canary/open production.

## Rollback Command

Use immediately if any response is wrong, generic, repeated, unsafe, leaks
internal text, or sends outside the approved contact.

```sql
UPDATE tenants
SET config = jsonb_set(
  config,
  '{agent_runtime_v2}',
  COALESCE(config->'agent_runtime_v2', '{}'::jsonb)
  || jsonb_build_object(
    'send_enabled', false,
    'outbox_enabled', false,
    'live_send_enabled', false,
    'single_contact_smoke_enabled', false,
    'runtime_mode', 'runtime_v2_controlled_single_contact_smoke_v3_retry_failed_no_send',
    'actions_enabled', false,
    'workflow_events_enabled', false,
    'workflow_side_effects_enabled', false,
    'canary_enabled', false,
    'open_production_enabled', false,
    'legacy_fallback_enabled', false,
    'provider_visible_fallback_enabled', false,
    'manual_recovery_visible_enabled', false,
    'controlled_smoke_v3_retry_rollback_at', now()::text
  ),
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

Then set `core/.env`:

```dotenv
ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false
ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false
ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false
```

Restart:

```powershell
docker compose up -d backend worker
docker compose stop baileys-bridge
```

Audit:

```sql
SELECT count(*)
FROM outbound_outbox
WHERE tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5'
  AND status IN ('pending', 'retry');

SELECT count(*)
FROM business_event_ledger
WHERE tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5'
  AND side_effects_allowed = true;
```

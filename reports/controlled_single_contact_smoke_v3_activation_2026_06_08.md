# Controlled Single-Contact Smoke V3 Activation - 2026-06-08

## Decision

`CONTROLLED_SINGLE_CONTACT_SMOKE_V3_ACTIVE`

Activation was explicitly approved for one contact only:

- contact_id: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- phone: `+5218128889241`

No production-wide traffic was enabled.

## Services

Started minimal services only:

- `postgres-v2`
- `redis-v2`
- `backend`
- `worker`
- `baileys-bridge`

Not started intentionally:

- `workflow-worker`

Health:

- backend `/health`: `{"status":"ok"}`
- `baileys-bridge`: healthy
- `postgres-v2`: healthy
- `redis-v2`: healthy

Baileys resumed the saved session and reported connected.

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

- `runtime_mode=runtime_v2_controlled_single_contact_smoke_v3_active`
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

## Rollback Command

Use if any response is wrong, generic, repeated, unsafe, or sent outside the approved contact.

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
    'runtime_mode', 'runtime_v2_controlled_single_contact_smoke_failed_no_send',
    'actions_enabled', false,
    'workflow_events_enabled', false,
    'workflow_side_effects_enabled', false,
    'canary_enabled', false,
    'open_production_enabled', false,
    'legacy_fallback_enabled', false,
    'provider_visible_fallback_enabled', false,
    'manual_recovery_visible_enabled', false,
    'controlled_smoke_v3_rollback_at', now()::text
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

## Expected Smoke Script

Use only approved contact.

1. `hola`
2. `info porfavor`
3. `tengo 2 años`
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
- no actions/workflows/canary/open production.


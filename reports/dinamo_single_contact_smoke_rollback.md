# Dinamo Single Contact Smoke Rollback Packet

Generated: 2026-06-03T23:52:46-06:00

Status: ready_as_proposal_only

No activation was applied, so no rollback was executed.

## Rollback Scope

Rollback owner: Felipe Balderas

Tenant: Dinamo Motos NL (`6ad78236-1fc9-467a-858d-90d248d57ee5`)

Agent: Francisco de Dinamo NL (`c169deec-226d-55b7-bd07-270f339e75a6`)

Approved phone: `+528212889421`

## Immediate Rollback Actions

- Disable live send for `agent_runtime_v2`.
- Disable any single-contact smoke flag if added later.
- Disable model provider for this tenant if provider failure appears.
- Disable runtime v2 for this tenant if needed.
- Keep `actions_enabled=false`.
- Keep `workflow_events_enabled=false`.
- Cancel pending outbox/send rows for the approved phone.

## SQL Proposals

Proposal only. Do not run unless a human owner approves rollback.

### Disable Send, Actions, Workflows, And Smoke Metadata

```sql
UPDATE tenants
SET config =
  jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          COALESCE(config, '{}'::jsonb),
          '{agent_runtime_v2,send_enabled}',
          'false'::jsonb,
          true
        ),
        '{agent_runtime_v2,actions_enabled}',
        'false'::jsonb,
        true
      ),
      '{agent_runtime_v2,workflow_events_enabled}',
      'false'::jsonb,
      true
    ),
    '{agent_runtime_v2,single_contact_smoke}',
    'null'::jsonb,
    true
  )
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

### Disable Model Provider If Provider Fails

```sql
UPDATE tenants
SET config = jsonb_set(
  COALESCE(config, '{}'::jsonb),
  '{agent_runtime_v2,model_provider_enabled}',
  'false'::jsonb,
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

### Disable Runtime V2 If Needed

```sql
UPDATE tenants
SET config = jsonb_set(
  COALESCE(config, '{}'::jsonb),
  '{agent_runtime_v2,runtime_v2_enabled}',
  'false'::jsonb,
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

### Cancel Pending Outbox For Approved Phone

```sql
UPDATE outbound_outbox
SET status = 'cancelled',
    last_error = 'single_contact_smoke_rollback_cancel_pending',
    updated_at = now()
WHERE tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5'
  AND status = 'pending'
  AND payload->>'to_phone_e164' = '+528212889421';
```

## Verification After Rollback

- `agent_runtime_v2.send_enabled=false`
- `agent_runtime_v2.actions_enabled=false`
- `agent_runtime_v2.workflow_events_enabled=false`
- no pending outbox for `+528212889421`
- no outbound message to any non-approved phone
- legacy runner fallback remains available

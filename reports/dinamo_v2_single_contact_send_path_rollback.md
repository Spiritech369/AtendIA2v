# Dinamo v2 single-contact send path rollback

Generated: 2026-06-05

Status: PROPOSAL_ONLY
Applied: false

## Rollback owner

- technical_rollback_owner: `Felipe Balderas`
- business_owner: `Francisco Esparza`

## Disable immediately

- `send_enabled=false`
- `outbox_enabled=false`
- `single_contact_smoke_enabled=false`
- `model_provider_enabled=false` if the failure is provider-related
- `runtime_v2_enabled=false` only for critical v2 failure
- pending outbox for the approved contact

## Keep disabled

- `actions_enabled=false`
- `workflow_side_effects_enabled=false`
- legacy fallback remains disabled while `runtime_v2_enabled=true`

## SQL proposal only

```sql
UPDATE tenants
SET config = jsonb_set(
  coalesce(config, '{}'::jsonb),
  '{agent_runtime_v2}',
  (
    coalesce(config->'agent_runtime_v2', '{}'::jsonb)
    || jsonb_build_object(
      'send_enabled', false,
      'outbox_enabled', false,
      'single_contact_smoke_enabled', false,
      'actions_enabled', false,
      'workflow_side_effects_enabled', false
    )
  ),
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';

UPDATE outbound_outbox
SET status = 'cancelled',
    last_error = 'single_contact_smoke_rollback'
WHERE tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5'
  AND status IN ('pending', 'retry')
  AND payload::text LIKE '%<approved-contact-id>%';
```

Provider-specific rollback, if needed:

```sql
UPDATE tenants
SET config = jsonb_set(
  config,
  '{agent_runtime_v2,model_provider_enabled}',
  'false'::jsonb,
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

Critical rollback, if needed:

```sql
UPDATE tenants
SET config = jsonb_set(
  config,
  '{agent_runtime_v2,runtime_v2_enabled}',
  'false'::jsonb,
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

No rollback SQL was executed.

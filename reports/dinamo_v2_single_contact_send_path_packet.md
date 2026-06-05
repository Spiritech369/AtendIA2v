# Dinamo v2 single-contact send path packet

Generated: 2026-06-05

Status: PROPOSAL_ONLY
Applied: false

## Tenant

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- tenant_email: `dinamomotosnl@gmail.com`
- agent_name: `Francisco de Dinamo NL`
- business_owner: `Francisco Esparza`
- technical_rollback_owner: `Felipe Balderas`

## Required flags

```json
{
  "runtime_v2_enabled": true,
  "rollout_mode": "single_contact_smoke",
  "send_enabled": true,
  "outbox_enabled": true,
  "actions_enabled": false,
  "workflow_side_effects_enabled": false,
  "single_contact_smoke_enabled": true,
  "send_scope": "approved_contact_only",
  "allowed_contact_ids": ["<approved-contact-id>"],
  "allowed_test_phones": ["<approved-phone>"],
  "legacy_fallback_disabled_when_v2_enabled": true
}
```

## Gates

- Legacy runner: blocked whenever `agent_runtime_v2.runtime_v2_enabled=true`.
- Visible copy authority: `TurnOutput.final_message`.
- Send scope: `approved_contact_only`.
- Contact allowlist: exactly one approved contact or test phone for this smoke.
- Actions: disabled.
- Workflow side effects: disabled.
- Provider fallback: blocks prepared send and stays internal/no-send.
- Outbox/WhatsApp: not executed by this packet.

## SQL proposal only

```sql
UPDATE tenants
SET config = jsonb_set(
  coalesce(config, '{}'::jsonb),
  '{agent_runtime_v2}',
  (
    coalesce(config->'agent_runtime_v2', '{}'::jsonb)
    || jsonb_build_object(
      'runtime_v2_enabled', true,
      'rollout_mode', 'single_contact_smoke',
      'send_enabled', true,
      'outbox_enabled', true,
      'actions_enabled', false,
      'workflow_side_effects_enabled', false,
      'single_contact_smoke_enabled', true,
      'send_scope', 'approved_contact_only',
      'allowed_contact_ids', jsonb_build_array('<approved-contact-id>'),
      'allowed_test_phones', jsonb_build_array('<approved-phone>')
    )
  ),
  true
)
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

This SQL was not executed.

## Current blocker

This packet needs the real approved contact id/phone and live-persisted tenant domain contract confirmation before single-contact smoke approval.

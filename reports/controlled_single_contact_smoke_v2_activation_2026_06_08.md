# Controlled Single-Contact Smoke V2 Activation - 2026-06-08

## Decision

`CONTROLLED_SINGLE_CONTACT_SMOKE_V2_ACTIVE_APPROVED_CONTACT_ONLY`

## Scope

- Tenant: Dinamo Motos NL
- Tenant ID: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- Approved contact ID: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- Approved phone: `+5218128889241`
- Send scope: `approved_contact_only`
- Activation time observed: `2026-06-08 01:07:10 -06:00`

## Human Approval

The user explicitly approved controlled single-contact smoke V2 only for:

- `05da6577-2647-4b79-ae24-2d233a22bbd3`
- `+5218128889241`

Allowed to turn on:

- `send_enabled=true`
- `outbox_enabled=true`
- `live_send_enabled=true`
- `single_contact_smoke_enabled=true`

Required to remain off:

- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`

## Changes Applied

### Local environment

`core/.env` was updated:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true`

The following remained disabled in effective backend/worker environment:

- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

### Tenant config

`tenants.config->agent_runtime_v2` was updated with:

- `runtime_mode=runtime_v2_controlled_single_contact_smoke_active`
- `smoke_phase=CONTROLLED_SINGLE_CONTACT_SMOKE_V2_ACTIVE`
- `send_scope=approved_contact_only`
- `send_enabled=true`
- `outbox_enabled=true`
- `live_send_enabled=true`
- `single_contact_smoke_enabled=true`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`
- `allowed_contact_ids=["05da6577-2647-4b79-ae24-2d233a22bbd3"]`
- `allowed_test_phones=["+5218128889241"]`

## Services

Recreated:

- `backend`
- `worker`

Not recreated:

- `workflow-worker`

Reason: workflow events and workflow side effects remain disabled for this smoke.

Observed running services:

- `backend`: running
- `worker`: running
- `baileys-bridge`: running and healthy
- `postgres-v2`: running and healthy
- `redis-v2`: running and healthy

Baileys observed:

- Saved session resumed.
- Session connected.
- Health checks returned `200`.

## DB Audit

Post-activation DB audit:

- `outbound_outbox` pending/retry: `0`
- `business_event_ledger` rows with `side_effects_allowed=true`: `0`

## Runtime Send Gate

The live SendAdapter gate is controlled by:

- global runtime flag: `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED`
- tenant `agent_runtime_v2.send_enabled`
- tenant `agent_runtime_v2.outbox_enabled`
- tenant `agent_runtime_v2.single_contact_smoke_enabled`
- tenant `agent_runtime_v2.send_scope`
- approved contact/phone allowlist
- provider fallback block

Relevant code paths reviewed:

- `core/atendia/agent_runtime/agent_service.py`
- `core/atendia/agent_runtime/send_adapter.py`
- `core/atendia/agent_runtime/send_policy.py`

The historical nested `tenant_domain_contract.safety` block still contains shadow/no-live values, but the active SendAdapter policy reads the top-level `agent_runtime_v2` rollout config and the global runtime flags.

## Not Performed

- No WhatsApp message was sent by Codex.
- No smoke script was executed by Codex.
- No production-open/canary activation was performed.
- No action execution was enabled.
- No workflow events or workflow side effects were enabled.
- No git cleanup, staging, commit, reset, restore, or push was performed.

## Rollback Packet

Immediate rollback requires:

1. Set `core/.env`:

   ```env
   ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false
   ```

2. Update tenant config:

   ```sql
   UPDATE tenants
   SET config = jsonb_set(
     config,
     '{agent_runtime_v2}',
     coalesce(config->'agent_runtime_v2', '{}'::jsonb) || jsonb_build_object(
       'send_enabled', false,
       'outbox_enabled', false,
       'live_send_enabled', false,
       'single_contact_smoke_enabled', false,
       'runtime_mode', 'runtime_v2_controlled_single_contact_smoke_failed_no_send',
       'smoke_phase', 'CONTROLLED_SINGLE_CONTACT_SMOKE_V2_ROLLED_BACK',
       'live_reactivation_allowed', false,
       'controlled_smoke_v2_rollback_at', now()::text
     ),
     true
   )
   WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
   ```

3. Recreate only backend/worker:

   ```powershell
   docker compose up -d --force-recreate backend worker
   ```

4. Confirm:

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

## Final State

- Controlled single-contact smoke V2 is active.
- Only the approved contact/phone is allowlisted.
- Outbox is enabled only under the single-contact smoke gate.
- Actions/workflows/canary/open production remain disabled.
- DB audit is clean at activation.


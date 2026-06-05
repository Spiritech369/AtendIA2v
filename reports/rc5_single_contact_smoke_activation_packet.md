# RC5 Single Contact Smoke Activation Packet

Generated: 2026-06-03T17:18:31.5306424-06:00
Decision: READY_FOR_SINGLE_CONTACT_LIVE_SMOKE_APPROVAL
Status: ready_for_human_approval
Traffic started: false
Tenant config applied: false
Canary 5 percent activated: false
Actions/workflows: false / false

## Scope

| field | value |
| --- | --- |
| tenant | Dinamo Motos NL |
| tenant_id | 6ad78236-1fc9-467a-858d-90d248d57ee5 |
| email | dinamomotosnl@gmail.com |
| agent | Francisco de Dinamo NL |
| agent_id | c169deec-226d-55b7-bd07-270f339e75a6 |
| business owner | Francisco Esparza |
| runtime owner | Felipe Balderas |
| provider owner | Felipe Balderas |
| DB owner | Felipe Balderas |
| ops owner | Felipe Balderas |
| rollback owner | Felipe Balderas |
| approved test phone | +528212889421 |
| expected volume | 1 conversation / 5-15 turns |
| window | Recommended: 30-60 minute supervised business-hours window in America/Mexico_City after final approval. |

## Technical Preflight

| gate | result |
| --- | --- |
| ruff | pass |
| observability export | pass |
| tests/agent_runtime | 169 passed, 2 warnings |
| provider stability | 5/5 |
| provider fallback | 0 |
| side effects | 0 |
| contact gate focused test | 3 passed, 1 skipped |

## Verified Contact Gate

The real gate is `dinamo_agent_first_live_limited`, not only `agent_runtime_v2.allowed_contact_ids`.

Required live-limited config:

```json
{
  "enabled": true,
  "allow_real_outbox": true,
  "human_monitoring_active": true,
  "rollback_ready": true,
  "restrict_to_allowlist": true,
  "allowed_tenant_ids": ["6ad78236-1fc9-467a-858d-90d248d57ee5"],
  "allowed_contact_ids": [],
  "allowed_phone_numbers": ["+528212889421"],
  "run_id": "rc5_single_contact_live_smoke_2026_06_03"
}
```

Evidence is recorded in `reports/rc5_single_contact_smoke_contact_gate_verification.md`.

## Required Flags

- `ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE=block`
- `ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE=block`
- Runtime/send global flags only at final manual activation for the approved contact.

## Tenant Config Proposal

```json
{
  "features": {
    "dinamo_agent_first": true
  },
  "agent_runtime_v2": {
    "runtime_v2_enabled": true,
    "shadow_mode_enabled": true,
    "preview_enabled": true,
    "send_enabled": true,
    "actions_enabled": false,
    "workflow_events_enabled": false,
    "model_provider_enabled": true,
    "rollout_mode": "manual_send",
    "allowed_agent_ids": ["c169deec-226d-55b7-bd07-270f339e75a6"],
    "metadata": {
      "rc5_stage": "single_contact_live_smoke",
      "expected_volume": "1 conversation / 5-15 turns",
      "business_owner": "Francisco Esparza"
    }
  },
  "dinamo_agent_first_live_limited": {
    "enabled": true,
    "allow_real_outbox": true,
    "human_monitoring_active": true,
    "rollback_ready": true,
    "restrict_to_allowlist": true,
    "allowed_tenant_ids": ["6ad78236-1fc9-467a-858d-90d248d57ee5"],
    "allowed_contact_ids": [],
    "allowed_phone_numbers": ["+528212889421"],
    "run_id": "rc5_single_contact_live_smoke_2026_06_03"
  }
}
```

## Activation SQL Proposal

```sql
-- PROPOSAL ONLY. Do not run until final human approval.
UPDATE tenants
SET config =
  jsonb_set(
    jsonb_set(
      jsonb_set(
        COALESCE(config, '{}'::jsonb),
        '{features,dinamo_agent_first}',
        'true'::jsonb,
        true
      ),
      '{agent_runtime_v2}',
      '{"runtime_v2_enabled":true,"shadow_mode_enabled":true,"preview_enabled":true,"send_enabled":true,"actions_enabled":false,"workflow_events_enabled":false,"model_provider_enabled":true,"rollout_mode":"manual_send","allowed_agent_ids":["c169deec-226d-55b7-bd07-270f339e75a6"],"metadata":{"rc5_stage":"single_contact_live_smoke","expected_volume":"1 conversation / 5-15 turns","business_owner":"Francisco Esparza"}}'::jsonb,
      true
    ),
    '{dinamo_agent_first_live_limited}',
    '{"enabled":true,"allow_real_outbox":true,"human_monitoring_active":true,"rollback_ready":true,"restrict_to_allowlist":true,"allowed_tenant_ids":["6ad78236-1fc9-467a-858d-90d248d57ee5"],"allowed_contact_ids":[],"allowed_phone_numbers":["+528212889421"],"run_id":"rc5_single_contact_live_smoke_2026_06_03"}'::jsonb,
    true
  )
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

## Rollback SQL Proposal

```sql
-- PROPOSAL ONLY. Restores the agent_runtime_v2 config observed before this smoke package
-- and removes the live-limited smoke gate.
UPDATE tenants
SET config =
  jsonb_set(
    COALESCE(config, '{}'::jsonb) - 'dinamo_agent_first_live_limited',
    '{agent_runtime_v2}',
    '{"runtime_v2_enabled":true,"shadow_mode_enabled":false,"preview_enabled":true,"send_enabled":false,"manual_send_enabled":false,"auto_send_enabled":false,"outbox_enabled":false,"actions_enabled":false,"workflow_events_enabled":false,"model_provider_enabled":true,"rollout_mode":"preview_only","required_eval_suite_passed":false,"min_eval_score":0.9,"last_readiness_score":0.9852,"ready_for_shadow":false,"ready_for_manual_send":false,"ready_for_live_preview":false,"metadata":{"owner":"dinamomotosnl@gmail.com","setup":"dinamo_fresh_tenant_v1","live_ready":false}}'::jsonb,
    true
  )
WHERE id = '6ad78236-1fc9-467a-858d-90d248d57ee5';
```

## Stop Conditions

- Any P0 alert from `rc5_metrics`.
- Any provider fallback response.
- Any provider retry exhausted spike.
- Any stale quote.
- Any price without snapshot.
- Any quoted without canonical product.
- Any duplicate side effect.
- Any false handoff.
- Any unsafe customer-visible message.
- Any message/contact outside `+528212889421`.
- Any owner requests immediate stop.

## Decision

READY_FOR_SINGLE_CONTACT_LIVE_SMOKE_APPROVAL. This packet is ready for final human approval and manual config application for one controlled phone only. It does not start traffic or approve canary 5 percent.

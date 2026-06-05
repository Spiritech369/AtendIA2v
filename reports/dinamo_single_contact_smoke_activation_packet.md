# Dinamo Single Contact Smoke Activation Packet

Generated: 2026-06-03T23:52:46-06:00

Status: blocked_not_prepared_for_application

Decision: NOT_READY_CONTACT_GATE_NOT_SUPPORTED

No traffic was started. No tenant config was applied. No WhatsApp was sent. Canary 5 percent was not activated. Real actions and workflow side effects remain off.

## Scope

| field | value |
| --- | --- |
| tenant | Dinamo Motos NL |
| tenant_id | 6ad78236-1fc9-467a-858d-90d248d57ee5 |
| tenant_email | dinamomotosnl@gmail.com |
| agent | Francisco de Dinamo NL |
| agent_id | c169deec-226d-55b7-bd07-270f339e75a6 |
| approved_test_phone | +528212889421 |
| approved_test_contact_id | unresolved |
| business_owner | Francisco Esparza |
| technical_rollback_owner | Felipe Balderas |
| expected_volume | 1 conversation / 5-15 turns |
| requested_runtime_mode | single_contact_live_smoke |

## Required Flags For The Test

```json
{
  "runtime_v2_enabled": true,
  "runtime_mode": "single_contact_live_smoke",
  "live_send_enabled": true,
  "send_scope": "approved_contact_only",
  "actions_enabled": false,
  "workflow_side_effects_enabled": false,
  "canary_enabled": false,
  "single_contact_smoke_enabled": true,
  "legacy_runner_fallback": true
}
```

## Current Flag Mapping

| requested flag | current mapping | status |
| --- | --- | --- |
| runtime_v2_enabled | `tenant.config.agent_runtime_v2.runtime_v2_enabled` | supported |
| runtime_mode | `agent_runtime_v2.rollout_mode=manual_send` plus metadata | partial, not first-class |
| live_send_enabled | `agent_runtime_v2.send_enabled` plus `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED` | supported only tenant/agent/channel scoped |
| send_scope=approved_contact_only | no universal `agent_runtime_v2` contact/phone gate found | unsupported |
| actions_enabled=false | `agent_runtime_v2.actions_enabled=false` plus global kill switch | supported |
| workflow_side_effects_enabled=false | `agent_runtime_v2.workflow_events_enabled=false` plus global kill switch | supported |
| canary_enabled=false | no canary rollout mode selected | supported by omission |
| single_contact_smoke_enabled=true | metadata only, not enforcement | unsupported as an enforcing gate |
| legacy_runner_fallback=true | `legacy_runner_fallback_enabled` or `allow_legacy_runner_fallback` | supported |

## Activation Config Proposal

No runnable activation config is prepared because the universal path cannot enforce `send_scope=approved_contact_only`.

Minimum required change before activation:

```json
{
  "agent_runtime_v2": {
    "runtime_v2_enabled": true,
    "rollout_mode": "manual_send",
    "send_enabled": true,
    "actions_enabled": false,
    "workflow_events_enabled": false,
    "legacy_runner_fallback_enabled": true,
    "single_contact_smoke": {
      "enabled": true,
      "restrict_to_allowlist": true,
      "allowed_contact_ids": ["<resolved approved contact_id or empty if phone gate is canonical>"],
      "allowed_phone_numbers": ["+528212889421"],
      "max_conversations": 1,
      "expected_turns": "5-15",
      "human_monitoring_active": true,
      "rollback_ready": true
    }
  }
}
```

That structure is illustrative only. It must be implemented and enforced before `stage_outbound` in the universal send route before any activation can be approved.

## Activation SQL Proposal

`BLOCKED_NO_ACTIVATION_SQL_PREPARED`

Reason: `live_send_enabled=true` cannot be limited to the approved phone/contact in the universal path today.

## Rollback Proposal

Rollback is prepared separately in `reports/dinamo_single_contact_smoke_rollback.md`.

## Stop Conditions

Stop immediately if any of the following occurs:

- provider fallback > 0
- provider retry exhausted > 0
- WhatsApp sent to a non-approved contact
- outbox duplicated
- workflow side effect real
- action real
- price without quote snapshot
- stale quote
- cash quote when the customer asked for credit
- requirements mixed
- document_received without attachment
- approval promised
- buro treated as automatic rejection
- strong repetition
- false handoff
- unsafe response
- owner requests stop

## Approval Statement

Not approvable yet. Final human approval must not be requested for activation until the universal contact/phone gate exists and passes focused tests.

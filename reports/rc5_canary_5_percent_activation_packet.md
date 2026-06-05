# RC5 5 Percent Activation Packet

Generated: 2026-06-03T16:05:16.8538256-06:00
Decision: NOT_READY_MISSING_OWNERS
Secondary blocker: NOT_READY_MISSING_APPROVED_SCOPE
Applied: false
Traffic started: false
Tenant config applied: false
Actions/workflows: false / false

## Technical Preflight

| gate | result |
| --- | --- |
| ruff | pass |
| observability export | pass |
| tests/agent_runtime | 169 passed, 2 warnings |
| provider advisor eval | 40/40, definition_of_done_pass=true |
| provider stability | 5/5, definition_of_done_pass=true |
| Docker test DB | pass after starting local Docker Desktop |
| Docker down | pass |

## Operational Gates

| gate | result |
| --- | --- |
| owners | blocked, all six owner roles missing |
| approved tenant | blocked, missing |
| approved agent | blocked, missing |
| canary window | blocked, missing |
| expected volume | blocked, missing |
| provider real approval | blocked, missing |
| send approval | blocked, missing |
| current RC5 replay dataset | not generated, missing approved scope |
| current RC5 replay eval | not run, missing dataset |

## Required Flags

- ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE=block
- ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE=block

## Tenant Config Proposal

~~~json
{
  "runtime_v2_enabled": true,
  "shadow_mode_enabled": true,
  "preview_enabled": true,
  "send_enabled": true,
  "actions_enabled": false,
  "workflow_events_enabled": false,
  "model_provider_enabled": true,
  "rollout_mode": "manual_send",
  "allowed_agent_ids": ["<approved-agent-id>"],
  "metadata": {
    "canary_stage": "5_percent"
  }
}
~~~

## Activation SQL Proposal

~~~sql
-- PROPOSAL ONLY. Do not run until owners and scope are approved.
-- Replace <approved-tenant-id> and <approved-agent-id> after human approval.
UPDATE tenant_configs
SET agent_runtime_v2_config = jsonb_set(
  COALESCE(agent_runtime_v2_config, '{}'::jsonb),
  '{rc5_canary_5_percent}',
  '{"runtime_v2_enabled":true,"shadow_mode_enabled":true,"preview_enabled":true,"send_enabled":true,"actions_enabled":false,"workflow_events_enabled":false,"model_provider_enabled":true,"rollout_mode":"manual_send","allowed_agent_ids":["<approved-agent-id>"],"metadata":{"canary_stage":"5_percent"}}'::jsonb,
  true
)
WHERE tenant_id = '<approved-tenant-id>';
~~~

## Rollback SQL Proposal

~~~sql
-- PROPOSAL ONLY. Manual rollback after human approval.
UPDATE tenant_configs
SET agent_runtime_v2_config = COALESCE(agent_runtime_v2_config, '{}'::jsonb) - 'rc5_canary_5_percent'
WHERE tenant_id = '<approved-tenant-id>';
~~~

## Stop Conditions

- Any quote safety rate above 0.0.
- Any price without snapshot above 0.0.
- Any stale quote above 0.0.
- Any duplicate side effect.
- Any false handoff caused by fallback or provider error.
- Provider retry exhausted or fallback spike above baseline.
- Progress guard block rate sustained above 0.05.
- DB write error rate sustained above 0.02.
- Any unsafe customer-visible message.
- Owner on call requests stop.

## Final Decision

NOT_READY_MISSING_OWNERS. The technical preflight is green, but the canary cannot start until owners and approved scope are real and signed off. No traffic was started and no tenant config was applied.

# RC5 5 Percent Human Approval Request

Status: blocked. Do not approve canary start yet.

The technical preflight is green, but the human approval request cannot be submitted for start until these fields are filled and signed off:

| field | value |
| --- | --- |
| tenant | missing approved tenant id |
| agent | missing approved agent id |
| window | missing approved window |
| volume | missing expected volume |
| provider real | missing approval |
| send | missing approval |
| actions/workflows | off / off |

## Risks To Approve Explicitly

- Real provider/send exposure, even in manual-send rollout.
- Provider retry exhausted, fallback, 429, timeout, or latency spike.
- Quote safety, stale quote, price without snapshot, or canonical product regression.
- Duplicate side effects or DB write errors.
- False handoff or unsafe customer-visible message.

## Stop Conditions

- Any quote safety rate above 0.0.
- Any price without snapshot above 0.0.
- Any stale quote above 0.0.
- Any duplicate side effect.
- Any false handoff.
- Provider retry exhausted or fallback spike above baseline.
- Progress guard block rate sustained above 0.05.
- DB write error rate sustained above 0.02.

## Rollback

Rollback SQL is prepared as a template only. It must be filled with the approved tenant id after human approval.

~~~sql
-- PROPOSAL ONLY. Manual rollback after human approval.
UPDATE tenant_configs
SET agent_runtime_v2_config = COALESCE(agent_runtime_v2_config, '{}'::jsonb) - 'rc5_canary_5_percent'
WHERE tenant_id = '<approved-tenant-id>';
~~~

## Activation SQL

Proposal only. Do not run until owners and scope are approved.

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

Requested decision after owners/scope are complete: approve or do not approve starting RC5 5 percent canary.

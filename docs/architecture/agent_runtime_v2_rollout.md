# AgentRuntime v2 Rollout Controls

Date: 2026-05-31

## Purpose

AgentRuntime v2 remains opt-in. Global flags are kill switches only; they do
not enroll tenants or agents by themselves. A tenant must also carry an
explicit rollout policy in `tenants.config.agent_runtime_v2`.

This protects production while allowing controlled tests by tenant, agent,
channel and capability.

## Policy Shape

```json
{
  "agent_runtime_v2": {
    "runtime_v2_enabled": true,
    "shadow_mode_enabled": true,
    "preview_enabled": true,
    "send_enabled": false,
    "actions_enabled": false,
    "workflow_events_enabled": false,
    "model_provider_enabled": false,
    "allowed_agent_ids": ["<agent_uuid>"],
    "allowed_channel_ids": ["whatsapp"],
    "required_eval_suite_passed": true,
    "min_eval_score": 0.9,
    "max_actions_per_turn": 3,
    "rollout_mode": "preview",
    "metadata": {
      "eval_suite_passed": true,
      "eval_score": 0.95,
      "owner": "ops"
    }
  }
}
```

Agent-specific overrides can live under `agent_overrides` or `agents` keyed by
agent UUID. Overrides merge on top of the tenant policy and inherit metadata.

## Global Flags vs Tenant Policy

Global flags are upper bounds:

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=false` blocks every v2 path.
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false` blocks send even when tenant send is true.
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false` forces actions to dry run.
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false` prevents real workflow events.
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=disabled` forces the mock provider.

Tenant policy is required as the second gate. If global is true but tenant
policy is missing or false, the capability is blocked.

## Rollout Modes

- `disabled`: no AgentRuntime v2 capability.
- `shadow`: runtime can execute against real conversation context with no side effects.
- `preview`: admin preview/test paths are allowed, still no production send.
- `manual_send`: explicit admin send endpoint may stage outbound through the outbox.
- `limited_auto`: reserved for future guarded automation.
- `full`: reserved for future broad rollout.

Actions, workflow events and model provider remain explicit booleans. They are
not automatically enabled by rollout mode.

## Shadow Mode

Manual endpoint:

```http
POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/shadow
```

Shadow mode:

- loads the real conversation context;
- retrieves Knowledge OS evidence;
- executes AgentRuntime v2;
- validates PolicyValidator output;
- records a `TurnTrace` with `mode=shadow`;
- returns simulated workflow events in debug;
- does not send messages;
- does not write customer fields;
- does not move lifecycle;
- does not execute actions;
- does not emit real workflow events.

## Readiness Gates

When `required_eval_suite_passed=true`, `send` is blocked until:

- `metadata.eval_suite_passed=true`;
- `metadata.eval_score >= min_eval_score`, when a minimum is configured.

Preview and shadow can remain enabled while send is blocked.

## Integration Points

- Agent test chat checks `can_preview` and `can_use_model_provider`.
- Conversation preview checks `can_preview`.
- Conversation shadow checks `can_shadow`.
- Conversation send checks `can_send`, `can_execute_actions`,
  `can_emit_workflow_events` and `can_use_model_provider`.
- `PostTurnActionExecutor` receives `dry_run=true` unless both global and tenant
  action gates allow real execution.
- Workflow events are real only when both global and tenant workflow gates allow
  them.
- Model provider is real only when both global and tenant model gates allow it;
  otherwise the mock provider is used.

## Rollback

Fastest rollback:

```json
{
  "agent_runtime_v2": {
    "rollout_mode": "disabled",
    "runtime_v2_enabled": false
  }
}
```

Environment rollback remains stronger: set
`ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=false` to block every tenant immediately.

## Risks And Debt

- The policy currently lives in `Tenant.config`, which avoids migration churn but
  lacks database-level constraints.
- Eval status is read from metadata until Eval Lab persists canonical suite
  results.
- `limited_auto` and `full` are named modes only; webhook replacement remains
  intentionally unimplemented.
- Shadow comparison stores v2 trace data but does not yet capture legacy output
  automatically from the webhook runner.

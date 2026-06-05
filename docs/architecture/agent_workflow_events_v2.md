# Agent Workflow Events v2

AgentRuntime v2 can now expose workflow-facing events without letting workflows
own the conversation. The agent still produces the only customer-visible
`TurnOutput.final_message`; workflows react around that output for operations,
handoff, auditing and follow-up automation.

## Events

The workflow trigger registry accepts these event types:

- `agent_turn_completed`
- `agent_confidence_low`
- `agent_needs_human`
- `agent_field_update_suggested`
- `agent_lifecycle_update_suggested`
- `agent_action_executed`
- `agent_knowledge_gap_detected`
- `agent_policy_blocked`

Every payload includes:

- `source: "agent_runtime_v2"`
- `tenant_id`
- `conversation_id`
- `customer_id`
- `agent_id`
- `trace_id`
- `confidence`
- `needs_human`
- `risk_flags`
- `dry_run`

Event-specific payloads add fields such as `field_key`, `lifecycle_stage`,
`action_id`, `status`, `policy_issues`, `evidence` and `missing_info`.

## Dry Run and Safety

Preview/test paths call `AgentWorkflowEventEmitter` in dry-run mode. The events
are returned in `debug.workflow_events` but no `EventRow` is inserted and no
workflow executes.

Real event insertion is behind
`ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false` by default. When the
flag is enabled on the manual send endpoint, events are persisted and evaluated
through the existing workflow engine. The send endpoint still uses the outbox
for the agent response and does not let workflow actions rewrite the agent's
final message.

## Trigger Conditions

Workflow `trigger_config` can now filter AgentRuntime events by:

- `confidence_lt`, `confidence_lte`, `confidence_gt`, `confidence_gte`
- `action_id` or `action_ids`
- `field_key` or `field_keys`
- `lifecycle_stage` or `lifecycle_stages`
- `risk_flags`

Existing trigger filters such as `field`, `to`, `from`, tags and categories are
unchanged.

Example:

```json
{
  "trigger_type": "agent_confidence_low",
  "trigger_config": {
    "confidence_lte": 0.5,
    "risk_flags": ["knowledge_gap"]
  }
}
```

## Loop Guard

The integration does not create an agent-run node inside workflows. Workflows
can react to events, but they should not trigger AgentRuntime recursively.
Existing workflow idempotency still prevents the same workflow from starting
twice for the same `EventRow`.

## Current Gaps

- The real workflow event flag is off by default until an operator-facing UX can
  make trigger effects explicit.
- There is no workflow canvas support yet for the new condition helpers.
- `agent_action_executed` reports PostTurnActionExecutor results, but action
  handlers remain governed by `AGENT_RUNTIME_V2_ACTIONS_ENABLED`.

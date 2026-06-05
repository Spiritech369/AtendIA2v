# Why This Answer v2

## Purpose

`Why this answer?` is a tenant-scoped observability view for AgentRuntime v2
turns. It aggregates existing persisted evidence without executing actions,
rewriting historical traces, or changing `TurnTrace` storage.

## Endpoint

`GET /api/v1/turn-traces/{trace_id}/why-answer-v2`

Optional query:

- `conversation_id`: narrows the lookup to a known conversation.

Permissions follow the existing turn trace policy: authenticated operators,
tenant admins, and superadmins can read only the scoped tenant's traces.

## Sources

The aggregator reads:

- `turn_traces`
- `action_execution_logs`
- `lifecycle_stage_history`
- `customer_field_update_evidence`
- `events` with `agent_*` event types
- `workflow_executions` triggered by those events
- latest `agent_readiness_eval_results`

Missing historical data is not treated as an error. Empty sections are returned
when a trace predates newer AgentRuntime v2 instrumentation.

## Output Shape

```json
{
  "trace_id": "5ad9...",
  "tenant_id": "c63a...",
  "conversation_id": "ad21...",
  "agent_id": "08f4...",
  "final_message": "Claro, el plan recomendado usa la política aprobada.",
  "confidence": 0.88,
  "knowledge": {
    "citations": [
      {
        "source_id": "source-policy",
        "title": "Policy Source",
        "snippet": "Approved policy snippet",
        "score": 0.91,
        "metadata": { "source_name": "Policy Source" }
      }
    ],
    "source_cards": [
      {
        "source_id": "source-policy",
        "title": "Policy Source",
        "snippet": "Approved policy snippet",
        "score": 0.91,
        "metadata": { "source_name": "Policy Source" }
      }
    ]
  },
  "field_updates": [
    {
      "field_key": "budget",
      "new_value": "$10,000",
      "reason": "Customer stated budget",
      "confidence": 0.9,
      "status": "applied"
    }
  ],
  "lifecycle_update": {
    "target_stage": "qualified",
    "reason": "Budget captured",
    "history": [
      {
        "from_stage": "new",
        "to_stage": "qualified",
        "reason": "Budget captured"
      }
    ]
  },
  "actions": {
    "planned": [{ "name": "update_contact_field" }],
    "executed": [{ "action_id": "add_tag", "status": "succeeded" }],
    "dry_run": [{ "action_id": "update_contact_field", "status": "skipped" }]
  },
  "workflow_events": [
    {
      "type": "agent_turn_completed",
      "workflow_executions": [{ "status": "running" }]
    }
  ],
  "policy": { "valid": true, "issues": [] },
  "rollout_policy": { "preview": { "allowed": true } },
  "readiness": { "passed": true, "score": 0.95 },
  "side_effects": {
    "sent_message": false,
    "executed_actions": 1,
    "dry_run_actions": 1,
    "workflow_events": 1
  },
  "human_summary": "The agent produced a final message using 1 knowledge citation(s) ..."
}
```

## Notes

- `final_message` is read from `TurnOutput.final_message` inside
  `turn_traces.composer_output` when available.
- Knowledge cards are derived from runtime citations in `kb_evidence` or
  `composer_output.knowledge_citations`.
- `planned` actions come from `TurnOutput.actions`; `executed` and `dry_run`
  actions come from `action_execution_logs`.
- Policy is reconstructed from `turn_traces.errors`, `rules_evaluated`, and
  optional debug policy payloads.
- This API is read-only. It does not execute actions, publish workflows, or
  mutate onboarding/readiness state.

## Remaining Gaps

- No large UI yet; this endpoint is ready for Agent Studio/Test Chat trace cards.
- Legacy traces may have sparse `composer_output`/`kb_evidence`, so explanations
  will be partial.
- Workflow simulation events that were never persisted can only be shown if they
  were stored in the trace payload.

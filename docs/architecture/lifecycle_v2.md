# Lifecycle v2

## Purpose

Lifecycle v2 is the general layer that lets AtendIA orient, measure and
automate conversation progress without letting lifecycle logic write the final
agent message or turn the agent into a form.

The existing tenant pipeline remains the source of truth for now. Lifecycle v2
adapts it into a generic contract that can be consumed by `AgentRuntime`,
Workflows and Inbox while preserving legacy behavior.

## Relationship With The Legacy Pipeline

Legacy pipeline data stays in:

- `tenant_pipelines.definition`
- `conversations.current_stage`
- `conversation_state.stage_entered_at`

`PipelineLifecycleAdapter` reads `tenant_pipelines.definition.stages` and exposes
each stage as a `LifecycleStage`. No pipeline route or state-machine code is
removed by this layer.

## LifecycleStage

`LifecycleStage` normalizes a pipeline stage into:

- `id` / `key`
- `name`
- `description`
- `goal`
- `entry_conditions`
- `exit_conditions`
- `recommended_fields`
- `required_fields`
- `recommended_actions`
- `allowed_actions`
- `sla_policy`
- `automation_policy`
- `is_lost_stage`
- `order`
- `active`
- `metadata`

The adapter maps legacy fields conservatively:

- `required_data.required_fields` becomes `required_fields`.
- Required and optional legacy fields become `recommended_fields`.
- `actions_allowed` becomes `allowed_actions`.
- `recommended_actions` is preserved when present.
- `timeout_hours` and `timeout_action` become `sla_policy`.
- `pause_bot_on_enter`, `handoff_reason` and `transitions` become
  `automation_policy`.

## Service

`LifecycleService` provides the runtime-safe API:

- `get_current_stage`
- `suggest_stage_update`
- `validate_stage_update`
- `apply_stage_update`
- `record_stage_history`

Validation checks tenant ownership, target stage existence, transition validity,
reason and evidence. Applying a stage update writes only the lifecycle state:
`conversations.current_stage`, `conversation_state.stage_entered_at` and an audit
row.

## Audit History

New table:

- `lifecycle_stage_history`

It records tenant, conversation, previous stage, target stage, reason, evidence,
confidence, source, trace id, creator, metadata and timestamp.

This gives AgentRuntime, workflows and human operators a common trail for stage
changes without depending on visible agent copy.

## AgentRuntime Integration

`TurnOutput.lifecycle_update` remains a suggestion. It is not applied by
`AgentRuntime`.

`PolicyValidator` requires lifecycle updates to include:

- `reason`
- `evidence`
- `confidence`

The confidence must be in `0..1`. Instructions or prompts cannot bypass this
validation.

`PostTurnActionExecutor` may receive a `LifecycleService`. When `dry_run=false`,
it can apply:

- `TurnOutput.lifecycle_update`
- registered `move_lifecycle` actions

Dry-run execution, including test-turn, never moves lifecycle.

## Boundaries

Lifecycle v2 does not:

- produce final visible copy;
- send outbound messages;
- update contact fields;
- trigger workflows directly;
- hardcode vertical stages or business-specific documents;
- replace the legacy state machine in this task.

## Tests

The Lifecycle v2 test suite covers:

- adapter reads the legacy pipeline;
- valid stage update applies;
- missing reason/evidence/confidence is rejected by policy;
- nonexistent stage fails;
- tenant isolation;
- lifecycle execution does not return final text;
- `move_lifecycle` uses `LifecycleService`;
- legacy pipeline rows still work with the new layer present.

## Migration Debt

- Replace hardcoded stage validation in pipeline routes with
  `LifecycleService.validate_stage_update`.
- Unify legacy event emission and `lifecycle_stage_history`.
- Add lifecycle admin endpoints when the UI needs to author generalized stages.
- Surface lifecycle audit history in Inbox/Command Center.
- Move pipeline authoring toward the `LifecycleStage` schema.
- Add workflow triggers as a separate automation layer that consumes lifecycle
  events instead of being called directly by the agent.

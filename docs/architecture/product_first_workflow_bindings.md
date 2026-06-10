# Product-First Workflow Bindings

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Workflow Bindings let agents emit normalized business events into existing
automation without letting workflows own the conversation.

This document defines the target contract for workflow bindings, event payloads,
side-effect modes, loop guards, publish blockers, trace, and Test Lab behavior.
It is documentation-only for this phase. It does not change runtime, DB,
Docker, WhatsApp, outbox, actions, workflows, smoke, or live flags.

## Product Principle

Workflows consume agent events. They do not write, replace, repair, or send
primary customer copy.

`TurnOutput.final_message` remains the only customer-facing text authority, and
SendAdapter remains the only route to customer delivery.

## Workflow Binding Contract

A Workflow Binding authorizes an agent version to emit a normalized event to a
specific workflow under explicit scope and mode.

Minimum target fields:

- `tenant_id`
- `agent_version_id`
- `workflow_id`
- `event_type`
- `enabled`
- `mode`
- `trigger_filters`
- `side_effect_policy`
- `customer_copy_policy`
- `loop_guard_policy`
- `idempotency_policy`
- `approval_required`
- `rollback_behavior`
- `published_workflow_version`

Allowed binding modes:

- `disabled`
- `dry_run_only`
- `emit_event_only`
- `requires_human_approval`
- `live_limited`

## Normalized Agent Events

Allowed target event families:

- `agent_turn_completed`
- `agent_needs_human`
- `agent_knowledge_gap_detected`
- `agent_policy_blocked`
- `agent_field_update_suggested`
- `agent_field_update_written`
- `agent_lifecycle_update_suggested`
- `agent_lifecycle_update_written`
- `agent_action_requested`
- `agent_action_executed`
- `agent_document_received`
- `agent_document_missing`

Minimum event payload:

- `source`
- `tenant_id`
- `conversation_id`
- `contact_id`
- `agent_id`
- `agent_version_id`
- `deployment_id`
- `trace_id`
- `event_type`
- `dry_run`
- `policy_status`
- `send_decision`
- `final_message_hash`
- `risk_flags`
- `evidence`

Payloads may include structured details such as field key, lifecycle stage,
action id, document type, missing source, or handoff reason.

## Customer Copy Boundary

Workflow output must not:

- overwrite `TurnOutput.final_message`
- append text to `TurnOutput.final_message`
- send customer text outside SendAdapter
- substitute fallback/recovery copy
- respond to customers when AgentService failed closed
- generate visible progress text

If a workflow needs customer messaging, it must create a structured
`message_send_request` action that goes through Action Registry, Policy,
Publish Control, and SendAdapter.

## Side-Effect Modes

Workflow side effects are controlled by mode:

- Test Lab: dry-run only, no workflow execution.
- no-send readiness: event preview only, no workflow execution.
- live-candidate: side-effect decision can be calculated, but no live side
  effect unless explicitly approved.
- live-limited: only approved workflow bindings within approved scope.
- production: future state only after completed DoD and explicit approval.

Workflow events and side effects must be tenant-scoped, idempotent, auditable,
and rollback-aware.

## Loop Guard

Workflow Bindings must prevent recursive or duplicate agent execution:

- workflow cannot directly trigger the same agent turn recursively
- same event cannot start the same workflow twice without idempotency override
- workflow-generated internal updates must not look like inbound customer text
- workflow side effects must not bypass AgentService or SendAdapter
- retry behavior must preserve idempotency key and trace id

## Publish Blockers

Publish Control must block when:

- workflow binding references an unknown or inactive workflow
- event type is unsupported
- side-effect policy is missing
- customer-copy policy is missing
- loop guard is missing
- idempotency policy is missing
- approval policy is missing for live side effects
- rollback behavior is missing
- Test Lab did not verify dry-run/event preview
- workflow can send customer copy outside SendAdapter
- workflow can overwrite `TurnOutput.final_message`

## Runtime Rules

At runtime:

- AgentService emits normalized event candidates after Policy and Trace.
- Workflow Binding validates whether the event is allowed.
- Test Lab records event preview without executing workflows.
- Publish Control controls whether real workflow side effects may run.
- Workflow execution results are structured operational results, not visible
  conversation copy.
- Trace records event candidate, binding decision, dry-run/live mode, workflow
  id, blocked reason, and side-effect result.

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- unknown workflow binding is blocked
- unsupported event type is blocked
- Test Lab records event preview without executing workflow
- no-send mode creates no workflow side effects
- workflow cannot overwrite `TurnOutput.final_message`
- workflow cannot send customer text outside SendAdapter
- recursive agent/workflow loop is blocked
- idempotency prevents duplicate workflow starts
- Publish Control blocks live workflow side effects without approval
- trace records workflow event candidate and binding decision

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 9 Acceptance

Fase 9 is complete when:

- Workflow Binding contract is documented
- normalized agent events are documented
- customer-copy boundary is documented
- side-effect modes, loop guard, publish blockers, runtime rules, and trace
  requirements are documented
- future tests are documented
- no live/runtime/DB behavior was changed

Decision for this documentary phase:

`PRODUCT_FIRST_PHASE_9_WORKFLOW_BINDINGS_DEFINED_DOCS_ONLY`

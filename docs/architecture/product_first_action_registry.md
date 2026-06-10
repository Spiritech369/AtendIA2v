# Product-First Action Registry

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Action Registry is the Product-First boundary for side effects and external
integrations. It turns actions into tenant-scoped, schema-driven, risk-rated,
auditable product capabilities.

This document defines the target contract for action definitions, action
bindings, execution modes, approvals, idempotency, audit, Test Lab behavior, and
Publish Control blockers. It is documentation-only for this phase. It does not
change runtime, DB, Docker, WhatsApp, outbox, actions, workflows, smoke, or live
flags.

## Product Principle

Tools resolve facts. Actions request or perform side effects.

Actions must not interpret conversation, compose visible customer copy, bypass
Policy, or send messages outside SendAdapter.

## Action Definition Contract

An Action Definition is a reusable capability that can be bound to an agent
version only through Product-First configuration.

Minimum target fields:

- `action_id`
- `name`
- `description`
- `category`
- `input_schema`
- `output_schema`
- `risk_level`
- `side_effect_type`
- `tenant_permission_requirements`
- `secret_requirements`
- `approval_policy`
- `dry_run_behavior`
- `live_behavior`
- `idempotency_strategy`
- `timeout_policy`
- `retry_policy`
- `rate_limit_policy`
- `redaction_policy`
- `audit_policy`
- `owner`
- `enabled`

Allowed risk levels:

- `read_only`
- `internal_write`
- `customer_visible`
- `external_write`
- `critical`

Allowed side-effect types:

- `none`
- `crm_write`
- `lifecycle_write`
- `tag_write`
- `assignment`
- `notification`
- `workflow_trigger`
- `webhook`
- `appointment`
- `payment`
- `document_request`
- `message_send_request`

## Action Binding Contract

An Action Binding authorizes an agent version to use a specific action within a
specific scope.

Minimum target fields:

- `tenant_id`
- `agent_version_id`
- `action_id`
- `enabled`
- `mode`
- `allowed_inputs`
- `field_policy_dependencies`
- `source_dependencies`
- `approval_required`
- `human_review_required`
- `send_scope_dependency`
- `max_calls_per_turn`
- `max_calls_per_conversation`
- `rollback_behavior`
- `published_action_version`

Allowed binding modes:

- `disabled`
- `dry_run_only`
- `suggest_only`
- `requires_human_approval`
- `live_limited`

No action may run in live mode unless Publish Control has approved that binding
and scope.

## Execution Contract

Action execution must receive structured inputs only:

- tenant id
- conversation id
- contact id
- agent version id
- trace id
- action id
- validated input payload
- evidence
- mode
- idempotency key
- approval context

Action execution must return structured output only:

- action id
- status
- dry-run/live mode
- normalized result
- blocked reason
- audit id
- rollback hint
- redacted debug metadata

Action outputs must not include customer-facing response text. Composer owns
customer copy and SendAdapter owns delivery of approved final output.

## Approval And Mode Rules

Actions are blocked unless their mode is allowed by the active deployment:

- Test Lab: dry-run only, no external side effects.
- no-send readiness: dry-run only, no external side effects.
- live-candidate: calculate decision, no side effects unless explicitly
  approved for staging.
- live-limited: only approved action bindings within approved scope.
- production: future state only after completed DoD and explicit approval.

`critical`, `external_write`, `payment`, and `message_send_request` actions
require explicit approval and rollback metadata before live use.

## Idempotency And Retry

Every write or external action must define:

- idempotency key strategy
- duplicate detection
- retryable errors
- non-retryable errors
- timeout behavior
- rollback or compensation behavior
- audit correlation id

Unknown idempotency means the action is not publish-ready.

## Publish Blockers

Publish Control must block when:

- an action binding references an unknown or disabled action
- input or output schema is missing
- risk level is missing
- dry-run behavior is missing
- approval policy is missing for a write/critical action
- idempotency strategy is missing for a write/external action
- rollback behavior is missing for live-limited write actions
- secrets or permissions are unresolved
- Test Lab did not verify dry-run behavior
- trace/audit output is not defined
- action output can include visible customer copy

## Runtime Rules

At runtime:

- ChatGPT may propose an action intent.
- AtendIA validates the action binding and mode.
- Policy evaluates risk and approval requirements.
- Action executor returns structured result.
- Composer may mention only safe, validated outcomes.
- SendAdapter remains the only customer-message sender.
- Universal trace records action proposal, approval, execution, result, and
  blocked reason.

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- unknown action is blocked
- disabled binding is blocked
- missing schema blocks publish
- missing approval policy blocks critical action publish
- missing idempotency blocks write action publish
- Test Lab action execution is dry-run only
- action result cannot contain visible customer copy
- SendAdapter is still the only send path
- action audit record includes trace id and redaction
- unauthorized tenant action is blocked

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Implemented Productized Binding Slice - 2026-06-07

Status: implemented as no-live control-plane slice.

Implemented:

- Product capability registry in backend control-plane code.
- Canonical separation between fact tools and side-effect actions.
- Fact tools currently registered:
  - `catalog.search`
  - `quote.resolve`
  - `requirements.lookup`
  - `document.check`
- Side-effect actions currently registered:
  - `update_contact_field`
  - `trigger_workflow`
  - `call_webhook`
  - `send_message`
- Tenant-scoped Product Agent endpoints for capability options.
- Draft-scoped Agent Tool Binding endpoints.
- Draft-scoped Agent Action Binding endpoints.
- Agent Builder UI tabs for Tools and Actions.
- Publish/readiness metadata for side-effect type, auth, permissions, blockers,
  and mode.

No-live guarantees:

- Productized action binding does not execute actions.
- `send_message` remains disabled and blocked as the SendAdapter boundary.
- Live action modes remain blocked by service validation.
- No Runtime V2, SendAdapter, WhatsApp, outbox, workflow side effect, smoke,
  canary, or production behavior changed.

Decision for this implementation slice:

`TOOL_ACTION_BINDINGS_PRODUCTIZED_READY`

## Phase 8 Acceptance

Fase 8 is complete when:

- Action Definition contract is documented
- Action Binding contract is documented
- execution, approval, mode, idempotency, retry, audit, and publish blockers
  are documented
- runtime and trace rules are documented
- future tests are documented
- no live/runtime/DB behavior was changed

Decision for this documentary phase:

`PRODUCT_FIRST_PHASE_8_ACTION_REGISTRY_DEFINED_DOCS_ONLY`

# Product-First Publish Control

Date: 2026-06-07  
Status: Active architecture contract; no-send MVP implemented  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Publish Control is the product gate that replaces scattered runtime flags,
manual smoke decisions, and ad hoc live activation with a tenant-scoped,
auditable deployment state machine.

This document defines publish states, approvals, readiness gates, rollback,
feature readiness dependencies, and live-safety boundaries. The current MVP
implements durable no-send publish requests and approval gates only. It does
not activate runtime live behavior, WhatsApp, outbox writes, actions, workflow
side effects, smoke, canary, or production flags.

## Product Principle

An agent version is not live because code exists or a smoke passed. It becomes
eligible for scoped live traffic only after:

- Definition of Ready was satisfied before implementation.
- DB-backed Test Lab passed.
- required Knowledge Sources are ready.
- required tools/actions/workflows are approved for their mode.
- policy and trace gates passed.
- rollback is defined.
- explicit human approval is recorded for any live send.

## Deployment State Machine

Allowed target states:

- `draft`: mutable configuration, never live.
- `configured`: required product entities are present but not proven.
- `test_lab_required`: readiness needs DB-backed Test Lab.
- `test_lab_running`: suite execution in progress.
- `test_lab_failed`: test evidence failed or is incomplete.
- `ready_for_approval`: gates passed, waiting for human approval.
- `published_no_send`: published for no-send or shadow operation only.
- `published_live_limited`: scoped live traffic is allowed.
- `paused`: deployment remains configured but sends are blocked.
- `rollback_required`: current version must be rolled back before further live.
- `rolled_back`: previous approved version restored.
- `deprecated`: deployment retired.

No state transition may be caused only by a scattered flag toggle.

## Publish Request Contract

Implemented no-send MVP fields:

- `tenant_id`
- `id`
- `agent_id`
- `agent_version_id`
- `deployment_id`
- `requested_state`
- `status`
- `send_scope`
- `channel_scope`
- `audience_scope`
- `test_run_ids`
- `readiness_snapshot`
- `blockers`
- `rollback_version_id`
- `approval_text`
- `requested_by_user_id`
- `approved_by_user_id`
- `decided_at`
- `decision_reason`
- timestamps

Publish requests are durable and auditable through `agent_publish_requests`.
The MVP allows only `requested_state=published_no_send` and `send_scope` of
`none` or `test_lab_no_send`.

## Readiness Gates

Publish Control must evaluate:

- Agent Version is immutable for publish.
- Agent Deployment target is tenant-scoped.
- Knowledge Sources required by bindings are `ready`.
- Source retrieval preview and Test Lab evidence exist.
- required tools are available and tenant-aware.
- Action Bindings have risk level, schema, approval policy, dry-run/live mode,
  idempotency, and audit behavior.
- Workflow Bindings cannot send customer copy or create live side effects
  unless explicitly approved.
- Field Policies exist for writable fields.
- Test Lab latest required run passed.
- no-send/live-candidate parity passed where send is in scope.
- outbox audit is zero before activation.
- business side-effect audit is zero before activation.
- Universal Turn Trace completeness is proven.
- feature readiness matrix has no blocking dependency.
- rollback version exists and is approved.
- live scope is explicit and narrow.

## Approval Rules

Human approval is required for:

- first live send for a tenant deployment
- any expansion of send scope
- any action with live side effects
- workflow side effects
- canary
- open production
- rollback from a failed live state

Approval must name the tenant, agent version, deployment, contact/audience or
segment scope, channel scope, enabled capabilities, disabled capabilities, and
rollback condition.

## Send Scope Rules

Allowed target send scopes:

- `none`
- `test_lab_no_send`
- `approved_contact_only`
- `approved_segment_only`
- `tenant_limited_beta`
- `production`

`approved_contact_only`, `approved_segment_only`, `tenant_limited_beta`, and
`production` are not reachable from the no-send MVP. They require future
explicit approval, implementation, Test Lab evidence, and completed DoD.

## Implemented No-Send MVP

Fase 7 implements:

- `AgentPublishRequest` ORM model and migration.
- tenant-scoped publish request API for create, latest, evaluate,
  approve-no-send, and reject.
- service-level validation that blocks live states and live send scopes.
- readiness evaluation from draft readiness, latest passed Test Lab run,
  trace ids, outbox audit, side-effect audit, and rollback target.
- approval transition to `published_no_send` only.
- safe deployment update with `runtime_mode=no_send`, `send_scope=none`, and
  all send/action/workflow/canary/production flags false.
- Product Agent Builder Publish tab with no-send-only controls.
- focused backend and frontend tests with 100% coverage of modified behavior.

Fase 7 does not implement:

- live-limited publish.
- approved-contact smoke activation.
- production publish.
- SendAdapter changes.
- outbox live writes.
- action/workflow side effects.

## Rollback Contract

A deployment must have rollback metadata before live-limited publish:

- previous approved agent version
- rollback state
- rollback trigger
- rollback owner
- rollback command or product action
- expected disabled capabilities
- post-rollback DB/outbox/side-effect audit checks
- trace/log review requirements

Rollback must disable send scope before investigating if visible customer
behavior is wrong or unsafe.

## Feature Readiness Dependency

Publish Control must consult `docs/architecture/feature_readiness_matrix.md`.

Blocked or deprecated features cannot be used as publish evidence. A feature may
advance only with tests, trace, rollback, and Codex code review where
implementation changed.

## Definition of Ready / Done

Definition of Ready controls whether a phase or feature may start.

Definition of Done controls whether a phase or feature may be called complete
or publish-ready.

Active contracts:

- `docs/architecture/product_first_definition_of_ready.md`
- `docs/architecture/product_first_definition_of_done.md`

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- publish is blocked when Test Lab has not passed
- publish is blocked when required source is unhealthy
- publish is blocked when rollback version is missing
- publish is blocked when trace completeness is missing
- publish is blocked when feature readiness has blockers
- live scope cannot expand without approval
- scattered send flags cannot bypass deployment state
- rollback pauses send before investigation
- `published_live_limited` requires explicit human approval

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 7 Acceptance

Fase 7 no-send MVP is complete when:

- publish states are documented
- publish request contract is documented
- readiness gates are documented
- approval and send-scope rules are documented
- rollback contract is documented
- feature readiness dependency is documented
- DoR and DoD are linked as active publish controls
- durable no-send publish request and approval paths exist
- no live/runtime-send/outbox/workflow/action behavior is activated

Decision for this no-send MVP phase:

`PUBLISH_CONTROL_MVP_NO_SEND_READY`

# Product-First Legacy Isolation

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Legacy Isolation defines how AtendIA prevents old response paths, guards,
fallbacks, workflows, smoke logic, fixture preflights, and tenant-specific
hardcoding from interfering with Product-First published agents.

This document does not delete legacy. It defines isolation gates before future
degradation or removal. It is documentation-only for this phase. It does not
change runtime, DB, Docker, WhatsApp, outbox, actions, workflows, smoke, or live
flags.

## Product Principle

Legacy may remain for non-migrated tenants, migration comparison, and rollback
only when it cannot produce visible customer copy for a Product-First published
deployment.

For Product-First published deployments, AgentService and
`TurnOutput.final_message` are the only visible response authorities.

## Isolation States

Allowed target states for legacy components:

- `allowed_for_legacy_tenants`
- `shadow_compare_only`
- `structured_signal_only`
- `blocked_for_product_first`
- `degraded_no_visible_copy`
- `delete_later_after_migration`
- `unknown_needs_audit`

These states complement the deprecation labels in
`docs/architecture/legacy_deprecation_plan.md`.

## Isolation Gates

Before a Product-First deployment can publish, legacy isolation must prove:

- Deployment Resolver routes Product-First agents to AgentService.
- Product-First published agents do not enter `ConversationRunner`.
- legacy runner cannot send customer copy.
- provider fallback cannot send customer copy.
- manual recovery cannot send customer copy.
- ConversationProgressGuard cannot replace final copy.
- StructuredRuntimeComposer cannot emit Product-First published customer copy.
- HumanResponseComposer cannot emit Product-First published customer copy.
- ValidatedResponsePlanBuilder cannot convert `pending_slot` or
  `next_best_question` into visible customer copy.
- workflow copy paths cannot send outside SendAdapter.
- outbox worker cannot enqueue without SendAdapter approval.
- smoke-only logic cannot set publish/live state.
- fixture-only preflight cannot satisfy publish readiness.
- tenant hardcoding cannot influence shared runtime behavior.

## Component Decisions

The active component classification lives in
`docs/architecture/legacy_deprecation_plan.md`.

Minimum components that must stay classified:

- ConversationRunner
- legacy runner
- old advisor brain / sales decision policy
- old response_contract / response_frame
- ConversationProgressGuard
- StructuredRuntimeComposer
- HumanResponseComposer
- ValidatedResponsePlanBuilder
- manual recovery visible
- provider fallback visible
- workflow copy paths
- smoke-only logic
- fixture-only preflight
- hardcoded Dinamo logic
- dispersed send flags
- contradictory docs
- outbox worker
- universal turn trace
- Knowledge OS
- workflow engine

## Runtime Rules

At runtime:

- legacy may provide structured diagnostics only when explicitly allowed
- legacy diagnostics must be trace-only and internal
- legacy cannot fill `TurnOutput.final_message`
- legacy cannot call SendAdapter
- legacy cannot write outbox
- legacy cannot activate actions or workflows
- legacy cannot mutate Product-First publish state
- legacy cannot mask provider/model/tool/policy failures with generic copy

## Migration Rules

Before degrading or deleting any legacy component:

- prove non-Product-First tenants are unaffected
- identify replacement Product-First component
- write tests for replacement behavior
- prove rollback
- update feature readiness
- update ADR if authority changes
- get explicit deletion approval

## Publish Blockers

Publish Control must block when:

- a published Product-First deployment can reach legacy visible output
- a fallback path can produce customer text
- a workflow can send customer text outside SendAdapter
- fixture-only readiness is used as live evidence
- smoke-only logic controls readiness
- a tenant-specific rule is embedded in shared runtime
- legacy classification is `UNKNOWN_NEEDS_AUDIT` for an affected component
- rollback depends on an unclassified visible legacy path

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- Product-First deployment resolves only to AgentService
- Product-First published deployment does not enter `ConversationRunner`
- legacy runner cannot send visible output for Product-First deployment
- provider fallback visible output is blocked
- manual recovery visible output is blocked
- ConversationProgressGuard cannot replace final message
- StructuredRuntimeComposer cannot emit Product-First published visible copy
- HumanResponseComposer cannot emit Product-First published visible copy
- ValidatedResponsePlanBuilder cannot author Product-First published visible
  questions from slots
- workflow copy path cannot bypass SendAdapter
- smoke-only state cannot publish
- fixture-only preflight cannot publish
- hardcoded tenant rules are blocked from shared runtime

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 11 Acceptance

Fase 11 is complete when:

- legacy isolation states are documented
- isolation gates are documented
- component classification is linked
- runtime rules are documented
- migration rules are documented
- publish blockers are documented
- future tests are documented
- no legacy code was deleted or modified
- no live/runtime/DB behavior was changed

Decision for this documentary phase:

`PRODUCT_FIRST_PHASE_11_LEGACY_ISOLATION_DEFINED_DOCS_ONLY`

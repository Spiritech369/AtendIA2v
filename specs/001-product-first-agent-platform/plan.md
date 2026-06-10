# Implementation Plan: Product-First Agent Platform

**Date**: 2026-06-06  
**Spec**: `specs/001-product-first-agent-platform/spec.md`  
**Canonical Architecture**: `Arquitectura-Deseada.md`

## Summary

Create the Product-First documentation and spec-kit foundation for AtendIA.
This phase does not implement runtime behavior. It aligns authority, captures
decisions, defines readiness/completion gates, classifies legacy, and prepares a
future implementation roadmap.

## Technical Context

**Language/Version**: Python/FastAPI backend, TypeScript/React frontend  
**Primary Dependencies**: PostgreSQL, SQLAlchemy, Redis/queues, OpenAI-backed
semantic providers, existing Knowledge OS and Runtime V2 modules  
**Storage**: Documentation files only in this phase  
**Testing**: Static documentation verification with `rg` and file existence
checks; no runtime tests in this phase  
**Project Type**: Multi-tenant web application and backend services  
**Constraints**: No live, no DB, no Docker, no smoke, no outbox, no workflow side
effects, no runtime code changes  
**Scope**: Documentation, specs, matrices, definitions, and ADRs

## Constitution Check

- Product-First Control Plane: PASS for documentation scope.
- Single Runtime Authority: captured as requirement, no runtime mutation.
- `TurnOutput.final_message` authority: captured in architecture and gates.
- Fail-closed safety: captured in acceptance tests.
- DB-backed Test Lab before live: captured in Product-First plan.
- New/modified behavior coverage: required for future code changes.
- Codex code review: required before implementation handoff or commit.
- Live/smoke/outbox/workflows/actions: explicitly out of scope.

## Project Structure

```text
.specify/
|-- feature.json
|-- memory/constitution.md
|-- templates/
specs/001-product-first-agent-platform/
|-- spec.md
|-- plan.md
|-- tasks.md
docs/architecture/
|-- legacy_deprecation_plan.md
|-- feature_readiness_matrix.md
|-- product_first_acceptance_tests.md
|-- product_first_definition_of_ready.md
|-- product_first_definition_of_done.md
|-- product_first_product_entities.md
|-- product_first_agent_builder.md
|-- product_first_knowledge_sources.md
|-- product_first_runtime_single_route.md
|-- product_first_test_lab.md
|-- product_first_publish_control.md
|-- product_first_action_registry.md
|-- product_first_workflow_bindings.md
|-- product_first_inbox_trace_ux.md
|-- product_first_legacy_isolation.md
|-- product_first_controlled_beta_dinamo.md
|-- openai_agent_builder_migration_analysis.md
|-- openai_agent_builder_to_atendia_mapping.md
|-- atendia_agent_builder_contract.md
|-- atendia_agent_runtime_sdk_contract.md
|-- workflow_to_agent_migration_plan.md
|-- openai_agent_builder_alignment_adrs.md
|-- product_first_implementation_backlog.md
|-- decisions/product_first_adrs.md
docs/product/
|-- agent_builder_product_spec.md
|-- agent_test_lab_spec.md
|-- agent_publish_control_spec.md
reports/
|-- spec_kit_source_alignment_2026_06.md
|-- product_first_phase_0_1_completion_2026_06.md
|-- product_first_phase_2_3_completion_2026_06.md
|-- product_first_phase_4_5_completion_2026_06.md
|-- product_first_phase_6_7_completion_2026_06.md
|-- product_first_phase_8_9_completion_2026_06.md
|-- product_first_phase_10_11_completion_2026_06.md
|-- product_first_task_23_32_final_verification_2026_06.md
|-- openai_agent_builder_alignment_2026_06.md
|-- product_first_implementation_backlog_2026_06.md
```

## Phases

### Phase 0 - Freeze / Stop Patching

Document that no live, smoke, send, outbox, actions, workflow side effects, DB
changes, or runtime changes are part of this phase.

### Phase 1 - Architecture Alignment

Make `Arquitectura-Deseada.md` canonical, keep `ARCHITECTURE.md` stable, and
make `AGENTS.md` the Codex operational rulebook.

### Phase 2 - Product Entities

Define Agent, Agent Version, Agent Deployment, Knowledge Source, Source Binding,
Action Definition, Action Binding, Test Suite, Publish State, and Rollback
Version.

### Phase 3 - Agent Builder

Plan the builder for identity, voice, prompt blocks, source bindings, action
bindings, fields, lifecycle, handoff, workflows, tests, publish, and rollback.

### Phase 4 - Knowledge Sources Productized

Plan source lifecycle, health, indexing status, Source Bindings, retrieval
preview, publish blockers, runtime rules, and source trace requirements.

### Phase 5 - Runtime Single Route

Plan AgentService as the single DB-backed runtime route for no-send and
live-candidate, including AgentTurnRequest, AgentTurnResult, SendAdapter
boundary, fail-closed rules, and legacy visible-output restrictions.

### Phase 6 - DB-Backed Test Lab

Plan Test Lab to use the same runtime route as live with SendAdapter in no-send
mode, including Test Suite, Scenario, turn execution, parity assertions,
evidence, and publish blockers.

### Phase 7 - Publish Control

Plan deployment states, publish request contract, approval, send scopes,
rollback, readiness gates, feature readiness dependency, and DoR/DoD controls.

### Phase 8 - Action Registry

Plan structured actions, schemas, risk, approval, dry-run/live, idempotency, and
audit trail as product bindings that cannot create visible customer copy.

### Phase 9 - Workflow Bindings

Plan workflows as consumers of normalized events, not visible response writers,
including side-effect modes, loop guards, publish blockers, and trace.

### Phase 10 - Inbox Trace UX

Plan trace panels for final message, tools, state writes, policy, actions,
workflow decisions, send decision, redaction, blockers, and exact final message
review.

### Phase 11 - Legacy Isolation

Classify legacy and plan isolation states, BLOCK_FOR_V2 gates, degradation, and
removal prerequisites before any legacy deletion.

### Phase 12 - Controlled Beta With Dinamo

Plan Dinamo as a tenant beta after Product-First gates pass. Dinamo-specific
behavior remains tenant data, never shared runtime logic. The beta contract
defines prerequisites, evidence packet, required scenarios, publish blockers,
rollback, and future tests.

### Cross-Cutting Gates And Final Verification

Future implementation must include tests, changed-behavior coverage, Codex code
review, feature readiness updates, and DoD evidence. Final documentation
verification confirms expected docs/specs exist, placeholders are absent,
smoke/live is not treated as architecture, and the final plan decision is
`SPEC_KIT_PRODUCT_FIRST_PLAN_READY`.

### Phase 13 - OpenAI Agent Builder Alignment

Research the official OpenAI Agent Builder migration guide and adapt it to
AtendIA. This phase is research and specification only. It creates OpenAI
alignment analysis, mapping, AtendIA Agent Builder contract, AtendIA Agent
Runtime SDK contract, product specs for Agent Builder/Test Lab/Publish Control,
workflow-to-agent migration plan, and alignment ADRs.

Decision: `OPENAI_AGENT_BUILDER_ALIGNMENT_READY`.

### Phase 14 - Product-First Implementation Backlog

Consolidate the architecture, OpenAI alignment, feature readiness matrix,
legacy deprecation plan, Agent Builder contract, Runtime SDK contract, product
specs, and readiness gates into ordered implementation epics with dependencies,
required tests, Done criteria, and a first no-live implementation slice.

Decision: `PRODUCT_FIRST_IMPLEMENTATION_BACKLOG_READY`.

## Risks

- Existing worktree contains many unrelated deletions and untracked files.
- README may be absent/deleted; do not restore it without explicit approval.
- Old reports may contradict the new architecture; precedence must be clear.
- Legacy may have hidden live response paths; classify first, change later.
- Documentation drift can reappear unless ADRs and readiness matrix stay updated.

## Rollback

Rollback for this documentation phase is file-level only: revert the docs/specs
created in this phase. No DB, runtime, live, outbox, workflow, or channel state
is touched.

## Verification

- Confirm all expected files exist.
- Confirm no unresolved template placeholders remain.
- Confirm authority hierarchy is present.
- Confirm no doc authorizes smoke/live as architecture.
- Confirm test coverage and code review requirements are present.
- Confirm final decision can be `SPEC_KIT_PRODUCT_FIRST_PLAN_READY`.

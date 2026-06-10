# Feature Specification: Product-First Agent Platform

**Feature Directory**: `001-product-first-agent-platform`  
**Created**: 2026-06-06  
**Status**: Draft  
**Canonical Architecture**: `Arquitectura-Deseada.md`

## Problem

AtendIA has many real parts: Inbox, Agents, Knowledge OS, contact fields,
pipeline/lifecycle, workflows, expedientes, Runtime V2, AgentService,
ContextBuilder, SemanticInterpreter, TenantKnowledgeToolLayer, StateWriter,
PolicyValidator, SendAdapter, Outbox, and universal turn trace.

The current risk is architectural: Runtime V2 and legacy paths can coexist as
visible decision routes; deterministic composer branches can repeat fixed copy;
workflow/action paths are partially connected; flags are dispersed; and manual
smoke/preflight work can diverge from live behavior.

## Goals

- Make AtendIA product-first: Inbox -> Agent Builder -> Knowledge Sources ->
  Actions -> Workflows -> Test Lab -> Publish Control -> Single Runtime ->
  Trace/Analytics.
- Make `Arquitectura-Deseada.md` the canonical architecture for Product-First
  transformation.
- Establish spec-kit governance, tasks, readiness, completion, and decisions.
- Define how legacy is classified before it is degraded or removed.
- Define how future implementation must be tested, reviewed, and verified.

## Non-Goals

- Do not implement runtime features in this phase.
- Do not modify DB schema or migrations in this phase.
- Do not activate WhatsApp, live send, outbox, smoke, canary, actions, or
  workflow side effects.
- Do not delete legacy yet.
- Do not hardcode Dinamo or any vertical into shared runtime.

## User Scenarios & Testing

### User Story 1 - Configure And Publish Agent (Priority: P1)

As a tenant admin, I can configure an agent through product entities and publish
only after Test Lab and Publish Control pass.

**Why this priority**: This converts AtendIA from runtime-first to product-first.

**Independent Test**: A draft agent version can be configured, tested in no-send,
approved, published, paused, and rolled back in a documented flow.

**Acceptance Scenarios**:

1. **Given** a draft agent, **When** sources/actions/tests are incomplete,
   **Then** Publish Control blocks publication.
2. **Given** a tested agent version, **When** explicit approval is recorded,
   **Then** the published deployment references an immutable version.

### User Story 2 - Validate Knowledge And Actions (Priority: P1)

As an admin, I can bind Knowledge Sources and Actions to an agent version and
see readiness blockers before publish.

**Why this priority**: Missing live sources and unsafe actions caused prior
runtime failures.

**Independent Test**: A required source missing or action not approved blocks
publish and appears in readiness.

**Acceptance Scenarios**:

1. **Given** a required source binding is unhealthy, **When** publish is
   requested, **Then** publish is blocked.
2. **Given** an action is critical, **When** it lacks approval policy,
   **Then** action readiness is blocked.

### User Story 3 - Run One DB-Backed Runtime Route (Priority: P1)

As an operator, I can trust that no-send and live-candidate use the same runtime
path and differ only in SendAdapter.

**Why this priority**: Different test/live paths make smoke results unreliable.

**Independent Test**: The same inbound, tenant, contact, conversation, and agent
version produce the same context, tools, StateWriter decisions, policy checks,
and `TurnOutput.final_message` in no-send and live-candidate.

**Acceptance Scenarios**:

1. **Given** a required tool is skipped, **When** the runtime evaluates send,
   **Then** visible send is no-send.
2. **Given** policy validation fails, **When** SendAdapter runs,
   **Then** no outbox write is attempted.

### User Story 4 - Audit Why It Responded (Priority: P2)

As an operator, I can inspect why a turn responded, which tools ran, what was
written or blocked, and why send was allowed or blocked.

**Why this priority**: Traceability is needed to diagnose robotic or unsafe
responses without guessing.

**Independent Test**: Every Test Lab and live-candidate turn has a universal
trace with input, GPT interpretation, tools, state, policy, and send decision.

## Functional Requirements

- **FR-001**: System MUST treat `Arquitectura-Deseada.md` as the canonical
  Product-First architecture.
- **FR-002**: System MUST maintain `ARCHITECTURE.md` as a short stable summary.
- **FR-003**: System MUST maintain `AGENTS.md` as Codex operational rules.
- **FR-004**: System MUST store current architecture contracts in
  `docs/architecture/`.
- **FR-005**: System MUST treat `reports/` as historical evidence, not canonical
  architecture.
- **FR-006**: System MUST define a Product-First constitution.
- **FR-007**: System MUST define a spec, implementation plan, and task plan.
- **FR-008**: System MUST define legacy classification before removal.
- **FR-009**: System MUST define feature readiness states and gates.
- **FR-010**: System MUST define Definition of Ready and Definition of Done.
- **FR-011**: System MUST define acceptance tests for fail-closed invariants.
- **FR-012**: System MUST require tests for all new or modified behavior.
- **FR-013**: System MUST require 100% coverage of new or modified behavior.
- **FR-014**: System MUST require Codex code review before commit or handoff.
- **FR-015**: System MUST define Knowledge Source lifecycle, health, bindings,
  retrieval preview, publish blockers, runtime rules, and trace requirements.
- **FR-016**: System MUST define AgentService as the future single DB-backed
  runtime route.
- **FR-017**: System MUST define that legacy, workflows, fallbacks, recoveries,
  adapters, tools, and actions cannot override `TurnOutput.final_message` for
  published Runtime V2 deployments.
- **FR-018**: System MUST define DB-backed Test Lab suites, scenarios, turn
  execution, no-send/live-candidate parity, evidence, and publish blockers.
- **FR-019**: System MUST define Publish Control states, publish request
  contract, readiness gates, approval rules, send scopes, rollback, and feature
  readiness dependency.
- **FR-020**: System MUST define Action Registry contracts for schema, risk,
  dry-run/live mode, approval, idempotency, retry, audit, and publish blockers.
- **FR-021**: System MUST define Workflow Binding contracts so workflows consume
  normalized events and cannot overwrite primary customer copy.
- **FR-022**: System MUST define Inbox Trace UX surfaces, panels, redaction,
  access rules, Test Lab dependencies, Publish Control dependencies, and trace
  publish blockers.
- **FR-023**: System MUST define legacy isolation states, gates, runtime rules,
  migration rules, and publish blockers before deleting or degrading legacy.
- **FR-024**: System MUST define Dinamo as a controlled beta tenant only after
  Product-First gates pass.
- **FR-025**: System MUST define Dinamo-specific behavior as tenant data,
  Knowledge Sources, domain contracts, configuration, or tenant-aware tool
  results, not shared runtime logic.
- **FR-026**: System MUST adapt OpenAI Agent Builder migration guidance into
  AtendIA Product-First contracts without treating export as behavior proof.
- **FR-027**: System MUST define AtendIA Agent Builder, AgentService runtime SDK
  equivalent, Test Lab Preview, Publish Control, and workflow migration
  contracts aligned with the official OpenAI guidance.
- **FR-028**: System MUST consolidate Product-First architecture, OpenAI
  alignment, readiness, legacy, Agent Builder, and Runtime SDK contracts into an
  implementation backlog before coding.

## Non-Functional Requirements

- **NFR-001**: Documentation MUST be tenant-aware and avoid Dinamo-specific
  runtime rules.
- **NFR-002**: Documentation MUST not authorize live activation, smoke, outbox,
  actions, workflows, DB changes, or runtime changes in this phase.
- **NFR-003**: Future implementation MUST be testable, traceable, reversible,
  and publish-gated.
- **NFR-004**: Future implementation MUST fail closed on required tool or policy
  failures.

## Key Entities

- **Agent**: tenant-owned configurable AI agent.
- **Agent Version**: immutable published or draft configuration snapshot.
- **Agent Deployment**: active binding of a version to channels/audience.
- **Prompt Block**: structured instruction, persona, policy, or example block
  assembled into a versioned agent prompt.
- **Knowledge Source**: tenant-scoped factual source.
- **Source Binding**: versioned binding between agent version and source.
- **Action Definition**: structured action capability with schema and risk.
- **Action Binding**: versioned binding between agent version and action.
- **Field Policy**: read/write/evidence rules for contact memory.
- **Workflow Binding**: authorized bridge from agent event to workflow.
- **Test Suite**: DB-backed scenarios and assertions for publish readiness.
- **Publish State**: draft/test/approval/published/paused/rollback lifecycle.
- **Rollback Version**: prior approved version for immediate recovery.
- **Universal Turn Trace**: audit record for one runtime turn.

Detailed entity ownership is defined in
`docs/architecture/product_first_product_entities.md`.

Agent Builder behavior is defined in
`docs/architecture/product_first_agent_builder.md`.

Knowledge Sources behavior is defined in
`docs/architecture/product_first_knowledge_sources.md`.

Runtime single-route behavior is defined in
`docs/architecture/product_first_runtime_single_route.md`.

DB-backed Test Lab behavior is defined in
`docs/architecture/product_first_test_lab.md`.

Publish Control behavior is defined in
`docs/architecture/product_first_publish_control.md`.

Action Registry behavior is defined in
`docs/architecture/product_first_action_registry.md`.

Workflow Binding behavior is defined in
`docs/architecture/product_first_workflow_bindings.md`.

Inbox Trace UX behavior is defined in
`docs/architecture/product_first_inbox_trace_ux.md`.

Legacy isolation behavior is defined in
`docs/architecture/product_first_legacy_isolation.md`.

Controlled Dinamo beta behavior is defined in
`docs/architecture/product_first_controlled_beta_dinamo.md`.

OpenAI Agent Builder alignment is defined in:

- `docs/architecture/openai_agent_builder_migration_analysis.md`
- `docs/architecture/openai_agent_builder_to_atendia_mapping.md`
- `docs/architecture/atendia_agent_builder_contract.md`
- `docs/architecture/atendia_agent_runtime_sdk_contract.md`
- `docs/product/agent_builder_product_spec.md`
- `docs/product/agent_test_lab_spec.md`
- `docs/product/agent_publish_control_spec.md`
- `docs/architecture/workflow_to_agent_migration_plan.md`
- `docs/architecture/openai_agent_builder_alignment_adrs.md`

Implementation backlog is defined in
`docs/architecture/product_first_implementation_backlog.md`.

## Success Criteria

- **SC-001**: All required Product-First docs and spec-kit files exist.
- **SC-002**: No generated spec-kit file contains unresolved placeholders.
- **SC-003**: `Arquitectura-Deseada.md`, `ARCHITECTURE.md`, and `AGENTS.md`
  state non-conflicting authority rules.
- **SC-004**: Legacy components are classified with migration action and test
  gate.
- **SC-005**: The 25 agent features have readiness states and next gates.
- **SC-006**: Acceptance tests for runtime invariants are documented.
- **SC-007**: No live/send/outbox/workflow/runtime implementation occurs.
- **SC-008**: Knowledge Source readiness, binding, retrieval preview, and
  publish blockers are documented.
- **SC-009**: Runtime single route, SendAdapter boundary, fail-closed behavior,
  and legacy visible-output boundary are documented.
- **SC-010**: DB-backed Test Lab contract, no-send/live-candidate parity, and
  publish blockers are documented.
- **SC-011**: Publish Control state machine, approvals, send scopes, rollback,
  feature readiness, DoR, and DoD dependencies are documented.
- **SC-012**: Action Registry schema, risk, mode, approval, idempotency, audit,
  and publish blockers are documented.
- **SC-013**: Workflow Binding event, side-effect, loop guard, customer-copy,
  and publish blockers are documented.
- **SC-014**: Inbox Trace UX surfaces, required panels, redaction, access,
  Test Lab, Publish Control, and trace blockers are documented.
- **SC-015**: Legacy isolation states, gates, runtime rules, migration rules,
  publish blockers, and component classification are documented.
- **SC-016**: Dinamo controlled beta prerequisites, tenant-data boundary,
  evidence packet, required scenarios, publish blockers, and future tests are
  documented.
- **SC-017**: Final documentation verification confirms expected files,
  placeholders, smoke/live architecture wording, testing/review gates, and final
  decision.
- **SC-018**: OpenAI Agent Builder migration guidance is summarized, mapped to
  AtendIA, and converted into contracts/specs for Agent Builder, AgentService,
  Test Lab, Publish Control, workflow migration, and ADRs.
- **SC-019**: Product-First implementation backlog defines ordered epics,
  dependencies, tests, gates, first implementation slice, and final backlog
  decision.

## Assumptions

- This phase is documentation and planning only.
- `spec-kit-main` is used as local template/source guidance, not as an installed
  dependency requirement.
- Legacy remains in place until a future approved phase implements isolation or
  removal.
- Coverage requirements apply to new or modified behavior, not global legacy
  coverage.

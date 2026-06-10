# Product-First Implementation Backlog

Date: 2026-06-06  
Status: Executive implementation backlog  
Canonical source: `Arquitectura-Deseada.md`  
Decision: `PRODUCT_FIRST_IMPLEMENTATION_BACKLOG_READY`

## Purpose

This document consolidates the Product-First architecture into a single
implementation backlog. It is the executive bridge between planning and future
code work.

This is still documentation and planning. It does not modify runtime, DB,
Docker, WhatsApp, outbox, actions, workflows, smoke, canary, production, or
legacy code.

## Source Documents

This backlog consolidates:

- `Arquitectura-Deseada.md`
- `docs/architecture/openai_agent_builder_migration_analysis.md`
- `docs/architecture/openai_agent_builder_to_atendia_mapping.md`
- `docs/architecture/atendia_agent_builder_contract.md`
- `docs/architecture/atendia_agent_runtime_sdk_contract.md`
- `docs/architecture/feature_readiness_matrix.md`
- `docs/architecture/legacy_deprecation_plan.md`
- `docs/architecture/product_first_definition_of_ready.md`
- `docs/architecture/product_first_definition_of_done.md`
- `docs/architecture/product_first_acceptance_tests.md`
- `docs/product/agent_builder_product_spec.md`
- `docs/product/agent_test_lab_spec.md`
- `docs/product/agent_publish_control_spec.md`

## Executive Sequence

Implementation must happen in this order:

1. Product data model and versioning foundation.
2. Agent Builder Control Plane.
3. Knowledge Sources readiness and bindings.
4. Tools, Action Registry, and Workflow Bindings.
5. AgentService single runtime route in no-send.
6. DB-backed Test Lab.
7. Publish Control state machine.
8. Inbox Trace UX.
9. Legacy isolation for Product-First deployments.
10. Workflow-to-agent migration tooling.
11. Controlled Dinamo beta only after gates pass.

No live send is part of the initial implementation backlog. Live-limited beta
requires a separate approval after Test Lab and Publish Control pass.

## Epic 0 - Safety Freeze And Implementation Discipline

Objective:

- Preserve no-live/no-smoke/no-runtime-side-effect boundaries while Product-First
  implementation begins.

Must implement:

- repo guidance enforcement
- Definition of Ready checklist
- Definition of Done checklist
- changed-behavior test requirement
- 100% coverage for new or modified behavior
- Codex code review before commit/handoff

Blockers:

- unclear live boundary
- missing rollback
- missing tests
- unclassified legacy impact

Done when:

- every implementation PR/task reports tests, coverage, review status, rollback,
  and feature readiness update.

## Epic 1 - Product Entities And Versioning

Objective:

- Make Agent, Agent Version, Agent Deployment, Prompt Blocks, Source Bindings,
  Action Bindings, Workflow Bindings, Test Suites, Publish State, and Rollback
  Version real product entities.

Must implement:

- DB schema or model layer for product entities
- immutable published agent versions
- draft vs published separation
- tenant isolation
- rollback target relationship
- audit fields

Required tests:

- draft edits do not affect published version
- published version is immutable
- cross-tenant source/action/workflow binding is blocked
- rollback target must be approved

Done when:

- Agent Builder can persist draft and published configuration without runtime
  hardcoding.

## Epic 2 - Agent Builder Control Plane

Objective:

- Build the tenant-facing product surface for configurable agents.

Must implement:

- Agent list
- draft editor
- prompt blocks
- Knowledge Source bindings
- tool/action bindings
- field and lifecycle permissions
- workflow bindings
- handoff rules
- safety policy
- Test Suite attachment
- publish readiness view
- version history and rollback view

Required tests:

- builder saves draft configuration
- publish request uses immutable version
- missing required config appears as readiness blocker
- no builder edit mutates live version directly

Done when:

- tenants can configure a complete draft agent without code changes.

## Epic 3 - Knowledge Sources Productized

Objective:

- Make sources publish-gated, tenant-scoped, health-checked, and traceable.

Must implement:

- source lifecycle
- health status
- parser/index status
- Source Binding readiness
- retrieval preview
- stale/unhealthy blockers
- trace source snapshots

Required tests:

- missing required source blocks publish
- stale/unhealthy source blocks publish
- retrieval preview uses only bound tenant sources
- unsupported factual claim is blocked

Done when:

- factual answers can be tied to healthy bound tenant sources.

## Epic 4 - Tools, Actions, And Workflows

Objective:

- Separate fact resolution, side effects, and automation.

Must implement:

- tenant-aware tool bindings
- Action Registry schemas, risk, auth, permissions, idempotency, dry-run/live
  modes
- Workflow Bindings as normalized event consumers
- no workflow visible-copy authority
- no action visible-copy authority

Required tests:

- unknown or disabled action is blocked
- missing action schema/auth/permission blocks publish
- Test Lab actions are dry-run only
- workflow cannot overwrite `TurnOutput.final_message`
- workflow side effects are zero in no-send

Done when:

- tools return facts, actions return structured side-effect results, and
  workflows consume events only.

## Epic 5 - AgentService Single Runtime Route

Objective:

- Make AgentService the only runtime path for Product-First published agents.

Must implement:

- `AgentTurnRequest`
- `AgentTurnResult`
- deployment resolver
- context builder with versioned agent config
- semantic provider call
- required tool execution and validation
- StateWriter evidence gate
- Composer final message
- Policy gate
- SendAdapter decision
- Universal Turn Trace

Required tests:

- no-send/live-candidate route parity
- required tool failure means no-send
- policy failure means no-send
- internal/debug/recovery text never visible
- legacy cannot produce visible output
- SendAdapter is the only delivery path

Done when:

- the same inbound produces the same context, tools, state decisions, policy,
  and final message in no-send and live-candidate; only SendAdapter differs.

## Epic 6 - DB-Backed Test Lab

Objective:

- Replace fixture-only preview with DB-backed no-send validation.

Must implement:

- Test Suite product entity
- Scenario product entity
- turn runner using AgentService no-send
- expected vs actual assertions
- exact final message review
- source/tool/state/policy/send trace panels
- outbox zero audit
- side-effect zero audit

Required tests:

- Test Lab uses same AgentService route
- exact final message is stored
- outbox remains zero
- side effects remain zero
- failed Test Lab blocks publish

Done when:

- publish readiness can be proven without live send or smoke.

## Epic 7 - Publish Control

Objective:

- Replace scattered send flags with a deployment state machine.

Must implement:

- publish states
- publish request record
- readiness gate evaluation
- human approval record
- send scope
- rollback metadata
- pause/rollback controls

Required tests:

- publish blocked without Test Lab passed
- publish blocked without rollback target
- publish blocked with legacy visible route
- send scope cannot expand without approval
- scattered flags cannot bypass deployment state

Done when:

- no deployment can reach live-limited send without Publish Control approval.

## Epic 8 - Inbox Trace UX

Objective:

- Give operators a complete "why this answer?" view.

Must implement:

- turn header panel
- context panel
- semantic understanding panel
- knowledge/tool panel
- StateWriter/lifecycle panel
- actions/workflows panel
- policy/send panel
- final message panel
- redaction and tenant-scoped access

Required tests:

- trace contains required panels
- trace redacts secrets and cross-tenant data
- missing required trace fields block publish
- trace cannot become customer-visible copy

Done when:

- every Test Lab and live-candidate turn can explain final message, blockers,
  tools, state, policy, and send decision.

## Epic 9 - Legacy Isolation

Objective:

- Prevent old code paths from affecting Product-First published agents.

Must implement:

- deployment resolver block for legacy visible paths
- provider fallback visible block
- manual recovery visible block
- workflow copy path block
- ConversationProgressGuard no-copy boundary
- StructuredRuntimeComposer degradation plan
- smoke-only and fixture-only readiness block

Required tests:

- Product-First deployment resolves only to AgentService
- legacy runner cannot send visible output
- fallback/recovery visible output is blocked
- workflow copy path cannot bypass SendAdapter
- fixture-only readiness cannot publish

Done when:

- legacy can remain for non-migrated tenants but cannot affect Product-First
  visible output.

## Epic 10 - Workflow-To-Agent Migration

Objective:

- Migrate only the right parts of existing workflows into agents.

Must implement:

- workflow inventory
- behavior classifier
- migration review UI/report
- representative Test Lab scenario generation
- action/tool/workflow binding recommendations
- deterministic workflow keep-as-workflow decision path

Required tests:

- deterministic workflow remains workflow
- conversational behavior can move to Agent Builder
- side effects remain action/workflow controlled
- migrated behavior passes representative inputs

Done when:

- migration is evidence-based and does not assume export equals correctness.

## Epic 11 - Controlled Dinamo Beta

Objective:

- Use Dinamo as first controlled beta only after Product-First gates pass.

Must implement:

- tenant-scoped Dinamo sources
- tenant-scoped tools/contracts
- Dinamo Test Lab scenarios
- explicit beta evidence packet
- approved-contact or approved-segment scope
- rollback plan

Required tests:

- Dinamo facts come from tenant data/tools
- no hardcoded Dinamo runtime logic
- quote claims require quote tool
- requirements claims require requirements tool/source
- no-send/live-candidate parity holds
- rollback disables send scope before investigation

Done when:

- Dinamo can be approved for a future live-limited beta without weakening shared
  runtime architecture.

## Implementation Readiness Gates

Every epic must satisfy Definition of Ready before coding:

- approved phase
- spec exists
- risks known
- tests planned
- rollback defined
- legacy impact classified
- live boundary explicit
- no hidden side effects

Every epic must satisfy Definition of Done before handoff:

- tests passed
- 100% changed-behavior coverage reported
- Codex code review complete
- trace/audit evidence where applicable
- feature readiness updated
- rollback documented
- no fixtures-only live readiness
- no legacy visible interference

## First Implementation Slice

Recommended first implementation slice:

1. Product entities and immutable Agent Version model.
2. Agent Builder draft/publish read model with no live send.
3. AgentService no-send request/result contract behind Test Lab only.
4. Test Lab scenario runner using no-send.
5. Trace record completeness for Test Lab turns.

This slice must not enable live, outbox, actions, workflow side effects, canary,
or production.

## Final Decision

`PRODUCT_FIRST_IMPLEMENTATION_BACKLOG_READY`

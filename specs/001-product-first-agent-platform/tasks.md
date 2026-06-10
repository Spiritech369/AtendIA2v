# Tasks: Product-First Agent Platform

**Input**: `spec.md`, `plan.md`, `Arquitectura-Deseada.md`, Product-First
constitution, `JunioAuditoria2026.md`, `Investigacion2026.docx`,
`AGENTS.md`, and `ARCHITECTURE.md`.

## Phase 0 - Freeze / Stop Patching

- [x] T001 Document that this phase does not touch runtime, DB, Docker, live,
  WhatsApp, send flags, outbox, actions, workflows, canary, smoke, or legacy
  deletion.
- [x] T002 Record current source alignment in
  `reports/spec_kit_source_alignment_2026_06.md`.

## Phase 1 - Architecture Alignment

- [x] T003 Update `Arquitectura-Deseada.md` as canonical Product-First
  architecture.
- [x] T004 Update `ARCHITECTURE.md` as stable summary only.
- [x] T005 Update `AGENTS.md` as Codex operational rulebook.
- [x] T006 Create Product-First ADRs in
  `docs/architecture/decisions/product_first_adrs.md`.

## Phase 2 - Product Entities

- [x] T007 Document control-plane entities in spec and target architecture.
- [x] T008 Document runtime-plane responsibilities and ownership boundaries.
- [x] T008A Implement Product Entities Foundation models, migration, isolated API,
  service validation, tests, and no-live safety defaults without connecting
  Runtime V2, WhatsApp, outbox, smoke, canary, actions, workflow side effects,
  or production traffic.

## Phase 3 - Agent Builder

- [x] T009 Define Agent Builder responsibilities for identity, prompt blocks,
  sources, actions, fields, lifecycle, handoff, workflows, tests, publish, and
  rollback.
- [x] T009A Implement no-live Agent Builder MVP with Product-First API endpoints,
  `/agent-builder` frontend surface, draft version editing, readiness checks,
  tests, and no Runtime V2/WhatsApp/outbox/workflow/live side effects.

## Phase 4 - Knowledge Sources Productized

- [x] T010 Define Knowledge Sources readiness, source health, bindings,
  retrieval preview, and publish blockers.
- [x] T010A Implement no-live Knowledge Sources productization in Product Agent
  Builder with tenant-scoped source options, draft source bindings, source
  health/readiness blockers, frontend Knowledge tab, tests, and no Runtime
  V2/WhatsApp/outbox/workflow/live side effects.

## Phase 4B - Tool/Action Bindings Productized

- [x] T010B Implement no-live Tool/Action binding productization in Product
  Agent Builder with fact-only tool capabilities, side-effect action
  capabilities, draft-scoped bind/unbind APIs, separate frontend Tools and
  Actions tabs, readiness metadata, tests, and no Runtime V2/WhatsApp/outbox/
  workflow/live side effects.

## Phase 5 - Runtime Single Route

- [x] T011 Define AgentService as the future single DB-backed runtime route.
- [x] T012 Document that legacy cannot override published Runtime V2 visible
  output.

## Phase 6 - DB-Backed Test Lab

- [x] T013 Define Test Lab acceptance tests in
  `docs/architecture/product_first_acceptance_tests.md`.
- [x] T014 Require same context/tools/StateWriter/Policy/TurnOutput between
  no-send and live-candidate.
- [x] T014A Implement DB-backed no-send Test Lab MVP with `AgentTestRun`,
  tenant-scoped suite/scenario APIs, AgentService no-send runner, outbox and
  side-effect audits, Product Agent Builder Test Lab tab, focused tests, and no
  Runtime V2/WhatsApp/outbox/workflow/action/live side effects.
- [x] T014B Implement and verify DB-backed Test Lab behavior validation with
  multiturn expected-vs-actual assertions, per-turn tools/state/policy/send
  evidence, readiness blockers, frontend evidence display, focused tests, and
  100% coverage for modified behavior.
- [x] T014C Implement `agent_service_real` DB-backed Test Lab no-send mode with
  real AgentService provider construction, OpenAI token/cost evidence,
  required-tool/policy blockers, frontend execution mode UI, focused tests, and
  100% coverage for Product Agent modified behavior. Actual real API scenario
  execution remains blocked until `OPENAI_API_KEY` is available in the
  execution environment.
- [x] T014D Implement `HUMAN_RESPONSE_COMPOSER_FROM_VALIDATED_FACTS` for
  Runtime V2 semantic no-send path with `ValidatedResponsePlanBuilder`,
  `HumanResponseComposer`, grounded policy checks, Test Lab evidence fields,
  focused tests, and no live/WhatsApp/outbox/workflow/action side effects.

## Phase 7 - Publish Control

- [x] T015 Define publish states, approval, rollback, and feature readiness
  gates.
- [x] T016 Create `docs/architecture/product_first_definition_of_ready.md`.
- [x] T017 Create `docs/architecture/product_first_definition_of_done.md`.
- [x] T017A Implement no-live Publish Control MVP with `AgentPublishRequest`,
  tenant-scoped publish request APIs, no-send approval state machine, Product
  Agent Builder Publish tab, focused tests, 100% coverage for modified
  behavior, and no Runtime V2/WhatsApp/outbox/workflow/action/live side
  effects.

## Phase 8 - Action Registry

- [x] T018 Define action registry requirements in architecture docs: schema,
  risk, dry-run/live mode, approval, idempotency, and audit.

## Phase 9 - Workflow Bindings

- [x] T019 Define workflow binding constraints: workflows consume events and
  cannot overwrite primary customer copy.

## Phase 10 - Inbox Trace UX

- [x] T020 Define trace expectations: GPT interpretation, tools, state writer,
  policy, final message, send decision, actions, workflows, and blockers.

## Phase 11 - Legacy Isolation

- [x] T021 Create `docs/architecture/legacy_deprecation_plan.md`.
- [x] T022 Classify ConversationRunner, legacy runner, old advisor brain,
  response contract, ConversationProgressGuard, StructuredRuntimeComposer,
  visible fallback/recovery, workflow copy paths, smoke-only logic,
  fixture-only preflight, hardcoded Dinamo, dispersed flags, and contradictory
  docs.

## Phase 12 - Controlled Beta With Dinamo

- [x] T023 Document Dinamo as beta tenant only after Product-First gates pass.
- [x] T024 Ensure Dinamo behavior remains tenant data, not shared runtime logic.

## Cross-Cutting Gates For Future Implementation

- [x] T025 Future code tasks must include unit/integration tests for new or
  modified behavior.
- [x] T026 Future code tasks must report 100% coverage for new or modified
  behavior.
- [x] T027 Future code tasks must run Codex code review against base branch or
  uncommitted changes before commit/handoff.
- [x] T028 Future code tasks must update feature readiness and DoD evidence.

## Documentation Verification

- [x] T029 Confirm all expected docs/specs exist.
- [x] T030 Confirm no unresolved spec-kit placeholders remain.
- [x] T031 Confirm no doc recommends smoke/live as architecture.
- [x] T032 Confirm final decision is `SPEC_KIT_PRODUCT_FIRST_PLAN_READY`.

## Phase 13 - OpenAI Agent Builder Alignment

- [x] T033 Read and summarize the official OpenAI Agent Builder migration guide.
- [x] T034 Create OpenAI-to-AtendIA concept mapping.
- [x] T035 Define AtendIA Agent Builder contract.
- [x] T036 Define AtendIA AgentService runtime SDK equivalent.
- [x] T037 Define Agent Builder product spec.
- [x] T038 Define Agent Test Lab product spec.
- [x] T039 Define Agent Publish Control product spec.
- [x] T040 Define workflow-to-agent migration plan.
- [x] T041 Define OpenAI Agent Builder alignment ADRs.
- [x] T042 Update `Arquitectura-Deseada.md` only with alignment improvements.
- [x] T043 Confirm final decision is `OPENAI_AGENT_BUILDER_ALIGNMENT_READY`.

## Phase 14 - Product-First Implementation Backlog

- [x] T044 Consolidate architecture, OpenAI alignment, feature readiness, legacy
  deprecation, Agent Builder contract, and Runtime SDK contract into one
  executive implementation backlog.
- [x] T045 Define ordered implementation epics, dependencies, required tests,
  Done gates, and first no-live implementation slice.
- [x] T046 Confirm final decision is
  `PRODUCT_FIRST_IMPLEMENTATION_BACKLOG_READY`.

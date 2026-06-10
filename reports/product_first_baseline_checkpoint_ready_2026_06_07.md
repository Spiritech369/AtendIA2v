# Product-First Baseline Checkpoint

Date: 2026-06-07

Decision: `PRODUCT_FIRST_BASELINE_CHECKPOINT_READY`

## Purpose

Record the current Product-First baseline before any next implementation phase.

This checkpoint is documentation-only. It is not a commit, not a reset, not a
cleanup, not staging, not a restore, and not a live activation. No dirty file
was reverted, deleted, moved, staged, or cleaned.

## Current Ready Decisions

- `SPEC_KIT_PRODUCT_FIRST_PLAN_READY`
- `PRODUCT_FIRST_IMPLEMENTATION_BACKLOG_READY`
- `PRODUCT_ENTITIES_FOUNDATION_READY`
- `AGENT_BUILDER_MVP_READY`
- `KNOWLEDGE_SOURCES_PRODUCTIZED_READY`
- `TOOL_ACTION_BINDINGS_PRODUCTIZED_READY`
- `DB_BACKED_TEST_LAB_MVP_READY`
- `PUBLISH_CONTROL_MVP_NO_SEND_READY`

## Phases Ready

### Phase 0 - Freeze / Stop Patching

Ready:

- Product-First transformation is documented as the active direction.
- Live/smoke/WhatsApp/outbox/workflow/action side effects remain out of scope
  unless explicitly approved.
- Reports remain historical evidence, not canonical architecture.

### Phase 1 - Architecture Alignment

Ready:

- `Arquitectura-Deseada.md` is canonical for Product-First transformation.
- `ARCHITECTURE.md` is the stable high-level summary.
- `AGENTS.md` is the Codex operational rulebook.
- `docs/architecture/` contains current contracts.
- `reports/` contains evidence, audits, simulations, incidents, and
  checkpoints.

### Phase 2 - Product Entities Foundation

Ready:

- Product Agent entities exist for agents, versions, deployments, bindings,
  tests, publish state, and rollback targets.
- Entities are tenant-scoped and generic.
- No Dinamo, motos, credit, phone, catalog, or vertical-specific rule is
  hardcoded into shared Product-First entity code.
- Deployment flags are safe by default and do not enable live send.

### Phase 3 - Agent Builder MVP

Ready:

- Product Agent Builder backend endpoints exist.
- `/agent-builder` frontend surface exists.
- Agent creation, draft creation, draft editing, identity fields, prompt blocks,
  readiness, and safety panel exist.
- Builder uses Product-First endpoints, not the legacy Agents API.
- Builder does not activate Runtime V2 live, WhatsApp, outbox, workflows,
  actions, smoke, canary, or production.

### Phase 4 - Knowledge Sources Productized

Ready:

- Tenant-scoped knowledge source options exist.
- Draft source binding list/create/remove exists.
- Builder Knowledge tab exists.
- Missing or unhealthy sources produce readiness blockers.
- Source health evidence is visible without claiming live readiness.

### Phase 5 - Tool/Action Bindings Productized

Ready:

- Tools and actions are separated.
- Tools are fact capabilities.
- Actions are side-effect capabilities.
- Draft tool/action binding APIs exist.
- Builder Tools and Actions tabs exist.
- Send boundary action remains disabled in Builder MVP.
- No action execution or workflow side effect is activated.

### Phase 6 - DB-Backed Test Lab MVP

Ready:

- Tenant-scoped Test Suite, Test Scenario, and Test Run entities exist.
- Builder Test Lab tab exists.
- No-send Test Lab run stores durable evidence.
- Test Lab records final message evidence, trace ids, tool/state evidence,
  outbox audit, and side-effect audit.
- Test Lab does not send WhatsApp and does not write live outbox.

### Phase 7 - Publish Control MVP

Ready:

- `AgentPublishRequest` exists.
- Publish request APIs exist for create, latest, evaluate, approve-no-send, and
  reject.
- Product Agent Builder Publish tab exists.
- Publish Control can approve only `published_no_send`.
- Approval keeps `runtime_mode=no_send`, `send_scope=none`, and live/action/
  workflow/canary/production flags false.
- Publish Control requires Test Lab, trace, outbox audit, side-effect audit,
  readiness, and rollback target evidence.
- Publish Control does not activate live, smoke, WhatsApp, SendAdapter, outbox,
  actions, workflow side effects, canary, or production.

## Principal Files Changed Or Added

### Core Product-First Backend

- `core/atendia/db/models/product_agent.py`
- `core/atendia/db/models/__init__.py`
- `core/atendia/db/migrations/versions/066_product_first_agent_entities.py`
- `core/atendia/db/migrations/versions/067_product_first_agent_test_runs.py`
- `core/atendia/db/migrations/versions/068_product_first_publish_control.py`
- `core/atendia/product_agents/`
- `core/atendia/api/product_agents_routes.py`

### Product-First Frontend

- `frontend/src/features/product-agent-builder/`
- `frontend/src/routes/(auth)/agent-builder.tsx`
- `frontend/src/features/navigation/menu-config.ts`
- `frontend/src/routeTree.gen.ts`

### Product-First Tests

- `core/tests/product_agents/`
- `frontend/tests/features/product-agent-builder/`

### Product-First Architecture And Specs

- `Arquitectura-Deseada.md`
- `ARCHITECTURE.md`
- `AGENTS.md`
- `.specify/`
- `specs/001-product-first-agent-platform/`
- `docs/architecture/`
- `docs/product/`

### Product-First Evidence

- `reports/product_entities_foundation_2026_06_07.md`
- `reports/product_first_phase_3_agent_builder_2026_06_07.md`
- `reports/product_first_phase_4_knowledge_sources_productized_2026_06_07.md`
- `reports/product_first_phase_5_tool_action_bindings_2026_06_07.md`
- `reports/product_first_phase_6_db_backed_test_lab_mvp_2026_06_07.md`
- `reports/product_first_phase_7_publish_control_mvp_2026_06_07.md`
- `reports/product_first_baseline_checkpoint_ready_2026_06_07.md`

## Current Worktree Status

Observed with `git status --short` on 2026-06-07:

- Total dirty entries: `425`
- Untracked entries: `84`
- Deleted entries: `318`
- Modified tracked entries: `23`
- Staged entries observed: `0`

Important interpretation:

- The repository is intentionally not clean.
- The Product-First baseline is mostly untracked because it has not been staged
  or committed.
- Many deleted entries are historical reports/docs/assets outside the current
  Product-First implementation scope.
- Nothing was cleaned, restored, reset, deleted, staged, or committed by this
  checkpoint.

## What Is Untracked

Main untracked categories:

- Product-First specs and `.specify/`.
- Product-First architecture contracts under `docs/architecture/`.
- Product docs under `docs/product/`.
- Product Agent backend code under `core/atendia/product_agents/`.
- Product Agent API route under `core/atendia/api/product_agents_routes.py`.
- Product Agent DB model and migrations.
- Product Agent tests under `core/tests/product_agents/`.
- Product Agent Builder frontend and tests.
- Product-First reports for phases 2 through 7.
- Runtime V2 no-send/parity support files from earlier approved work.
- Tenant source docs restored under `docs/tenant_sources/dinamo/`.

These untracked files should be preserved until there is an explicit staging,
commit, branch, or cleanup plan.

## Tests Passed

Latest verification relevant to the current Product-First baseline:

### Backend

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run ruff check atendia/product_agents atendia/api/product_agents_routes.py tests/product_agents atendia/db/models/product_agent.py atendia/db/models/__init__.py atendia/db/migrations/versions/068_product_first_publish_control.py
```

Result:

- `All checks passed!`

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Result:

- `114 passed`
- Product Agent backend coverage: `100.00%`

### Frontend

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder
```

Result:

- `Checked 3 files`
- `No fixes applied`

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include="src/features/product-agent-builder/**/*.{ts,tsx}" --coverage.reporter=text --coverage.thresholds.lines=100 --coverage.thresholds.functions=100 --coverage.thresholds.branches=100 --coverage.thresholds.statements=100
```

Result:

- `24 passed`
- statements: `100%`
- branches: `100%`
- functions: `100%`
- lines: `100%`

### Safety Search

```powershell
rg -n "Dinamo|8128889241|send_enabled=true|live_send_enabled=true|single_contact_smoke_enabled=true|published_live_limited|production|canary|WhatsApp" core/atendia/product_agents core/atendia/api/product_agents_routes.py frontend/src/features/product-agent-builder frontend/tests/features/product-agent-builder core/tests/product_agents
```

Result:

- No tenant/contact hardcode found in shared Product-First implementation.
- Live/canary/production references are schemas, blocked states, safety checks,
  or tests proving they are not exposed/enabled.

## What Follows

Recommended next work:

1. Do not go to WhatsApp.
2. Do not start a smoke.
3. Use the DB-backed Test Lab as the next validation surface.
4. Expand Test Lab from infrastructure MVP to real agent-behavior validation:
   - canonical conversation suites
   - exact final message review
   - trace review
   - tool-call evidence
   - state writer evidence
   - policy/fail-closed evidence
   - no-send/live-candidate parity evidence when send scope becomes relevant
5. Keep Publish Control as the gate, not as a live activation shortcut.

## Do Not Touch Without Explicit Approval

- WhatsApp send.
- single-contact smoke.
- canary.
- open production.
- SendAdapter live behavior.
- outbound outbox live writes.
- workflow events.
- workflow side effects.
- action execution.
- legacy deletion.
- destructive filesystem cleanup.
- `git reset`, `git clean`, `git restore`, `git checkout --`, rebase, push, or
  any force/destructive git operation.
- historical incident/report evidence.
- tenant-specific Dinamo behavior inside shared Product-First runtime code.

## Remaining Risks

- Worktree is dirty with 425 entries.
- Product-First work is not staged or committed.
- Many unrelated deleted files remain visible in git status.
- Future work should stay narrowly scoped or first create an explicit commit/
  cleanup plan.
- Global legacy build/test status is not asserted by this checkpoint; this
  checkpoint records Product-First scoped verification only.

## Checkpoint Decision

`PRODUCT_FIRST_BASELINE_CHECKPOINT_READY`

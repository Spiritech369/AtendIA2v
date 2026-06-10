# Product-First Phase 6 DB-Backed Test Lab MVP

Date: 2026-06-07

Decision: `DB_BACKED_TEST_LAB_MVP_READY`

## Scope

Implemented the no-send MVP for Fase 6 - DB-backed Test Lab.

This phase did not activate WhatsApp, live send, smoke, canary, outbox
dispatch, workflow side effects, action side effects, Runtime V2 live behavior,
Baileys, or open production.

## Implemented

- Added durable `AgentTestRun` ORM model and migration.
- Added tenant-scoped Test Suite and Test Scenario schemas/services/API routes.
- Added no-send Test Lab runner that calls `AgentService.handle_turn` with
  `mode="no_send"`.
- Added sandbox DB conversation creation for Test Lab execution.
- Recorded turn evidence: inbound, final message, trace id, required tools,
  tool results, send status, errors, and state persistence.
- Recorded run evidence: scenario results, turn results, pass/fail/blocked
  counts, trace ids, outbox audit, side-effect audit, and decision.
- Added Product Agent Builder Test Lab tab for suite/scenario creation, no-send
  run execution, latest run evidence, exact final message, trace count, outbox
  audit, and side-effect audit.
- Updated Product-First Test Lab architecture/spec/tasks/readiness docs.

## Files Changed

- `core/atendia/db/models/product_agent.py`
- `core/atendia/db/models/__init__.py`
- `core/atendia/db/migrations/versions/067_product_first_agent_test_runs.py`
- `core/atendia/product_agents/schemas.py`
- `core/atendia/product_agents/service.py`
- `core/atendia/product_agents/test_lab.py`
- `core/atendia/api/product_agents_routes.py`
- `core/tests/product_agents/test_agent_test_lab_service.py`
- `core/tests/product_agents/test_agent_test_lab_runner.py`
- `core/tests/product_agents/test_agent_builder_api_routes.py`
- `core/tests/product_agents/test_agent_model_tenant_scoped.py`
- `frontend/src/features/product-agent-builder/api.ts`
- `frontend/src/features/product-agent-builder/components/AgentBuilderPage.tsx`
- `frontend/tests/features/product-agent-builder/AgentBuilderPage.test.tsx`
- `docs/architecture/product_first_test_lab.md`
- `docs/product/agent_test_lab_spec.md`
- `docs/architecture/feature_readiness_matrix.md`
- `specs/001-product-first-agent-platform/tasks.md`

## Verification

Backend lint:

```text
uv run ruff check atendia/product_agents atendia/api/product_agents_routes.py tests/product_agents atendia/db/models/product_agent.py atendia/db/models/__init__.py atendia/db/migrations/versions/067_product_first_agent_test_runs.py
All checks passed.
```

Backend tests and coverage:

```text
uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
100 passed.
Total coverage: 100.00%.
```

Frontend lint:

```text
npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder
Checked 3 files. No fixes applied.
```

Frontend tests and coverage:

```text
npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include="src/features/product-agent-builder/**/*.{ts,tsx}" --coverage.reporter=text --coverage.thresholds.lines=100 --coverage.thresholds.functions=100 --coverage.thresholds.branches=100 --coverage.thresholds.statements=100
17 passed.
Statements: 100%.
Branches: 100%.
Functions: 100%.
Lines: 100%.
```

## Build Blocker

Global frontend build was attempted:

```text
npm.cmd run build
```

It is blocked by existing legacy/global TypeScript issues outside the Product
Agent Builder/Test Lab change, including missing module type resolution for
`zustand`, `recharts`, `@xyflow/react`, and many pre-existing implicit `any`
parameters in unrelated components/stores.

This blocker does not indicate a Fase 6 Test Lab failure, but it must be tracked
before claiming global frontend build readiness.

## No-Live Confirmation

- No WhatsApp send activated.
- No smoke activated.
- No canary activated.
- No open production activated.
- No live outbox dispatch added.
- No SendAdapter behavior changed.
- No workflow side effects enabled.
- No action side effects enabled.
- No Dinamo or vertical rule added to shared runtime/product code.

## Remaining Gates

- Publish Control must consume latest required Test Lab run evidence.
- no-send/live-candidate parity must be enforced before send scope is in play.
- Global frontend build legacy blocker should be resolved or accepted before
  product-wide build readiness.

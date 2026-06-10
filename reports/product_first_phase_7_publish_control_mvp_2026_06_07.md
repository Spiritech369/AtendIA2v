# Product-First Phase 7 - Publish Control MVP

Date: 2026-06-07

Decision: `PUBLISH_CONTROL_MVP_NO_SEND_READY`

## Scope

Implemented Fase 7 Publish Control as a no-send MVP only.

This phase did not activate WhatsApp, smoke, canary, open production, live send,
outbox live writes, action execution, workflow events, workflow side effects, or
SendAdapter behavior.

## Implemented

- Added `AgentPublishRequest` as a tenant-scoped durable publish request entity.
- Added migration `068_product_first_publish_control.py`.
- Added publish request schemas for create, decision, and read payloads.
- Added service validation and state machine for:
  - create publish request
  - evaluate gates
  - approve no-send
  - reject
- Added Product Agent API routes for publish request create/latest/evaluate/
  approve-no-send/reject.
- Added Product Agent Builder Publish tab.
- Added no-send safety enforcement so approval can only reach
  `published_no_send`.

## Safety Invariants

- `requested_state` is limited to `published_no_send`.
- `send_scope` is limited to `none` or `test_lab_no_send`.
- No live-limited or production state can be approved by this MVP.
- Approval writes `runtime_mode=no_send` and `send_scope=none`.
- Approval forces send, outbox, live send, smoke, actions, workflow events,
  workflow side effects, canary, and open production flags to false.
- Required gates include latest passed Test Lab run, trace ids, outbox audit
  pass/count zero, side-effect audit pass/count zero, readiness without blockers,
  and rollback target.
- No Dinamo tenant logic, phone allowlist, catalog, credit rule, or vertical
  data was added to shared Product-First code.

## Tests And Verification

Commands executed:

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
- `Required test coverage of 100% reached`
- total backend coverage: `100.00%`

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

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2
rg -n "Dinamo|8128889241|send_enabled=true|live_send_enabled=true|single_contact_smoke_enabled=true|published_live_limited|production|canary|WhatsApp" core/atendia/product_agents core/atendia/api/product_agents_routes.py frontend/src/features/product-agent-builder frontend/tests/features/product-agent-builder core/tests/product_agents
```

Result:

- no tenant/contact hardcode found in shared Product-First implementation
- live/canary/production references are schema fields, blocked states, safety
  assertions, or tests confirming they are not exposed/enabled

## Files Changed In This Phase

- `core/atendia/db/models/product_agent.py`
- `core/atendia/db/models/__init__.py`
- `core/atendia/db/migrations/versions/068_product_first_publish_control.py`
- `core/atendia/product_agents/schemas.py`
- `core/atendia/product_agents/service.py`
- `core/atendia/api/product_agents_routes.py`
- `core/tests/product_agents/test_publish_control_service.py`
- `core/tests/product_agents/test_publish_control_api_routes.py`
- `frontend/src/features/product-agent-builder/api.ts`
- `frontend/src/features/product-agent-builder/components/AgentBuilderPage.tsx`
- `frontend/tests/features/product-agent-builder/AgentBuilderPage.test.tsx`
- `docs/architecture/product_first_publish_control.md`
- `docs/product/agent_publish_control_spec.md`
- `docs/architecture/feature_readiness_matrix.md`
- `specs/001-product-first-agent-platform/tasks.md`
- `reports/product_first_phase_7_publish_control_mvp_2026_06_07.md`

## Remaining Risks

- Publish Control does not yet connect published Product-First deployments to
  Runtime V2 live traffic.
- Live-limited publish requires a separate approved phase with no-send/live
  parity, rollback, allowlist/segment scope, and explicit human approval.
- Existing legacy worktree changes remain outside this phase and were not
  reverted.

## Final Decision

`PUBLISH_CONTROL_MVP_NO_SEND_READY`

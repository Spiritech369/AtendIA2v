# Product-First Phase 5 - Tool/Action Bindings Productized

Date: 2026-06-07

## Decision

`TOOL_ACTION_BINDINGS_PRODUCTIZED_READY`

## Scope Implemented

Implemented a no-live Product-First control-plane slice for Tool and Action
Bindings.

Backend:

- Added canonical product capability registry.
- Added fact-only tool capability options:
  - `catalog.search`
  - `quote.resolve`
  - `requirements.lookup`
  - `document.check`
- Added side-effect action capability options:
  - `update_contact_field`
  - `trigger_workflow`
  - `call_webhook`
  - `send_message`
- Added tenant-scoped capability option endpoints.
- Added draft-scoped Agent Tool Binding list/create/delete endpoints.
- Added draft-scoped Agent Action Binding list/create/delete endpoints.
- Added service validation that blocks live action modes and keeps
  `send_message` as a disabled SendAdapter boundary.

Frontend:

- Added Tools tab to Agent Builder.
- Added Actions tab to Agent Builder.
- Added Product-First API methods for tool/action options and bindings.
- Displayed side-effect type, risk, execution mode, auth, permissions, and
  publish blockers.

Docs:

- Updated Agent Builder contract.
- Updated Action Registry contract.
- Updated Agent Builder product spec.
- Updated Feature Readiness Matrix.
- Updated spec-kit tasks.

## No-Live Confirmation

This phase did not:

- change Runtime V2 behavior
- touch Baileys or WhatsApp
- change SendAdapter
- write outbox
- execute actions
- trigger workflows
- enable smoke
- enable canary
- enable production traffic
- remove legacy
- introduce Dinamo hardcode into shared runtime

## Verification

Backend:

- `uv run ruff check atendia/product_agents atendia/api/product_agents_routes.py tests/product_agents`
  - Result: passed.
- `uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100`
  - Result: 85 passed.
  - Coverage: 100%.

Frontend:

- `npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder`
  - Result: passed.
- `npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include="src/features/product-agent-builder/**/*.{ts,tsx}" --coverage.reporter=text --coverage.thresholds.lines=100 --coverage.thresholds.functions=100 --coverage.thresholds.branches=100 --coverage.thresholds.statements=100`
  - Result: 14 passed.
  - Coverage: 100% statements, branches, functions, and lines.
- `npm.cmd run build`
  - Result: passed.

## Remaining Risks

- Tool/action bindings are productized but not connected to runtime execution.
- Live action execution still requires Test Lab, Publish Control, approval,
  rollback, and SendAdapter boundary work.
- Workflow bindings remain separate from actions and must keep customer-visible
  copy blocked.

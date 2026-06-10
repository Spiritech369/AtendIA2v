# Product-First Phase 3 Agent Builder MVP

Date: 2026-06-07

## Scope

Implemented the first no-live Product-First Agent Builder MVP on top of Phase 2
Product Entities.

## Implemented

- Backend Builder endpoints under `/api/v1/product-agents`.
- Frontend `/agent-builder` route.
- Product-First agent list/create flow.
- Draft version creation.
- Draft identity, instructions, and prompt block editing.
- Readiness checks for identity, knowledge, tools, actions, field policy,
  workflow bindings, and deployment safety.
- Safety snapshot with send/outbox/live/actions/workflow/canary/production off.

## Not Touched

- Runtime V2 behavior.
- Baileys.
- WhatsApp send.
- SendAdapter.
- Outbox.
- Workflow side effects.
- Actions side effects.
- Smoke/canary/production.
- Tenant-specific Dinamo logic.
- Legacy deletion.

## Verification

- `uv run pytest tests/product_agents -q`
  - Result: `56 passed`.
- `uv run ruff check atendia/product_agents atendia/api/product_agents_routes.py tests/product_agents`
  - Result: `All checks passed!`.
- `uv run python -m coverage run -m pytest tests/product_agents -q; uv run python -m coverage report --include="atendia/product_agents/*,atendia/api/product_agents_routes.py" --show-missing --fail-under=100`
  - Result: `56 passed`, `TOTAL 572 0 100%`.
- `npm.cmd run test -- AgentBuilderPage.test.tsx --run`
  - Result: `7 passed`.
- `npm.cmd exec -- vitest run AgentBuilderPage.test.tsx --coverage --coverage.include="src/features/product-agent-builder/**/*.{ts,tsx}" --coverage.thresholds.lines=100 --coverage.thresholds.functions=100 --coverage.thresholds.branches=100 --coverage.thresholds.statements=100`
  - Result: `Statements 100%`, `Branches 100%`, `Functions 100%`, `Lines 100%`.
- `npm.cmd exec -- biome check src/features/product-agent-builder/api.ts src/features/product-agent-builder/components/AgentBuilderPage.tsx 'src/routes/(auth)/agent-builder.tsx' src/features/navigation/menu-config.ts tests/features/product-agent-builder/AgentBuilderPage.test.tsx`
  - Result: `Checked 5 files`, no fixes required.
- `npm.cmd run build`
  - Result: `tsc --noEmit && vite build` passed.
- `rg -n "Dinamo|dinamo|motos|8128889241|send_enabled\s*[:=]\s*true|outbox_enabled\s*[:=]\s*true|live_send_enabled\s*[:=]\s*true|workflow_side_effects_enabled\s*[:=]\s*true|open_production_enabled\s*[:=]\s*true" core/atendia/product_agents core/atendia/api/product_agents_routes.py frontend/src/features/product-agent-builder 'frontend/src/routes/(auth)/agent-builder.tsx'`
  - Result: no matches.
- `git diff --check -- frontend/src/features/navigation/menu-config.ts frontend/src/routeTree.gen.ts`
  - Result: no whitespace errors; Git reported existing CRLF normalization warnings only.
- Diff/code review performed against changed Builder API/service/schemas,
  frontend Builder surface, route tree, docs, and tests.

## Decision

`AGENT_BUILDER_MVP_READY`

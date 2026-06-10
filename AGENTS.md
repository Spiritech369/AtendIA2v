# AGENTS.md

## Purpose

AtendIA is a multi-tenant conversational automation platform. Every Codex
change must keep the system tenant-safe, product-first, traceable, tested,
reversible, and suitable for more than one business domain.

## Document Authority

- `Arquitectura-Deseada.md` is the canonical source for the Product-First
  transformation of AtendIA.
- `ARCHITECTURE.md` is the stable high-level system summary.
- `AGENTS.md` is the operational rulebook for Codex work.
- `docs/architecture/` contains current architecture contracts and decisions.
- `reports/` contains historical evidence, audits, simulations, and incidents.
- If reports conflict with `Arquitectura-Deseada.md`, `Arquitectura-Deseada.md`
  wins for future implementation.

## Non-Negotiable Runtime Rules

- Do not hardcode a vertical, tenant, Dinamo, motos, credit rules, catalog data,
  document requirements, prompts, prices, plans, or business policy inside
  shared runtime code.
- Tenant-specific behavior belongs in tenant configuration, tenant domain
  contracts, Knowledge OS sources, published tenant data, or current specs under
  `docs/architecture/`.
- `TurnOutput.final_message` is the only authority for customer-facing response
  text. No tool, action, workflow, fallback, recovery path, adapter, legacy path,
  debug path, or smoke helper may invent or overwrite visible copy.
- Tools and actions return structured data only. They must not return final
  visible response text.
- DB-backed no-send and live-candidate must use the same runtime path. Only the
  SendAdapter behavior may differ.
- If a required tool is missing, skipped, failed, or blocked, the turn must fail
  closed for visible sending.
- If policy validation fails, the turn must fail closed for visible sending.
- Internal text, `/goal`, prompts, trace text, debug text, errors, and recovery
  text must never reach a customer.
- Runtime V2 published agents must not be touched by legacy paths except where a
  documented migration adapter explicitly allows read-only compatibility.

## Product-First Planning Rules

For architecture, runtime, DB, live traffic, outbox, workflow, smoke/canary,
tenant config, destructive filesystem/git, broad behavioral changes, or Product-
First implementation:

1. Inspect the current repo state first.
2. Reference `Arquitectura-Deseada.md` and the active spec under `specs/`.
3. Confirm the relevant Definition of Ready.
4. Provide a concise plan with files, risks, invariants, tests, rollback, and
   verification.
5. Wait for explicit user approval before modifying files or state.

Small read-only diagnostics may run without a plan. Implementation starts only
after approval.

## Testing And Review Requirements

- Every new or modified behavior must include unit tests or integration tests as
  appropriate.
- Coverage is mandatory for 100% of the new or modified behavior. Global legacy
  coverage does not block this documentation phase, but any legacy gap that
  prevents verifying a feature must be documented as a blocker.
- Codex must run the relevant tests and report exact commands and results.
- Before commit or implementation handoff, Codex must review the diff against
  the base branch or uncommitted changes to catch bugs, regressions,
  architecture violations, missing tests, and unsafe side effects.
- If tests, coverage, or review cannot be completed, the delivery is incomplete
  unless the blocker is explicitly documented and accepted.

## Implementation Rules

When implementation is approved:

- Make the smallest change that satisfies the approved scope.
- Keep behavior generic and tenant-aware.
- Prefer tenant-scoped data and documented contracts over global assumptions.
- Add or update focused tests for every behavioral change.
- Update detailed specs under `docs/architecture/` after major runtime, tool,
  state, tracing, frontend, rollout, or testing changes.
- Do not alter live, smoke, canary, outbox, workflow side effects, actions,
  production traffic, or WhatsApp send unless that exact activation is explicitly
  approved.
- Do not use fixtures, mocks, or a different path as proof of live readiness.

## Restricted Commands

Do not run destructive filesystem or git commands without explicit approval.

Restricted examples include:

- `rm`, `rm -rf`
- `git reset`, `git reset --hard`
- `git clean`
- `git checkout --`
- `git restore`
- `git rebase`
- `git push`
- Force flags or any command that deletes, overwrites, rewrites history, moves
  data in bulk, or destroys incident evidence

If one is necessary, explain why, show the exact command, and wait for approval.

## Reference Docs

- `Arquitectura-Deseada.md`: canonical Product-First target architecture.
- `ARCHITECTURE.md`: stable system overview; should change rarely.
- `.specify/memory/constitution.md`: spec-kit constitution and governance.
- `specs/001-product-first-agent-platform/`: active Product-First spec-kit plan.
- `docs/architecture/decisions/product_first_adrs.md`: architectural decisions.
- `docs/architecture/product_first_definition_of_ready.md`: start gate.
- `docs/architecture/product_first_definition_of_done.md`: completion gate.
- `docs/architecture/`: current technical contracts.
- `docs/runbooks/`: operational runbooks.
- `reports/`: historical evidence, audits, simulations, and incidents.

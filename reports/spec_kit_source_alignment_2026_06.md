# Spec-Kit Source Alignment - Product-First AtendIA

Date: 2026-06-06  
Decision: `SPEC_KIT_PRODUCT_FIRST_PLAN_READY` when all companion files exist and verification passes.

## Sources Reviewed

| Source | Role | Main Signals |
|---|---|---|
| `Investigacion2026.docx` | Research authority | Product-First direction, respond.io/Intercom/HubSpot patterns, control plane + single runtime, DB-backed Test Lab, publish control, Action Registry, trace/evals |
| `JunioAuditoria2026.md` | Repo audit evidence | 25-feature readiness reality, connected/partial/blocked status, robotic composer risk, legacy/runtime coexistence |
| `Arquitectura-Deseada.md` | Canonical target | Product-First architecture, control plane, runtime plane, non-negotiable invariants, migration phases |
| `AGENTS.md` | Codex operational rules | No tenant hardcoding, plan before risky work, tests and code review, no live without approval |
| `ARCHITECTURE.md` | Stable summary | High-level product surfaces, runtime authorities, tenant isolation, live safety |

## Agreements

- AtendIA must become Product-First, not smoke-first or patch-first.
- ChatGPT should interpret and converse; AtendIA should govern data, state,
  tools, actions, safety, publication, and send.
- One AgentService should own the visible response path for Product-First
  agents.
- `TurnOutput.final_message` must be the only visible response authority.
- No-send and live-candidate must share the same DB-backed route.
- Required tool failures and policy failures must fail closed.
- Knowledge Sources, Actions, Workflows, Test Lab, Publish Control, and Trace
  are product surfaces, not ad hoc runtime helpers.
- Legacy must be classified before removal.

## Contradictions Resolved

| Conflict | Resolution |
|---|---|
| Reports contain incident-specific guidance that may be stale | `reports/` is historical evidence; `Arquitectura-Deseada.md` wins for future architecture |
| Runtime-first fixes vs Product-First platform | Product-First wins; runtime patches require approved phase and specs |
| Smoke/manual recovery as readiness | Smoke is not architecture; DB-backed Test Lab + Publish Control is required |
| Legacy fallback as safety | Legacy cannot touch published Runtime V2 visible output unless explicitly classified and approved |
| Fixtures as proof of live readiness | Fixtures support unit tests only; live readiness requires DB-backed tenant path |
| 100% global legacy coverage vs practical delivery | 100% coverage applies to new/modified behavior; legacy gaps that block verification are documented blockers |

## Source Of Truth Order

1. `Arquitectura-Deseada.md` for Product-First transformation.
2. `.specify/memory/constitution.md` for spec-kit governance.
3. `docs/architecture/decisions/product_first_adrs.md` for active decisions.
4. `ARCHITECTURE.md` for stable overview.
5. `AGENTS.md` for Codex operational rules.
6. `docs/architecture/` for current contracts.
7. `reports/` for historical evidence and incidents.

## Gaps Added To `Arquitectura-Deseada.md`

- Explicit canonical status.
- Clear authority split between `Arquitectura-Deseada.md`, `ARCHITECTURE.md`,
  `AGENTS.md`, `docs/architecture/`, and `reports/`.
- Definition of Ready.
- Definition of Done.
- Feature readiness registry.
- Legacy classification language.
- Explicit prohibition on workflow/fallback/adapter visible copy overrides.
- Testing and coverage rules for future implementation.

## README Status

`README.md` appears deleted in the current worktree. This phase did not restore
or recreate it to avoid reverting unrelated user changes. If README alignment is
required later, restore or recreate it only with explicit approval.

## What Was Not Done

- No runtime code changed.
- No DB/migrations changed.
- No Docker used.
- No WhatsApp/live/send/outbox/workflow/action/canary/smoke touched.
- No legacy deleted.
- No production state changed.

## Follow-Up

Future implementation must begin with Definition of Ready, reference
`Arquitectura-Deseada.md`, use the active spec-kit tasks, and update Feature
Readiness after tests and review.

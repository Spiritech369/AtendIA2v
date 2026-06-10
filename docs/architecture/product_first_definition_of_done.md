# Product-First Definition of Done

Date: 2026-06-06  
Status: Active

A Product-First feature is done only when every applicable item below is true.

## Required Completion Gates

- **Spec satisfied**: Requirements in the active spec are implemented.
- **Architecture aligned**: The implementation follows `Arquitectura-Deseada.md`.
- **UI/API/DB/runtime connected**: Applicable product surfaces are wired end to
  end, or explicitly marked out of scope.
- **Tests passed**: Unit/integration tests for new or modified behavior pass.
- **Changed-behavior coverage**: 100% coverage is reported for new or modified
  behavior.
- **Legacy gaps documented**: Global legacy coverage does not block by itself,
  but any legacy gap that prevents verification is documented as a blocker.
- **Trace visible**: Universal trace or equivalent audit evidence exists for
  runtime behavior.
- **Policy passed**: Policy gates and fail-closed behavior are verified.
- **No fixtures-only readiness**: Live readiness is not claimed from fixtures or
  alternate harnesses.
- **No legacy interference**: Legacy cannot override or replace Product-First
  visible output.
- **Rollback documented**: Rollback procedure is documented and tested where
  practical.
- **Codex code review complete**: Diff review against base branch or
  uncommitted changes is complete before commit/handoff.
- **Feature readiness updated**: `feature_readiness_matrix.md` reflects the new
  state and evidence.
- **Test Lab evidence recorded**: Features that affect runtime, publish, send,
  sources, tools, actions, workflows, state, or policy have DB-backed Test Lab
  evidence or are explicitly marked not applicable.
- **Publish Control evidence recorded**: Features that affect deployment or live
  scope have publish readiness, approval, and rollback evidence.

## Not Done If

- A required tool failure can still send visible output.
- Policy failure can still send visible output.
- Internal/debug text can reach customers.
- Workflow, recovery, adapter, or legacy paths can overwrite
  `TurnOutput.final_message`.
- Outbox writes can happen before send policy allows them.
- Live behavior differs from no-send except for SendAdapter.
- A feature claims publish readiness without the required Test Lab and Publish
  Control evidence.

## Delivery Evidence

Every implementation delivery must include:

- files changed
- commands run
- tests and results
- coverage evidence for changed behavior
- code review status
- trace/log/DB checks where relevant
- known gaps and blockers
- final readiness decision

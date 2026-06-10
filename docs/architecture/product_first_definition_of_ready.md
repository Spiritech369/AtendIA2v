# Product-First Definition of Ready

Date: 2026-06-06  
Status: Active

A Product-First phase or feature can start only when every required item below
is true.

## Required Gates

- **Approved phase**: The user has explicitly approved the phase or task.
- **Spec exists**: The relevant spec exists under `specs/` or
  `docs/architecture/`.
- **Canonical alignment**: The task references `Arquitectura-Deseada.md`.
- **Risks known**: Known risks and open blockers are documented.
- **Tests planned**: Unit/integration tests are planned for new or modified
  behavior.
- **Coverage target defined**: 100% coverage is required for new or modified
  behavior.
- **Rollback defined**: Rollback is documented for code, config, data, and live
  effects as applicable.
- **Legacy impact classified**: Any affected legacy component has a
  classification in `legacy_deprecation_plan.md`.
- **Live boundary clear**: The task confirms it does not touch live unless
  explicit live approval is present.
- **No hidden side effects**: DB, outbox, WhatsApp, workflow side effects,
  actions, canary, and smoke are either out of scope or explicitly approved.
- **Test Lab impact known**: The feature states whether it adds, changes, or
  depends on DB-backed Test Lab suites or assertions.
- **Publish Control impact known**: The feature states whether it affects
  publish state, approval, send scope, rollback, or readiness gates.

## Not Ready If

- The task depends only on fixtures to prove live readiness.
- The runtime path is ambiguous.
- The expected visible output authority is unclear.
- Required tools, policy, SendAdapter, or trace behavior is not specified.
- Rollback is missing.
- Tests or coverage cannot be planned because legacy behavior is unknown.
- The feature would affect publish/live behavior but does not identify the
  required Test Lab and Publish Control gates.

## Output

When Ready passes, the implementer records:

- phase/task id
- approving user message
- files/components affected
- tests planned
- coverage target
- rollback
- legacy classification
- live/offline scope

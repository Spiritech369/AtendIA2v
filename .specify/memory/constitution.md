<!--
Sync Impact Report
Version change: none -> 1.0.0
Modified principles: initial Product-First constitution
Added sections: Document Authority, Core Principles, Quality Gates, Governance
Templates requiring updates: .specify/templates/* created for this repo
Deferred items: none
-->

# AtendIA Product-First Constitution

## Document Authority

`Arquitectura-Deseada.md` is the canonical source for the Product-First
transformation of AtendIA. `ARCHITECTURE.md` is the stable summary.
`AGENTS.md` is the operational rulebook for Codex. `docs/architecture/`
contains current contracts and decisions. `reports/` contains historical
evidence and incidents, not canonical architecture. If reports conflict with
`Arquitectura-Deseada.md`, `Arquitectura-Deseada.md` wins.

## Core Principles

### I. Product-First Control Plane

Agent configuration MUST be modeled as product entities: Agent, Agent Version,
Agent Deployment, Prompt Blocks, Knowledge Sources, Source Bindings, Action
Bindings, Field Policies, Workflow Bindings, Test Suites, Publish State, and
Rollback Version. Shared runtime code MUST NOT carry tenant-specific business
rules.

### II. Single Runtime Authority

One AgentService MUST own visible response, state, tool execution, action
requests, handoff, policy, and send decision for Product-First agents. Legacy
paths may remain only as classified migration support and MUST NOT override
published Runtime V2 visible output.

### III. Final Message Authority

`TurnOutput.final_message` is the only customer-facing text authority. Tools,
actions, workflows, fallbacks, recovery paths, adapters, debug paths, and legacy
paths MUST NOT invent or overwrite customer-visible copy.

### IV. Fail-Closed Safety

Required tool missing, skipped, failed, or blocked means no-send. Policy failure
means no-send. Internal text, `/goal`, prompts, traces, debug, recoveries, and
errors MUST never reach customers.

### V. DB-Backed Test Lab Before Live

No-send and live-candidate MUST use the same DB-backed runtime route; only
SendAdapter may differ. Test Lab MUST use real tenant configuration, source
bindings, tools, StateWriter, Policy, and TurnOutput. Fixtures may support unit
tests but do not prove live readiness.

### VI. Evidence-Based State And Actions

StateWriter writes only validated, evidenced state. Tools return structured
facts. Actions are permissioned, auditable, idempotent where needed, and gated
by dry-run/live/approval policy.

### VII. Automated Testing Coverage

Every new or modified behavior MUST have unit tests or integration tests as
appropriate. Coverage is mandatory for 100% of new or modified behavior. Global
legacy coverage does not block this documentation phase, but any legacy gap
that prevents verifying a feature MUST be documented as a blocker.

### VIII. Codex Code Review Before Commit

Before commit or implementation handoff, Codex MUST review the diff against the
base branch or uncommitted changes to catch bugs, regressions, architecture
violations, missing tests, and unsafe side effects.

### IX. Traceability And Rollback

Every behavior that can affect a customer, state, workflow, action, or send
decision MUST be traceable and have a documented rollback path before publish.

## Quality Gates

- Definition of Ready MUST pass before implementation starts.
- Definition of Done MUST pass before a feature is called complete.
- Feature Readiness MUST be updated when implementation evidence changes.
- Code changes MUST report tests, coverage of changed behavior, verification
  commands, and code review status.
- Live, smoke, canary, outbox, workflow side effects, and WhatsApp send require
  explicit approval.

## Governance

This constitution supersedes local habits and temporary incident reports for
Product-First work. Amendments require updating this file, `AGENTS.md`,
`Arquitectura-Deseada.md`, and affected specs or decisions. Versioning follows
semantic versioning:

- MAJOR for principle removals or incompatible governance changes.
- MINOR for new principles or materially expanded gates.
- PATCH for clarifications.

**Version**: 1.0.0 | **Ratified**: 2026-06-06 | **Last Amended**: 2026-06-06

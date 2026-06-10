# Product-First ADRs

Date: 2026-06-06  
Status: Active  
Canonical source: `Arquitectura-Deseada.md`

## ADR-001 - `Arquitectura-Deseada.md` Is Canonical

**Decision**: `Arquitectura-Deseada.md` is the canonical source for the
Product-First transformation of AtendIA.

**Rationale**: The repo has historical audits, incident reports, and runtime
specs that may conflict. A single canonical document prevents future work from
following temporary incident context as architecture.

**Consequences**: Future implementation must reference `Arquitectura-Deseada.md`
and the active spec-kit phase before changing runtime, DB, workflows, send, or
product surfaces.

## ADR-002 - `ARCHITECTURE.md` Is Stable Summary

**Decision**: `ARCHITECTURE.md` remains a short stable overview.

**Rationale**: It should orient readers without becoming a volatile roadmap.

**Consequences**: Detailed Product-First work belongs in `Arquitectura-Deseada.md`,
`specs/`, and `docs/architecture/`.

## ADR-003 - `AGENTS.md` Is Codex Operational Rulebook

**Decision**: `AGENTS.md` governs how Codex works in this repo.

**Rationale**: Codex needs concise operational rules: no hardcoding tenants,
plan before risky changes, test changed behavior, review diffs, and avoid
destructive/live actions without approval.

**Consequences**: If implementation conflicts with `AGENTS.md`, stop and update
the plan or ask for approval.

## ADR-004 - Reports Are Historical Evidence

**Decision**: `reports/` is evidence, not canonical architecture.

**Rationale**: Reports capture incidents, audits, simulations, and temporary
findings. They are essential evidence but can become stale.

**Consequences**: If reports conflict with `Arquitectura-Deseada.md`, the
canonical architecture wins. If a report reveals a new risk, update current docs
or ADRs.

## ADR-005 - Single Runtime Via AgentService

**Decision**: Product-First agents must execute through one DB-backed
AgentService route.

**Rationale**: Different no-send/live paths and legacy visible paths caused
unreliable smoke results and robotic/repeated output.

**Consequences**: Legacy must be classified and blocked from published Runtime
V2 visible output before production rollout.

## ADR-006 - `TurnOutput.final_message` Is The Only Visible Output

**Decision**: Only `TurnOutput.final_message` can be customer-visible text.

**Rationale**: Tools, workflows, recoveries, adapters, and fallbacks must not
invent or overwrite visible copy.

**Consequences**: Any path that produces visible text outside this authority is
BLOCK_FOR_V2 until merged or removed.

## ADR-007 - DB-Backed Test Lab Before Publish Or Live

**Decision**: Publish/live requires DB-backed Test Lab.

**Rationale**: Fixtures and alternate harnesses can hide missing tenant sources,
tool failures, state drift, and send policy issues.

**Consequences**: Test Lab must run the same route as live, with SendAdapter in
no-send mode and side effects disabled.

## ADR-008 - Legacy Is Classified Before Removal

**Decision**: Legacy is not deleted in this phase. It is classified as KEEP,
MERGE, DEGRADE, BLOCK_FOR_V2, DELETE_LATER, or UNKNOWN_NEEDS_AUDIT.

**Rationale**: Deleting legacy without impact analysis risks breaking current
operations and destroying incident evidence.

**Consequences**: Every legacy removal requires tests, rollback, and explicit
approval in a later implementation phase.

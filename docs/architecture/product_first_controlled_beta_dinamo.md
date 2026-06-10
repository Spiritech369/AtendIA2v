# Product-First Controlled Beta With Dinamo

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Dinamo may be used as a controlled beta tenant only after Product-First gates
pass. Dinamo is not the architecture. Dinamo is one tenant exercising the
Product-First platform through tenant-scoped configuration, Knowledge Sources,
tools, actions, workflows, Test Lab, Publish Control, trace, policy, and
rollback.

This document defines the target beta contract. It is documentation-only for
this phase. It does not change runtime, DB, Docker, WhatsApp, outbox, actions,
workflows, smoke, or live flags.

## Product Principle

Dinamo-specific behavior must live in tenant data:

- agent configuration
- prompt blocks
- Knowledge Sources
- Source Bindings
- domain contracts
- catalog source
- requirements source
- FAQ/policy source
- tools configured against those sources
- field policies
- Action Bindings
- Workflow Bindings
- Test Suites
- Publish Control records

Dinamo-specific behavior must not live in shared runtime code.

## Beta Prerequisites

Controlled beta cannot start until:

- Product-First architecture contracts are complete.
- Definition of Ready passes for the beta phase.
- required Knowledge Sources are healthy and bound.
- required tools are tenant-aware and source-backed.
- Action Bindings are dry-run or explicitly approved for limited live use.
- Workflow Bindings are dry-run/event-preview unless explicitly approved.
- DB-backed Test Lab passes.
- no-send/live-candidate parity passes where send is in scope.
- Publish Control marks the deployment ready for approval.
- rollback version and rollback procedure exist.
- explicit human approval names tenant, deployment, channel, send scope,
  enabled capabilities, disabled capabilities, and rollback condition.

## Allowed Beta Scope

Allowed target scopes:

- no-send beta
- approved-contact-only live-limited beta
- approved-segment-only live-limited beta

Blocked in this contract:

- open production
- canary without Publish Control
- live actions without explicit approval
- workflow side effects without explicit approval
- contacts outside approved scope
- tenant behavior hardcoded into runtime
- smoke as architecture or publish proof

## Tenant Data Boundary

Dinamo credit, motos, catalog, requirements, documents, pricing, buro handling,
income plans, and dealership-specific language are tenant data.

Shared runtime may know product concepts such as:

- pending slot
- source binding
- required tool
- field policy
- publish state
- send scope
- trace
- policy

Shared runtime must not know Dinamo-specific meanings such as a plan percentage,
model list, document count, price, business phrase, or vertical-specific
decision rule unless it arrives through tenant-scoped data or a tenant-aware
tool result.

## Beta Evidence Packet

Before any Dinamo live-limited beta approval, evidence must include:

- active tenant id
- active agent id
- active agent version id
- deployment id
- send scope
- allowlist or approved segment
- Knowledge Source health snapshot
- required Test Lab run ids
- no-send/live-candidate parity result
- trace ids for reviewed scenarios
- exact final messages reviewed
- outbox audit result
- business side-effect audit result
- action/workflow mode summary
- rollback version id
- rollback procedure
- explicit approval text

## Required Dinamo Test Scenarios

Dinamo beta scenarios must be stored as Test Lab scenarios, not as ad hoc smoke
instructions:

- credit quote with model and buro mention
- income pending slot answer
- antiguedad answer
- requirements lookup
- future document promise
- question mark resumes real pending context
- model change
- "trabajo" ambiguity cases
- document attachment classification
- handoff request
- policy-blocked unsupported claim

Each scenario must assert interpretation, tools, StateWriter decisions, Policy,
final message, trace, and send decision.

## Publish Blockers

Publish Control must block Dinamo beta when:

- any Dinamo behavior is implemented in shared runtime code
- required tenant source is missing, stale, or unhealthy
- quote/requirements facts are not tool-backed
- Test Lab evidence is fixture-only
- no-send/live-candidate parity fails
- trace cannot explain the final message
- legacy visible output can run
- send scope is wider than approval
- actions/workflows have live side effects without approval
- rollback is missing

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- Dinamo-specific model/plan/catalog facts come from tenant sources or tools
- shared runtime contains no Dinamo hardcoded decision rules
- beta publish is blocked without DB-backed Test Lab
- beta publish is blocked without exact approved send scope
- quote claims require quote tool result
- requirements claims require requirements source/tool result
- document completeness requires document/expediente tool result
- no-send/live-candidate parity holds for approved scenarios
- trace explains every final message reviewed for beta
- rollback disables send scope before investigation

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 12 Acceptance

Fase 12 is complete for this documentation phase when:

- Dinamo is documented as a controlled beta tenant only
- Dinamo-specific behavior is explicitly tenant data, not runtime code
- beta prerequisites are documented
- beta evidence packet is documented
- required scenarios are documented
- publish blockers are documented
- future tests are documented
- no live/runtime/DB behavior was changed

Decision for this documentary phase:

`PRODUCT_FIRST_PHASE_12_CONTROLLED_BETA_DINAMO_DEFINED_DOCS_ONLY`

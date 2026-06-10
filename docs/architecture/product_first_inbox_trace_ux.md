# Product-First Inbox Trace UX

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Inbox Trace UX is the operator-facing explanation layer for Product-First agent
turns. It must make every customer-visible response auditable without exposing
internal prompts, debug text, provider failures, or recovery copy to customers.

This document defines the target trace panels, required evidence, redaction,
blocker display, and publish/Test Lab dependencies. It is documentation-only
for this phase. It does not change runtime, DB, Docker, WhatsApp, outbox,
actions, workflows, smoke, or live flags.

## Product Principle

Every visible customer response must answer:

- what did the customer say?
- which agent version handled it?
- what did ChatGPT understand?
- what sources/tools/actions/workflows were considered?
- what state was written or blocked?
- what did Policy allow or block?
- why was this exact `TurnOutput.final_message` selected?
- why was send allowed or blocked?

Trace is internal operator evidence. Trace text must never become customer copy.

## Trace UX Surfaces

Minimum target surfaces:

- Inbox message detail panel
- "Why this answer?" drawer
- Test Lab turn trace
- Publish Control readiness trace review
- Incident replay trace
- Rollback review trace

The same trace record should support all surfaces; UX may summarize but must not
invent evidence that is absent from the trace.

## Required Panels

### Turn Header

- tenant
- conversation
- contact
- channel
- inbound message id
- trace id
- agent id
- agent version id
- deployment id
- runtime mode
- send mode
- timestamp

### Context Panel

- last messages used
- last bot question
- pending slot
- contact snapshot
- conversation snapshot
- selected Knowledge Source bindings
- allowed tools/actions/workflows

### Semantic Understanding Panel

- intent
- semantic summary
- missing field
- confidence
- ambiguity status
- proposed fields
- required tools
- final message draft before validation

This panel shows model interpretation as evidence, not as final truth. AtendIA
validation remains authoritative for hard facts and state writes.

### Knowledge And Tool Panel

- source bindings considered
- retrieval queries
- citations or structured records
- tool calls requested
- tool inputs
- tool results
- tool failures or blockers
- claim basis

Unsupported factual claims must be visible as blocked claims.

### StateWriter And Lifecycle Panel

- proposed writes
- accepted writes
- blocked writes
- evidence
- confidence
- field policy used
- lifecycle transition proposed
- lifecycle transition accepted or blocked

### Actions And Workflows Panel

- action candidates
- action binding decision
- dry-run/live mode
- action result or blocked reason
- workflow event candidates
- workflow binding decision
- side-effect decision
- idempotency key

Actions and workflows must be shown as structured operational evidence, not as
customer copy.

### Policy And Send Panel

- policy checks
- policy issues
- send decision
- SendAdapter mode
- outbox decision
- no-send reason
- side-effect counts
- rollback hint

Policy failure must explain no-send without creating visible recovery text.

### Final Message Panel

- exact `TurnOutput.final_message`
- source/tool basis summary
- message status
- customer-visible send status
- if blocked, blocked reason instead of fake customer copy

## Redaction And Access

Trace UX must redact:

- secrets
- credentials
- private integration payloads
- raw provider debug data not needed for operators
- PII outside the operator's tenant permission
- internal prompts where policy says they are not operator-visible

Trace access is tenant-scoped and role-gated.

## Publish And Test Lab Dependency

Publish Control must block if required trace panels cannot be produced for
Test Lab or live-candidate runs.

Test Lab must preserve exact final messages and trace ids so humans can review
the customer-visible text before live approval.

## Runtime Rules

At runtime:

- trace is written as structured evidence
- trace is not customer copy
- missing trace for required decisions means publish/readiness failure
- trace summaries must distinguish model proposal from AtendIA validation
- trace must show whether legacy, fallback, workflow, or provider recovery tried
  to affect visible output

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- trace contains final message or blocked reason
- trace contains semantic interpretation and validation result
- trace contains tool inputs/results and source basis
- trace contains accepted and blocked StateWriter decisions
- trace contains Policy and SendAdapter decisions
- trace contains action/workflow candidates and side-effect decisions
- trace redacts secrets and cross-tenant data
- trace cannot become customer-visible copy
- missing required trace fields block publish
- Test Lab exact final message is reviewable from trace

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 10 Acceptance

Fase 10 is complete when:

- trace UX surfaces are documented
- required panels are documented
- redaction and access rules are documented
- Test Lab and Publish Control dependencies are documented
- runtime and future test rules are documented
- no live/runtime/DB behavior was changed

Decision for this documentary phase:

`PRODUCT_FIRST_PHASE_10_INBOX_TRACE_UX_DEFINED_DOCS_ONLY`

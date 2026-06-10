# Agent Publish Control Product Spec

Date: 2026-06-07  
Status: Product specification; no-send MVP implemented  
Canonical source: `Arquitectura-Deseada.md`

## Objective

Replace scattered live flags and manual smoke decisions with a product state
machine for publishing, pausing, approving, and rolling back agent deployments.

## States

- `draft`
- `configured`
- `test_lab_required`
- `test_lab_running`
- `test_lab_failed`
- `ready_for_approval`
- `published_no_send`
- `published_live_limited`
- `paused`
- `rollback_required`
- `rolled_back`
- `deprecated`

The implemented MVP can approve only `published_no_send`.

## Publish Blockers

Publish Control blocks when:

- source missing
- source unhealthy
- tool missing
- auth missing
- permission missing
- policy missing
- Test Lab failed
- trace disabled
- rollback target missing
- legacy visible route present
- no-send/live parity failed
- action side effect not approved
- workflow side effect not approved

## Approval Requirements

Live approval must name:

- tenant
- agent
- version
- deployment
- channel
- contact/segment scope
- enabled capabilities
- disabled capabilities
- rollback condition

The implemented MVP records no-send approval text and blocks live approval
paths. Live approval remains future work.

## Rollback

Rollback must:

- pause send scope first
- restore approved previous version
- record trace/log review
- audit outbox and side effects
- preserve evidence for incident review

## Acceptance

Publish Control is the only path from tested version to future live-limited
send. Current implementation is no-send only:

- publish request create/latest/evaluate/approve-no-send/reject APIs exist
- Test Lab pass, trace ids, outbox audit, side-effect audit, readiness, and
  rollback target are evaluated before approval
- `published_no_send` keeps send, live send, outbox, actions, workflows,
  canary, and production flags disabled
- no WhatsApp, smoke, SendAdapter, workflow side effect, or outbox live write is
  activated

# Product Builder Capability Matrix

Date: 2026-06-09  
Status: Active planning contract; docs-only  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Product-First is not only runtime. The product builder must let a tenant
configure, test, publish, roll back, and audit the whole agent without adding
business rules to shared runtime code.

## Capability Matrix

| Capability | Builder must configure | Runtime must consume | Publish/Test gate |
|---|---|---|---|
| Prompt | instructions, role, tone, language, prompt blocks | immutable published prompt package | prompt version is published and traceable |
| KB | sources, bindings, retrieval scope, health | tenant-scoped source facts | missing/unhealthy source blocks publish |
| Tools | allowed tools, schemas, required tools | execute permitted tools only | required tool failure means no-send |
| Actions | action bindings, auth, schema, risk, mode | dry-run/live according to approval | unauthorized/live-risk action blocks publish |
| Fields | writable fields, evidence rules, confidence | validate field write proposals | unsupported write blocked and traced |
| Workflows | trigger bindings, schema, mode, side effects | emit normalized events only | workflow cannot write customer copy |
| Handoff | reasons, teams, queues, SLA, copy policy | propose or create handoff according to mode | handoff reason and target required |
| Pipeline | stages, transitions, evidence | validate lifecycle proposals | invalid transition blocked |
| Publish | state, send scope, approvals, readiness | deployment resolver uses published state | no scattered flag can publish |
| Rollback | target version, owner, trigger, command/action | pause/send-scope rollback first | rollback metadata required before live |
| Test suites | scenarios, assertions, replay sets | same route as live, no-send adapter | latest required suite must pass |
| Trace | required trace fields, redaction, review | record turn decisions and blockers | trace completeness required |

## Builder Completeness Gate

A Product Agent cannot be considered live-ready unless Builder can show:

- active published agent version
- deployment state and send scope
- prompt/instructions snapshot
- KB/source binding health
- tool bindings and required tool status
- action bindings and approval mode
- field policy coverage
- workflow bindings and side-effect mode
- handoff policy
- pipeline/lifecycle policy
- latest Test Lab run
- latest parity/replay result
- publish blockers
- rollback target
- trace links for evaluated turns

## UI/Product Builder Non-Goals

Builder must not:

- write live runtime flags directly
- bypass Publish Control
- bypass Test Lab
- create tenant-specific shared code
- approve workflow/action side effects implicitly
- use smoke success as publish readiness
- hide missing trace, source, tool, or rollback blockers

## Required Future Tests

- tenant cannot bind another tenant source/action/workflow
- draft edits do not affect published version
- publish blocks without required Test Lab
- publish blocks without rollback metadata for live scope
- publish blocks if live route still reaches legacy visible copy
- Builder displays blockers for source/tool/action/workflow/field/trace gaps
- rollback returns deployment to a no-send or paused state before investigation


# Product-First Legacy Decommission Plan

Date: 2026-06-09  
Status: Active planning contract; docs-only  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

This plan turns legacy isolation into a real decommission sequence for
Product-First published agents.

The target is not "block bad phrases" or "make the composer better". The target
is:

```txt
Published Product Agent
-> never enters ConversationRunner
-> never uses legacy composer
-> never uses visible fallback
-> never receives workflow customer-copy
-> sends only TurnOutput.final_message through SendAdapter
```

This document does not delete code and does not activate live behavior.

## Decommission Scope

The following visible-copy risks are in scope:

- `ConversationRunner` as live entrypoint for published Product Agents
- legacy runner NLU/control/composer/response contracts
- `StructuredRuntimeComposer`
- `HumanResponseComposer` as customer-facing author for published Product
  Agents
- `ValidatedResponsePlanBuilder` as slot-first message authority
- `pending_slot` to automatic question copy
- `next_best_question` to automatic question copy
- advisor pipeline fallback copy
- provider fallback visible copy
- manual recovery visible copy
- workflow nodes or bridges that send customer text
- action/tool outputs that include final visible response text
- smoke/canary/manual flags that bypass Publish Control

## Target States

| Component | Product-First published state | Legacy tenant state | Removal gate |
|---|---|---|---|
| `ConversationRunner` | `blocked_for_product_first_entrypoint` | allowed until migrated | ProductAgentRuntime direct live entrypoint proven |
| legacy runner composer/prompts | `blocked_visible_copy` | allowed until migrated | RespondStyleAgentTurn passed Test Lab and replay |
| `StructuredRuntimeComposer` | `delete_later_after_migration` | allowed only as legacy | replacement tests cover equivalent safe behavior |
| `HumanResponseComposer` | `degraded_no_visible_copy` | allowed only as transitional/non-published | RespondStyleAgentTurn owns final_message |
| `ValidatedResponsePlanBuilder` | `structured_signal_only` | allowed only as transitional | no slot-first final copy tests pass |
| provider/manual fallback copy | `blocked_visible_copy` | trace/handoff only | policy no-send tests pass |
| workflow customer-copy | `blocked_visible_copy` | migrate to workflow bindings | workflow event consumer tests pass |
| outbox worker | `keep_delivery_only` | keep | SendAdapter-only enqueue test passes |

## Entry Decommission Gate

No Product-First agent can advance to live-limited until a test proves:

```txt
Channel Adapter
-> Inbox Event
-> Deployment Resolver
-> ProductAgentRuntime
-> AgentService
-> RespondStyleAgentTurn
-> Validator
-> SendAdapter
```

and proves it did not call:

```txt
ConversationRunner.run_turn
legacy composer
response_contract visible rewrite
workflow customer-copy
fallback visible copy
```

## Kill Map Output

The Customer Copy Kill Map must record for every source:

- file/module
- function/class
- current customer-copy authority
- Product-First classification
- allowed mode, if any
- blocker code
- replacement component
- required tests
- rollback note

Required decision marker:

`CUSTOMER_COPY_SOURCES_MAPPED`

## Decommission Phases

1. Map all visible-copy sources.
2. Add publish blockers for unknown or unsafe sources.
3. Create ProductAgentRuntime direct entrypoint in no-send.
4. Connect Test Lab to the same runtime route.
5. Prove live-candidate/no-send parity.
6. Prove multi-tenant simulations.
7. Block ConversationRunner for published Product Agents.
8. Freeze legacy visible-copy modules for non-migrated tenants only.
9. Delete legacy modules only after migration, tests, rollback, and explicit
   deletion approval.

## Tests Required Before Decommission

- Product-First deployment resolves directly to ProductAgentRuntime.
- Published Product Agent cannot call `ConversationRunner`.
- Legacy composer cannot fill `TurnOutput.final_message`.
- Provider/manual fallback cannot become visible copy.
- Workflow cannot send customer text outside SendAdapter.
- Tools/actions return structured data only.
- Outbox enqueue occurs only after SendAdapter approval.
- Non-migrated legacy tenant behavior remains covered or explicitly accepted.

## Rollback

Rollback is not "fall back to visible legacy" for Product-First published
agents. Rollback means:

- pause deployment send scope
- restore previous approved Product Agent version
- keep `SendAdapter` in no-send or paused mode until gates pass again
- preserve trace, outbox, side-effect, and incident evidence


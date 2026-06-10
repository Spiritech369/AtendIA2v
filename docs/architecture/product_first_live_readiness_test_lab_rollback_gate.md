# Product-First Live Readiness, Test Lab, And Rollback Gate

Date: 2026-06-09  
Status: Active gate contract; docs-only  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

This gate defines what must be true before AtendIA returns to WhatsApp/Baileys
live attempts for Product-First published agents.

## Non-Negotiable Route Rule

Test Lab, replay, live-candidate, and live must use the same
ProductAgentRuntime route.

The only allowed difference is `SendAdapter` behavior:

- Test Lab: no-send
- replay/readiness: no-send
- live-candidate: send decision calculated, no customer send unless approved
- live-limited: SendAdapter may enqueue only inside explicit approved scope

## Live Readiness Gate

Live-limited cannot be requested until all are true:

- baseline checkpoint exists
- Customer Copy Kill Map is complete
- ProductAgentRuntime direct route exists in no-send
- published Product Agent does not enter `ConversationRunner`
- RespondStyleAgentTurn owns `TurnOutput.final_message`
- LLM tool loop is implemented and traced
- validator feedback retry is implemented
- required tools/policy failures fail closed
- workflows emit events only and cannot send customer text
- Test Lab uses the same runtime route as live
- no-send/live-candidate parity passes
- real transcript replay passes
- multi-tenant simulations pass
- outbox pending/retry audit is zero before activation
- business side-effect audit is zero before activation
- Publish Control has explicit live approval
- rollback packet exists

## Required Replay Sets

Minimum replay coverage:

- failed live transcripts from recent Dinamo incidents
- repeated-question cases
- objection/price cases
- requirements/document cases
- workflow/handoff proposal cases
- tool failure cases
- provider/model failure cases

Replay is not live readiness if it uses fixtures or a different runtime path.

## Required Multi-Tenant Simulation

Minimum domains:

- Dinamo/motorcycle dealership
- dental clinic
- barbershop
- real estate
- auto sales
- technical service
- tourism
- ecommerce

The gate fails if behavior depends on shared-code Dinamo assumptions.

## Controlled Smoke Gate

Controlled smoke can be prepared only after live readiness passes.

Approval packet must name:

- tenant
- agent id/version/deployment
- channel
- exact contact or audience scope
- enabled tools
- disabled actions/workflows
- send scope
- rollback trigger
- rollback owner
- expected outbox state before and after
- expected side-effect state before and after
- trace review process

## Rollback Rules

Rollback must:

- pause or reduce send scope first
- preserve all traces and incident evidence
- restore previous approved Product Agent version when available
- keep SendAdapter blocked/no-send until post-rollback checks pass
- never fall back to legacy visible copy for Product-First published agents

## Required Decision Markers

- `RESPOND_STYLE_TEST_LAB_READY`
- `RESPOND_STYLE_REPLAY_GATE_PASSED`
- `RESPOND_STYLE_MULTI_TENANT_SIMULATION_PASSED`
- `LEGACY_CUSTOMER_COPY_BLOCKED_FOR_PRODUCT_AGENTS`
- `PRODUCT_FIRST_LIVE_CANDIDATE_NO_SEND_READY`
- `CONTROLLED_SMOKE_READY_FOR_APPROVAL`


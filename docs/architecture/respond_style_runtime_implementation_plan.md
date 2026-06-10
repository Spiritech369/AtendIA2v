# Respond-Style Runtime Implementation Plan

Date: 2026-06-09  
Status: Active implementation plan; docs-only  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

This plan defines the runtime AtendIA should implement after baseline and
approval. It replaces the composer-as-scriptwriter model with an LLM turn loop
where AtendIA validates, gates, traces, and sends.

## Target Live Route

```txt
WhatsApp/Baileys/Meta
-> Channel Adapter
-> Inbox Event
-> Deployment Resolver
-> ProductAgentRuntime
-> AgentService
-> LLM Agent Turn
-> Tool/Field/Action/Workflow Validator
-> SendAdapter
```

The target route is not:

```txt
WhatsApp
-> ConversationRunner
-> if flag then Runtime V2
-> else legacy
```

## Core Runtime Concept

Use `RespondStyleAgentTurn` or `LLMAgentTurn` as the customer-turn authoring
unit.

It must not compose from slot templates. It asks the LLM to respond from:

- published agent instructions
- tenant-scoped KB/source facts
- tool schemas and tool results
- allowed fields and write policies
- allowed actions and workflow bindings
- contact/conversation state
- hard safety and send policies
- validator feedback from previous attempts

AtendIA validates the result. AtendIA does not write customer conversation copy
with deterministic branches.

## Turn Loop

```txt
1. Build AgentTurnInput.
2. Build AgentContextPackage.
3. LLM proposes message, tool calls, field writes, actions, workflows, handoff.
4. If tools are requested, execute approved tools.
5. Add tool results back to context.
6. LLM generates final_message from real facts.
7. Validator checks facts, policy, fields, actions, workflows, trace, send.
8. If invalid and retryable, return structured feedback to LLM.
9. If valid, emit TurnOutput.final_message.
10. SendAdapter applies no-send/live behavior.
11. If invalid after retries or non-retryable, fail closed/no-send.
```

## Required Contracts

### AgentTurnInput

Minimum fields:

- `tenant_id`
- `deployment_id`
- `agent_id`
- `agent_version_id`
- `runtime_mode`
- `send_mode`
- `channel`
- `conversation_id`
- `contact_id`
- `inbound_event_id`
- `inbound_text`
- `attachments`
- `recent_messages`
- `contact_snapshot`
- `conversation_snapshot`
- `trace_context`

### AgentContextPackage

Minimum fields:

- `agent_identity`
- `instructions`
- `voice_guide`
- `knowledge_bindings`
- `retrieved_context`
- `tool_schemas`
- `tool_results`
- `field_policies`
- `action_schemas`
- `workflow_trigger_schemas`
- `handoff_policy`
- `send_policy`
- `validator_feedback`

### LLMAgentTurnOutput

Minimum fields:

- `final_message`
- `tool_requests`
- `field_write_proposals`
- `action_proposals`
- `workflow_event_proposals`
- `handoff_proposal`
- `claims`
- `confidence`
- `needs_retry_reason`

### ValidationResult

Minimum fields:

- `status`
- `retryable`
- `feedback_for_llm`
- `accepted_tool_requests`
- `accepted_field_writes`
- `accepted_actions`
- `accepted_workflow_events`
- `blocked_items`
- `send_decision`
- `blocked_reason`

## Tool Loop Rules

- LLM can request a tool by name and structured input.
- AtendIA decides whether the tool exists, is bound, is permitted, and is
  required.
- Tools return structured data only.
- A missing/skipped/failed/blocked required tool means no-send unless a retry can
  ask the LLM to correct the tool request.
- Facts such as price, requirements, catalog, appointments, documents, and
  workflow eligibility must come from tools/KB/source data, not shared-code
  hardcoding.

## Shadow Runner Rules

The shadow runner compares a current-path snapshot or injected adapter against
the Respond-Style path without activating live behavior.

Rules:

- current path is adapter/snapshot-based and must not send
- Respond-Style path must use `RespondStyleToolLoop`
- both paths return structured evidence
- comparison scores copy quality, supported facts, internal leaks, generic copy,
  and recommendation
- shadow output is evidence for Phase 7 only; it does not replace AgentService,
  ConversationRunner, SendAdapter, workflows, actions, or outbox behavior

## Retry Rules

Invalid output must not trigger visible fallback copy.

Allowed retry path:

```txt
validator error
-> structured feedback_for_llm
-> LLM correction
-> validator re-check
-> approved final_message or no-send
```

Retry feedback must be structured and traceable. Examples:

- `missing_required_tool`
- `unsupported_claim`
- `field_write_without_evidence`
- `workflow_binding_missing`
- `action_not_allowed`
- `internal_text_visible`
- `final_message_empty`
- `legacy_copy_source_detected`

## Multi-Tenant Simulations

The implementation is not Ready if it only works for Dinamo. Minimum simulation
domains:

- motorcycle dealership
- dental clinic
- barbershop
- real estate
- auto sales
- technical service
- tourism
- ecommerce

Shared runtime code must not contain tenant, vertical, price, plan, document, or
business policy hardcoding.

## Implementation Phases

1. Baseline and branch/worktree decision.
2. Customer Copy Kill Map.
3. Respond-Style Validator.
4. LLM Agent Turn Provider no-send/shadow.
5. Tool loop no-send.
6. Shadow runner old vs new.
7. ProductAgentRuntime direct path.
8. Remove ConversationRunner from published Product Agents.
9. Test Lab same route as live.
10. Live-candidate parity.
11. Controlled smoke approval packet.
12. Decommission legacy visible-copy paths.

## Not In Scope Without Separate Approval

- WhatsApp live send
- Baileys live send
- outbox live writes
- action side effects
- workflow side effects
- canary
- production
- destructive git/filesystem cleanup
- legacy deletion

## Phase 0.5 Amendment (2026-06-09)

Status: `RESPOND_STYLE_CONTRACT_VALIDATOR_AMENDED_VERIFIED_NO_SEND`

- `turn_kind = tool_request | final_response | handoff_request` in the turn
  contract; `final_message` is null for `tool_request` and customer copy
  there is a parse error.
- Validator fact gates apply only to visible copy; `tool_request` turns are
  never fact-gated, so tool proposals are no longer dropped by topic regexes.
- Declarative tenant `hard_policies` (`trigger_patterns` + `requires_any` of
  `tool:<name>` / `basis:<claim_basis>`). Built-in bilingual defaults act as
  safety tripwire only. Malformed tenant policy fails closed.
- Verified against real OpenAI no-send: the Phase 6 fail-closed "model"
  scenario now completes tool_request -> tool_result -> final_response.
  Evidence: `reports/respond_style_phase_0_5_amended_no_send_2026_06_09.md`.

## Phase 7 — Respond-Style Context Package Builder (2026-06-09)

Status: `PHASE_7_RESPOND_STYLE_CONTEXT_PACKAGE_BUILDER_READY`

File: `core/atendia/agent_runtime/respond_style_context_builder.py`

`RespondStyleContextPackageBuilder` is a pure, no-live packager: it builds
`AgentTurnInput` + `AgentContextPackage` from an already-loaded
`RespondStyleContextSnapshot` (tests/runners today; a Product Agent config
adapter supplies snapshots in Phase 8). It performs no I/O, no DB writes, no
tool/action/workflow execution, no field writes, no delivery, and authors no
customer copy or questions.

Normalization invariants:

- Transcript stays ordered and structured (`customer | assistant |
  system_internal`), never flattened to a blob and never synthesized.
- Fields are exposed as data (`missing=true`), never as questions; no
  `next_best_question` / `suggested_question` / `pending_slot` anywhere.
- Tools are capabilities: preconditions, required_context,
  `output_facts_schema`, `produces_claim_support`, forced
  `no_customer_copy=true`.
- Workflows default `dry_run_only=true`, `approval_required=true`;
  `side_effects_allowed` is forced false in no_send mode. Actions likewise.
- KB snippets require a stable `source_id` (build fails closed without it)
  so validator claims can cite them.
- Tenant `hard_policies` are structurally validated at build time; malformed
  config raises `ContextSnapshotError` (fail closed in Test Lab).
- Handoff policy declares `customer_message_authored_by_llm=true`; the
  builder never writes the message.

Evidence: `reports/respond_style_context_builder_no_send_2026_06_09.md`,
runner `tools/run_respond_style_context_builder_no_send_2026_06_09.py`
(three generic tenants: sales, scheduling, support — all tenant-neutral).

Next phase: Phase 8 — ProductAgentRuntime direct path no-send (deployment
resolver + snapshot adapter from Product Agent config + tool executor
fact-only + the amended provider/tool loop/validator, end to end, no send).

## Phase 8 — ProductAgentRuntime Direct Path no-send (2026-06-09)

Status: `PHASE_8_PRODUCT_AGENT_RUNTIME_DIRECT_PATH_NO_SEND_READY`

File: `core/atendia/agent_runtime/respond_style_product_agent_runtime.py`

Pipeline: `ProductAgentRuntimeInput -> ProductAgentRuntimeSnapshotAdapter
(protocol, owns I/O) -> RespondStyleContextPackageBuilder ->
RespondStyleToolLoop -> ProductAgentRuntimeResult`.

- `requested_mode` is schema-locked to `no_send`; live snapshots, adapter
  failures, and malformed config all fail closed with structured reasons.
- Result model refuses `send_decision != no_send` and
  `side_effects_allowed != false` at the pydantic layer.
- Field/workflow/action/handoff outputs are proposals only — nothing is
  executed or persisted. `FinalTurnDecision.accepted_handoff` added
  (additive contract change) so handoff proposals propagate.
- Evidence: `reports/product_agent_runtime_direct_no_send_2026_06_09.md`
  (real OpenAI, 3 generic tenants, 103/103 tests, ruff clean).

Known limitation carried forward: the tool loop implements a single
fact-only round; multi-round (2-3 with budget) is required before live for
sequential/refining tool needs.

Next phase: Phase 9 — DB-backed read-only snapshot adapter from published
Product Agent config + Test Lab routed through this same direct path.

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

## Phase 9 + 9.5 — Config Adapter & Live Simulated Channel (2026-06-09)

Status: `PHASE_9_5_LIVE_SIMULATED_CHANNEL_ANALYSIS_READY`

- Phase 9: `respond_style_product_agent_config_adapter.py` — pure read-only
  mapper from ProductAgentPublishedConfig (AgentVersion-shaped payload
  supported via `published_config_from_version_payload`) + conversation
  state to RespondStyleContextSnapshot. Always no-send; malformed config
  fails closed.
- Phase 9.5: `respond_style_live_simulated_channel.py` — WhatsApp-shaped
  harness over the SAME direct runtime path; simulated delivery and
  in-memory state only; `outbound_outbox_writes` is Literal[0]; no
  outbox/delivery imports (test-enforced).
- Real OpenAI run: 7 scenarios / 10 turns; 9 simulated outbounds; 1 correct
  fail-closed; all no_send; zero side effects.
- Defect found & fixed: provider now retries contract-shape parse errors
  once with `output_parse_error` feedback (was failing closed on first
  attempt; empty field-write evidence was the trigger).
- Findings for Phase 10: (F1) same-turn field proposals are invisible to
  the same turn's tool executor — compound first messages fail closed;
  (F2) missing_fields exposure biases the model toward form-filling over
  satisfiable tools.

Evidence: `reports/live_simulated_channel_no_send_2026_06_09.md`.

## Phase 10 — F1/F2 Fixes + Test Lab Direct (2026-06-09)

Status: `PHASE_10_RESPOND_STYLE_SIMULATED_LIVE_FIXES_AND_TESTLAB_API_READY`

- F1: tool loop injects the turn's VALIDATED field proposals as provisional
  contact state for the same turn's tool round (and merges them into the
  final decision). No persistence — provisional context only. Chaotic
  compound case: live simulated channel now 10/10 turns, 0 blocked.
- F2: prompt + builder declare fields as opportunistic capture
  (`field_capture_policy: opportunistic_never_agenda`), never an agenda;
  satisfiable tools take priority over field collection.
- Test Lab Direct: `respond_style_test_lab_direct.py` runs scenarios over
  the SAME direct path and emits TestLabScenarioResult evidence through an
  injected TestLabEvidenceSink (in-memory default; DB/API adapter = Phase
  11). Legacy product_agents/test_lab.py intentionally untouched.
- Carried-forward pre-live requirement (re-confirmed by chaotic Test Lab
  run blocking on `tool_round_limit_reached`): configurable multi-round
  tool loop with budget.

Evidence: `reports/respond_style_phase_10_fixes_and_test_lab_direct_2026_06_09.md`.

## Phase 11 — Multi-Round Loop, Test Lab DB/API, Deployment Resolver (2026-06-09)

Status: `PHASE_11_RESPOND_STYLE_MULTIRound_TESTLAB_RESOLVER_NO_SEND_READY`

- 11A: tool loop is multi-round with budgets (`max_tool_rounds` default 1,
  `max_total_tool_calls`, `max_elapsed_seconds`; exhaustion fails closed).
  Succeeded tools are never re-executed (dedupe + one structured nudge to
  write from existing tool_results). Real OpenAI: chaotic compound resolved
  in 3 rounds; sequential option_id dependency in 2 rounds.
- 11B: `test_lab_direct_adapter.run_direct_test_suite` + route
  `POST /test-suites/{suite_id}/runs/respond-style-direct` store direct-path
  evidence as AgentTestRun rows (mode no_send, clean outbox/side-effect
  audits, JSONB evidence; no migration). `DryFactsToolExecutor` is the
  generic config-driven fact executor (bindings declare dry_facts +
  preconditions). Legacy test_lab.py untouched.
- 11C: `RespondStyleDeploymentResolver` previews product_agent_direct vs
  legacy_runner per deployment; resolution model is schema-locked to
  no_send/no live routing; live flags only surface as blocked reasons.

Evidence: `reports/respond_style_phase_11_multiround_testlab_resolver_2026_06_09.md`.

Next: Phase 12 — HTTP+DB end-to-end Test Lab direct in Docker, resolver
preview wired into inbound (log-only), legacy customer-copy hard-block
test battery from the kill map.

## Phase 12 — Docker E2E, Inbound Preview, Legacy Copy Hard Block (2026-06-09)

Status: `PHASE_12_DOCKER_E2E_AND_LEGACY_COPY_HARD_BLOCK_READY`

- 12A: real-container E2E PASSED — the respond-style-direct Test Lab
  endpoint ran inside `atendia_backend` against real Postgres with real
  OpenAI; AgentTestRun evidence persisted (mode no_send, status passed);
  outbox row delta 0; CSRF middleware exercised.
- 12B: `routing_preview.py` wired into `_run_inbound_pipeline` as a 9-line
  log-only block (fail-safe, swallows all errors). Per-deployment opt-in
  flag: `metadata_json.respond_style_enabled`. Real previews captured in
  Docker: all no_send, live_routing_active=false.
- 12C: hard-block battery `test_product_agent_legacy_copy_hard_block.py` —
  transitive import-graph proof that the direct route cannot load any kill
  map copy source, plus output-structure guarantees (no fallback copy on
  blocked turns, handoff/workflow proposals carry no copy, no plan
  artifacts). Kill map amended with the missing ConversationProgressGuard
  row.

Evidence: `reports/respond_style_phase_12_docker_e2e_hard_block_2026_06_09.md`.

Next: Phase 13 — Publish Control gates on the hard-block battery, resolver
flip behind per-deployment opt-in in shadow, failed V2/V3 transcript replay
through the direct route, live-candidate parity gate.

## Phase 13 — Publish Gates, Inbound Shadow, Replay, Parity (2026-06-09)

Status: `PHASE_13_PUBLISH_CONTROL_AND_INBOUND_SHADOW_PARITY_READY`

- 13A: Publish Control now adds blockers for respond_style deployments
  unless the kill-map import audit is clean AND the latest direct Test Lab
  run passed. Audit logic centralized in `respond_style_route_audit.py`.
- 13B: opt-in inbound shadow (`respond_style_inbound_shadow_enabled`) runs
  the direct route no-send per inbound and logs evidence; fail-safe step 2c
  in the pipeline. Docker harness PASSED (real DB + OpenAI; outbox 0).
  Resolver fix: accepts `published_no_send` (DB's published state).
- 13C: failed V2/V3 transcripts replayed through the direct route with real
  OpenAI: 9/9 answered, 0 internal leaks, 0 silent turns. Both historical
  failure modes do not reproduce.
- 13D: parity gate proves no_send Test Lab mode and simulated
  live-candidate mode are the same code path with the send-policy label as
  the only difference; schema-locked legacy_path_used=False + import audit.

Evidence: `reports/respond_style_phase_13_publish_shadow_parity_2026_06_09.md`.

Path to live from here: shadow-soak on a pilot deployment, human review of
shadow candidates, then controlled live-candidate smoke gated by parity +
publish gates + rollback packet.

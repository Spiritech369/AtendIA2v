# Respond-Style Phase 7 — Context Package Builder (no-send)

Date: 2026-06-09
Decision: `PHASE_7_RESPOND_STYLE_CONTEXT_PACKAGE_BUILDER_READY`
Module: `core/atendia/agent_runtime/respond_style_context_builder.py`
Tests: `core/tests/agent_runtime/test_respond_style_context_builder.py` (20 tests)
Runner: `tools/run_respond_style_context_builder_no_send_2026_06_09.py`
Raw result: `reports/respond_style_context_builder_no_send_result_2026_06_09.json`

## Purpose

`RespondStyleContextPackageBuilder` packages an already-loaded structured
snapshot (`RespondStyleContextSnapshot`) into the amended turn contract:
`AgentTurnInput` + `AgentContextPackage`. It is the context layer for the
Respond-Style runtime. It does not converse, does not author or repair
visible text, does not route tools by keyword, does not execute anything,
and does not touch persistence or delivery.

## Input accepted (snapshot, no I/O in the builder)

Identity (tenant/deployment/agent/version/conversation/contact/channel),
runtime_mode + send_mode, inbound text/attachments, recent messages,
contact fields with write metadata, conversation stage, agent config
(name, persona, instructions, language, tone, goals, do_not_do,
escalation_rules), KB snippets, tool/action/workflow bindings, handoff
options, declarative hard policies, publish_state + send_scope, trace
context.

## Context package generated

- **Transcript**: structured messages (`customer | assistant |
  system_internal`), order preserved, role aliases normalized
  (user/inbound→customer, agent/outbound→assistant). No blob, no synthesis.
- **Agent config**: passed through verbatim into `agent_identity` +
  `instructions`. No if-rules derived from it.
- **Capabilities (tools)**: name, description, input_schema,
  output_facts_schema, preconditions, required_context,
  produces_claim_support, binding_id, dry_run/approval metadata, and forced
  `no_customer_copy=true`. Missing name/description fails the build closed.
- **Fields**: field_key, label, type, current_value, writable, required,
  derived `missing` flag, write_policy, evidence_required, allowed_sources,
  confidence, last_evidence, can_propose_update. Missing fields are data —
  no question text, no `next_best_question`, no `pending_slot`.
- **Workflows**: binding/event names required; `dry_run_only=true` and
  `approval_required=true` by default; `side_effects_allowed` forced false
  in no_send even if the binding says otherwise.
- **Actions**: same defaults; permission metadata passed through; never
  executed.
- **KB snippets**: stable `source_id` required (build fails closed with
  `kb_snippet_missing_source_id`), title/excerpt/citation/freshness/
  allowed_claim_types. Source ids land in both `retrieved_context` and
  `knowledge_bindings`, so validator claims with basis `knowledge_source`
  can cite them — verified end-to-end against `RespondStyleTurnValidator`.
- **Hard policies**: Phase 0.5 format (policy_id, trigger_patterns,
  requires_any + optional applies_to/severity/retryable/error_code).
  Structurally validated at build time; malformed config raises
  `ContextSnapshotError` (fail closed). No conversational rules.
- **Handoff**: enabled/targets/reasons_allowed/dry_run_only +
  `customer_message_authored_by_llm=true`. No message text.
- **Mode/scope**: runtime_mode, send_mode, publish_state, send_scope,
  deployment_id, runtime_path (`respond_style_no_send` when no_send). The
  builder carries the policy; it never decides send.

## Runner (three generic tenants, no hardcoded vertical)

| Check | sales | scheduling | support |
|---|---|---|---|
| turn_input + package valid (strict round-trip) | yes | yes | yes |
| send_mode | no_send | no_send | no_send |
| tools all `no_customer_copy` | yes | yes | yes |
| workflows dry_run + no side effects | yes | yes | yes |
| actions no side effects | yes | yes | yes |
| KB snippets with stable source_id | yes | yes | yes |
| missing fields derived as data | yes | yes | yes |
| no final_message / question fields | yes | yes | yes |
| handoff message authored by LLM only | yes | yes | yes |

## Verification

- pytest: 91/91 across contract, validator, provider, tool loop, shadow
  runner, and context builder.
- ruff: clean on the three new files.
- Source audit (grep): no ConversationRunner / HumanResponseComposer /
  StructuredRuntimeComposer / SendAdapter / outbox / enqueue_messages /
  evaluate_event / AgentService anywhere in the builder; no
  next_best_question / suggested_question / pending_slot; no tenant or
  vertical hardcode (word-boundary check incl. dinamo/motos/credito/sat/
  metro). Builder imports only `re`, `typing`, `pydantic`, and the turn
  contract.
- The builder never reads `inbound_text` for routing (verified by test):
  no keyword→tool forcing.

## No side effects

No DB reads or writes, no network, no outbox, no workflows, no actions, no
delivery, no WhatsApp, no smoke. Snapshot in, contract models out.

## Shadow integration note

`RespondStyleShadowRunner` and `RespondStyleToolLoop` already accept
`AgentTurnInput`/`AgentContextPackage`, so builder output plugs into the
existing no-send loops without code changes. Connecting a Product Agent
config adapter (snapshot source) and AgentService remains Phase 8+.

## Decision

`PHASE_7_RESPOND_STYLE_CONTEXT_PACKAGE_BUILDER_READY`

This marker does not prove live readiness and does not authorize send,
smoke, canary, workflow/action side effects, or production traffic.

# Respond-Style Phase 8 — ProductAgentRuntime Direct Path (no-send)

Date: 2026-06-09
Decision: `PHASE_8_PRODUCT_AGENT_RUNTIME_DIRECT_PATH_NO_SEND_READY`
Module: `core/atendia/agent_runtime/respond_style_product_agent_runtime.py`
Tests: `core/tests/agent_runtime/test_product_agent_runtime_direct_no_send.py` (12 tests)
Runner: `tools/run_product_agent_runtime_direct_no_send_2026_06_09.py` (real OpenAI)
Raw result: `reports/product_agent_runtime_direct_no_send_result_2026_06_09.json`

## Pipeline

```
ProductAgentRuntimeInput
  -> ProductAgentRuntimeSnapshotAdapter (protocol; owns all I/O)
  -> RespondStyleContextPackageBuilder (pure)
  -> RespondStyleToolLoop (provider + dry fact executor)
  -> ProductAgentRuntimeResult (always no_send, side_effects_allowed=false)
```

No ConversationRunner, no HumanResponseComposer, no StructuredRuntimeComposer,
no ValidatedResponsePlanBuilder, no SendAdapter, no outbox, no AgentService,
no workflow/action execution, no field persistence. Field updates, workflow
events, actions, and handoff come out as validated **proposals** for a later
execution layer — nothing is executed.

## Fail-closed guarantees (all schema- or code-enforced, all tested)

- `ProductAgentRuntimeInput.requested_mode` is `Literal["no_send"]` — a live
  request cannot even be constructed.
- Snapshot with `send_mode != no_send` → blocked `send_mode_not_no_send`
  before the builder or any LLM call.
- Snapshot with live `runtime_mode` → blocked `runtime_mode_not_no_send`.
- Adapter exception → blocked `snapshot_adapter_failed:<type>`, never a crash.
- Malformed config (e.g. KB snippet without stable source_id) → blocked with
  the builder's `ContextSnapshotError` code.
- `ProductAgentRuntimeResult.send_decision` only accepts `no_send`;
  `side_effects_allowed` only accepts `False` (pydantic validators).

## Contract addition

`FinalTurnDecision.accepted_handoff` (additive): the validator now propagates
a valid, needed handoff proposal into the decision so the runtime can expose
it as a proposal. Backwards compatible; full suite stayed green.

## Real OpenAI no-send run (3 generic tenants, tenant-neutral)

| Check | sales | scheduling | support |
|---|---|---|---|
| send_decision | no_send | no_send | no_send |
| side_effects_allowed | false | false | false |
| blocked_reason | none | none | none |
| tools executed (dry) | requirements.lookup | availability.lookup | — (KB-grounded) |
| validation | valid | valid | valid |
| final_message from facts | yes | yes | yes (KB snippet) |
| runtime_path | respond_style_no_send_direct | same | same |

The support scenario answered correctly from the KB snippet without a tool
round — legitimate, since the KB covered the question; the direct tool path
is proven by the other two scenarios.

## Honest notes from the first run (kept for the record)

1. First execution returned `PHASE_8_BLOCKED_BY_MODEL_BEHAVIOR` because the
   scheduling scenario asked "tienen espacio manana?" while the dry tool
   returned slots **without a date**; the model re-requested a date-specific
   lookup in turn 2 and the 1-round loop blocked fail-closed
   (`tool_round_limit_reached`). That block was CORRECT behavior — the model
   refused to invent a date. The scenario facts were fixed
   (`date_scope: next_business_day`, question without a pinned day).
2. Takeaway carried to Phase 9+: live conversations will need a configurable
   multi-round tool loop (2–3 rounds with budget) for sequential/refining
   tool needs. `RespondStyleToolLoopConfig.max_tool_rounds` exists but the
   loop currently implements a single round.

## Verification

- pytest: 103/103 across the whole respond-style suite (contract, validator,
  provider, tool loop, shadow runner, context builder, product agent runtime).
- ruff: clean on all touched files (including two pre-existing nits in the
  Phase 0.5 validator that were fixed here).
- Source audit: no legacy/live imports in the runtime module; no tenant or
  vertical hardcode (word-boundary check); the runtime never inspects
  `inbound_text` (no keyword routing) — all enforced by tests.

## No side effects

No DB writes, no outbox, no delivery, no workflows, no actions, no WhatsApp,
no smoke. Two independent real-OpenAI runs of the final code produced the
same READY decision.

## Decision

`PHASE_8_PRODUCT_AGENT_RUNTIME_DIRECT_PATH_NO_SEND_READY`

This marker does not prove live readiness and does not authorize send, smoke,
canary, workflow/action side effects, or production traffic. Next: Phase 9 —
Product Agent config snapshot adapter (DB-backed, read-only) + Test Lab on
this same route.

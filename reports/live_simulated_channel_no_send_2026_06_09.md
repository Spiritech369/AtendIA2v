# Respond-Style Phase 9 + 9.5 — Config Adapter & Live Simulated Channel (no-send)

Date: 2026-06-09
Decision: `PHASE_9_5_LIVE_SIMULATED_CHANNEL_ANALYSIS_READY`
Modules:
- Phase 9: `core/atendia/agent_runtime/respond_style_product_agent_config_adapter.py`
- Phase 9.5: `core/atendia/agent_runtime/respond_style_live_simulated_channel.py`
Tests: `core/tests/agent_runtime/test_respond_style_live_simulated_channel.py` (12) + provider parse-retry tests (2)
Runner: `tools/run_live_simulated_channel_no_send_2026_06_09.py` (real OpenAI)
Raw result: `reports/live_simulated_channel_no_send_result_2026_06_09.json`

## Phase 9 — ProductAgentConfigSnapshotAdapter

Pure, read-only mapper: `ProductAgentPublishedConfig` (identity, persona,
instructions, bindings, field definitions, hard policies, handoff, send
scope — shaped after the Product Agent version schema: role/tone/language/
instructions + knowledge/tool/action/field/workflow/safety policies) +
`ConversationStateSnapshot` (messages, field values, stage) →
`RespondStyleContextSnapshot`. Always emits no-send snapshots; live modes
remain a separately gated phase. `published_config_from_version_payload()`
maps an AgentVersion-shaped payload directly; malformed payloads or field
definitions fail closed with `ContextSnapshotError`.

## Phase 9.5 — LiveSimulatedChannel

WhatsApp-shaped harness over the SAME direct path as Phase 8/Test Lab:
config adapter → context builder → tool loop → validator → ProductAgentRuntime.
Differences from live are simulation-only:

- A valid final_message becomes a **simulated outbound** appended to the
  in-memory conversation (so multi-turn context grows naturally).
- Accepted field proposals update only the **in-memory** contact state
  (recorded as `simulated_field_writes`; `side_effects.field_writes=false`).
- `outbound_outbox_writes` is `Literal[0]` in the summary model — the
  module has no outbox/dispatcher/delivery import at all (enforced by test).
- Every turn record captures: final_message candidate, validation result,
  tools + tool_results, field/workflow/action proposals, handoff, retry
  instruction, send_policy (`delivery: simulated`), full trace.

## Real OpenAI run — 7 scenarios, 10 turns

Totals: 9/10 turns produced a simulated outbound; 1 fail-closed; all 10
`send_decision=no_send`; outbox writes 0; side effects 0.

### Turn-by-turn analysis

**greeting_info** — natural greeting; on "busco informacion" it ran
`catalog.search` and answered from facts ("opción estándar y premium").
Correct capability use without keyword routing.

**requirements** — turn 1 captured `selected_option="opción estándar"` as a
field write WITH evidence (after the parse-retry fix). Turn 2 asked for
budget/work type instead of proposing `requirements.lookup` despite
`selected_option` being in contact state. See finding F2.

**price** — `quote.resolve` then "La opción estándar cuesta $120 USD al
mes." Exact price, tool-supported, hard policy exercised and passed.

**ambiguous_merchant** — asked naturally for the missing detail; no
invented eligibility claim. Acceptable.

**price_objection** — empathetic, no invented discount, but turn 2 nearly
repeated turn 1's question. Mild repetitiveness; live would need the
progress signal to come from conversation quality evals, not rewriters.

**robot_handoff** — best turn of the run: honest response, visible message
authored by the LLM, and a structured handoff proposal
(`needed=true, target="sales"`) captured without execution.

**chaotic** — "quiero la opcion estandar trabajo por mi cuenta que necesito
y cuanto cuesta": model proposed `requirements.lookup` + `quote.resolve`
but the executor could not resolve `selected_option` (same-turn field
proposal not yet applied; tool arguments did not carry it) → required tool
skipped → **fail-closed no_send**. Correct safety behavior; see finding F1.

## Findings for Phase 10

- **F1 (coordination gap, blocking-quality):** facts the LLM extracts in
  the same turn (field proposals) are not visible to the tool executor of
  that turn. Options: pass the turn's accepted field proposals to the
  executor as provisional context, and/or instruct the model to copy known
  values into tool arguments. Without this, compound first messages
  fail closed unnecessarily.
- **F2 (form-filling bias):** exposing `missing_fields` nudges gpt-4o-mini
  toward collecting fields before using tools that are already satisfiable.
  Prompt should state that fields are opportunistic captures, never an
  agenda, and that satisfiable tools take priority over field collection.
- **F3 (fixed during this phase):** contract-shape errors from the model
  (e.g. field write with empty evidence) were failing closed on attempt 1.
  The provider now retries once with structured `output_parse_error`
  feedback; with retries disabled it still fails closed. The first channel
  run surfaced this (5/10 turns blocked), the fix took blocked turns from
  5 to 1 — exactly the kind of defect Phase 9.5 exists to catch before any
  live wire.

## Verification

- pytest: 117 passed (whole respond-style + product agent runtime suite,
  including 12 new channel/adapter tests and 2 new provider retry tests).
- ruff: clean on all new/touched files.
- Source audit (test-enforced): no ConversationRunner / composers /
  ValidatedResponsePlan / delivery adapter / outbound_dispatcher /
  stage_outbound / enqueue_messages / evaluate_event / AgentService /
  baileys in adapter or channel; no tenant/vertical hardcode
  (word-boundary, incl. r4).

## No side effects

No outbox writes (structurally impossible — no import), no workflows, no
actions, no delivery, no DB persistence, no WhatsApp, no smoke. All turns
forced no_send at three independent layers (provider, tool loop, runtime
result model).

## Decision

`PHASE_9_5_LIVE_SIMULATED_CHANNEL_ANALYSIS_READY`

This marker does not prove live readiness and does not authorize send,
smoke, canary, workflow/action side effects, or production traffic.
Next: Phase 10 — F1/F2 fixes + Test Lab API routed through this same
direct path, then AgentService integration no-send.

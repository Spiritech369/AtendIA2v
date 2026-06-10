# Respond-Style Phase 10 — F1/F2 Fixes + Test Lab Direct (no-send)

Date: 2026-06-09
Decision: `PHASE_10_RESPOND_STYLE_SIMULATED_LIVE_FIXES_AND_TESTLAB_API_READY`
Modules:
- F1: `core/atendia/agent_runtime/respond_style_tool_loop.py` (provisional fields)
- F2: `respond_style_llm_provider.py` (prompt) + `respond_style_context_builder.py` (capture policy)
- Test Lab: `core/atendia/agent_runtime/respond_style_test_lab_direct.py`
Tests: `core/tests/agent_runtime/test_respond_style_test_lab_direct.py` (13 new; 127 total)
Runners:
- `tools/run_live_simulated_channel_no_send_2026_06_09.py` → `reports/live_simulated_channel_no_send_result_2026_06_09.json`
- `tools/run_respond_style_test_lab_direct_no_send_2026_06_09.py` → `reports/respond_style_test_lab_direct_no_send_result_2026_06_09.json`

## F1 — Same-turn field proposals as provisional facts

The tool loop now merges the turn's VALIDATED field proposals into the tool
round's context (`agent_identity.contact_state` + `provisional_field_keys`,
with those keys removed from `missing_fields`), so the executor can satisfy
preconditions like `selected_option` extracted from the same message.

- Provisional only: no StateWriter, no session/commit, no outbox — enforced
  by source test. Real persistence remains a later validated layer; the
  simulated state updates only inside LiveSimulatedChannel.
- Turn-1 field proposals are merged into the FINAL decision (final turn
  wins on collisions), so evidence is never lost when the final response
  does not repeat them.
- Loop trace records `provisional_field_keys`.

**Result with real OpenAI:** the Phase 9.5 chaotic case ("quiero la opcion
estandar trabajo por mi cuenta que necesito y cuanto cuesta") now completes:
live simulated channel went from 9/10 to **10/10 turns answered, 0 blocked**.

## F2 — Fields as opportunistic capture, never agenda

- System prompt now states: known/missing fields are awareness, "never an
  agenda and never a questionnaire"; capture opportunistically with quoted
  evidence; same-turn proposals count as known facts for tool
  preconditions; prefer intent + satisfiable tools over field collection;
  ask at most one blocking detail at a time.
- Builder exposes `field_capture_policy: "opportunistic_never_agenda"` in
  agent_identity as the declarative contract.

## Test Lab Direct

`RespondStyleTestLabDirect` runs scenarios through the SAME direct path
(config adapter → builder → tool loop → validator → ProductAgentRuntime via
LiveSimulatedChannel) and hands `TestLabScenarioResult` evidence to an
injected `TestLabEvidenceSink` (in-memory by default; DB/API persistence is
a Phase 11 adapter — the runner itself persists nothing).

Evidence captured per turn: context trace, provisional field keys, tools +
tool_results, validator result, final_message, field/workflow/handoff
proposals, `send_decision` (Literal "no_send"), `outbound_outbox_writes`
(Literal 0), side_effects (all false).

Deliberate scope note: the legacy `product_agents/test_lab.py` (AgentService
+ composer traces) was NOT rewired — it stays on the old route until Phase
11 decides its fate. Wiring the new runner into the existing DB-backed Test
Lab API is an adapter task on top of `TestLabEvidenceSink`.

## Real OpenAI runs

**Live simulated channel (7 scenarios / 10 turns):** 10/10 simulated
outbounds, 0 blocked, all no_send, outbox 0. Chaotic case resolved by F1.

**Test Lab direct (3 scenarios):** decision READY; evidence saved 3/3; all
turns no_send; outbox 0; side effects 0.

- greeting_info: natural 2-turn conversation.
- chaotic_compound: blocked `tool_round_limit_reached` — the CORRECT
  reason: this run the model resolved `quote.resolve` in round 1 (reading
  selected_option from tool arguments) and then needed `requirements.lookup`
  in a second round, which the 1-round loop does not allow. NOT a
  provisional-context failure (acceptance criterion met). This is the
  already-documented pre-live requirement: configurable multi-round tool
  loop (2-3 rounds with budget). Model variance note: the same compound
  ask completed in one round in the channel run.
- handoff: `handoff_request` turn with structured proposal
  (`target=support`) and no visible message — valid per contract;
  conversationally, live policy should decide whether a visible
  acknowledgment is required (LLM-authored) before handoff executes.

## Verification

- pytest: 127 passed (full respond-style + product agent runtime + test lab
  direct suites).
- ruff: clean on all touched files.
- Source audits (test-enforced): tool loop has no persistence APIs; test
  lab direct imports no legacy (ConversationRunner/composers/
  ValidatedResponsePlan/AgentService/StateWriter/outbox/baileys); no
  tenant/vertical hardcodes anywhere new.

## No side effects

No outbox (structurally impossible), no workflows, no actions, no DB
writes, no delivery, no WhatsApp, no smoke. All turns no_send.

## Decision

`PHASE_10_RESPOND_STYLE_SIMULATED_LIVE_FIXES_AND_TESTLAB_API_READY`

Not live readiness. Next: Phase 11 — multi-round tool loop (config-gated,
budgeted), Test Lab API/DB adapter over TestLabEvidenceSink, and the
deployment resolver groundwork for ConversationRunner bypass.

# Respond-Style Phase 0.5 — Contract/Validator Amendment Verification (no-send)

Date: 2026-06-09
Decision: `RESPOND_STYLE_CONTRACT_VALIDATOR_AMENDED_VERIFIED_NO_SEND`
Runner: `tools/run_respond_style_phase_0_5_amended_no_send_2026_06_09.py`
Raw result: `reports/respond_style_phase_0_5_amended_no_send_result_2026_06_09.json`
Code under test: commit `18cd2eb9` (phase 0.5 amendment)
Key source: `core/.env:ATENDIA_V2_OPENAI_API_KEY` (real OpenAI, gpt-4o-mini, strict JSON schema)

## What was amended (commit 18cd2eb9)

- `turn_kind = tool_request | final_response | handoff_request` in the turn contract.
- `final_message` is null for `tool_request`; customer copy there is a parse error.
- Validator fact gates apply only to visible copy; `tool_request` turns are never
  fact-gated, so proposing a tool about a topic no longer invalidates the turn.
- Declarative tenant `hard_policies` (trigger_patterns + requires_any of
  `tool:<name>` / `basis:<claim_basis>`); built-in bilingual defaults act as
  tripwire only; malformed tenant policy fails closed.

## Why this run matters

The Phase 6 shadow run had one fail-closed scenario ("model": customer names a
selected option). Root cause: turn-1 always required a visible message, the
validator fact-gated that message before the proposed tool could run, and the
invalid turn dropped the tool proposals. This run replays that scenario against
the amended contract with the real model.

## Verified checklist (all three scenarios, real OpenAI)

| Check | model ("metro") | requirements ("que ocupo") | price ("cuanto cuesta") |
|---|---|---|---|
| turn 1 is `tool_request` | yes | yes | yes |
| turn 1 has NO visible message | yes (final_message null) | yes | yes |
| tool executed (dry/fact-only) | requirements.lookup | requirements.lookup | quote.resolve |
| tool_result present in turn-2 context | yes | yes | yes |
| turn 2 is `final_response` | yes | yes | yes |
| final validator status | valid | valid | valid |
| send_decision | no_send | no_send | no_send |
| LLM turns total | 2 | 2 | 2 |

The previously fail-closed "model" scenario now produces a fact-grounded
final_response (requirements list written from the tool result). The price
scenario exercised the default hard policy ("costo ... 120" triggers the price
tripwire) and passed because `quote.resolve` succeeded — the gate is active and
fact-supported, not bypassed.

## No-side-effects confirmation

- The runner imports only respond_style modules; no AgentService,
  ConversationRunner, SendAdapter, outbox, workflow engine, or DB session.
- Tool executor is injected dry/fact-only (in-memory facts, no I/O).
- `side_effects` in result: `outbox=false, workflows=false, actions=false,
  delivery=false`. Every decision forced `send_decision=no_send` by the
  provider and the tool loop independently.
- No WhatsApp, no live, no canary, no smoke. This is no-send evidence only.

## Run notes

- Two independent real runs produced the same decision (first run discarded for
  console-encoding mojibake in the saved JSON; behavior identical).
- gpt-4o-mini followed the `turn_kind` contract on turn 1 in 3/3 scenarios with
  no retry needed.
- Unit suite at this commit: 71/71 passing
  (`core/tests/agent_runtime/test_respond_style_*`).

## Gate status

`RESPOND_STYLE_CONTRACT_VALIDATOR_AMENDED_READY` (code) +
`RESPOND_STYLE_CONTRACT_VALIDATOR_AMENDED_VERIFIED_NO_SEND` (real model) →
Phase 7 (`RespondStyleContextPackageBuilder`) is unblocked.

This marker does not prove live readiness and does not authorize send, smoke,
canary, workflow/action side effects, or production traffic.

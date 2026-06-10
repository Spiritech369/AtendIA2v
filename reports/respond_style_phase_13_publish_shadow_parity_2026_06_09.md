# Respond-Style Phase 13 — Publish Gates, Inbound Shadow, Transcript Replay, Parity Gate

Date: 2026-06-09
Decision: `PHASE_13_PUBLISH_CONTROL_AND_INBOUND_SHADOW_PARITY_READY`
Artifacts:
- 13A: `core/atendia/product_agents/publish_gates.py` (+ wiring in
  `service.evaluate_publish_request`) and
  `core/atendia/agent_runtime/respond_style_route_audit.py`
- 13B: `core/atendia/product_agents/inbound_shadow.py` (+ step 2c in
  `_run_inbound_pipeline`), Docker harness
  `tools/run_inbound_shadow_docker_2026_06_09.py` →
  `reports/inbound_shadow_docker_result_2026_06_09.json`
- 13C: `tools/run_failed_transcript_replay_direct_2026_06_09.py` →
  `reports/failed_transcript_replay_direct_result_2026_06_09.json`
- 13D: `core/atendia/agent_runtime/respond_style_parity_gate.py`
- Tests: `test_respond_style_phase_13.py` (10) + battery refactor; suite 166.

## 13A — Publish Control gates

`respond_style_publish_blockers` adds ADDITIVE blockers to publish-request
evaluation for deployments with `metadata_json.respond_style_enabled`:

- `respond_style_hard_block_battery_failed` — the kill-map import-graph
  audit (now shared single-source in `respond_style_route_audit.py`, used by
  both the test battery and Publish Control) found a legacy copy module
  reachable from the direct route. Audit errors fail closed
  (`respond_style_hard_block_audit_failed`).
- `respond_style_test_lab_direct_missing` / `_not_passed` — the latest
  AgentTestRun with `execution_mode=respond_style_product_agent_direct`
  must exist and be `RESPOND_STYLE_DIRECT_NO_SEND_READY`.

Deployments without the opt-in flag are untouched; existing blockers are
never removed.

## 13B — Opt-in inbound shadow (observation only)

For deployments with `respond_style_inbound_shadow_enabled` AND a
`product_agent_direct` resolver preview, each inbound ALSO runs through
ProductAgentRuntime no-send (config from the active version, transcript
from the last 12 conversation messages, DryFacts executor, 3-round budget)
and the evidence is logged. Wired as fail-safe step 2c in the inbound
pipeline; without the flag (default) behavior is byte-identical.

**Docker harness PASSED** (real Postgres + real OpenAI inside
`atendia_backend`): seeded a `published_no_send` deployment with both
flags; shadow produced a no_send candidate with a field proposal whose
evidence quotes the customer; side effects all false; **outbox delta 0,
pending/retry 0**.

Found & fixed by the harness: the resolver required `publish_state ==
"published"`, but the deployment schema's published state for this stage is
`published_no_send` (DB check constraint). The resolver now accepts both
(`PUBLISHED_STATES`).

## 13C — Failed V2/V3 transcript replay (real OpenAI, direct route)

`PHASE_13C_FAILED_TRANSCRIPT_REPLAY_PASSED` — 9/9 turns answered, 0
internal leaks, 0 silent turns, all no_send.

- **V2 replay** ("Hola" → "Info porfavor" → "Me pagan por transferencia" →
  "?"): the historical failure was SILENCE after the income answer
  (required tool skipped on missing tenant source). Now every turn answers;
  the income answer gets a natural follow-up question; "?" re-engages
  instead of dead air.
- **V3 replay** (adds "15 meses"): the historical failure was the internal
  leak *"campo no está visible"*. Now: "Entiendo que tienes 15 meses de
  experiencia laboral. ¿Cuál es tu tipo de ingreso?" — checked against an
  explicit leak-marker list (campo no visible / field_not_visible /
  StateWriter / error técnico variants): zero hits across all turns.

## 13D — Parity gate (no_send vs simulated live-candidate)

`run_parity_gate` runs the same scenario through the same direct route
twice — labels `no_send` vs `live_candidate_simulated` — with a
deterministic provider, and compares turn-by-turn evidence
(final_message, blocked_reason, proposals, field writes, handoff,
simulated outbound). `ParityGateResult.legacy_path_used` is
`Literal[False]` and the gate re-runs the import audit
(`legacy_import_violations` must be empty). Verified: identical runs pass
with full audit; an injected divergence is detected and reported
field-by-field; both paths remain strictly no_send; the ONLY difference is
the send-policy label.

## Verification

- pytest: 166 passed (whole respond-style + product agent battery).
- ruff: clean on all new/touched files.
- Runners: 13C replay PASSED (real OpenAI), 13B Docker shadow PASSED
  (real DB + OpenAI), DB outbox audit 0/0.
- Import audit (rg-equivalent, stronger): shared route audit clean —
  enforced in tests, Publish Control, and the parity gate.

## No live behavior change

ConversationRunner untouched. Inbound diff: one fail-safe, flag-gated,
log-only block. No outbox writes, no workflows/actions, no delivery, no
WhatsApp, no smoke, no live routing.

## Decision

`PHASE_13_PUBLISH_CONTROL_AND_INBOUND_SHADOW_PARITY_READY`

Not live readiness. The remaining path to live: a shadow-soak window on
real inbound traffic (flag on for one pilot deployment), human review of
shadow candidates vs legacy replies, then the controlled live-candidate
smoke gated by the parity gate + publish gates + rollback packet.

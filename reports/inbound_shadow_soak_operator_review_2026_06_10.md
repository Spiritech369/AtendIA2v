# Phase 16 — Inbound Shadow Soak: Operator Review (no-send)

Date: 2026-06-10
Decision: `PHASE_16_INBOUND_SHADOW_SOAK_AND_OPERATOR_REVIEW_READY`
Harness: `tools/run_inbound_shadow_soak_2026_06_10.py` →
`reports/inbound_shadow_soak_result_2026_06_10.json`
Suite: 215 tests passing, ruff clean.

## What Phase 16 changed

- **Inbound shadow now runs through the REAL AgentService** (16A): the
  same `run_inbound_shadow` wired into the Baileys pipeline (step 2c)
  delegates each opted-in inbound to `AgentService.handle_turn` no-send —
  so the shadow exercises publish gates, shadow field memory (Phase 15A),
  the no_send_followup policy (15B) and multi-deployment resolution (15C)
  exactly as the future live route will. Evidence per turn: route,
  legacy_path_used, candidate, tools, validator, field_state (with
  audit), no_send_followup, handoff, send/outbox flags.
- **15C extension:** a channel signal (metadata `channel`/`reply_channel`)
  now disambiguates multi-deployment tenants; without a signal, multiple
  matches still fail closed (`respond_style_deployment_ambiguous`).
- **15B surfaced in soak evidence:** every turn carries the internal
  attention decision; blocked turns appear in the report's
  `internal_attention_items`.

## Soak window result (Docker, real DB + OpenAI, real pipeline function)

4 conversations / 12 inbound messages: **12/12 answered**, all
`route=respond_style_agent_service_no_send`, `legacy_path_used=false`
everywhere, all no_send, **no outbox attempts, outbox delta 0**,
pending/retry 0, **4 shadow-field rows persisted** (one per
conversation), 0 internal-attention items (no blocked turns this window).

## Operator review — transcript-by-transcript (human score /5)

**flujo_normal — 4.5.** Qualification flows; state accumulates
({seniority:15} → {+income:transferencia}); "qué ocupo" answered with the
EXACT tool-backed document list using the remembered income. This is the
Phase 15 memory paying off in the pipeline function itself.

**requisitos_primero — 4.5.** Early "qué ocupo" answered with the
KB-grounded general list (F20); "dame los papeles primero" pivots
naturally: "Para darte la lista exacta necesito saber tu tipo de ingreso."

**correccion — 3.0, the window's real finding.** The customer corrects
"15 meses → 10 meses". The STATE handles it perfectly (shadow audit:
15 → 10, `corrected_previous_value`) and the next assistant turn
acknowledges "10 meses". But the FINAL turn's copy says "Con 15 meses de
antigüedad..." while the state correctly holds 10 — a **copy/state
divergence**: the model referenced the stale value from an earlier turn
even though the snapshot carried the corrected one. State is right; words
are wrong. Watch-item for the real soak; candidate fix is a prompt line
("when known contact values are present, always restate THOSE values,
never values from older turns") — config/prompt iteration, not
architecture.

**humano — 4.5.** Immediate handoff with visible ack and structured
proposal (`target=ventas`).

Window average: **4.1** (indicative only — 4-conversation window; the
formal quality gate remains the 10-conversation battery with the
two-consecutive-battery rule).

## Readiness verdict for controlled smoke

The PLUMBING is ready: opt-in inbound shadow runs the full future-live
stack end to end with memory, gates, audit and zero side effects, and the
review process (this document) works from harness evidence alone. Before
a real-traffic soak window on the pilot tenant: (1) flip the two flags on
the pilot deployment, (2) let real inbound traffic accumulate evidence,
(3) review with this same format including the copy/state divergence
watch-item, (4) then the controlled smoke decision.

## Decision

`PHASE_16_INBOUND_SHADOW_SOAK_AND_OPERATOR_REVIEW_READY`

No send, no smoke, no canary authorized by this marker.

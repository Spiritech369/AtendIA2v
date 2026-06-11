# Real-Tenant Shadow — Window 3 Review (post F27-ENFORCED/F28/F30/D)

Date: 2026-06-10 · Tenant: 6ad78236 · 17 real inbounds, 18:29–18:31
Version: 6c108993 (gate 12/12 gpt-4o) · Shadow state: started CLEAN (F28)
Decision: **`SHADOW_WINDOW_3_PASSED_READY_FOR_CONFIRMATION_WINDOW`** — avg **4.44/5**

## Hard checks (all 17 turns)

| Check | Result |
|---|---|
| route=respond_style_agent_service_no_send | ✓ 17/17 |
| legacy_path_used=false | ✓ 17/17 |
| send_decision=no_send / send_allowed=false | ✓ 17/17 |
| model | gpt-4o (deployment metadata, bridge-enforced) |
| outbox rows created in window | **0** |
| workflow executions in window | **0** |
| side_effects (delivery/workflows/actions/field_writes-live) | all false |

## Gate scorecard

| Gate condition | Result |
|---|---|
| Average >= 4.2 | **PASSED — 4.44** |
| No critical turn < 4 | ✓ (lowest critical: 4.0; two NON-critical greetings at 3.5) |
| 0 unsupported claims | ✓ (buró deflected via KB; every price/requirement tool-backed) |
| 0 invalid selected_model writes accepted | ✓ (U2: no write; R4: no write; only "Metro" — valid) |
| 0 poisoned state reused | ✓ (window started with 0 shadow rows) |
| 0 mixed correction values | ✓ ("5 años", "transferencia" — clean canonical) |
| 0 media hallucination | ✓ (no invented content for [imagen]/PDF) |
| 0 price/requirements without tool/KB | ✓ |

## The 10 critical cases

1. **noviembre → 5 años (t4–t5): 5.0.** Captured "noviembre", then audit
   `corrected_previous_value: noviembre -> 5 años`; copy says "Con 5 años".
2. **nómina → transferencia (t9): 4.5.** Copy gives the
   estados-de-cuenta nuance via tool; state captured **"transferencia"
   clean** (F30 verified). See finding W3-A for the accent wrinkle.
3. **U2 (t7): 5.0.** "No encontré un modelo llamado 'U2' en nuestro
   catálogo" + alternatives; **no field write** (F27-ENFORCED held).
4. **R4 (t10): 4.0.** No hallucination, no field write; chose handoff to
   an advisor instead of t7's honest not-in-catalog phrasing —
   inconsistent style, safe outcome (W3-C).
5. **[imagen] (t17): 4.0.** No hallucination, no price/product dump. The
   conversation was already in a handoff cascade (customer asked for a
   human at t14), so the reply continued the handoff instead of the media
   ack. Contextually defensible; retest media EARLY in a conversation
   (W3-D).
6. **credencial .pdf (t16): 4.0.** Same handoff-cascade context; no
   hallucination.
7. **buró (t11): 5.0.** KB-grounded deflection + advisor offer. The
   invented-claim class stays closed.
8. **qué motos manejas (t3): 5.0.** Catalog via tool; "Metro es nuestra
   opción más económica" is grounded in catalog price_tier.
9. **requisitos (t12): 5.0.** Exact list via requirements.lookup.
10. **enganche/precio (t13): 4.5.** Quote via tool for Metro (valid,
    state-selected); all numbers tool-backed.

Handoffs (t10, t14–t17): immediate, warm, exact target `ventas`; the
"está caro" objection went to handoff (safe; weaker than the r8o sales
handling — acceptable in a cascade where the customer already asked for
a human). `budget_concern: "caro"` captured with audit.

## Findings (NO fixes applied — review only, per directive)

- **W3-A (next fix round): accent-sensitive allowed_values.** t6 proposed
  income "nómina" (accented); allowed list has "nomina" → runtime
  REJECTED it (`value_not_allowed`) three turns in a row. Safety held and
  t9's correction landed clean, but these are FALSE rejections — the
  canonical matcher needs unicode/diacritic normalization. Cost: state
  lacked income for 3 turns (tools still ran via same-turn provisional
  facts).
- **W3-B (tone, minor):** t1/t4 open with an unprompted "soy un asistente
  digital… ¿quieres un humano?" — the kb-honestidad disclaimer is leaking
  into greetings. Non-critical turns (3.5).
- **W3-C:** unknown-model handling inconsistent (t7 honest answer vs t10
  handoff). Either is safe; pick one in the prompt later.
- **W3-D:** media ack untested outside a handoff cascade — include
  image/PDF EARLY in the confirmation window.

## Decision

`SHADOW_WINDOW_3_PASSED_READY_FOR_CONFIRMATION_WINDOW`

First real-traffic window to clear the full gate. Per the
two-consecutive-windows rule: one more real window >= 4.2 with the same
hard checks (include early media + the W3-A accent case) and the
`PHASE_19_SINGLE_CONTACT_SMOKE_APPROVAL_PACKET` can be assembled.
NO smoke, NO send, NO live until then.

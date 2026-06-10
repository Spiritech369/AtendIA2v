# Real-Tenant Inbound Shadow — Operator Review (window 1)

Date: 2026-06-10 · Tenant: 6ad78236 (real) · Contact: allowlisted test phone
Window: 13 real WhatsApp inbounds, 16:47–17:18 (America/Mexico_City)
Evidence: `turn_traces` rows with `router_trigger=respond_style_inbound_shadow_auto`
Decision: **SHADOW_PLUMBING_PASSED — SMOKE_BLOCKED_BY_QUALITY_WINDOW_3_9**

## Plumbing verdict: PASSED, fully

Every single real inbound (including an image) produced a durable
evidence row automatically via the Baileys pipeline. All 13:
`route=respond_style_agent_service_no_send`, `legacy_path_used=false`,
`send_decision=no_send`, outbox delta 0, side effects 0. Field memory
worked across real turns (income+seniority captured, then reused by
tools). **15B fired in the wild for the first time**: the one blocked
turn raised `handoff_internal_needed / notify_operator=true` — in live,
a human would have been paged instead of dead air.

## Turn-by-turn human score (avg 3.92/5)

| # | Inbound | Score | Note |
|---|---|---|---|
| 1 | PUES CUALES MOTOS TIENES | 5.0 | Grounded catalog via tool — the exact turn legacy silenced |
| 2 | [imagen] | 3.0 | Answered with an unprompted catalog; should ask about the image (media gap, finding D) |
| 3 | hola | 4.5 | Clean greeting |
| 4 | Quiero más información del crédito | 2.5 | SILENT — listed concrete docs without citation; validator blocked correctly after retry; 15B raised operator signal (VALIDATION_CORRECT_BLOCK) |
| 5 | quiero info | 4.5 | Recovered: asks income+seniority naturally |
| 6 | desde noviembre pasado | 4.0 | Correct pivot to income; soft ack of the seniority datum |
| 7 | me pagan por nomina | 4.5 | Plan via tool; fields captured {income: nomina, seniority: noviembre} |
| 8 | que ocupo | 5.0 | Exact docs via requirements.lookup |
| 9 | realmente no me dan nomina solo me transfieren | 3.5 | Copy handles the correction well (generals + "lista exacta se confirma") but **no field proposal — state kept income=nomina** (finding B) |
| 10 | revisan buro? | 2.5 | **"Sí, revisan el buró de crédito" — unsupported claim**: no tool, no KB covers buró; slipped past hard policies (they only gate price/requirements patterns) (finding A) |
| 11 | que motos tienes, tienes catalogo? | 4.5 | Catalog via tool |
| 12 | me interesa la R4 | 4.0 | Honest "la R4 no está en nuestro catálogo" + alternatives — but `selected_model="R4"` was captured into state (finding C) |
| 13 | que ocupo? | 3.5 | Docs correct via tool, but says "para el crédito de la moto R4" — state contaminated by finding C |

## Findings (all config/prompt — zero architecture, zero legacy)

- **A (worst, F25): unsupported business-policy claim.** "Sí, revisan el
  buró" is invented: nothing in tools or KB covers credit-bureau policy.
  Hard policies gate price/requirements only. Fix: tenant config — either
  a KB snippet answering buró/aprobación honestly, or a hard policy
  trigger for approval/eligibility/buró assertions requiring
  kb/tool support. (This is exactly why smoke waits for shadow.)
- **B (F26): corrections must also update state.** The income correction
  (nomina→transferencia) fixed the COPY but produced no field proposal,
  so state kept `income=nomina`. Prompt: when the customer corrects a
  known value, ALWAYS propose the corrected field write (Phase 17 covers
  copy-vs-state; this is the propose-the-write half).
- **C (F27): selected_model must be catalog-grounded.** The model
  honestly said R4 doesn't exist, yet captured `selected_model="R4"`.
  Prompt/config: only capture selected_model with a model_id present in
  catalog tool facts.
- **D: media inbound.** "[imagen]" got an unprompted catalog; should
  acknowledge it can't view images and ask. Prompt line now; real media
  understanding is its own phase.

## Decision

`SHADOW_PLUMBING_PASSED` + `SMOKE_BLOCKED_BY_QUALITY_WINDOW_3_9`

The pipeline is exactly what Phase 19 needs; the quality window (3.92,
1 silence, 1 unsupported claim) is below the 4.2 gate. Path: apply
F25/F26/F27/D (tenant config + prompt lines, new version through the
same publish gates), then a fresh real-traffic window from the
allowlisted phone. Two consecutive windows >= 4.2 with 0 unsupported
claims → assemble `PHASE_19_SINGLE_CONTACT_SMOKE_APPROVAL_PACKET`.

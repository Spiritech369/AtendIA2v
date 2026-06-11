# Respond-Style — Final Confirmation Window (post W6-A/W6-B)

Date: 2026-06-10 · Tenant: 6ad78236 · Version: 0cee95e8 (gpt-4o) ·
Fresh conversation, clean state · 15 scripted turns via run_inbound_shadow
Decision: **`BLOCKED_BY_REFERENT_RESOLUTION`** — avg **4.63**, one
critical silence (t5) caused by a FALSE POSITIVE of the new W6-A check.

## Hard checks

15/15 direct route on version 0cee95e8, legacy_path_used=false, all
no_send, **outbox delta 0**, side effects 0, 0 unsupported claims,
0 invalid writes accepted, 0 media hallucination, **0 wrong-referent
quotes** (the window-6 t13 bug did NOT recur), 0 premature formal
handoffs.

## The critical validations, one by one

| Validation | Result |
|---|---|
| "esa cuanto queda?" resolves Metro, not DNM2.5 | **Neither — SILENT** (see below). The wrong quote is gone; the turn blocked. |
| Unresolvable referent → ask, don't quote | ✗ it should have asked; it went silent instead |
| buró → offer in copy, NO formal handoff | ✅ t6: KB deflection + "puedo conectarte" as a question, no proposal |
| "pasame con alguien" → formal handoff | ✅ t15: HANDOFF → ventas |
| NOMINA/nómina/nomina normalize | ✅ t8: "NOMINA" → state `nomina` |
| "transferencia bancaria no nomina" → clean canonical | ✅ t9: state `transferencia`, audit `corrected_previous_value: nomina -> transferencia` — no blends |
| noviembre → 5 años corrects state | ✅ t10/t11: textbook audit pair |
| Image without caption → no invented catalog | ✅ t12: "Recibí la imagen, pero no puedo verla. ¿Qué muestra?" |
| Requirements/price only with tool/KB | ✅ every list/number tool-backed; generals KB-cited (t7) |

## t5 — the blocker, dissected

"esa cuanto queda?" after t4 discussed la Metro. The model resolved the
referent CORRECTLY (Metro) but proposed `selected_model` as the
canonical id **`metro-city`** — and the W6-A grounding check requires
the proposed value's folded text to appear in the latest exchange.
"metrocity" never appears in "y la metro?" / "La Metro es una moto…",
so `field_value_referent_unverified` fired, the retry re-proposed the
same id, and the turn failed closed (15B raised the operator signal).

So: the window-6 bug (wrong referent quoted) is FIXED; the new check is
over-strict by one notch — it cannot see that `metro-city` and `Metro`
are the same product because `allowed_values` is a flat list with no
alias grouping. Right referent, wrong spelling, safe outcome, silent
customer. Fail-closed in the correct direction, but a critical turn
under 4 (2.5).

## Scores

t1 4.5 · t2 5 · t3 5 · t4 5 · **t5 2.5 (silent)** · t6 5 · t7 4.5 ·
t8 5 · t9 5 · t10 4.5 · t11 5 · t12 5 · t13 4.5 · t14 4.0 · t15 5 →
**4.63/15**

## Proposed fix (W7 — NOT applied; review-only window)

Group product aliases in config: `allowed_values` entries become
groups (e.g. `{"value": "metro-city", "aliases": ["Metro"]}`), the
canonical matcher accepts any alias and stores the canonical value, and
the W6-A grounding check passes when ANY alias of the proposed group
appears in the latest exchange. One config schema extension + the two
matchers; the prompt already lists the vocabulary.

## Decision

`BLOCKED_BY_REFERENT_RESOLUTION`

Average 4.63 with every safety check at zero and 14/15 validations
green. One structural notch left: alias grouping for referent
grounding. After W7 + gate re-run, repeat THIS same 15-message window —
a pass completes the confirmation pair with window 3 →
`PHASE_19_SINGLE_CONTACT_SMOKE_APPROVAL_PACKET`.

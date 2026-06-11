# Respond-Style — Final Confirmation Window (post W6/W7)

Date: 2026-06-10 · Tenant: 6ad78236 · gpt-4o · fresh conversation, clean state
Final run: version 270574ad (W7 alias groups), 15 scripted turns via
run_inbound_shadow (Baileys step 2c hook)
Decision: **`FINAL_CONFIRMATION_WINDOW_PASSED_READY_FOR_PHASE_19_SMOKE_PACKET`**
— avg **4.80/5**, no turn below 4.0, all hard checks at zero.

## History of this window (three runs, honestly)

1. **Run 1 (version 0cee95e8): BLOCKED_BY_REFERENT_RESOLUTION.** t5 went
   silent: the model resolved the referent CORRECTLY (Metro) but proposed
   the canonical id `metro-city`, which never appears verbatim in the
   exchange — the W6-A grounding check false-positived.
2. **W7 (fix): alias groups in allowed_values.** Entries may be
   `{"value": canonical, "aliases": [...]}`; the canonical matcher
   accepts any alias and STORES the canonical; the grounding check passes
   when any alias of the proposed group appears in the latest exchange.
   Generic mechanism; product names live in tenant config. 240 tests.
3. **Run 2 still blocked t5 — and the diagnosis found a HARNESS-CLASS
   bug worth gold:** `_recent_transcript` ordered by `created_at`, which
   is TRANSACTION time in Postgres — all messages inserted in one
   transaction tie, scrambling transcript order (this also explains the
   window-6 harness t13 wrong-referent: its rows all share timestamp
   02:37:25). Real WhatsApp traffic was never affected (one transaction
   per message), but batch processing would be. Fixed in runtime:
   transcript orders by `sent_at` (the message's real, always-distinct
   time) with created_at as tiebreak.
4. **Run 3 (version 270574ad): PASSED.**

## The critical validations — final run

| Validation | Result |
|---|---|
| "esa cuanto queda?" resolves Metro, not DNM2.5 | ✅ **"La Metro tiene un precio de $32,500…"** — quote.resolve for the right product; state captured `metro-city` (canonical, via alias) |
| buró → offer in copy, NO formal handoff | ✅ deflection + "si quieres, puedo conectarte" |
| "pasame con alguien" → formal handoff | ✅ HANDOFF → ventas |
| NOMINA normalizes | ✅ state `nomina` |
| "transferencia bancaria no nomina" → clean canonical | ✅ audit `corrected_previous_value: nomina -> transferencia` |
| noviembre → 5 años corrects state | ✅ textbook audit pair |
| Captionless image → no invented catalog | ✅ "Recibí la imagen, pero no puedo verla…" |
| Requirements/price only with tool/KB | ✅ all tool-backed; generals KB-cited |
| 0 invalid selected_model accepted · 0 outbox · 0 side effects · legacy=false | ✅ 15/15 |

Final shadow state: `{income_type: transferencia, employment_seniority:
"5 años", selected_model: metro-city, budget_concern: caro}` — every
value canonical, every change audited.

## Scores (final run)

t1 4.5 · t2 5 · t3 5 · t4 5 · **t5 5** · t6 5 · t7 4.5 · t8 4.5 · t9 5 ·
t10 4.5 · t11 5 · t12 5 · t13 5 · t14 4.0 · t15 5 → **4.80/15**

## Decision

`FINAL_CONFIRMATION_WINDOW_PASSED_READY_FOR_PHASE_19_SMOKE_PACKET`

With window 3 (4.44) this completes the two-consecutive-windows rule.
Next: assemble the PHASE_19_SINGLE_CONTACT_SMOKE_APPROVAL_PACKET
(evidence bundle, rollback packet, single-contact allowlist plan).
NO smoke, NO send, NO live until that packet is explicitly approved.

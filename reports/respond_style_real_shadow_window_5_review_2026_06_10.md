# Real-Tenant Shadow — Window 5 Review

Date: 2026-06-10 · Tenant: 6ad78236 · 10 real inbounds, 19:54–19:55
Version: 6c108993 + W4 contract fixes · Fields started CLEAN
Decision: **`BLOCKED_BY_SHADOW_QUALITY`** — avg **3.90** (gate 4.2)

## Hard checks — clean again

10/10 direct route, legacy false, no_send, **outbox 0**, side effects 0,
0 unsupported claims, 0 invalid writes ACCEPTED (enforcement held), 0
media hallucination, 0 mixed values IN STATE (state is pristine:
`{income_type: "transferencia", employment_seniority: "5 años"}`).

## W4 fixes under real traffic — split verdict

- **W4-A (latest message outranks state): ✅ WORKS.** t8 "bueno creo que
  si es nomina porque me cae en tarjeta" → copy switches to nómina
  immediately; t7's correction noviembre→5 años is textbook
  (`corrected_previous_value` audit + copy "Con 5 años"). The
  window-4 failure mode did not recur.
- **W4-C announced media: ✅** t2 "te mande una imagen de una moto" →
  perfect cannot-view + ask (5.0).
- **W4-B info-before-handoff: ❌ beaten by the cascade.** t1 "hola quiero
  mas informacion del credito" → handoff punt again; t3 bare [imagen] and
  t5 seniority answer also punted. The prompt line works in clean context
  (validated locally) but loses against a transcript whose recent tail is
  five unresolved "Te conecto con un asesor…" promises.

## Two systemic findings

**W5-A — the model insists on ANNOTATED field values; enforcement
rejects them; capture suffers.** Five rejections in ten turns:
"transferencia bancaria (no nómina)", "transferencia (corriente)",
"nomina (tarjeta)", "transferencia (nomina)". The runtime did exactly
its job (state stayed canonical; t9 finally landed a clean
"transferencia") — but the income field was empty for 3 turns while
the model kept annotating. Substring extraction is NOT safe ("nomina
(tarjeta)" contains two canon candidates). The architectural fix:
validate allowed_values in the TURN VALIDATOR as a RETRYABLE error —
the provider's retry loop then feeds back "use exactly one of: nomina,
transferencia, …" and the model re-proposes canonically IN the same
turn. The post-hoc application check stays as backstop.

**W5-B — handoff-pending limbo is a shadow artifact with no runtime
concept.** In live, a proposed handoff pauses the bot and a human takes
over. In shadow nothing resolves the handoff, so the transcript
accumulates unresolved "te conecto" promises and the model coherently
keeps "connecting" (t1/t3/t5 are cascade continuations, not pure
quality failures). The runtime needs the concept: when a handoff was
recently proposed and no human has joined, the context should say so
explicitly ("handoff already offered; keep helping normally until the
human joins; do not re-handoff unless asked"). That is a context/state
feature, not another prompt plea.

## Scores

t1 2.5 (info punt) · t2 5.0 (media ack) · t3 3.0 (placeholder punt) ·
t4 4.5 (catalog) · t5 3.0 (punt, though seniority captured) · t6 4.0
(plan ✓, annotated value rejected) · t7 5.0 (correction textbook) ·
t8 4.0 (W4-A works; annotated value) · t9 4.0 (clean capture at last) ·
t10 4.0 (plan ✓, hedged copy) → **3.90**

## Decision

`BLOCKED_BY_SHADOW_QUALITY`

Proposed fix round (both architectural, no prompt pleas):
1. **W5-A:** allowed_values validation in RespondStyleTurnValidator as a
   retryable error (in-turn repair via the existing retry loop);
   application-layer enforcement remains as backstop.
2. **W5-B:** handoff-pending awareness in the context package (recent
   unresolved handoff proposal → explicit dynamic-context note; in live,
   this state is where the bot-pause/human-takeover wiring will attach).
Then a fresh window. Window 3 remains the standing pass.

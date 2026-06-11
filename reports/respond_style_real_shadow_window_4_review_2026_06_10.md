# Real-Tenant Shadow — Window 4 (confirmation) Review

Date: 2026-06-10 · Tenant: 6ad78236 · 16 real inbounds, 18:56–18:58
Version: 6c108993 + accent-insensitive allowed_values (runtime)
Decision: **`BLOCKED_BY_SHADOW_QUALITY`** — avg **4.16** (gate 4.2), one
critical turn below 4. Confirmation window NOT passed; window 3's pass
stands but the two-consecutive rule is not met.

## Hard checks — all clean

16/16 direct route, legacy_path_used=false, no_send, **outbox 0 in the
window**, side effects 0, 0 unsupported claims, 0 invalid model writes,
0 mixed correction values, 0 media hallucination. The safety layer is
not the problem.

## What went WELL (several firsts)

- **t4 — media exactly as prescribed (5.0):** "te mande una foto aver si
  esa manejan" → *"Recibí la imagen, pero no puedo verla. Si me dices qué
  modelo es, puedo verificar si lo manejamos."* W3-D closed for announced
  media.
- **t16 — R4 consistency (5.0):** *"No tengo información sobre la R4 en
  el catálogo actual"* + alternatives, zero field write. W3-C closed.
- **t13 — full quote tool-backed for Metro (5.0)**; t14/t15 — buró and
  "debo como 20 mil" handled with KB deflection + advisor, no promises
  (5.0/4.5); t10 — "no se si sea nomina, me transfiere el patron nomas"
  handled with the right plan and canonical state (4.5); t12 — direct
  "Sí, calificas" tool-backed (4.5).
- Customer-grade orthography throughout ("q onda", "aver", "resibos",
  "jalando") never broke capture or grounding.

## What BLOCKED the window

**W4-A (the finding, critical): stored state overrides the customer's
NEW statement.** t8: customer says "me pagan por nomina" — the model
replies *"Para un crédito con ingresos por transferencia..."* and
re-proposes `transferencia`, ignoring what the customer JUST said
(state had transferencia from window 3's correction). t7 same shape:
"tengo desde noviembre jalando" → keeps "5 años", no acknowledgment,
hands off. The Phase-17 rule ("current state wins over the transcript")
is being over-applied to the customer's LATEST message. The correct
contract: state wins over OLD transcript; the customer's newest
statement wins over state — capture it as a correction or ASK to
disambiguate ("antes me dijiste que te transfieren sin recibos — ¿tienes
recibos de nómina entonces?"). Never assert stored state against the
customer's fresh words. t8 scored 3.0 → critical correction case < 4.

**W4-B: handoff-cascade momentum.** t1/t2 greetings ("Quiero más
información del credito", "q onda busco info") → instant handoffs with
no info attempt. The transcript carried window 3's five-handoff tail, so
the model kept connecting. A fresh info request should re-engage; offer
the human as an option, not as the answer. (3.0/3.0, non-critical class.)

**W4-C: raw media placeholder inconsistent.** t4 (announced photo)
perfect; t5 (bare "[imagen]") fell back to a generic identity+handoff
line — no hallucination, but not the media ack (3.5).

Note on state carryover: window 4 reused window 3's state
(transferencia/Metro/5 años). That is NOT poison — it was captured under
current validation rules in the same conversation; it is the field
memory working. The accent fix (W3-A) went unexercised: the model
proposed canonical values throughout — which is the fix's intended
steady state.

## Scores

t1 3.0 · t2 3.0 · t3 4.5 · t4 5.0 · t5 3.5 · t6 4.5 · t7 3.0 · t8 3.0 ·
t9 4.5 · t10 4.5 · t11 4.0 · t12 4.5 · t13 5.0 · t14 5.0 · t15 4.5 ·
t16 5.0 → **4.16/16**

## Decision

`BLOCKED_BY_SHADOW_QUALITY`

Fix round (small, prompt-contract): (1) W4-A — "the customer's latest
message outranks stored state: contradictions are corrections to capture
or clarify, never assert stored values against fresh words"; (2) W4-B —
"an information request gets information (or qualification); offer a
human as an option, not as the answer, unless the customer asks for one";
(3) W4-C — extend the media ack to bare placeholders. Then a fresh
confirmation window (consider a NEW conversation/clean state for an
uncascaded read). Window 3 remains the first pass; the next window >=4.2
completes the pair → PHASE_19 packet.

# Manual Simulator — Human Review of 10 Conversations (no-send)

Date: 2026-06-09
Gate: `MANUAL_SIMULATOR_HUMAN_REVIEW_FAILED`
Config: `tools/configs/manual_review_moto_credit_config.json` (tenant DATA file —
moto-credit flavored config passed via `--config`; runtime code stays
tenant-neutral). Model: gpt-4o-mini via the direct route, 3-round budgeted
tool loop, DryFacts executor.
Evidence: `reports/manual_live_simulator_run_*_conv01..conv10.{json,md}`

## Gate conditions

| Condition | Result |
|---|---|
| 10 manual conversations | ✓ 10/10 ran, 71 turns total |
| 0 internal leaks | ✓ zero (marker scan + read-through) |
| 0 invented prices/requirements | ✓ every number/list traces to a succeeded tool (enganche 30% ← credit_plan.resolve; $32,500/$9,750/$689 ← quote.resolve; papeles ← requirements.lookup). Hard policies actively blocked 3 unsupported requirement claims. |
| 0 legacy copy | ✓ zero canned legacy phrases |
| 0 "si tienes otra consulta" closers | ✗ 1 (conv04: "Si tienes alguna otra pregunta o necesitas más información, ¡dímelo!") |
| 0 outbox / 0 side effects | ✓ all reports: outbox=0, side_effects all false |
| Average human score >= 4.2/5 | ✗ **2.7/5** |
| No critical turn < 4 | ✗ multiple (see below) |

**15 of 71 turns (21%) produced NO visible message.** In live those are a
customer left on read. That alone fails the gate.

## Per-conversation scores (human /5)

| # | Conversation | Score | Verdict in one line |
|---|---|---|---|
| 1 | flujo normal | 2.5 | Great start, then DIES at the hottest moment: "qué ocupo para avanzar" and "cuánto doy de enganche?" got **silence with blocked=None** |
| 2 | caótico | 3.0 | First compound ask → silence; decent recovery; objection handled form-ishly |
| 3 | requisitos primero | 2.5 | Customer asked papeles 2× → silence 2×; answered only at turn 6 |
| 4 | comerciante ambiguo | 3.0 | Natural qualification, good papeles; generic closer; final "cuánto tendría que dar" → silence (income never captured from "vendo comida desde mi casa") |
| 5 | comerciante SAT | 2.5 | Asked income type 3× in a row; SAT answer sidestepped; "metro" never became selected_model (proposed in a blocked turn, so lost); 2 silences |
| 6 | objeción precio | 3.0 | Solid until the objection: "está muy caro" / "hay una más barata?" → 2 silences (asked fail-closed for a model instead of offering catalog options) |
| 7 | frustrado | 2.0 | "qué ocupo" → silence; **"eres robot?" answered by repeating the SAT question verbatim** — worst turn of the batch (KB even has the honesty snippet) |
| 8 | cambio de datos | 2.0 | Seniority correction OK; income correction IGNORED: customer said "realmente por transferencia sin recibos" and the agent wrote income_type="nómina" and contradicted itself next turn |
| 9 | modelo ambiguo | 2.5 | "la roja del anuncio" never matched against catalog colors (catalog HAS rojo); SAT question injected without need; "qué opciones hay" → silence with catalog.search succeeded |
| 10 | handoff | 4.0 | Best of the batch: natural qualification, real quote from tools, honest handoff + structured proposal. Deductions: "qué ocupo" answered with a price repeat; final message repeated verbatim |

Average: **2.7/5**.

## What the 10 criteria say overall

1. **¿Suena humano?** Opening/qualifying turns yes (4-5); degradation via verbatim repetition (conv01,06,07,09,10) and silence.
2. **¿Responde primero lo que pregunté?** Often no: requisitos answered with plan info, "qué ocupo" with price, "eres robot?" with SAT.
3. **¿Usa tools para precio/requisitos?** YES — flawless. Zero unsupported numbers; hard policies blocked the 3 attempts.
4. **¿No inventa?** Correct. The fail-closed machinery works perfectly.
5. **¿No suena a formulario?** Mixed: income-type menu question repeated up to 3× (conv05, conv08) is form-like.
6. **¿No pide datos que ya tiene?** Fails: conv05 (income asked 3×), conv07 (SAT 2×), conv08 (income re-asked after answer).
7. **¿Estado avanza bien?** Partially: captures with quoted evidence work; BUT proposals from blocked turns are lost ("metro" conv05), and a correction was overwritten wrong (conv08).
8. **¿no_send reason tiene sentido?** When present, yes (missing_precondition / hard_policy). **4 turns had NO message AND blocked=None** — a real runtime defect (see F4).
9. **¿Handoff natural?** Yes (conv10) — message + structured proposal, honest tone.
10. **¿Digno de WhatsApp?** conv10 mostly yes; the rest no — silence and repetition are disqualifying.

## Root causes (ranked, with the fix — no big architecture)

- **F4 (runtime defect, fix in tool loop):** a turn can end as a valid
  `tool_request` with all tools already satisfied → after the single nudge,
  the loop returns final_message=None with NO blocked reason (conv01 t7-t8,
  conv09 t7-t8). Fix: if the post-nudge decision still has no
  final_message, **block with structured reason**
  `no_final_response_after_tools` (never silent-valid), and make the
  post-tools provider call explicitly demand final_response.
- **F5 (loop behavior):** required tool skipped on `missing_precondition`
  hard-blocks the turn (11 silences). The model should be retried ONCE with
  feedback "ask for the missing precondition naturally instead of calling
  the tool" — converting silence into the natural question the prompt
  already mandates.
- **F6 (prompt):** corrections must win: "when the customer corrects a
  value, propose the corrected value and never restate the old one"
  (conv08).
- **F7 (prompt):** direct questions about the assistant get answered first
  and honestly (conv07 robot); never re-ask a question already answered
  this conversation (conv05/07/08); never repeat the previous message
  verbatim — advance or rephrase (5 conversations).
- **F8 (channel):** field proposals from blocked turns are discarded —
  consider capturing validated field proposals even when the turn blocks,
  so "metro"/"comerciante" survive into the next turn's state.
- **F9 (prompt, minor):** the generic availability closer slipped once
  despite the instruction (conv04).

## Decision

`MANUAL_SIMULATOR_HUMAN_REVIEW_FAILED`

Per the gate: NO AgentService integration, NO smoke. Next step is fixing
F4-F9 (tool-loop behavior + prompt adjustments, no new architecture) and
re-running these same 10 conversations until the gate passes.

The safety half of the system is production-grade: zero invented facts,
zero leaks, zero legacy copy, zero side effects across 71 adversarial
turns. The conversation half is not yet WhatsApp-worthy: 21% of turns are
silence and repetition breaks the human feel. The simulator did exactly
its job: these defects were caught for free instead of on a real customer.

---

# Round 2 — after F4-F9 fixes (2026-06-10)

Fixes applied: F4 (silent-valid escape now blocks with
`no_final_response_after_tools`), F5 (missing-precondition skip retries
once into a natural question), F6/F7/F9 (prompt: corrections win, answer
direct questions about the assistant, never repeat verbatim, never re-ask
known values), F8 (validated field proposals survive blocked turns).
Suite: 176 passing (3 new tests), ruff clean. Same 10 conversations re-run.

## Delta

| Metric | Round 1 | Round 2 |
|---|---|---|
| Turns answered | 56/71 (79%) | **63/71 (89%)** |
| Silent with NO reason (bug) | 4 | **0** |
| Blocked (structured reason) | 11 | 8 |
| Average human score | 2.7/5 | **3.0/5** |

Conversation scores R1→R2: c01 2.5→4.0 (full flow, exact enganche from
quote.resolve), c02 3.0→3.5 (compound ask now gets a natural question —
F5 working), c03 2.5→2.5, c04 3.0→3.5 (income finally captured from
"vendo comida"), c05 2.5→3.0 (SAT captured, all turns answered), c06
3.0→2.5 (same paragraph 3×), c07 2.0→2.5 (everything answered BUT "eres
robot?" still deflected), c08 2.0→2.0 (income correction still ignored),
c09 2.5→2.0 (catalog dead-end 3×), c10 4.0→4.0.

## Gate: still `MANUAL_SIMULATOR_HUMAN_REVIEW_FAILED` (3.0 < 4.2)

Remaining defects, in order of damage:

- **F10 — catalog dead-end (5 of 8 blocks):** after `catalog.search`
  succeeds, gpt-4o-mini keeps emitting tool_request instead of writing the
  options, exhausting the nudge → `no_final_response_after_tools`
  (conv09 ×3, conv03, conv06). The structural cause is the known provider
  weakness: the whole context rides as one JSON blob in a single user
  message, so loop feedback gets drowned. Fix prescription: render the
  context as structured prompt sections with the transcript as real chat
  messages (the provider upgrade already flagged in the original
  architecture review), and/or strip tool proposals on the final forced
  attempt.
- **F11 — answers the wrong sub-question:** "cuánto tendría que dar" →
  document list; "qué ocupo" → price repeat (c01, c04, c10). Prompt
  ordering pressure; likely improves with structured prompting.
- **F12 — "eres robot?" still deflected** despite the new prompt line and
  the KB honesty snippet (c07). Same root as F10: instructions buried.
- **F13 — income correction still loses** ("realmente por transferencia
  sin recibos" → keeps nómina, c08).
- Repetition pressure persists when the customer stalls (c02, c06).

## Conclusion

The structural/runtime half is now clean: zero unexplained silences, zero
invented facts, zero leaks, zero side effects, natural asks on missing
preconditions, corrections of state captured with evidence. What remains
is conversation quality bounded by the provider's prompt rendering and the
small model. Next iteration is F10 (structured prompt rendering in
RespondStyleLLMTurnProvider) — a contained provider change, not new
architecture — then re-run this same battery. No AgentService, no smoke
until this gate passes.

---

# Round 3 — after F10 structured prompt rendering (2026-06-10)

F10 applied: `build_respond_style_messages` now renders a structured system
prompt (platform contract + agent config + capabilities + field policy
sections), the transcript as REAL chat turns, a dynamic-context system
message (known values "do NOT ask again", missing fields, KB with source
ids, THIS-turn tool results, prominent feedback with error codes), and the
inbound as the final user message — replacing the single JSON blob.
Suite: 176 passing, ruff clean. Same 10 conversations re-run.

## Delta

| Metric | R1 | R2 | R3 |
|---|---|---|---|
| Turns answered | 56/71 | 63/71 | **63/71** |
| Catalog dead-ends (F10) | — | 5 | **0** |
| Average human score | 2.7 | 3.0 | **3.65** |

Scores R2→R3: c01 4.0→**4.5** (every question gets the RIGHT answer:
papeles→requirements, enganche→exact quote; DNM2.5 grounded in catalog
colors), c02 3.5→3.0, c03 2.5→3.5, c04 3.5→3.5, c05 3.0→3.5 (SAT→20%
correctly, Metro captured, exact quote), c06 2.5→3.5 ("cuánto me queda"
now ASKS for the model naturally), c07 2.5→**3.5** ("eres robot?" →
"Sí, soy un asistente digital... ¿te paso con un asesor humano?" — F12
FIXED), c08 2.0→**4.0** (BOTH corrections now win, including
"realmente por transferencia" — F13 FIXED), c09 2.0→**4.5** ("la roja del
anuncio" matched against catalog colors offering both red models — F10
showcase), c10 4.0→3.0 (regression at the handoff moment, see F15/F16).

## Gate: still short — 3.65 < 4.2 (but the trend is 2.7 → 3.0 → 3.65)

Safety intact in round 3: 0 invented facts, 0 leaks, 0 outbox, 0 side
effects; hard policies blocked 4 unsupported claims correctly.

Remaining defects (narrow, specific):

- **F14:** when a required tool skips on missing_precondition, the F5
  retry fires but the model sometimes RE-proposes the same tool →
  hard block (conv02 t2, conv04 t7). Fix: on the F5 retry, ignore/strip
  new tool proposals — force a final_response that asks for the missing
  detail.
- **F15:** `handoff_request` turns may carry no visible message (valid by
  contract) → the customer asking "me puedes pasar con alguien?" gets
  structured handoff but SILENCE (conv10 t8). Fix: when handoff is
  accepted without a message, nudge once for a short visible ack
  (config declares customer_message_authored_by_llm).
- **F16:** model proposed a workflow event with an invented binding name →
  retryable block consumed the turn (conv10 t7). Binding names are now
  rendered; reinforce "only these exact binding names".
- Handoff offered as deflection 3× in conv02 instead of helping with
  catalog options; occasional verbatim repeat (conv05 final turn).

## Conclusion

F10 delivered exactly what it targeted: catalog dead-ends 5→0, robot
honesty fixed, corrections win, grounded model disambiguation by color.
Remaining work is three contained loop/prompt adjustments (F14-F16), then
another battery run. Still NO AgentService and NO smoke until >= 4.2.

---

# Round 4 — after F14/F15/F16 (2026-06-10)

F14: a visible reply with un-run required tool proposals now KEEPS the
message and drops the proposals (trace records `dropped_tool_requests`);
the F5 retry no longer re-executes tools. F15: a valid-but-silent handoff
gets ONE nudge for an LLM-authored visible ack (never synthetic copy; if
the nudge fails the silent handoff stands). F16: workflow binding names
rendered as exact-values-only; handoff instructions clarified
(handoff_proposal, not workflow events, with a visible message).
Suite: 179 passing (3 new tests; 1 legacy test updated to the amended
F14 semantics), ruff clean.

## Delta

| Metric | R1 | R2 | R3 | R4 |
|---|---|---|---|---|
| Turns answered | 56/71 | 63/71 | 63/71 | **65/71** |
| Silent handoffs | — | — | 1 | **0** |
| Average human score | 2.7 | 3.0 | 3.65 | **3.95** |

Highlights: conv02's chaotic FIRST message now gets a full useful answer
(papeles + natural asks — F14 showcase, was silence in R1-R3); conv04
"cuánto tendría que dar" now asks for the model naturally (4.5); conv07
frustrated flow is now complete including honest robot answer + handoff
offer (4.5); conv08 corrections perfect (4.5); conv10 handoff now has a
warm visible ack ("Claro, te conectaré con un asesor humano...").

Scores: c01 4.5, c02 3.5, c03 3.5, c04 4.5, c05 3.5, c06 3.0, c07 4.5,
c08 4.5, c09 3.5, c10 4.0 → **3.95**.

## Gate: still short — 3.95 < 4.2

Safety intact: 0 invented facts, 0 leaks, 0 outbox, 0 side effects.
6 remaining silences, with two roots:

- **(a) model insists tool-only after the F5 retry** (conv03 "pero dime
  los papeles primero", conv06 "cuánto me queda", conv09 "qué opciones
  hay"): correct fail-closed, but gpt-4o-mini ignores the explicit "do NOT
  include tool_requests" feedback under pressure.
- **(b) hard-policy blocks on benign mentions** (conv05 t2, conv06 t8):
  the model writes "requisitos"/price-adjacent words without the
  supporting tool in that turn.
- **F17 (trivial):** conv10 handoff target invalid once
  (`handoff_target_not_allowed`) — render handoff targets as
  exact-values-only like binding names.

## Recommendation

The structural machinery is done — every remaining failure is the small
model ignoring explicit instructions under pressure. Two moves left,
in order of leverage:

1. **Run round 5 with a stronger model** (config change only:
   `RespondStyleLLMTurnProviderConfig(model="gpt-4o")` — the provider is
   already model-configurable). Expected to clear both remaining roots.
2. F17 exact handoff targets (one render line).

Still NO AgentService and NO smoke until >= 4.2.

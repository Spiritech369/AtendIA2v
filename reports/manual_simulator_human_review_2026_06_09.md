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

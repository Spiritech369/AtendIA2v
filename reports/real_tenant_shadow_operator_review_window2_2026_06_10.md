# Real-Tenant Inbound Shadow — Operator Review (window 2)

Date: 2026-06-10 · Tenant: 6ad78236 · 13 real inbounds, 17:43–17:45
Version under test: e40f1506 (F25/F26/F27/D + gpt-4o per deployment)
Decision: **SMOKE_BLOCKED_BY_POISONED_STATE_AND_F27_ENFORCEMENT — window avg 3.42**

## Fix verdicts (the point of this window)

| Fix | Verdict | Evidence |
|---|---|---|
| **F25 buró** | ✅ **WORKS** | "y si estoy en buro?" → "Puedo conectarte con un asesor humano para que te confirme los detalles..." + HANDOFF→ventas proposed. The invented "Sí, revisan el buró" is gone. Best turn of the window (5.0). |
| **F26 corrections→state** | ✅ mechanically / ⚠ value hygiene | Two corrections captured with audit (noviembre→"5 años"; nomina→…). But the income correction wrote **"nomina (transferencia)"** — a mangled blend, not the clean new value (finding F30). |
| **F27 catalog-grounded captures** | ❌ **prompt alone is INSUFFICIENT** | "es la mas economica?" answered honestly ("la U2 no está en nuestro catálogo") yet the SAME turn captured `selected_model="U2"`. The model says one thing and proposes another — this must be ENFORCED in the field-application layer, not requested in the prompt. |
| **D media** | ❌ not honored | "[imagen]" got a U2 quote + buró follow-up instead of "no puedo ver la imagen, ¿qué muestra?". "credencial .pdf" got a catalog dump. |

## The dominant root cause: poisoned persistent state

Window 1 captured `selected_model="R4"` BEFORE F27 existed. That value
survived in `respond_style_shadow_fields` and drove window 2's worst
behavior: "hola" → unsolicited **quote for the nonexistent R4 at
$32,500** (quote.resolve ran because its precondition selected_model was
"satisfied" by the poison; dry facts are static per-model). Then turn 11
captured "U2" (the F27 leak) and turn 13 quoted **the U2**. Three of the
four worst turns trace to state poisoning, not to this version's
conversation quality.

## Turn-by-turn (avg 3.42/5)

t1 hola → R4 quote out of nowhere **2.0** · t2 quiero info → same quote
**2.5** · t3 qué motos manejas → catalog **4.5** · t4 5 años → correction
captured ✓, but asserts stale "nómina" + unsolicited catalog **3.5** ·
t5 por transferencia → plan via tool, mangled correction value **3.5** ·
t6 catalogo? → clean **4.5** · t7 credencial .pdf → ignored the document
**2.5** · t8 ok → another catalog dump **3.0** · t9 nómina por correo →
good nuance (estados de cuenta válidos) via tool **4.0** · t10 U2 →
catalog, doesn't flag unknown model yet **3.5** · t11 es la más
económica? → honest Metro + "U2 no está en catálogo", but captures U2
**4.0** · t12 y si estoy en buro? → KB deflection + handoff **5.0** ·
t13 [imagen] → U2 quote **2.0**

Safety: 0 unsupported business claims (the buró class is closed), all
prices tool-backed (against poisoned model identity — the harness's
static dry facts cannot 404 an unknown model the way real tools will),
0 outbox, 0 side effects, followups raised where due.

## Required before window 3

1. **F27-ENFORCED (runtime, generic):** field policies gain optional
   `allowed_values`; `apply_field_proposals` REJECTS values outside it
   (audit reason `value_not_allowed`). Moto config: `selected_model`
   allowed_values = the catalog model names (data). The prompt line
   stays; the enforcement makes it irrelevant whether the model obeys.
2. **F28: state hygiene on re-arm.** Setup tool resets
   `respond_style_shadow_fields` for allowlisted conversations when
   pointing the deployment at a new version — captured fields predating
   current validation rules are not trustworthy. Plus immediate cleanup
   of the poisoned row (R4/U2/"nomina (transferencia)").
3. **F30 (prompt):** a corrected field value must be ONLY the clean new
   value, never a blend of old and new.
4. **D-retry:** keep the media line; re-verify in window 3 once state is
   clean (t13's media miss had heavy competing context from the poison).

## Decision

`SMOKE_BLOCKED_BY_POISONED_STATE_AND_F27_ENFORCEMENT`

F25 is closed and F26 works. The window's failures concentrate on state
poisoning (pre-fix captures) and on F27 needing enforcement instead of
politeness. After fixes 1–3 + state cleanup + re-arm through the gate:
window 3. Two consecutive windows >= 4.2 with 0 unsupported claims →
PHASE_19 packet.

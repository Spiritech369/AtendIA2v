# Sandbox & Debug Roadmap — Design (W2, K1, P2, A3, A4)

> **Fecha:** 2026-05-15 · **Estado:** diseño aprobado, pendiente de implementación
> **Origen:** brainstorming tras cerrar Wave 1 parte 2 (merge `13e2554`).
> **Contrato:** una pieza por sesión, TDD RED→GREEN, verificado en CLI/browser,
> cortes de scope explícitos (ver `docs/ESTADO-Y-GAPS.md` §11).

## 0. Tesis y decisiones tomadas

Los 5 ítems 🔴 más pesados del roadmap (≈5-6 semanas). Decisiones del brainstorm:

- **Esta sesión = solo este doc + plan de implementación.** Cero código de feature.
- **Orden (cada pieza = su propia sesión/worktree):**
  `harness → A4 → A3 → P2 → W2 → K1`.
- **A4/A3 llaman al LLM real**, con estimación de costo previa y **tope
  configurable confirmable** (cortar si excede).
- **W2 = step-through post-hoc** sobre ejecuciones ya corridas (sin motor
  pausable; reusa `/executions/{id}/replay`).
- **K1 = corte YAGNI**: construir 3 crons de alto impacto, diferir 2.

Sinergia clave: **P2, A3, A4 comparten un harness de ejecución sin
side-effects**. W2 y K1 son independientes.

---

## 1. Pieza 0 — Sandbox harness (fundación)

**Módulo nuevo** `core/atendia/sandbox/` (librería, sin rutas propias).

- `SandboxContext`: overrides opcionales de prompt/agent_patch, `cost_cap_usd`,
  `run_id`.
- `SandboxResult`: por turno → NLU output, composer output, KB evidence,
  flow_mode, outbound *que se habría enviado*, tokens, `cost_usd`,
  `latency_ms`; + totales de la corrida.

**Aislamiento de side-effects en dos capas (defensa en profundidad):**

1. **Stubs de transporte**: implementaciones no-op de la cola outbound (sin
   `arq` enqueue), el adapter WhatsApp (Meta/Baileys — sin send) y el
   publisher realtime (sin Redis/WS). El outbound se *captura*.
2. **Transacción revertida**: toda la corrida en un `AsyncSession` con
   `rollback()` garantizado (try/finally). Aunque algo escape los stubs
   (turn_traces, field_suggestions, state, messages), nada persiste. Los
   **reads** sí golpean data real del tenant (catálogo, FAQs, pipeline,
   agente) → alta fidelidad.

**Guarda de costo**: acumulador `cost_usd`; el servicio estima
`N × turnos_prom × ~$/turno` desde `turn_traces` históricos y lo devuelve
para confirmación; exceder el tope a mitad de corrida aborta limpio con
resultados parciales.

**Reusa el `ConversationRunner` real** sin fork de lógica (solo acepta los
puertos inyectados + override opcional de prompt/agent) → salida sandbox ==
comportamiento producción.

**Test (crítico de seguridad):** invariante *cero side-effects* — una
corrida asserta **0 filas nuevas** en messages/turn_traces/field_suggestions/
conversation_state, que los stubs recibieron el would-be send, y que
`SandboxResult` trae composer output + costo.

Costo estimado: ~3-4d.

---

## 2. A4 — Sandbox replay

`POST /api/v1/agents/{id}/sandbox-replay/estimate` → `{estimated_cost_usd, n_turns}`.
`POST /api/v1/agents/{id}/sandbox-replay` body
`{ prompt_override?, agent_patch?, source: {last_n} | {conversation_ids}, confirm_cost_usd }`
(el run exige eco de `confirm_cost_usd` ≥ estimado).

Servicio: selecciona últimas N conversaciones (tenant-scoped, por
last_activity desc) o ids dados; por cada una toma su secuencia de mensajes
inbound ordenada y la corre por el harness con el prompt/config override;
devuelve por conversación
`{conversation_id, turns:[{inbound, historical_outbound (de messages), sandbox_outbound, changed, cost}]}`
+ totales.

Frontend: sub-tab "Sandbox Replay" en el Operations Center del agente —
elegir N/filtro, ver histórico vs prompt-nuevo lado a lado por turno con
diff highlight + costo total. Read-only, nada se persiste.

Costo estimado: ~3-4d.

---

## 3. A3 — A/B test de prompt variants

`POST /api/v1/agents/{id}/ab-test` body
`{ variant_a:{prompt?,patch?}, variant_b:{prompt?,patch?}, inputs:{conversation_id}|{messages:[str]}, confirm_cost_usd }`.

Corre inputs idénticos por el harness **dos veces** (A y B) → es el *loop de
replay de A4 ejecutado dos veces con distinta config*. Devuelve outputs
pareados por turno + costo/latencia por variante.

Frontend: reusa el patrón compare-mode existente del agente — dos columnas,
A vs B por turno, divergencia resaltada.

Implementación: extraer el core de replay de A4 reutilizable → A3 queda
delgado. Costo estimado: ~2-3d (depende de A4).

---

## 4. P2 — Pipeline test mode

`POST /api/v1/pipeline/test-run` body
`{ script:[str], pipeline_version?, seed_attrs? }`.

Crea un customer+conversation **sintético efímero dentro de la txn revertida
del sandbox** (nunca persiste), corre el script por el router + state machine
+ composer reales; devuelve por paso
`{inbound, stage_before, stage_after, flow_mode, bot_reply, extracted_fields, rules_evaluated}`.

Frontend: panel "Modo prueba" en PipelineEditor — escribir/seed un script,
correr, ver la conversación con transiciones de stage visualizadas sobre el
kanban/stage-list existente (reusa la forma `rules_evaluated` que ya muestra
el DebugPanel).

Costo estimado: ~3-4d.

---

## 5. W2 — Workflow step-through (post-hoc, sin cambios de motor)

Backend: enriquecer el existente `GET /api/v1/executions/{id}/replay`
(`_execution_replay`) para incluir por paso
`{node_id, node_type, entered_at, variables_snapshot, config, output, status}`.

Frontend: panel stepper en `ExecutionsPanel` de WorkflowsPage — prev/next
sobre los pasos del replay, **resaltar el nodo actual sobre el canvas visual
existente** (canvas + node ids ya existen), mostrar variables/payload por
paso.

Independiente del harness (opera sobre ejecuciones ya grabadas).
Costo estimado: ~1-1.5w.

---

## 6. K1 — Workers cron (corte YAGNI)

5 sub-workers listados; **construir 3 de alto impacto, diferir 2.**

**Construir** (arq cron en `WorkerSettings.cron_jobs`, espejo del probado
`poll_followups`/`poll_appointment_reminders`: `SELECT … FOR UPDATE SKIP
LOCKED`, flag de idempotencia, `LIMIT` por tick, evento de audit):

1. **catalog-expiry** — catálogo stale → cotizaciones mal. Impacto directo.
2. **kb-health-snapshots** — alimenta la UI de health-history (ya existe,
   hoy delgada).
3. **conflicts-detector** — `kb_conflicts` ya tiene UI real (Sprint B.3
   `db4fb8c`); este la mantiene fresca.

**Diferir** (ítems propios futuros, infra alta / valor inmediato bajo):

- KB regression-test cron — requiere un golden-set harness (sizeable).
- KB import worker — feature distinta, no "completar cron".

Costo estimado: ~3-4d (los 3 del corte).

---

## 7. Cross-cutting

- **Testing**: cada pieza TDD RED→GREEN. El harness lleva el test invariante
  *cero side-effects* (crítico). Backend pytest contra dev DB real (puerto
  5433, copiar `core/.env` al worktree), frontend vitest. Espejo de Wave 1.2.
- **Contrato**: 6 sesiones/worktrees separadas, cada una su branch, verificada
  en CLI/browser, cortes de scope explícitos, sin claims verdes sin verificar.
  Una pieza por sesión.
- **Secuencia y costo**: harness 3-4d · A4 3-4d · A3 2-3d · P2 3-4d ·
  W2 1-1.5w · K1 3-4d ≈ **~5 semanas / 6 sesiones**. Cada sesión futura:
  "cargar el plan, ejecutar una pieza".
- **Riesgo agudo**: la garantía no-side-effects del harness — mitigada por
  el aislamiento de dos capas (stubs + rollback) + el test invariante.

## 8. Próximo paso

`writing-plans` para la **pieza 0 (harness)** en pasos bite-sized (es la
fundación; A4/A3/P2 dependen de ella). Las piezas siguientes generan su
propio plan al inicio de su sesión.

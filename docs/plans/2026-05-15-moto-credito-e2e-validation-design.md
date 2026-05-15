# Validación E2E Moto-Crédito — Design

> **Fecha:** 2026-05-15 · **Estado:** diseño aprobado por el usuario, pendiente plan ejecutable
> **Origen:** el usuario pidió validar su caso real (Dínamo moto-crédito) end-to-end a
> través de los 5 subsistemas, cargando su `docs/Prompt master.txt` **vía el frontend**
> (no SQL directo), con score + bugs + comparación vs Respond.io.
> **Contrato:** heredado de `docs/ESTADO-Y-GAPS.md §11` (post trust-break 2026-05-08):
> "funciona" = verificado en browser/CLI con evidencia; si se recorta scope se dice
> explícito; bugs se reportan, no se tapan; sin emojis verdes sin verificar; una pieza
> por sesión.

## 0. Decisiones tomadas (vía AskUserQuestion)

- **Vía de prueba = Híbrido:** configuración por los **mismos endpoints REST que usa el
  frontend** (`POST /auth/login`, `POST /agents`, `PUT /tenants/pipeline`, `POST /kb/*`,
  `POST /workflows`, `POST /agents/{id}/preview-response`) + **verificación en navegador
  real** (SPA + backend arriba; abrir Conversaciones/Agente IA y mostrar que aparece y se
  afina desde la UI) + **harness sandbox** (runner real, LLM real, cero side-effects) para
  comportamiento.
- **Alcance de ESTA sesión = Moto-crédito E2E.** El caso general / multi-nicho se difiere
  a la sesión siguiente.

## 1. Objetivo

Validar honestamente el caso moto-crédito de Dínamo a través de **Agente IA, Conocimiento
(KB), Pipelines, Conversaciones y Workflows**, más el **orden lógico del flujo**
mensaje→proceso→envío. Entregable: un **scorecard** por subsistema (score 0-10 con
evidencia, bugs con `file:line` + repro, cómo mejorar, y "vs Respond.io: mejor / igual /
detrás") + una recomendación premium-SaaS.

## 2. Infra y aislamiento

- Stack arriba: backend `:8001`, frontend vite `:5173`, Postgres `:5433`, Redis `:6380`.
  (Trampa conocida: Docker monta el `core/` del **main checkout**; trabajar ahí.)
- **Tenant fresco aislado** (`dele.zored@hotmail.com` / `dinamo123`, superadmin, tenant
  sin seed) para no contaminar data y poder limpiar.
- Presupuesto LLM: ~$0.30–0.60 estimado (turnos reales ~$0.003–0.01 c/u); **cap duro por
  corrida**, acumulado reportado, nunca exceder **$1.53**.

## 3. Fases (cada una deja evidencia concreta)

| # | Fase | Qué prueba | Evidencia |
|---|---|---|---|
| 0 | Stack + login | `POST /auth/login`, SPA carga, tenant fresco usable | screenshot login |
| 1 | **Orden del flujo** msg→proceso→envío | Traza ordenada real (`meta_routes`→`run_turn`→pipeline/agent load→Vision/NLU→extracción→`flow_router`→composer→handoff→outbound→turn_trace→followups) con `file:line`; detectar bugs de orden | doc de flujo + 1 corrida harness |
| 2 | **Agente IA** (Prompt master) | `POST /agents` con `system_prompt`=Prompt master + mapear su `#FLOW ROUTER LOGIC` a `flow_mode_rules` (gap detectado: sin reglas, todo cae en SUPPORT) + `knowledge_config`; verificar en browser que aparece/edita; `POST /agents/{id}/preview-response` (path de prueba propio del producto) real | screenshot + respuesta LLM real |
| 3 | **Conocimiento (KB)** | Ingerir `CATALOGO_MODELOS.json`, `FAQ_CREDITO.json`, `REQUISITOS_PLANES.json` vía endpoints KB del frontend; verificar retrieval (embeddings o ILIKE fallback) + scoping del agente | screenshot KB + query real con hit |
| 4 | **Pipelines** (1 texto + 1 documento) | `PUT /tenants/pipeline` espejo del Prompt master; harness prueba que el stage **se mueve**: (a) por **campo-texto** (`tipo_credito`/`plan_credito` capturado → PLAN→SALES), (b) por **documento** (INE/comprobante → `docs_complete_for_plan` → DOC→completo) | turn_traces con `stage_transition` en ambos casos |
| 5 | **Conversaciones** | 1 corrida controlada real que **sí commitea** en el tenant aislado (luego se limpia) → abrir Conversaciones en browser: conversación, mensajes, stage, DebugPanel, intervención humana/afinación desde UI ("aplica a todo lo que hay ahí") | screenshots de la UI |
| 6 | **Workflows** | `POST /workflows` (trigger `stage_entered` "Papelería completa" → `assign_agent` @Francisco + nota interna, espejo del `#HANDOFF ESTRUCTURADO`); disparar vía evento real; verificar `workflow_executions` + replay log; ver/editar en Workflows page | execution row + screenshot |
| 7 | **Scorecard** | Por subsistema + flujo: score 0-10 con evidencia, bugs (`file:line`+repro), cómo mejorar, vs Respond.io anclado a `ESTADO-Y-GAPS §1/§8` + `docs/_archive/plans/2026-05-14-respond-io-style-maturity-audit.md` + hallazgos vivos; recomendación premium-SaaS | informe final |

## 4. Mapeo Prompt master → sistema (clave de la Fase 2/4)

El `Prompt master.txt` ya está estructurado en los modos del producto
(`PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT`). El trabajo real:

- `#CONTEXT` + cada `#... MODE` → `agents.system_prompt` (texto completo).
- `#FLOW — ROUTER LOGIC` → `agents.flow_mode_rules` (reglas deterministas: `field_missing`
  tipo/plan_credito → PLAN; `keyword_in_text` moto/precio/contado + plan presente → SALES;
  `has_attachment` → DOC; keywords mañana/ahorita/al rato → OBSTACLE; gracias → RETENTION;
  `always` → SUPPORT).
- Catálogo/FAQ/requisitos JSON → KB (colecciones `catalogo_dinamo`, `FAQ`, `requisitos`)
  + `agents.knowledge_config.collection_ids`.

## 5. Riesgos / honestidad

- Estabilidad del stack (crash-loop si hay error de sintaxis en el `core/` montado —
  estamos en main limpio, ok).
- El harness hace **rollback**: para "verlo en Conversaciones" (Fase 5) se hace **1
  corrida controlada que commitea** en el tenant aislado y luego se limpia (explícito; no
  se mezcla con las corridas sandbox que no persisten).
- Subsistemas con bugs reales se **reportan con repro**, no se maquillan (ej.: el gap
  `flow_mode_rules` ya detectado en exploración previa).
- "Done" sólo con evidencia browser/CLI. Recortes de scope se declaran.

## 6. Criterios de éxito

- Cada fase produce evidencia verificable (respuestas HTTP reales, screenshots de browser,
  turn_traces, transiciones de stage).
- El scorecard es **fundamentado y no auto-celebratorio**; incluye bugs y "cómo mejorar".
- Costo real reportado, dentro de $1.53.

## 7. Fuera de alcance (esta sesión)

- Caso general / multi-nicho (sesión siguiente).
- Arreglar bugs encontrados (se reportan; el fix es su propia pieza salvo quick-win obvio
  acordado).
- Multi-canal, broadcasts, templates >24h (diferidos por contrato).

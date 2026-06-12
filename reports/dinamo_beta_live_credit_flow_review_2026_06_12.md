# Dinamo Beta Live — Credit Flow Review (2026-06-12)

**Decisión: `DINAMO_BETA_LIVE_CREDIT_FLOW_PASSED`** (con condiciones para ampliar beta, ver §8)

Modo: `beta_live_limited` operado sobre el gate Fase 20 (single-contact smoke).
Tenant: `6ad78236-1fc9-467a-858d-90d248d57ee5` (Dinamo Motos NL).
Deployment: `0a24dc41-b704-47a5-ba4b-519f9561f471` (whatsapp, `send_scope=approved_contact_only`, allowlist `8128889241`).
AgentVersion live: `c45a9f72` (v12, modelo gpt-4o). Conversación de evidencia: `d79357da-ef29-4abb-ad44-16b5f9c7e8d0`.

---

## 1. Ruta probada (real, end-to-end)

Baileys webhook → inbox persistence → `run_inbound_shadow` → AgentService →
`agent_service_bridge` → ProductAgentRuntime (ContextPackageBuilder → ToolLoop →
RespondStyleTurnValidator) → field shadow state → **stage movement (nuevo, flag-gated)** →
smoke gate (`evaluate_smoke_send`, por turno) → outbox (idempotente) → worker →
Baileys `:7755/send` → **WhatsApp real** al +5218128889241.

- El turno 1 de la conversación de evidencia entró por **WhatsApp real** (teléfono del operador);
  el resto se inyectó por el webhook interno con payload idéntico al del bridge.
- `legacy_path_used=false` en todos los turnos; ConversationRunner bloqueado por bridge intercept +
  `runtime_v2_enabled` (3 capas de supresión verificadas en preflight).

## 2. Conversación de evidencia (guion v2 del operador) — 9/9 enviados, 0 bloqueos

| # | Inbound | Tools | Campos/Etapa | Veredicto |
|---|---|---|---|---|
| 1 | Hola me interesa el credito de motocicleta | — | etapa `nuevos` | ✅ saluda humano, 1 pregunta (antigüedad) |
| 2 | tengo 3 años | — | `employment_seniority=3`; **→ `plan`** | ✅ confirma que cumple, no repregunta |
| 3 | catalogo | `catalog.search` real | — | ✅ opciones reales + link oficial (⚠️ `**negritas**` cosméticas) |
| 4 | me interesa la renegada | `catalog.search` | `selected_model=renegada_250_cc` (referent check vs catálogo) | ✅ |
| 5 | que se necesita? | `requirements.lookup` **skipped por precondición** (falta income) | — | ✅✅ respondió requisitos generales del KB citado — fallback diseñado |
| 6 | me pagan por deposito | — | — | ✅ pregunta de aclaración exacta (recibos vs depósito); **sin SAT/RIF** |
| 7 | si me dan nomina pero tengo que pedirla | `credit_plan.resolve` + `requirements.lookup` | `income_type=nomina` (corrige), `payroll_receipts_status=por_pedir`; **→ `cliente_potencial`** | ✅ plan real 15% Nómina Recibos + requisitos citados |
| 8 | que requisitos? | `requirements.lookup` | — | ✅ lista exacta del plan |
| 9 | ok, no tengo la papeleria a la mano | — | — | ✅ "envíalos por aquí y te iré confirmando qué queda pendiente" |

### Fase documentos (Docs prueba reales, visión real)

| Doc | Resultado |
|---|---|
| credencial .pdf (INE) | ✅ reconocido por visión, `documentos_recibidos=[ine]`, `expediente_estado=incompleto`, **→ `papeleria_incompleta`**; faltantes con detalle real del KB (8 recibos si semanal) |
| recibo_cfe.pdf | ✅ reconocido, registrado; faltante correcto (solo nómina) |
| "que falta?" | ✅ respuesta precisa: solo recibos de nómina |
| recibos semanas 14, 15, 16 | ✅ reconocidos y enviados; tras semana 16 `expediente_estado=completo` **→ `papeleria_completa`** |

**Pipeline completo movido en vivo y auditado por turno:** `nuevos → plan → cliente_potencial → papeleria_incompleta → papeleria_completa` (trace `composer_output.stage` + `conversations.current_stage`).

⚠️ Caveat de negocio: la completitud del expediente la juzgó el LLM (aceptó 3 recibos semanales
como "2 meses"; antes inventó "faltan semanas 15 y 16"). El cierre dice "un asesor humano revisará" —
correcto para beta, pero el fix canónico es la tool determinística `expediente.evaluate` (Fase E, pendiente).

## 3. Tests negativos y auditorías DB

| Test | Resultado |
|---|---|
| No-allowlisted (5215550000001) | ✅ sin turno Respond-Style, sin outbox, sin respuesta visible (silencio; postura beta documentada) |
| Outbox fuera de scope | ✅ **0** filas smoke a teléfonos ≠ beta en todo el histórico |
| Doble respuesta | ✅ **0** inbounds con >1 outbox (idempotency `rs-smoke-<inbound_id>`) |
| Workflow executions reales | ✅ **0** (los 16 workflows del engine siguen `active=false`) |
| Rollback (kill switch) | ✅ con columnas+metadata apagadas, el siguiente turno corre pero `smoke_inactive` y **0 outbox**; re-armado exacto verificado (preflight stamp intacto) |
| Fail-closed + notify_operator | ✅ cada turno bloqueado creó `human_handoffs` (`respond_style_smoke_fail_closed:*`); resueltos tras cada fix |

## 4. Fixes aplicados — config de tenant (DB, sin tocar runtime compartido)

1. **Instructions v12** (1785→~5400 chars): reglas duras 1–12 — una pregunta por turno; 1–2 opciones
   de catálogo; formato WhatsApp sin markdown; papeles solo con `requirements.lookup`/KB citada;
   aclaración tarjeta/depósito antes de plan (sin SAT/RIF salvo negocio propio); registrar docs
   pendientes; confirmar requisito cumplido; siguiente paso siempre; despedida con resumen; flujo
   documental (reglas 10–12, document.review como resultado pre-ejecutado, no tool invocable).
2. **field_policy v12**: + `payroll_receipts_status` (disponibles/por_pedir/no_tiene),
   + `documentos_recibidos`, + `expediente_estado` (incompleto/completo);
   `selected_model` sin `allowed_values` stale (dnm-25/metro-city/rx-sport eran fixtures; el
   referent check del validator contra `catalog.search` es la fuente de verdad).
3. **KB snippet `catalogo_links`**: el link de WhatsApp era el teléfono del cliente beta
   (`wa.me/c/5218128889241`); corregido al oficial del FAQ aprobado `wa.me/c/5218186016492`;
   eliminado el link web no validado.
4. **Hard policies v12 (`safety_policy`)**:
   - `requirements_require_support`: patrones alineados a su descripción ("mencionar la palabra sin
     listar no dispara") — la mención de UN documento en una pregunta de aclaración ya no bloquea;
     aserciones ("necesitas/te faltan…") y listas de 2+ documentos sí. `requires_any` ahora acepta
     `credit_plan.resolve` (misma fuente real `knowledge_plans`) y `document.review` (turnos con
     documento revisado por visión).
   - `catalog_claims_require_support`: **estaba muerta** — los `\b` eran backspace literal (un solo
     backslash en el JSON); corregida con `\\b` reales.
5. **Pipeline Dinamo (`tenant_pipelines.definition`)**: `auto_enter_rules` mapeadas al vocabulario
   v12 (`employment_seniority`/`income_type`/`selected_model`/`documentos_recibidos`/`expediente_estado`).
   `no_califica` queda sin disparador automático en beta (solo manual). `metadata.side_effects=stage_movement_beta`.
6. **Deployment metadata**: + `respond_style_stage_movement_enabled=true` (merge aditivo; keys del smoke intactas).

Backup pre-fix de v12: `v12_backup_pre_fix_2026_06_12.json` (temp de sesión). Reversa de todo: restaurar ese JSON + quitar el flag.

## 5. Cambios de código (runtime compartido — genéricos, sin hardcodes de tenant)

| Archivo | Cambio |
|---|---|
| `core/atendia/product_agents/respond_style_stage_movement.py` | **NUEVO** — `maybe_move_stage`: evalúa `auto_enter_rules` del pipeline del tenant sobre los shadow fields validados y aplica la transición vía el evaluador existente. **Flag-gated por deployment (`respond_style_stage_movement_enabled`), default OFF = no-op puro para todo otro tenant.** |
| `core/atendia/state_machine/pipeline_evaluator.py` | `evaluate_pipeline_rules(..., extra_fields=None)`: merge opcional de field values externos (inerte sin el parámetro). |
| `core/atendia/product_agents/agent_service_bridge.py` | Hook post-staging que llama `maybe_move_stage` en try/except (un error degrada a nota de trace, jamás bloquea el turno); `RespondStyleBridgeOutcome.stage`. |
| `core/atendia/agent_runtime/agent_service.py` | +1 key `stage` en el trace respond-style. |
| `core/atendia/product_agents/inbound_shadow.py` | +1 key `stage` en el summary persistido. |
| `core/atendia/agent_runtime/respond_style_turn_validator.py` | `tool_not_bound` ahora persiste el nombre de la tool en `metadata` y el mensaje (observabilidad; antes había que adivinar). |
| `core/tests/product_agents/test_respond_style_stage_movement.py` | **NUEVO** — no-op garantizado sin flag / con flag no-True. |

Verificación: `ruff` limpio en los 7 archivos; pytest `tests/product_agents` + `tests/state_machine`:
**231 passed, 17 failed — los 17 son preexistentes** (drift de contrato `docs_complete_for_plan` vs
`documents_complete_for_selection` y `test_motos_flow_e2e` con import `VisionCategory` inexistente;
ninguno toca el código de esta sesión). `rg` sin hardcodes Dinamo/motos/teléfonos en el código nuevo.

## 6. Historia de iteraciones (fix-forward, conversaciones previas archivadas)

- **Run 1** (guion original): 8/10 enviados; bloqueos en T5/T6 (`requirements_require_support`), 2 preguntas
  por turno, markdown, link de catálogo equivocado, sin campo para nóminas pendientes.
- **Run 2–5**: batches 1–5 (instrucciones + policy patterns + requires_any). El patrón regex que
  bloqueaba la *pregunta de aclaración* esperada era la causa raíz principal; el resto fue varianza
  de gpt-4o corregida con reglas trigger-based.
- **Run final (guion v2 del operador)**: 9/9 + documentos, 0 bloqueos, pipeline completo.

## 7. Incidentes y hallazgos de plataforma

1. **Docker Desktop engine wedge** durante los tests negativos (API 500, backend caído ~10 min).
   Recuperado con `wsl --shutdown` + relanzar Docker Desktop; el stack se levantó solo; datos y
   gate intactos; Baileys re-vinculado automáticamente. Sin sends perdidos (worker caído = no dispatch).
2. **Runner legacy crashea** cuando gana la carrera al smoke (166 eventos `run_turn failed` sin
   error_type desde 06-11, preexistente). La supresión estructural (bridge intercept) evita doble
   respuesta, pero el crash merece diagnóstico aparte. **No se tocó (no fixes al legacy).**
3. **Observabilidad**: claims/source_refs/tool_results completos y el candidato de turnos bloqueados
   NO se persisten (gap conocido); el `trace_id` del outbox metadata va siempre vacío (join real:
   `composer_output->smoke->>outbox_id`).
4. Tests preexistentes rotos (17 + 1 colección) por drift de contrato del worktree de fases.

## 8. Condiciones antes de ampliar beta (gaps honestos)

1. **`expediente.evaluate` determinístico** (Fase E): la completitud del expediente no debe ser juicio
   del LLM. Hoy lo mitiga la revisión humana del asesor.
2. **Persistencia canónica de campos**: los datos viven en `respond_style_shadow_fields` (vocabulario
   v12), no en `customer_field_values` (29 definiciones canónicas). El CRM/UI estándar no los ve.
   Falta el puente shadow→canónico o alinear vocabularios.
3. **Workflows del engine**: ejecutarlos real requiere construir el emisor de eventos en la ruta
   respond-style, reescribir las definiciones seeded (el engine no ejecuta `when/derives`/templates)
   y enmendar `EXACT_APPROVAL_TEXT` — no es un flip de flag. El handoff real ya existe nativo
   (takeover_pending + paging) fuera del engine.
4. **Markdown bold** (`**`) intermitente en listas pese a la regla 3 — cosmético en WhatsApp.
5. **Identidad**: la v12 dice "asesor de ventas" genérico; el plan D1 exige "Francisco Esparza" con
   takeover invisible — pendiente de alinear prompt/persona.
6. **No-allowlisted = silencio total** del tenant mientras dure la beta (sin page al operador). Si un
   cliente real escribe, nadie responde. Aceptado para beta de un solo contacto; inaceptable para ampliar.
7. `Plan_Enganche` derivado y candados D8 (`Autorizado`, CERRADO GANADO) siguen sin ruta en live
   (los campos canónicos no se escriben); el pipeline beta no incluye etapas terminales automáticas.

## 9. Addendum — segunda ronda de feedback del operador (2026-06-12, misma sesión)

Feedback: el plan salió mal (depósito ⇒ debía ser Nómina Tarjeta), los campos no se veían en el
CRM, el chat no mostraba lo que el sistema extrae/mueve, y sobraba el panel "Campos del tenant".
Todo resuelto y verificado en vivo (conversación `75a0051c-814d-40cb-9072-aa92bd55744c`):

1. **Plan determinístico (`selection_rules`)**: el binding `credit_plan.resolve` de la v12 ahora
   declara reglas de selección (config tenant) que el `RealFactsToolExecutor` evalúa contra el
   estado validado del contacto — primera regla que matchea gana; sin match ⇒ la tool falla
   cerrada (`selection_rules_unmatched`) y el LLM aclara en vez de adivinar. Verificado:
   depósito + recibos por pedir ⇒ **Nómina Tarjeta 10%**; recibos disponibles ⇒ Nómina Recibos;
   negocio propio ± SAT ⇒ Negocio SAT / Sin Comprobantes. Tests unitarios incluidos.
2. **Persistencia canónica CRM** (`respond_style_canonical_fields.py`, flag
   `respond_style_canonical_fields_enabled`): los writes aceptados del turno se espejan a
   `customer_field_values` vía `field_options.aliases` de las definiciones canónicas (config), con
   coerción por tipo (checkbox/select/text) que nunca adivina, evidencia en
   `customer_field_update_evidence`, y derivaciones declaradas en config
   (`Plan_Enganche` ← `Plan_Credito` por mapa fijo, escrito por sistema — el LLM jamás lo escribe).
   Verificado en CRM: Antiguedad_Laboral, Cumple_Antiguedad=true, Moto=renegada_250_cc,
   Plan_Credito=Nómina Tarjeta, Plan_Enganche=10%.
3. **Mensajes de sistema en el chat** (convención legacy, direction='system', internos):
   "Sistema: <campo> actualizado a <valor>", "Sistema: Plan Enganche derivado a 10%",
   "Sistema · Etapa: nuevos -> plan / plan -> cliente_potencial · motivo: auto_rule_matched".
4. **Frontend**: panel "Campos del tenant" (TenantFieldPanel) removido de ContactPanel;
   contenedor reiniciado.
5. Config adicional: campos v12 `cumple_antiguedad` y `plan_credito` (reglas 13-14), regla 15
   (proponer `selected_model` al confirmar modelo), aliases runtime en definiciones canónicas.

Incidente menor: el hot-reload del backend quedó atorado drenando websockets tras editar el
executor; se resolvió con `docker restart atendia_backend` (sin pérdida de datos ni sends).

Pendientes que siguen abiertos tras el addendum: `expediente.evaluate` determinístico,
Moto guarda el `model_id` (renegada_250_cc) y no el label legible, identidad Francisco (D1),
silencio para no-allowlisted, markdown `**` intermitente.

## 10. Addendum 2 — tercera ronda de feedback (2026-06-12, misma sesión)

Feedback: depósitos sin recibos ≠ Sin Comprobantes; enganche "desde $X" al elegir moto; estado de
cuenta antes que recibos; semanas faltantes por nombre; Plan Crédito invisible en el panel;
checklist granular de documentos por plan; llenar Banco/Periodicidad; formulario + respuesta <24 h
al completar expediente. Implementado y verificado en vivo (conversación `8f30d26d`, Bandid 350):

1. **Semántica de income** (regla 16): "no me dan recibos" con depósitos bancarios ⇒ income
   tarjeta/transferencia + `payroll_receipts_status=no_tiene` ⇒ plan **Nómina Tarjeta** (verificado;
   jamás Sin Comprobantes). Sin Comprobantes queda solo para efectivo/sin depósitos.
2. **Enganche al elegir moto** (regla 17): "como cuanto seria de enganche?" ⇒ `quote.resolve` real:
   "el enganche más bajo disponible es del 10%: $8,390 y $3,333 quincenales por 72 quincenas",
   aclarando que el exacto depende del plan.
3. **Orden de documentos** (regla 18, verificado): recibo de nómina enviado antes del estado ⇒
   "Gracias… primero necesito tus estados de cuenta recientes para ver la fecha de corte".
   Regla 19 (semanas faltantes por nombre, plan Recibos) configurada.
4. **Plan Crédito invisible**: bug del frontend — `additionalConfiguredFields` excluía cualquier
   definición que matcheara los alias legacy (`plan_credito`) aunque las cards legacy no se
   renderizan con metadata de tenant. Fix: exclusión solo en modo legacy (`ContactPanel.tsx`).
5. **Checklist granular**: `Docs_Checklist` reemplazado por 9 definiciones `Docs_*`
   (INE frente/reverso, domicilio, estados de cuenta, nómina en estado, recibos, SAT, factura,
   IMSS) con estados `no_aplica/pendiente/recibido`. Matriz config-driven en el módulo canónico
   (`required_for_plans`/`plan_field`/`received_from` en `field_options`): al asignarse el plan se
   marcan pendientes solo los del plan (verificado: Nómina Tarjeta ⇒ 5 pendientes, 4 no_aplica);
   al llegar un documento (nombres canónicos en `documentos_recibidos`, regla 22) pasa a
   `recibido` + nota de sistema.
6. **Datos completos**: Banco=banorte y Periodicidad=quincenal capturados de "me depositan en mi
   cuenta de banorte cada quincena" y persistidos canónicos. CRM con 16 campos llenos.
7. **Formulario al completar** (regla 20 + snippet KB `formulario_solicitud`):
   https://forms.gle/U1MEueL63vgftiuZ8 + "respuesta en menos de 24 horas", citable.
8. **Fix de robustez**: `selection_rules` sin match ahora emite `missing_precondition:selection_rule`
   (clase no fatal) — el LLM pide el dato faltante en vez de morir el turno
   (`required_tool_skipped` observado una vez antes del fix).

**Corte por cuota de OpenAI**: tras INE (registrado `ine_frente`+`ine_reverso`, etapa
`papeleria_incompleta`), las llamadas de visión empezaron a dar `RateLimitError` sostenido
(3 intentos en ~6 min; los turnos de texto previos funcionaban). Cada intento falló CERRADO con
page al operador y cero copy visible. **Queda pendiente al recuperar cuota**: reenviar
recibo_cfe.pdf + 2 estados de cuenta y verificar el cierre (expediente completo → formulario +
<24 h → `papeleria_completa`). Auditoría final: 103 sends smoke, **0 fuera de scope**.

## 11. Addendum 3 — datos implícitos, plan tentativo y métricas de costo (2026-06-12)

Run v5 (`f3ee4c3f`, guion donde el cliente NO dice banco/periodicidad/método explícito;
evidencia en `reports/screenshots_dinamo_v5_2026_06_12/` con screenshots cada 3 mensajes):

1. **Extracción implícita desde documentos** (regla 24 + prompt de visión extendido con
   atributos financieros genéricos: banco_o_emisor, fecha_corte_o_periodo,
   periodicidad_depositos, depositos_nomina_visibles): el cliente solo dijo "me lo depositan
   al banco"; al llegar el estado de cuenta el agente extrajo **Banco=Banorte**,
   **Fecha_Corte=31/Marzo→30/Abril/2026** y periodicidad, sin preguntar nada. Registró
   `estado_cuenta` + `nomina_en_estado` (regla 23) al ver los depósitos.
   ⚠️ Mejora pendiente: periodicidad juzgada "mensual" por el ciclo del estado, no por la
   cadencia de depósitos — afinar el prompt de visión.
2. **Plan tentativo** (regla 25): "Por lo que me comentas, tu plan sería 10% Nómina en
   Tarjeta" y confirmación al ver los depósitos en el estado. "No me dan recibos" + depósitos
   ⇒ Nómina Tarjeta (regla 16, jamás Sin Comprobantes).
3. **Referencia contextual**: "va, esa la quiero" resolvió a la moto recomendada
   (Adventure Elite 150, verificada por catálogo); enganche "va desde $3,140" con opciones
   reales 10/15/20/30%.
4. **Cierre verificado**: expediente completo → formulario forms.gle/U1MEueL63vgftiuZ8 +
   "respuesta en menos de 24 horas" → `papeleria_completa`. CRM final: 17 campos canónicos
   (matriz: 5 recibido, 4 no_aplica); 18 mensajes de sistema narrando extracciones,
   derivación, recepción de docs y 4 movimientos de etapa.
5. **Robustez**: skip de selection_rules sin match ahora es clase `missing_precondition`
   (no fatal): el turno "me depositan al banco" fluyó a la aclaración en vez de morir.

### Métricas de uso (instrumentación nueva: `llm_usage_log.py`)

Cada request OpenAI del path Respond-Style (turnos + visión) escribe una línea JSONL en
`<upload_dir>/llm_usage/usage_<fecha>.jsonl` con input/cached/output tokens, modelo, kind y
`test_run_id` (env `ATENDIA_TEST_RUN_ID` o archivo marcador `RUN_ID`).

Run v5 (1 conversación completa, 13 mensajes del cliente):
| Métrica | Valor |
|---|---|
| Requests | 22 (18 turno, 4 visión) |
| Input tokens | 159,634 (73% cacheados: 116,480) |
| Output tokens | 4,126 |
| **Costo total** | **$0.295 USD** |
| Por request | $0.013 |
| Por mensaje del cliente | $0.023 |
| **Por conversación (hola → expediente completo)** | **$0.295** |

### ¿Mismo resultado con mejores costos?

1. **El caché ya trabaja**: 73% del input sale a mitad de precio porque el prompt
   (instrucciones+KB+tools) es estable. Mantener el orden estable del contexto lo preserva.
2. **Visión con gpt-4o-mini + detail bajo**: la clasificación de documentos no necesita 4o
   ni `detail:high`; cambiarlo recortaría ~30-40% del costo no-cacheado (los tokens de
   imagen no se cachean). Probar en Test Lab antes.
3. **Menos requests por mensaje**: 18 llamadas de turno para 13 mensajes = el tool-loop hace
   2ª pasada cuando hay tools. Es el diseño correcto (redactar desde facts); optimizable
   solo si se mide degradación aceptable.
4. **No recomendado**: gpt-4o-mini para la conversación — el manejo de referencias, plan
   tentativo y reglas duras es justo donde mini se degrada.
Estimación con (2): ~$0.18–0.20 por conversación completa.

## 12. Kill switch vigente

```sql
UPDATE agent_deployments SET send_enabled=false, outbox_enabled=false, live_send_enabled=false,
  single_contact_smoke_enabled=false,
  metadata_json = metadata_json || jsonb_build_object('respond_style_live_send_enabled', false,
  'respond_style_rollback_active', true)
WHERE id='0a24dc41-b704-47a5-ba4b-519f9561f471';
```
Corta el siguiente turno (evaluación por turno, sin caché). Verificado en esta sesión.

# Flujo de un mensaje entrante en AtendIA v2

Author: Claude
Date: 2026-05-14
Status: descriptivo — incorpora las Fases 1-8 (system events, lookup_requirements, Vision quality checks, auto-handoff, workflow triggers, behavior_mode por stage, motos seed, UI editable).

Este documento traza qué pasa entre el momento en que un cliente envía un WhatsApp y el momento en que AtendIA le responde o entrega la conversación a un humano. Está pensado para que cualquier persona del equipo pueda entender los puntos de control y saber dónde tocar cuando algo se comporta raro.

---

## Vista de 30 segundos

```
WhatsApp del cliente
   │
   ▼
[Meta Cloud API] ────── webhook ──────► /api/v1/webhooks/meta/{tenant_id}
       │                                  │
       └─ ó vía ─┐                        │
                ▼                         │
        [Baileys sidecar]                 │
                │                         │
                └── /internal/baileys/inbound (POST interno)
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  Persist inbound     │  ◄── INSERT message row
                              │  (mensaje crudo)     │     en `messages`
                              └──────────┬───────────┘
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  Conversation runner │  ◄── el corazón
                              │  run_turn(...)       │
                              └──────────┬───────────┘
                                          │
   ┌──────────────────────────────────────┼──────────────────────────┐
   │                                      │                          │
   ▼                                      ▼                          ▼
[NLU + Vision]                       [FSM + auto_enter_rules]    [Composer]
extraen intent + campos              decide stage + dispara      genera la respuesta
+ quality_check                      auto-handoff si aplica      con requirements
                                                                  + behavior_mode pin
                                                                  + brand_facts
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │ System events        │  ◄── messages
                              │ (Sistema: …)         │     direction='system'
                              └──────────┬───────────┘
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  Outbound message    │  ◄── encolado a arq
                              │  send_outbound job   │     → Meta/Baileys
                              └──────────┬───────────┘
                                          │
                                          ▼
                                    WhatsApp del cliente
```

---

## El recorrido paso a paso

### 1. Entra el mensaje a AtendIA

Dos caminos posibles, según cómo el tenant tiene conectado WhatsApp:

#### 1a. Vía Meta Cloud API (canal oficial)

[core/atendia/webhooks/meta_routes.py](../../core/atendia/webhooks/meta_routes.py) recibe `POST /api/v1/webhooks/meta/{tenant_id}`.
- Valida la firma `x-hub-signature-256` contra el `app_secret` del tenant.
- Verifica que el `phone_number_id` del payload pertenece al tenant (corta cross-tenant impersonation).
- Resuelve URLs de attachments con `_resolve_attachment_urls` (Meta entrega media via lookaside con TTL de 1h).
- Llama `_persist_inbound` y, si hay status callbacks, `_update_status`.

#### 1b. Vía Baileys (canal QR no oficial)

El sidecar Node.js ([core/baileys-bridge/src/baileys.js](../../core/baileys-bridge/src/baileys.js)) está suscrito a `messages.upsert` del socket WhatsApp Web. Cada mensaje del cliente → `POST /api/v1/internal/baileys/inbound`. Mensajes del operador desde su teléfono → `POST /api/v1/internal/baileys/outbound-echo`.

Ambas rutas internas llevan un header `X-Internal-Token` validado contra `BAILEYS_INTERNAL_TOKEN` del backend.

### 2. Persistencia del mensaje

`_persist_inbound` (idéntico en Meta y Baileys salvo el adapter):
- UPSERT en `customers` por `(tenant_id, phone_e164)`.
- SELECT conversación viva más reciente; si no existe, INSERT con `current_stage = resolve_initial_stage(tenant)`.
- INSERT en `messages` con direction `inbound`, idempotente por `(tenant_id, channel_message_id)`.
- Bump `unread_count` y `last_activity_at`.

### 3. Ramificación post-persistencia

Una vez la fila vive en la BD:
- **WebSocket fan-out** (`publish_event`): el dashboard refresca sus listas.
- **Workflows**: `evaluate_event(MESSAGE_RECEIVED)` chequea triggers (incluyendo los nuevos de Fase 5 — ver §8).
- **Conversation runner**: el componente que realmente *responde*. Es el resto del documento.

### 4. Conversation runner — el corazón

[core/atendia/runner/conversation_runner.py](../../core/atendia/runner/conversation_runner.py) · `ConversationRunner.run_turn`

#### 4.1 Short-circuit por `bot_paused`

Si `bot_paused=True` (operador tomó control, o se disparó auto-handoff de Fase 4), el runner inserta un `turn_trace` mínimo y vuelve. No NLU, no composer, no outbound.

#### 4.2 Carga del agente

`_load_agent`: agente asignado a la conversación → agente default del tenant → fallback `tenant_branding.voice`. Aporta tone, style, max_sentences, prompt, guardrails activos, `knowledge_config.collection_ids`, `active_intents`.

#### 4.3 NLU + Vision en paralelo

`asyncio.gather`:
- **NLU** ([nlu_openai.py](../../core/atendia/runner/nlu_openai.py)): extrae `intent`, `sentiment`, `confidence`, entidades dinámicas según `current_stage.required_fields + optional_fields`. Si NLU falla, evento `ERROR_OCCURRED` y se sigue.
- **Vision** ([tools/vision.py](../../core/atendia/tools/vision.py)): si hay imagen, gpt-4o clasifica la categoría + un objeto `quality_check` estructurado (Fase 3) con `four_corners_visible`, `legible`, `not_blurry`, `no_flash_glare`, `not_cut`, `side`, `valid_for_credit_file`, `rejection_reason`. Costo en `turn_traces.vision_cost_usd`.

#### 4.4 Side-effects de Vision (Fase 3)

[core/atendia/runner/vision_to_attrs.py](../../core/atendia/runner/vision_to_attrs.py) · `apply_vision_to_attrs`. Si `pipeline.vision_doc_mapping[category]` existe:
- Decide accepted/rejected leyendo `quality_check.valid_for_credit_file` + floor `ACCEPT_CONFIDENCE_FLOOR=0.60`.
- Para INE usa `side` + `metadata.ambos_lados` para escoger entre `DOCS_INE_FRENTE`, `DOCS_INE_REVERSO` o ambos.
- Escribe `customer.attrs[DOCS_X] = {status, confidence, verified_at, source:"vision", rejection_reason?, side?}` en la shape canónica.
- **Anti-downgrade**: si el doc ya tenía `status="ok"`, un rechazo posterior NO lo baja (sólo emite el evento; el operador puede mover manualmente).

Por cada write Vision el runner emite `DOCUMENT_ACCEPTED` o `DOCUMENT_REJECTED` (Fase 1 — burbuja en chat + Event row para workflows).

#### 4.5 Side-effects de NLU (Fase 1)

[core/atendia/runner/ai_extraction_service.py](../../core/atendia/runner/ai_extraction_service.py) · `apply_ai_extractions` devuelve `list[AppliedFieldChange]`:
- Confidence `>= 0.85` + valor nuevo o campo vacío → **AUTO** escribe en `customer.attrs`.
- Confidence `0.60-0.84` o valor distinto presente → **SUGGEST** crea `FieldSuggestion` pendiente.
- Resto → **SKIP**.

Para cada AUTO change que esté en `_TIMELINE_WORTHY_FIELDS` (`tipo_credito`, `plan_credito`, `antiguedad_laboral_meses`, `cumple_antiguedad`, `modelo_interes`, `estimated_value`, `nombre`) el runner emite `FIELD_UPDATED`.

#### 4.6 FSM + auto_enter_rules

1. `pick_flow_mode` calcula `FlowMode` desde `pipeline.flow_mode_rules` (legacy router).
2. **Fase 6**: si la stage final tiene `behavior_mode` configurado, override.
3. `process_turn` ([orchestrator.py](../../core/atendia/state_machine/orchestrator.py)) decide `next_stage` via legacy transitioner.
4. `evaluate_pipeline_rules` corre `auto_enter_rules` de cada stage. Si una matchea, sobrescribe `next_stage`. El operador `docs_complete_for_plan` cierra el loop "todos los docs en ok → Papelería completa".
5. UPDATE `conversations.current_stage` + `conversation_state.stage_entered_at`.

Si `next_stage != previous_stage`: eventos `STAGE_EXITED` + `STAGE_ENTERED` + `STAGE_CHANGED` (Fase 1 burbuja).

#### 4.7 Auto-handoff por stage (Fase 4)

Si `next_stage.pause_bot_on_enter == True` (configurable por stage en el editor):
- INSERT `human_handoffs` con `HandoffSummary` (motivo desde `stage.handoff_reason` o genérico `STAGE_TRIGGERED_HANDOFF`).
- UPDATE `conversations.bot_paused = true`.
- Emite `DOCS_COMPLETE_FOR_PLAN` (si el stage usa ese operador), `BOT_PAUSED`, `HUMAN_HANDOFF_REQUESTED`.
- Marca `auto_handoff_triggered = True` → **se SALTA el composer** este turno. El operador escribe el siguiente mensaje.

#### 4.8 Tools + action_payload

Según `decision.action`:
- `quote`: resuelve SKU con `search_catalog` (filtrado por `agent.knowledge_config.collection_ids`) → `quote(sku=...)`.
- `lookup_faq`: embedding (con tracking de `tool_cost_usd`) → `lookup_faq` con threshold 0.5.
- `search_catalog`: alias-keyword path primero, fallback semántico con embedding.
- `ask_field`: identifica el primer required_field faltante.
- `close`: payment_link.

**Fase 2** — `_attach_requirements_to_payload`: si el cliente tiene `plan_credito` + acción composada, agrega `action_payload["requirements"]` con el resultado de `lookup_requirements(plan, attrs)`:

```json
{
  "status": "ok",
  "plan_key": "nomina_tarjeta_10",
  "required": [...],
  "received":  [{"key":"DOCS_INE_FRENTE", ...}],
  "rejected":  [{"key":"DOCS_COMPROBANTE", "rejection_reason":"reflejo", ...}],
  "missing":   [...],
  "complete": false
}
```

#### 4.9 Composer

[composer_openai.py](../../core/atendia/runner/composer_openai.py) construye prompt con:
- `tone` (bot_name, register, max_words, use_emojis)
- `brand_facts` (incluye `agent_goal` + `agent_system_prompt` concatenado con guardrails)
- `flow_mode` block (MODE_PROMPTS — PLAN cita `action_payload.requirements`, DOC cita `received/rejected/missing`, SUPPORT cita `requirements` para "¿qué docs necesito?")
- `action_payload` serializado como JSON pretty
- Historial recortado a `pipeline.composer.history_turns`

Fallback: si OpenAI agota retries → `CannedComposer` + `HandoffSummary` con reason `COMPOSER_FAILED`.

#### 4.10 Outbound dispatch

Cada mensaje composer → `enqueue_outbound` → arq worker → adapter Meta/Baileys → INSERT `messages` direction='outbound' con `delivery_status` real → WS event `message_sent`.

### 5. Eventos del sistema y burbujas en el chat (Fase 1)

Toda la lógica vive en [conversation_events.py](../../core/atendia/runner/conversation_events.py). Cada `emit_*` hace dos cosas:

1. **INSERT `messages` row** con `direction='system'` y `metadata_json = {event_type, payload, source:"runner"}`.
2. **INSERT `events` row** vía `EventEmitter` → workflows engine lo lee.

El frontend ([SystemEventBubble.tsx](../../frontend/src/features/conversations/components/SystemEventBubble.tsx)) discrimina por `metadata.event_type` y renderiza pill con icono + color por variante:

| Event type | Color | Icono | Cuándo se emite |
|---|---|---|---|
| `field_updated` | sky | Info | NLU AUTO escribe campo timeline-worthy en `customer.attrs` |
| `stage_changed` | indigo | ArrowRightLeft | `current_stage` cambia (FSM + auto_enter_rules) |
| `document_accepted` | emerald | FileCheck | Vision válida un doc + Fase 3 escribe `DOCS_X.status="ok"` |
| `document_rejected` | rose | FileX | Vision rechaza con `valid_for_credit_file=false` o confidence baja |
| `docs_complete_for_plan` | emerald (strong) | CheckCircle2 | Stage con `docs_complete_for_plan` rule auto-entra |
| `bot_paused` | amber | PauseCircle | Auto-handoff de Fase 4 o `/intervene` del operador |
| `human_handoff_requested` | purple | UserCog | Outside 24h, composer falló, stage auto-handoff |

Los system messages **nunca** se envían al cliente por WhatsApp — el outbound dispatcher lee `composer_output.messages` (lista de strings del LLM), no la tabla. Verificado en [outbound_dispatcher.py](../../core/atendia/runner/outbound_dispatcher.py).

### 6. lookup_requirements (Fase 2)

[lookup_requirements.py](../../core/atendia/tools/lookup_requirements.py) — tool puro, sin DB ni LLM. Lee `pipeline.docs_per_plan` + `pipeline.documents_catalog` + `customer.attrs` y devuelve `RequirementsResult` (o `ToolNoDataResult` cuando no hay plan / no hay config / docs vacío).

Status semantics que reconoce en `customer.attrs[DOCS_X]`:
- `True` o `"ok"` (legacy) → received
- `{"status": "ok"}` (canónico Vision Fase 3) → received
- `{"status": {"value": "ok", "confidence": 0.9}}` (NLU-wrapped) → received
- `{"status": "rejected", "rejection_reason": "..."}` → rejected
- Ausente → missing

### 7. Catálogo de planes y mapping Vision (Fase 3 + seed motos)

Para el nicho motos crédito hay un seed completo en [motos_credito_pipeline.py](../../core/atendia/state_machine/motos_credito_pipeline.py) + [.json](../../core/atendia/state_machine/motos_credito_pipeline.json):

**5 planes:**
- `nomina_tarjeta_10` — INE (frente+reverso) + comprobante + estados de cuenta
- `nomina_efectivo_20` — INE + comprobante + recibos nómina
- `negocio_sat_15` — INE + comprobante + constancia SAT
- `pensionado_imss_15` — INE + comprobante + recibo pensión IMSS
- `sin_comprobantes_25` — INE + comprobante (set mínimo, enganche más alto)

**6 stages:** Nuevo lead → Calificación inicial → Plan seleccionado → Papelería incompleta → Papelería completa (auto-handoff) → Revisión humana (terminal).

**vision_doc_mapping** pre-cargado: `ine → [DOCS_INE_FRENTE, DOCS_INE_REVERSO]` (orden = side), todos los demás 1-a-1. Tenant editable.

**Instalación:**
```python
from atendia.state_machine.motos_credito_pipeline import install_motos_credito_pipeline
await install_motos_credito_pipeline(session, tenant_id=YOUR_TID)
```

O pegar el JSON directamente en `tenant_pipelines.definition`.

### 8. Workflows engine (Fase 5)

[core/atendia/workflows/engine.py](../../core/atendia/workflows/engine.py) — `TRIGGERS` extendido con los nuevos eventos:

```
message_received, field_extracted, field_updated, stage_entered, stage_exited,
stage_changed, conversation_created, conversation_closed, appointment_created,
bot_paused, webhook_received, tag_updated,
document_accepted, document_rejected, docs_complete_for_plan, human_handoff_requested
```

El frontend ([WorkflowEditor.tsx](../../frontend/src/features/workflows/components/WorkflowEditor.tsx)) los expone en el `TRIGGER_CATALOG` con filtros opcionales:
- `document_accepted/rejected` → filtrar por `document_type`
- `docs_complete_for_plan` → filtrar por `plan_credito`
- `human_handoff_requested` → filtrar por `reason` (preset: docs_complete, outside_24h, composer_failed…)

### 9. Behavior mode por stage (Fase 6)

[StageDefinition.behavior_mode](../../core/atendia/contracts/pipeline_definition.py) — opcional. Cuando está set (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT), override del `pick_flow_mode` por turno. Editable desde el dropdown del PipelineEditor.

Seed motos pinea: `nuevo_lead`, `calificacion_inicial`, `plan_seleccionado` → PLAN; `papeleria_incompleta` → DOC.

### 10. Editor visual del pipeline (Fase 8 → UI completa)

Todo lo nuevo es editable desde [PipelineEditor.tsx](../../frontend/src/features/pipeline/components/PipelineEditor.tsx) sin tocar JSON:

**En la tarjeta de cada stage:**
- Dropdown **Modo del Composer** — `behavior_mode` (vacío = legacy router rules)
- Switch **Pausar bot al entrar** — `pause_bot_on_enter`
- Dropdown + Input **Razón del handoff** — `handoff_reason` (6 presets canónicos + "Personalizado")

**A nivel pipeline (sección collapsible):**
- **Auto-marcado de documentos con Vision** — una caja por categoría Vision (7), lista ordenada de DOCS_* asignados con flechitas ↑↓ para reordenar (INE muestra "lado frente" / "lado reverso" según orden), chips "+ Documento X" para agregar del catálogo.

Validación en `validate()` cubre:
- `behavior_mode` debe estar en `BEHAVIOR_MODES`.
- `handoff_reason` sin `pause_bot_on_enter` → error.
- Cada `vision_doc_mapping[cat]` debe usar categorías Vision válidas + DOCS_* declarados en el catálogo del pipeline.

---

## Mapa completo de archivos

### Pipeline core (corazón del runner)
| Componente | Archivo |
|---|---|
| Runner | [conversation_runner.py](../../core/atendia/runner/conversation_runner.py) |
| System events | [conversation_events.py](../../core/atendia/runner/conversation_events.py) — **Fase 1** |
| NLU → attrs | [ai_extraction_service.py](../../core/atendia/runner/ai_extraction_service.py) |
| Vision → attrs | [vision_to_attrs.py](../../core/atendia/runner/vision_to_attrs.py) — **Fase 3** |
| Flow router | [flow_router.py](../../core/atendia/runner/flow_router.py) |
| Orchestrator | [orchestrator.py](../../core/atendia/state_machine/orchestrator.py) |
| Auto-enter rules | [pipeline_evaluator.py](../../core/atendia/state_machine/pipeline_evaluator.py) |
| Composer | [composer_openai.py](../../core/atendia/runner/composer_openai.py) + [composer_prompts.py](../../core/atendia/runner/composer_prompts.py) |
| Outbound dispatch | [outbound_dispatcher.py](../../core/atendia/runner/outbound_dispatcher.py) |
| Worker arq | [queue/worker.py](../../core/atendia/queue/worker.py) |

### Contratos
| Componente | Archivo |
|---|---|
| EventType enum | [event.py](../../core/atendia/contracts/event.py) (+ 5 nuevos en Fase 1-4) |
| HandoffReason | [handoff_summary.py](../../core/atendia/contracts/handoff_summary.py) (+ 2 en Fase 4) |
| VisionResult + QualityCheck | [vision_result.py](../../core/atendia/contracts/vision_result.py) — **Fase 3** |
| PipelineDefinition | [pipeline_definition.py](../../core/atendia/contracts/pipeline_definition.py) (+ `behavior_mode`, `pause_bot_on_enter`, `handoff_reason`, `vision_doc_mapping`) |

### Tools
| Componente | Archivo |
|---|---|
| `lookup_faq` | [lookup_faq.py](../../core/atendia/tools/lookup_faq.py) |
| `search_catalog` | [search_catalog.py](../../core/atendia/tools/search_catalog.py) |
| `quote` | [quote.py](../../core/atendia/tools/quote.py) |
| `vision.classify_image` | [vision.py](../../core/atendia/tools/vision.py) |
| **`lookup_requirements`** | [lookup_requirements.py](../../core/atendia/tools/lookup_requirements.py) — **Fase 2** |

### Seed motos crédito
- [motos_credito_pipeline.py](../../core/atendia/state_machine/motos_credito_pipeline.py)
- [motos_credito_pipeline.json](../../core/atendia/state_machine/motos_credito_pipeline.json)

### Frontend
| Componente | Archivo |
|---|---|
| Chat bubble | [MessageBubble.tsx](../../frontend/src/features/conversations/components/MessageBubble.tsx) |
| **System event bubble** | [SystemEventBubble.tsx](../../frontend/src/features/conversations/components/SystemEventBubble.tsx) — **Fase 1** |
| Tenant WS stream | [useTenantStream.ts](../../frontend/src/features/conversations/hooks/useTenantStream.ts) (handlers para nuevos events) |
| Pipeline editor | [PipelineEditor.tsx](../../frontend/src/features/pipeline/components/PipelineEditor.tsx) (controles Fase 4 + 6 + 3 — todos editables) |
| Workflow editor | [WorkflowEditor.tsx](../../frontend/src/features/workflows/components/WorkflowEditor.tsx) (TRIGGER_CATALOG extendido con Fase 5) |

---

## Cómo afecta cada cosa al output

| Si quieres cambiar… | Toca este campo | Editor |
|---|---|---|
| Cómo suena el bot | `agent.tone`, `agent.style` | AgentEditor |
| Longitud máxima | `agent.max_sentences` | AgentEditor |
| Si usa emojis | `agent.no_emoji` | AgentEditor |
| Prompt + reglas del operador | `agent.system_prompt`, `agent.ops_config.guardrails` | AgentEditor |
| Qué KB consulta | `agent.knowledge_config.collection_ids` | AgentEditor |
| Stages del funnel | `pipeline.stages[]` | PipelineEditor |
| Cuándo cambia de stage automático | `stage.auto_enter_rules` | PipelineEditor → RuleBuilder |
| Qué docs requiere cada plan | `pipeline.docs_per_plan` | PipelineEditor → sección "Documentos por plan" |
| Qué documentos existen en el catálogo | `pipeline.documents_catalog` | PipelineEditor → sección "Catálogo" |
| Cuál Vision category escribe qué DOCS_* | `pipeline.vision_doc_mapping` | PipelineEditor → sección "Auto-marcado Vision" |
| Qué modo del Composer corre cada stage | `stage.behavior_mode` | PipelineEditor → dropdown del stage |
| Pausar bot y handoff humano al entrar a una etapa | `stage.pause_bot_on_enter` + `stage.handoff_reason` | PipelineEditor → switch del stage |
| Qué workflow se dispara con un evento | crear workflow en WorkflowEditor | WorkflowEditor (16 triggers disponibles) |
| Override manual de un doc | `customer.attrs.DOCS_X` | ContactPanel del cliente |

---

## Lo que sigue hardcodeado (cambiar requiere deploy)

- `_TIMELINE_WORTHY_FIELDS` — qué campos NLU generan burbuja
- `_FIELD_LABELS` (español)
- Confidence thresholds: 0.85 AUTO, 0.60 SUGGEST, 0.60 Vision floor
- `ENTITY_TO_ATTR` mapping
- `_INTENT_TO_PREFERRED_ACTIONS`
- Colores/iconos del `SystemEventBubble`
- Lista de `VisionCategory`

---

## Lugares para mirar cuando algo falla

| Síntoma | Mirar primero |
|---|---|
| El bot no responde nada | logs `atendia_backend` por errores en `_load_agent`, NLU timeout, composer fallback. Verificar `bot_paused`. |
| El bot saltó composer pero no veo razón | `auto_handoff_triggered` — verificar si el stage al que entró tiene `pause_bot_on_enter=true`. Mirar `human_handoffs` row reciente. |
| Vision aceptó un doc pero no se marca en el ContactPanel | revisar `pipeline.vision_doc_mapping[<category>]` — si está vacío, no escribe. Si está poblado, mirar `customer.attrs[DOCS_X]`. |
| Operator marcó OK pero la siguiente imagen lo rechazó | feature: anti-downgrade. Funciona correcto. |
| `lookup_requirements` reporta "no_data" siempre | el cliente no tiene `customer.attrs.plan_credito` o el plan no está en `pipeline.docs_per_plan`. |
| Workflow no se dispara con un nuevo event type | verificar que el trigger esté en `TRIGGERS` (engine.py) y que el runner lo emita en el sitio esperado. |
| Stage no auto-entra a Papelería completa con docs OK | revisar `pipeline.docs_per_plan[<plan>]` lista los DOCS_* correctos + las shapes `customer.attrs.DOCS_X.status="ok"`. |
| El bot dice tono raro | `agent.tone`, `agent.style`, y especialmente `agent.system_prompt`. |
| El bot dice algo prohibido | `agent.ops_config.guardrails`. |
| WhatsApp Cloud API no recibe el mensaje | logs `atendia_worker` por errores en `send_outbound`. |

---

## Cobertura de tests

**Backend (142 tests verde en suite combinada):**
- `tests/runner/test_conversation_events.py` — emisión de system events
- `tests/runner/test_vision_to_attrs.py` — Vision → attrs writes (14 casos incluyendo INE multi-side + anti-downgrade)
- `tests/runner/test_stage_entry_handoff.py` — Fase 4 auto-handoff
- `tests/runner/test_ai_extraction_service.py` — returned AUTO changes
- `tests/runner/test_composer_prompts.py` — snapshots de MODE_PROMPTS
- `tests/tools/test_lookup_requirements.py` — 11 casos
- `tests/state_machine/test_motos_credito_pipeline.py` — seed validation
- `tests/state_machine/test_behavior_mode_field.py` — Fase 6
- `tests/state_machine/test_motos_flow_e2e.py` — walkthrough 4 pasos del flujo

**Frontend (23 tests):**
- `tests/features/conversations/SystemEventBubble.test.tsx` — variantes + render
- `tests/features/pipeline/PipelineEditor.fields.test.ts` — parsePipeline/serialise roundtrip + validate

**Mockup visual:**
- `.claude/mockups/system-event-bubble-preview.html` — preview servido por el panel Launch (las 7 burbujas + sección stage editor + sección Vision mapping + triggers nuevos).

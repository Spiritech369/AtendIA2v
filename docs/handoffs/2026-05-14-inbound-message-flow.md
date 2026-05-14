# Flujo de un mensaje entrante en AtendIA v2

Author: Claude
Date: 2026-05-14
Status: descriptivo — refleja el estado del código en commit `[siguiente]`

Este documento traza qué pasa entre el momento en que un cliente envía
un WhatsApp y el momento en que AtendIA le responde. Está pensado para
que cualquier persona del equipo pueda entender los puntos de control y
saber dónde tocar cuando algo se comporta raro.

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
[NLU]                                [Composer]                 [Pipeline evaluator]
extrae intent +                      genera la                   mueve la conversación
campos (plan_credito,                respuesta con el            de stage si las reglas
DOCS_*, etc.)                        agente predeterminado       de auto-entrada matchean
                                     + tono + guardrails +
                                     KB filtrado por agente
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

El sidecar Node.js ([core/baileys-bridge/src/baileys.js](../../core/baileys-bridge/src/baileys.js)) está suscrito a `messages.upsert` del socket WhatsApp Web. Por cada mensaje:
- Si `type === 'notify'` y `!fromMe` → es un mensaje del cliente → `POST /api/v1/internal/baileys/inbound`.
- Si `type === 'append'` o `'notify'` con `fromMe` (operador mandó desde su teléfono) → `POST /api/v1/internal/baileys/outbound-echo`.
- Resuelve LIDs (Linked Identity) a teléfonos reales usando un cache local de mappings.

Ambas rutas internas llevan un header `X-Internal-Token` validado contra `BAILEYS_INTERNAL_TOKEN` del backend.

### 2. Persistencia del mensaje

`_persist_inbound` (idéntico en Meta y Baileys salvo el adapter):
- UPSERT en `customers` por `(tenant_id, phone_e164)`.
- SELECT conversación viva (`deleted_at IS NULL`) más reciente para ese cliente; si no existe, INSERT con `current_stage = resolve_initial_stage(tenant)` — esto evita el bug histórico donde nuevas conversaciones caían en un stage inexistente.
- INSERT en `messages` con direction `inbound`, idempotente por `(tenant_id, channel_message_id)` para sobrevivir reintentos del webhook.
- Bump `unread_count` y `last_activity_at`.

### 3. Ramificación post-persistencia

Una vez la fila vive en la BD, varias cosas pasan en paralelo:

- **WebSocket fan-out** (`publish_event`): el dashboard refresca sus listas y abre la conversación si está abierta.
- **Workflows**: `evaluate_event(MESSAGE_RECEIVED)` chequea si algún workflow del tenant tiene un trigger que matchee. Workflows aprobados se encolan en `arq:queue:workflows`.
- **Conversation runner**: el componente que realmente *responde* al cliente. Es el resto de este documento.

### 4. Conversation runner — el corazón

[core/atendia/runner/conversation_runner.py](../../core/atendia/runner/conversation_runner.py) · `ConversationRunner.run_turn`

Es un solo método largo. Su trabajo se divide en 6 fases:

#### 4.1 Short-circuit por `bot_paused`

Si la conversación tiene `bot_paused=True` (porque el operador tomó control vía `/intervene`), el runner inserta un `turn_trace` mínimo y vuelve. No hay NLU, no hay composer, no hay outbound — el humano maneja la respuesta.

#### 4.2 Carga del agente

`_load_agent(conversation_id, tenant_id)`:
- Si la conversación tiene `assigned_agent_id`, carga ese agente.
- Si no, busca el agente `is_default=True` del tenant.
- Si no hay default tampoco, el runner usa los defaults del `tenant_branding.voice` (estilo Phase 3 antiguo).

El agente cargado aporta:
- `tone` → registro emocional del LLM
- `style` → forma de redactar
- `max_sentences` → tope duro de longitud
- `no_emoji` → bandera para el composer
- `goal` → meta del turno, inyectada en `brand_facts.agent_goal`
- `system_prompt` → prompt maestro del operador
- `ops_config.guardrails[]` → reglas duras (cada `active=true` se agrega como bullet en el system prompt bajo "REGLAS QUE NO PUEDES ROMPER")
- `knowledge_config.collection_ids[]` → colecciones del KB a las que tiene acceso

#### 4.3 NLU + Vision en paralelo

`asyncio.gather` para no bloquear:
- **NLU** ([core/atendia/runner/nlu_openai.py](../../core/atendia/runner/nlu_openai.py)): extrae `intent`, `sentiment`, `confidence` y campos como `plan_credito`, `modelo_interes`, `DOCS_INE`, etc. desde el texto. Costo: tokens del prompt + tokens de la respuesta.
- **Vision**: si el mensaje trae attachments (foto de INE, etc.), llama gpt-4o-vision para extraer texto + clasificar el documento. Costo: aparte, persiste en `turn_traces.vision_cost_usd`.

Ambos resultados se fusionan en `extracted_data` y se aplican a `customer.attrs` via `apply_ai_extractions`.

#### 4.4 Estado deterministista (FSM + auto-enter rules)

1. `pick_flow_mode` → decide PLAN / SALES / DOC / OBSTACLE / RETENTION / SUPPORT basado en `pipeline.flow_mode_rules` y la NLU.
2. `process_turn` (orchestrator) → corre el `next_stage` transitioner del pipeline. Devuelve `OrchestratorDecision(next_stage, action, reason)`.
3. **Auto-enter rules**: `evaluate_pipeline_rules` recorre cada stage con `auto_enter_rules.enabled=true` y evalúa sus condiciones contra `customer.attrs` + `extracted_data`. Si alguna matchea, **sobrescribe** el `next_stage` decidido por el FSM. Aquí es donde el operator `docs_complete_for_plan` cierra el loop "todos los docs del plan en ok → Papelería completa".
4. UPDATE `conversations.current_stage` y `conversation_state.stage_entered_at`.

#### 4.5 Tools + Composer

Según la `action` que produjo el orchestrator (`quote`, `lookup_faq`, `search_catalog`, `ask_field`, `escalate_to_human`...) el runner llama herramientas:

- `lookup_faq` y `search_catalog` ahora aceptan `collection_ids` y respetan el filtro del agente. Si el agente tiene `knowledge_config.collection_ids=["uuid1"]`, las queries SQL agregan `WHERE collection_id IN (...)`. Si está vacío, el agente ve todo el KB del tenant.
- `quote` se invoca para cotizaciones tras resolver el SKU vía `search_catalog`.

Los resultados de cada tool se acumulan en `action_payload`, que se pasa al **composer**:

[core/atendia/runner/composer_openai.py](../../core/atendia/runner/composer_openai.py) construye el prompt final con:
- `tone` (incluyendo `bot_name`, `register`, `max_words_per_message`, `use_emojis`)
- `brand_facts` (entre ellos `agent_goal` y `agent_system_prompt` — el system_prompt del operador + sus guardrails activos concatenados)
- `flow_mode` block (MODE_PROMPTS específicos por modo)
- `action_payload` serializado
- Historial recortado a `pipeline.composer.history_turns`

Devuelve `ComposerOutput.messages: list[str]` — el split en N mensajes ya viene del LLM (WhatsApp prefiere mensajes cortos).

#### 4.6 Outbound dispatch

Cada mensaje de `ComposerOutput.messages` se encola en arq via `enqueue_outbound`. El worker `send_outbound` ([core/atendia/queue/worker.py](../../core/atendia/queue/worker.py)) lo toma:
- Decide canal: Baileys si el tenant tiene `tenant_baileys_config.enabled + prefer_over_meta + last_status=connected`; si no, Meta.
- Maneja circuit breaker por tenant (defer si abierto).
- Persiste outbox row, llama al adapter, persiste el mensaje en `messages` con `delivery_status` real, publica `message_sent` por WebSocket.
- Retry exponencial en errores transientes.

El cliente recibe el mensaje en WhatsApp.

### 5. Telemetry y costos

Antes de cerrar el turno, el runner persiste un `turn_trace` con:
- `nlu_input`, `nlu_output`, `nlu_cost_usd`, `nlu_latency_ms`
- `composer_input`, `composer_output`, `composer_cost_usd`, `composer_latency_ms`
- `tool_cost_usd` (embeddings, vision)
- `state_before`, `state_after`, `stage_transition`
- `total_cost_usd`, `total_latency_ms`
- `flow_mode`, `bot_paused`, `errors`

El panel "Monitor" del agente lee estos `turn_traces` agregados via `GET /api/v1/agents/{id}/monitor`.

---

## Mapa de funciones por archivo

| Componente | Archivo | Función principal |
|---|---|---|
| Webhook Meta | `core/atendia/webhooks/meta_routes.py` | `receive_inbound` → `_persist_inbound` |
| Webhook Baileys | `core/atendia/api/baileys_routes.py` | `baileys_inbound`, `baileys_outbound_echo` |
| Sidecar | `core/baileys-bridge/src/baileys.js` | `messages.upsert` listener |
| Persistencia inbound | `core/atendia/webhooks/meta_routes.py` | `_persist_inbound` |
| Pipeline default | `core/atendia/state_machine/default_pipeline.py` | `ensure_default_pipeline`, `DEFAULT_PIPELINE_DEFINITION` |
| Stage inicial | `core/atendia/state_machine/pipeline_loader.py` | `resolve_initial_stage` |
| Runner | `core/atendia/runner/conversation_runner.py` | `ConversationRunner.run_turn` |
| Carga del agente | `core/atendia/runner/conversation_runner.py` | `_load_agent` |
| NLU | `core/atendia/runner/nlu_openai.py` | `extract` |
| Vision | `core/atendia/runner/vision.py` | `analyze_attachments` |
| Flow router | `core/atendia/runner/flow_router.py` | `pick_flow_mode` |
| FSM | `core/atendia/state_machine/orchestrator.py` | `process_turn`, `next_stage` |
| Auto-enter rules | `core/atendia/state_machine/pipeline_evaluator.py` | `evaluate_pipeline_rules`, `evaluate_condition` |
| Tools KB | `core/atendia/tools/lookup_faq.py`, `search_catalog.py` | `lookup_faq`, `search_catalog` (ambos con `collection_ids` filter) |
| Composer | `core/atendia/runner/composer_openai.py` | `OpenAIComposer.compose` |
| Outbound enqueue | `core/atendia/runner/outbound_dispatcher.py` | `enqueue_messages` |
| Worker | `core/atendia/queue/worker.py` | `send_outbound` |
| Adapter Meta | `core/atendia/channels/meta_cloud_api.py` | `MetaCloudAPIAdapter.send` |
| Adapter Baileys | `core/atendia/queue/worker.py` | `_send_via_baileys` |
| Followups | `core/atendia/queue/followup_worker.py` | `poll_followups` (3h + 12h silencio) |
| Workflows | `core/atendia/workflows/engine.py` | `evaluate_event`, `execute_workflow_step` |
| Monitor metrics | `core/atendia/api/agents_routes.py` | `agent_monitor` (route) |

---

## Cómo afecta cada cosa al output

Lista práctica para cuando "el bot no contesta lo que quiero":

| Si quieres cambiar… | Toca este campo del agente | Lo lee… |
|---|---|---|
| Cómo suena (cálido, formal, directo…) | `tone` | `_load_agent` → `Tone.register` |
| Cómo escribe (corto, detallado…) | `style` | `_load_agent` → tone_data |
| Longitud máxima de respuesta | `max_sentences` | `max_words_per_message = max_sentences × 20` |
| Si usa emojis o no | `no_emoji` | `tone_data.use_emojis = "never"` cuando True |
| Meta del turno | `goal` | `brand_facts.agent_goal` |
| Instrucciones libres del operador | `system_prompt` | `brand_facts.agent_system_prompt` |
| Reglas duras ("nunca prometas X") | `ops_config.guardrails[].rule_text` (active=true) | Se concatenan a `agent_system_prompt` bajo bloque "REGLAS QUE NO PUEDES ROMPER" |
| Qué FAQs/catálogo puede consultar | `knowledge_config.collection_ids` | `lookup_faq` / `search_catalog` filtran por esa lista |
| A qué clientes responde | `is_default` (toggle) + `conversation.assigned_agent_id` | `_load_agent` busca asignado, fallback a default |

---

## Punto ciego conocido

- **El nombre del agente NO se inyecta en outbound a WhatsApp como remitente.** WhatsApp Cloud API muestra siempre el nombre del WABA, no del agente. El `agent.name` solo se usa como `bot_name` dentro del prompt del LLM y como referencia interna en el dashboard.
- **Extracción de campos** del agente está suprimida — la verdad está en `pipeline.documents_catalog` + `customer_fields_definitions`. Editas en el editor del pipeline.
- **`active_intents`** del agente sí se aplica: si el NLU detecta un intent que NO está en la lista, el runner lo filtra a "none". Esto pasa antes del orchestrator.
- **`return_to_flow`** todavía no se consume.
- **`behavior_mode`, `status`, `version`, `dealership_id`, `branch_id`** son metadata informativa para el dashboard; no afectan al runner.

---

## Lugares para mirar cuando algo falla

| Síntoma | Mirar primero |
|---|---|
| El bot no responde nada | logs `atendia_backend` por errores en `_load_agent`, NLU timeout, composer fallback. Verificar `bot_paused`. |
| El bot responde con tono raro | `agent.tone`, `agent.style`, y especialmente `agent.system_prompt` — vista previa los expone explícitamente. |
| El bot dice algo prohibido | `agent.ops_config.guardrails` — agregar regla o subir severity. |
| El bot no encuentra una FAQ que sí está en KB | revisar `agent.knowledge_config.collection_ids` y la `collection_id` de la FAQ. |
| La conversación no avanza de stage | pipeline.stages[].auto_enter_rules — usar el evaluator console (próxima feature) o leer logs `resolve_initial_stage`. |
| Mensajes que mandé desde mi teléfono no aparecen en AtendIA | sidecar Baileys: verificar que `messages.upsert` con `fromMe=true` llega; rebuild de `baileys-bridge` si el código no se cargó. |
| WhatsApp Cloud API no recibe el mensaje | logs `atendia_worker` por errores en `send_outbound`; verificar `meta_access_token` + `phone_number_id` del tenant. |

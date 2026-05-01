# Diseño AtendIA v2 — Asistente de Ventas WhatsApp Multi-Tenant

> **Estado:** diseño aprobado, pendiente de plan de implementación.
> **Fecha:** 2026-04-30
> **Autor:** brainstorm conjunto (Frank + Claude)
> **Reemplaza:** arquitectura actual de `ai-engine/` + `gateway/` + Baileys

---

## 1. Contexto y motivación

El sistema actual (v1) acumuló módulos sin límites de responsabilidad claros. Síntomas observados en producción:

- **Estructural:** 24 servicios en `ai-engine/` con responsabilidades solapadas (`evaluator` + `pipeline_evaluator` + `conversation_governor`, `flow_engine` + `workflow_runner` + `workflow_engine`, `composer` + `action_engine`). Agregar features rompe otras.
- **Conversacional:** alucinaciones, no sigue el flujo de ventas, pierde contexto entre turnos, no maneja ambigüedad.
- **Operacional:** Baileys inestable, mensajes que no se actualizan en tiempo real en el panel, logs dispersos, integraciones frágiles.
- **Multi-tenant débil:** lógica de Dinamo escrita en código (`dinamo_sales_flow.py`, migraciones 021–024 específicas), no en configuración.

El v2 ataca estos problemas desde la raíz con una arquitectura nueva, manteniendo el frontend React existente y reescribiendo gateway + ai-engine desde cero, además de reemplazar Baileys por WhatsApp Cloud API oficial de Meta.

---

## 2. Visión

> **Tesis del rediseño:** AtendIA no necesita "más IA"; necesita una arquitectura donde la IA esté encerrada en los lugares correctos. Que pueda manejar lo impredecible, sí, pero sin tener permiso de romper el flujo, inventar datos o decidir cosas críticas sin estado verificable.

Sistema multi-tenant que conduce conversaciones de venta por WhatsApp con tres propiedades innegociables:

1. **Predecible donde importa** — el flujo de ventas no se sale de los rieles.
2. **Flexible donde se necesita** — maneja preguntas raras, ambigüedad y mensajes fuera de tema sin romperse.
3. **Trazable y barato** — cada turno se puede inspeccionar; cada decisión tiene costo conocido.

Producto comparable: lo que respond.io es como plataforma, pero con el motor de IA de ventas resuelto y verticalizado por tenant via configuración (no via código).

---

## 3. Principios de diseño

| # | Regla | Por qué |
|---|---|---|
| 1 | Estado vive en Postgres, no en prompts | Si el prompt es la memoria, pierdes contexto cada vez que truncas |
| 2 | Determinismo donde importa, LLM donde se necesita | El flujo es código; la redacción es LLM. No al revés |
| 3 | Configuración como datos, no como código | Cada tenant es un row, no un archivo `.py` |
| 4 | Tools tipadas + acciones acotadas | El LLM no improvisa estructura; solo elige entre N acciones permitidas |
| 5 | Adaptadores delgados | Canal y proveedor LLM son intercambiables sin tocar el core |
| 6 | Trazabilidad por turno | Cada decisión de cada turno queda registrada en `turn_traces` |
| 7 | Costo consciente | Cada llamada LLM tiene presupuesto; cada template de Meta tiene contador |
| 8 | Una responsabilidad por servicio | Si dos servicios "casi hacen lo mismo", uno sobra |

---

## 4. Decisiones tomadas en el brainstorm

| Decisión | Elección | Alternativas descartadas |
|---|---|---|
| Estrategia general | **Núcleo nuevo + migración controlada** (no greenfield total) | Greenfield total, refactor in-place, doc estratégico sin código |
| Alcance del rediseño | Backend completo nuevo (gateway + ai-engine), frontend evoluciona | Reescribir frontend también, refactor parcial |
| Orden de construcción | **Datos → Transporte → IA → Observabilidad → UI** | IA primero (ego de implementador), Transporte primero sin estado |
| Filosofía del motor | Orquestador híbrido (rieles + cerebro acotado) | Agente LLM puro, máquina de estados pura |
| Transporte WhatsApp | Meta Cloud API directo | Baileys, BSPs (Twilio, Gupshup, 360dialog) |
| Modelo NLU | `gpt-4o-mini` con JSON mode | Claude Haiku (descartado por preferencia), modelos open-source |
| Modelo composer | `gpt-4o` | gpt-4o-mini (calidad insuficiente para redacción comercial) |
| Almacenamiento estado | Postgres (verdad) + Redis (caché y pub/sub) | Solo Redis, solo Postgres |
| Tenant config | Data-driven (JSONB en DB) | Archivos YAML, código Python |

### Justificación del orden Datos → Transporte → IA → Observabilidad → UI

- **Datos primero** porque sin una sola fuente de verdad (conversación, contacto, estado, eventos, contexto, acciones) cualquier capa que pongas encima hereda la inconsistencia. El v1 sufre exactamente de esto.
- **Transporte segundo** porque "los mensajes lleguen, salgan y se actualicen bien" es ortogonal a la inteligencia. Si la transmisión es inestable, agregar IA no la arregla, la oculta.
- **IA tercero** porque ya tiene un sustrato confiable donde escribir su estado y un canal funcional para hablar. La IA es la parte más inestable del sistema; conviene que se monte sobre lo más estable.
- **Observabilidad cuarto** ("sistema nervioso", no lujo) porque sin saber por qué la IA respondió X, no puedes corregirla. Debe llegar antes que el frontend porque es prerrequisito para iterar la IA.
- **UI quinto** porque con un backend ordenado y observable, las pantallas son refactor mecánico, no arqueología.

---

## 5. Arquitectura de alto nivel

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend React                          │
│   Inbox · Pipeline · Tenant Config · Debug Panel · Métricas │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST + WebSocket (auth tenant-scoped)
┌──────────────────────────▼──────────────────────────────────┐
│                  Gateway (Node 20 + TS)                     │
│                                                             │
│  webhookReceiver · turnCoordinator · outboundDispatcher     │
│  realtimeBroadcaster · authMiddleware · tenantResolver      │
│  REST API · WebSocket server · Worker queue (BullMQ)        │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTP/JSON con contrato versionado
┌──────────────────────────▼──────────────────────────────────┐
│              AI Engine (Python 3.12 + FastAPI)              │
│                                                             │
│   ┌──────────┐    ┌──────────────┐    ┌──────────────┐      │
│   │   NLU    │───▶│ Orchestrator │───▶│  Composer    │      │
│   │ Extractor│    │ (state mach) │    │ (LLM writer) │      │
│   └──────────┘    └──────┬───────┘    └──────────────┘      │
│        │                 │                    ▲             │
│        │            ┌────▼────┐               │             │
│        │            │  Tools  │───── data ────┤             │
│        │            │ (typed) │               │             │
│        │            └────┬────┘               │             │
│        └─────────────────┴────────────────────┘             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  PostgreSQL (state, config, history) + Redis (cache, p/s)   │
└──────────────────────────▲──────────────────────────────────┘
                           │
                  ┌────────┴─────────┐
                  │  Meta Cloud API  │
                  │     (WhatsApp)   │
                  └──────────────────┘
```

### Repositorios

- `atendia-frontend` — React, ya existe, evoluciona con nuevas pantallas contra Gateway v2.
- `atendia-gateway` — Node/TS, **nuevo**.
- `atendia-ai-engine` — Python/FastAPI, **nuevo**.
- `atendia-shared-contracts` — JSON Schema con tipos generados a TS y Python, **nuevo**.

---

## 6. Motor conversacional (núcleo)

### 6.1 NLU Extractor

Una llamada LLM por turno, modelo `gpt-4o-mini`, JSON mode estricto.

**Input:**
- Mensaje actual del cliente.
- Últimos 2–3 turnos para contexto.
- Stage actual de la conversación.
- Catálogo mínimo de intents/entities posibles del tenant.

**Output (Pydantic schema fijo):**

```python
class NLUResult(BaseModel):
    intent: Literal["greeting", "ask_info", "ask_price", "buy",
                    "schedule", "complain", "off_topic", "unclear"]
    entities: dict[str, ExtractedField]
    sentiment: Literal["positive", "neutral", "negative"]
    confidence: float  # 0.0–1.0 global
    ambiguities: list[str]
```

**Regla clave:** si `confidence < 0.7` o hay `ambiguities`, el orquestador NO ejecuta acción de venta. Pregunta de confirmación primero. Aquí muere la alucinación.

### 6.2 Orchestrator (sin LLM, código puro)

Es una máquina de estados parametrizada por tenant. Recibe `(state, nlu_result)` y decide:

1. ¿Hay ambigüedad pendiente? → acción `ask_clarification`.
2. ¿El stage actual permite esta intent? → ejecutar acción correspondiente.
3. ¿Se cumplen condiciones de transición? → cambiar de stage.
4. ¿No hay match? → acción de fallback (FAQ → escalación humana).

Stages típicos (configurables por tenant):

```
greeting → qualify → catalog_browse → quote →
negotiate → close → post_sale_followup
                            │
                            └─→ escalate_to_human (en cualquier punto)
```

Cada stage define:
- `actions_allowed`: subset de tools que el orquestador puede ejecutar aquí.
- `required_fields`: datos mínimos que necesita extraer antes de avanzar.
- `transitions`: condiciones para pasar al siguiente stage.
- `timeout`: si pasa X horas sin respuesta, programa follow-up.

### 6.3 Tools (funciones tipadas, sin LLM)

Conjunto cerrado, versionado, validado con Pydantic:

```python
@tool
def search_catalog(tenant_id: str, query: str,
                   filters: CatalogFilters) -> list[Product]: ...

@tool
def quote(tenant_id: str, product_id: str,
          options: QuoteOptions) -> Quote: ...

@tool
def lookup_faq(tenant_id: str, question: str,
               top_k: int = 3) -> list[FAQMatch]: ...

@tool
def book_appointment(tenant_id: str, customer_id: str,
                     slot: datetime) -> Booking: ...

@tool
def escalate_to_human(conversation_id: str, reason: str) -> None: ...

@tool
def schedule_followup(conversation_id: str, when: datetime,
                      template_id: str | None) -> None: ...
```

Cada tool:
- Valida inputs con Pydantic.
- Loggea cada llamada en `tool_calls`.
- Retorna outputs estructurados (nunca strings libres).
- Es testeable en aislamiento.

### 6.4 Composer (LLM redactor, no decisor)

Una llamada LLM por turno, modelo `gpt-4o`, sin tools.

**Input:**
- Stage actual.
- Acción ejecutada por orquestador + su resultado (ej: lista de productos).
- Tono del tenant (informal mexicano, formal, etc.).
- Últimos 2 turnos para coherencia tonal.

**Output:** `list[str]` — 1 a 3 mensajes cortos, listos para enviar. NO decide qué decir, solo CÓMO decirlo.

Si el envío está fuera de la ventana de 24h, el composer NO redacta. Devuelve `template_id` + parámetros, y el gateway envía el template aprobado.

### 6.5 Memoria de conversación (DB-backed)

`conversation_state` por conversación:

```json
{
  "conversation_id": "uuid",
  "current_stage": "qualify",
  "extracted_data": {
    "nombre": "Juan",
    "ciudad": "CDMX",
    "interes_modelo": "Italika 150Z",
    "presupuesto_max": 35000
  },
  "pending_confirmation": null,
  "last_intent": "ask_price",
  "stage_entered_at": "2026-04-30T14:23:00Z",
  "followups_sent_count": 0,
  "total_cost_usd": 0.0234
}
```

El prompt de cada llamada LLM se reconstruye en cada turno desde este state + últimos N mensajes. Nunca confiamos en que el LLM "recuerde".

---

## 7. Configuración por tenant (data-driven)

### 7.1 Pipeline definition

Almacenada como JSONB en `tenant_pipelines`:

```json
{
  "version": 3,
  "stages": [
    {
      "id": "qualify",
      "required_fields": ["interes_producto", "ciudad"],
      "actions_allowed": ["ask_field", "lookup_faq", "search_catalog"],
      "transitions": [
        {"to": "quote", "when": "all_required_fields_present AND intent==ask_price"},
        {"to": "escalate", "when": "sentiment==negative AND turn_count>3"}
      ],
      "timeout_hours": 6,
      "timeout_action": "schedule_followup_template:lead_warm_v2"
    }
  ],
  "tone": {
    "register": "informal_mexicano",
    "use_emojis": "sparingly",
    "max_words_per_message": 40
  },
  "fallback": "escalate_to_human"
}
```

### 7.2 Otras tablas de config por tenant

- `tenant_catalogs` — productos/SKUs/precios estructurados, indexables, con embeddings opcionales.
- `tenant_faqs` — preguntas + respuestas + embeddings (`text-embedding-3-small`).
- `tenant_templates_meta` — templates aprobados (`template_id`, `category`, `language`, `cost_estimate_usd`).
- `tenant_tools_config` — qué tools están habilitadas, qué endpoints externos usan.
- `tenant_branding` — nombre del bot, voice, mensajes default.

**Onboarding nuevo tenant = crear ~6 filas + subir catálogo CSV.** Cero código.

### 7.3 Migración de "Dinamo en código" → "Dinamo en datos"

`dinamo_sales_flow.py` se vuelve:
- Pipeline JSON con sus stages reales.
- Catalog populado desde su CSV de motos.
- FAQs migradas de seeds → tabla.
- Templates de Meta migradas.

Si en el futuro entra "Yamaha-Sur" como tenant nuevo, son los mismos 6 inserts. Cero archivos `.py` nuevos.

---

## 8. Transporte WhatsApp (Meta Cloud API)

### 8.1 Adapter

Interfaz canónica en `gateway/src/channels/whatsappMeta.ts`:

```ts
interface ChannelAdapter {
  receiveWebhook(req: Request): Promise<IncomingMessage[]>
  sendMessage(msg: OutgoingMessage): Promise<DeliveryReceipt>
  sendTemplate(t: TemplateMessage): Promise<DeliveryReceipt>
  validateSignature(req: Request): boolean
}
```

Si en el futuro queremos meter Twilio o Instagram DM, implementan la misma interfaz. El core no se entera.

### 8.2 Anti-fragilidad

- **Webhook deduplication:** Redis `SET msg:{id} 1 EX 86400 NX`. Si ya existe, ignora.
- **Idempotency en envíos:** cliente genera `idempotency_key`, gateway no envía dos veces.
- **Reintentos con backoff exponencial:** 1s, 2s, 4s, 8s. Después de 4 fallos → marca `failed` y notifica.
- **Circuit breaker:** si Meta falla > 10 veces en 1 min, abre circuito, encola mensajes, alerta.
- **Rate limit awareness:** lee headers de Meta, throttlea automático.
- **Status callbacks:** `delivery_status` en `messages`, visible en panel.

### 8.3 Manejo de templates (follow-ups fuera de 24h)

Tabla `tenant_templates_meta`:

```
template_id | name | category | language | body_template | est_cost_mxn | last_approved_at
```

Composer, cuando detecta envío fuera de ventana:
- Busca template por `intent + stage` en config del tenant.
- Si existe → envía template, descuenta presupuesto del tenant.
- Si no existe → marca conversación `requires_human_followup`, no inventa.

**Cap configurable:** "máximo N templates en la vida del lead" (configurable por tenant).

---

## 9. Realtime + Panel

### 9.1 Flujo de eventos

```
Mensaje entrante de Meta
  → webhookReceiver inserta en `messages`
  → publica en Redis: "tenant:{tid}:conv:{cid}:new_message"
  → WebSocket subscribers (paneles abiertos en frontend) reciben
  → frontend re-renderiza inbox + conversación abierta
```

Mismo patrón para mensajes salientes, cambios de stage, escalaciones, status updates de delivery.

### 9.2 Por qué soluciona "mensajes no se actualizan"

El problema actual es polling o WebSocket roto. El nuevo:
- Una sola fuente de eventos (Redis Pub/Sub).
- Cada cambio de estado emite evento, no hay "el panel pregunta cada 5 seg".
- Auth tenant-scoped en WS: un usuario solo ve eventos de su tenant.
- Reconexión automática con resync: si el WS cae, al reconectar pide deltas desde `last_seen_at`.

---

## 10. Observabilidad

### 10.1 `turn_traces` — el corazón del debug

Cada turno (cliente envía → bot responde) genera un row:

```sql
CREATE TABLE turn_traces (
  id uuid PRIMARY KEY,
  conversation_id uuid,
  tenant_id uuid,
  turn_number int,

  inbound_message_id uuid,
  inbound_text text,

  nlu_input jsonb,
  nlu_output jsonb,
  nlu_model text,
  nlu_tokens_in int,
  nlu_tokens_out int,
  nlu_cost_usd numeric(10,6),
  nlu_latency_ms int,

  state_before jsonb,
  state_after jsonb,
  stage_transition text,

  tool_calls jsonb,

  composer_input jsonb,
  composer_output jsonb,
  composer_model text,
  composer_tokens_in int,
  composer_tokens_out int,
  composer_cost_usd numeric(10,6),
  composer_latency_ms int,

  outbound_messages jsonb,

  total_cost_usd numeric(10,6),
  total_latency_ms int,

  errors jsonb,
  created_at timestamptz
);
```

### 10.2 Debug Panel (frontend)

Por conversación, muestra timeline visual:
- Mensaje cliente → NLU output (intent + confidence + entities) → orquestador (stage antes/después + decisión) → tools llamadas → composer output → mensaje saliente.
- Cada nodo es expandible (ver JSON crudo).
- Costo y latencia por turno y agregado por conversación.

Esto resuelve "no sé dónde se echó a perder todo": abres la conversación rota, ves exactamente en qué paso se descarriló.

### 10.3 Métricas agregadas

Dashboards (Grafana o tab interno):
- Costo LLM por tenant / día / por conversación cerrada.
- Embudo de stages: cuántas conversaciones pasan de `qualify` → `quote` → `close`.
- Latencia P50/P95 por componente.
- Tasa de escalación a humano (por tenant, por stage).
- Templates enviados + tasa de respuesta + costo por respuesta.
- Confidence distribution del NLU (si baja, hay deriva).

---

## 11. Modelo de datos (alto nivel, ~15 tablas core)

```
tenants (id, name, plan, status, meta_business_id, ...)
tenant_users (tenant_id, user_id, role)
tenant_pipelines (tenant_id, version, definition_jsonb, active)
tenant_catalogs (tenant_id, sku, name, attrs_jsonb, embedding)
tenant_faqs (tenant_id, question, answer, embedding)
tenant_templates_meta (tenant_id, template_id, category, body, cost_est)
tenant_tools_config (tenant_id, tool_name, enabled, config_jsonb)
tenant_branding (tenant_id, voice, emoji_policy, max_msg_words)

customers (id, tenant_id, phone, name, attrs_jsonb)
conversations (id, tenant_id, customer_id, channel, status, current_stage)
conversation_state (conversation_id, extracted_data, pending_conf, ...)
messages (id, conversation_id, direction, text, meta_msg_id, delivery_status, sent_at)

turn_traces (... ver §10.1)
tool_calls (turn_trace_id, tool_name, input, output, latency_ms)
followups_scheduled (conversation_id, run_at, template_id, status)
human_handoffs (conversation_id, reason, assigned_user_id, status)
```

Migraciones versionadas con `node-pg-migrate` o `alembic`, todas reversibles.

---

## 12. Estrategia de LLMs y costos

| Componente | Modelo | Tokens típicos | Costo/turno |
|---|---|---|---|
| NLU Extractor | `gpt-4o-mini` | 200 in / 100 out | ~$0.0001 |
| Orchestrator | (sin LLM) | — | $0 |
| Tools | (sin LLM) | — | $0 |
| Composer | `gpt-4o` | 500 in / 100 out | ~$0.0019 |
| FAQ embeddings | `text-embedding-3-small` | (precomputado) | ~$0 |
| **Total por turno** | | | **~$0.002 USD** |

Conversación promedio (~30 turnos hasta cierre o abandono): **~$0.06 USD en LLM**.
1,000 conversaciones/mes: **~$60 USD en LLM** (más Meta WhatsApp).

**Presupuesto por tenant** configurable: si un tenant supera $X USD/día, se alerta y opcionalmente pausa.

El diseño es **agnóstico al modelo**. Si un modelo más nuevo es mejor/más barato, se cambia en una variable de entorno por componente. Recomendación: arrancar con gpt-4o-mini + gpt-4o (probados, baratos, JSON mode estable) y reevaluar cada trimestre.

---

## 13. Roadmap de migración (Núcleo nuevo + migración controlada)

Cinco fases lineales más una fase 0 de setup y una fase de cutover. Cada fase entrega algo verificable de forma aislada antes de pasar a la siguiente. **Migración controlada**: el sistema viejo sigue corriendo en producción hasta que el nuevo demuestre paridad o mejor en métricas.

### Fase 0 — Setup (1 semana)

**Objetivo:** infraestructura mínima para empezar a construir.

- Repos creados: `atendia-gateway`, `atendia-ai-engine`, `atendia-shared-contracts`.
- CI básico (lint, type-check, tests) en cada repo.
- Doc de diseño aprobado y commiteado.
- Contratos JSON Schema iniciales (mensaje canónico, evento canónico, estado canónico).
- Decisión de hosting (mismo VPS / nuevo / staging separado).

**Verificación:** push a main dispara CI, todo verde.

### Fase 1 — Núcleo conversacional (2–3 semanas)

**Objetivo:** una sola fuente de verdad para conversación, contacto, estado, eventos, contexto y acciones. State machine ejecutándose **sin LLM**, con flujos canned.

- Schema Postgres definitivo: `tenants`, `customers`, `conversations`, `conversation_state`, `messages`, `events`, `turn_traces`, `tool_calls`, `tenant_pipelines`, `tenant_catalogs`, `tenant_faqs`, `tenant_templates_meta`, `tenant_tools_config`, `tenant_branding`, `followups_scheduled`, `human_handoffs`.
- Migraciones reversibles (`alembic` o `node-pg-migrate`).
- Motor de state machine (código puro): consume `tenant_pipelines` JSONB, transiciona, valida `required_fields`.
- Tools tipadas con stubs (firmas + Pydantic, retornan datos canned).
- Event store: cada cambio de estado emite evento persistido.

**Verificación:** suite de fixtures de conversación canned (ej: "qualify completo → quote → close") pasa por el state machine y produce los eventos esperados, sin tocar LLM ni WhatsApp.

### Fase 2 — Transporte WhatsApp (2 semanas)

**Objetivo:** los mensajes lleguen, salgan y se actualicen bien. Sin IA todavía.

- Adapter `whatsappMetaAdapter` (envío + recepción + validación HMAC).
- Webhook receiver con deduplicación por `message_id` (Redis).
- Cola de outbound (BullMQ) con reintentos exponenciales y circuit breaker.
- Status callbacks de Meta → actualización de `delivery_status`.
- Realtime: Redis Pub/Sub + WebSocket server con auth tenant-scoped.
- Bot "echo" minimal: responde "recibí: X" para validar el ciclo completo.

**Verificación:** mandar 100 mensajes desde un número real, todos llegan, todos se almacenan, todos los status updates se reflejan en el panel en < 2 seg.

### Fase 3 — Motor IA híbrido (3 semanas)

**Objetivo:** la IA encerrada en lugares correctos. NLU extractor + composer + tools tipadas, todo conectado al estado de Fase 1 y al transporte de Fase 2.

- NLU Extractor (`gpt-4o-mini`, JSON mode) con schema Pydantic estricto.
- Orchestrator decide acciones permitidas por stage; ambigüedad < 0.7 confidence dispara `ask_clarification`.
- Tools reales: `search_catalog`, `quote`, `lookup_faq`, `book_appointment`, `escalate_to_human`, `schedule_followup`.
- Composer (`gpt-4o`) redacta dentro de bounds; fuera de 24h devuelve `template_id`.
- Pipeline de Dinamo cargado en `tenant_pipelines` (migración del `dinamo_sales_flow.py` actual a JSONB).
- Catálogo de motos de Dinamo migrado a `tenant_catalogs` con embeddings.
- FAQs de Dinamo migradas a `tenant_faqs`.

**Verificación:** suite de E2E con 30+ conversaciones reales históricas de Dinamo. Output del v2 comparable o mejor al output que dio v1, sin alucinaciones, sin perder contexto.

### Fase 4 — Sistema nervioso (debug panel + reglas) (2 semanas)

**Objetivo:** ver por qué respondió, qué datos usó, qué acción eligió, qué falló. **No es lujo, es prerrequisito para iterar la IA en producción.**

- Endpoint Gateway: `GET /api/conversations/:id/turn-traces`.
- Endpoint Gateway: `GET /api/tenants/:id/pipeline` (lectura del JSONB) y `PUT` (con validación).
- Frontend: timeline visual de cada conversación (mensaje → NLU → orchestrator → tools → composer → output) expandible a JSON crudo.
- Frontend: editor JSON de `tenant_pipelines` con validación en cliente.
- Frontend: dashboard de métricas agregadas (costo, latencia, embudo, tasa escalación).

**Verificación:** abrir cualquier conversación con problema y ubicar en menos de 60 segundos en qué paso se descarriló.

### Fase 5 — Frontend e integraciones (2 semanas)

**Objetivo:** paridad funcional con el v1 + mejoras. Con backend ordenado, el frontend ahora es refactor mecánico.

- Inbox: rehacer contra Gateway v2 (REST + WS).
- Pipeline UI: vista visual del embudo con drag-drop (opcional).
- Tenant config UI: catálogo, FAQs, templates, branding (CRUD básico).
- Integración Google Sheets (export de leads/conversaciones).
- Integración calendario (book_appointment via Calendly o Google Calendar).
- Onboarding asistido para tenant nuevo (wizard de 4–5 pasos).

**Verificación:** un usuario operador puede atender Dinamo desde el panel v2 sin extrañar funcionalidad del v1.

### Fase 6 — Migración controlada de Dinamo (2 semanas)

**Objetivo:** Dinamo en producción en v2, v1 todavía corriendo en paralelo como fallback.

- Feature flag por tenant: `tenant.engine_version = 'v2'`.
- Routing de webhook: si flag = v2, dirige a Gateway v2; si v1, al sistema viejo.
- Comparación métrica diaria: tasa de cierre, costo por conversación, latencia, escalación humana.
- Si las métricas se degradan, flip flag a v1 sin downtime.

**Verificación:** 2 semanas con métricas v2 ≥ v1 dispara aprobación de cutover.

### Fase 7 — Cutover Dinamo + tenants restantes (1 semana por tenant)

**Objetivo:** apagar v1 para Dinamo, migrar tenants restantes uno por uno con la misma estrategia.

- Apagar webhook v1 para Dinamo.
- Para cada tenant restante: migrar config (1–3 días) + soft launch (1 sem) + cutover (1 día).

---

**Total a producción para Dinamo:** ~13–14 semanas (1 dev full-time).
**Total para apagar v1 completamente:** depende del número de tenants restantes (~1 semana por tenant).

---

## 14. Anti-patrones explícitos (lo que NO repetimos del v1)

1. ❌ Servicios con responsabilidad solapada — **una función, un dueño**.
2. ❌ Lógica de tenant específico en código — **todo via config**.
3. ❌ Estado de conversación en prompts — **Postgres es la verdad**.
4. ❌ LLM tomando decisiones de flujo — **el orquestador decide, el LLM redacta**.
5. ❌ Baileys o cualquier stack no oficial de WhatsApp.
6. ❌ "Engine" sin trace por turno.
7. ❌ Migraciones no reversibles.
8. ❌ Acoplamiento directo gateway↔ai-engine — **HTTP API contractual versionada**.
9. ❌ Polling para realtime — **eventos Pub/Sub**.
10. ❌ Logs sin correlation_id — **cada turno tiene `trace_id` que cruza todo**.

---

## 15. Fuera de alcance del v2 inicial (YAGNI)

- Multi-canal (Instagram, web, email) — se agrega después como adapter, el core ya lo soporta.
- Builder visual de pipelines en UI — primera versión es JSON editable; UI gráfica es v2.1.
- Marketplace de templates — innecesario hasta tener 10+ tenants.
- A/B testing de prompts — nice-to-have, no bloqueante.
- Voice notes / multimedia avanzado — primera versión solo texto + imágenes simples.
- Self-service tenant onboarding — primero onboardeas a mano, automatizas después.

---

## 16. Riesgos identificados

| Riesgo | Mitigación |
|---|---|
| Migración de Dinamo introduce regresión en conversiones | Soft launch detrás de feature flag con métricas comparativas |
| Costo LLM se dispara con un tenant abusivo | Presupuesto por tenant + auto-pausa al superar |
| Templates de Meta se rechazan al aprobarse | Reusar catálogo de templates ya aprobados de Dinamo; nuevos templates con review interno antes de submit |
| Verificación de tenants nuevos en Meta toma 1–3 días | Onboarding asincrónico con estado claro en UI |
| Latencia LLM sumada (NLU + Composer) supera 3s | Llamadas paralelas donde es posible; circuit breaker; fallback a respuesta canned |
| Schema JSONB de pipeline difícil de versionar | Validación estricta con Pydantic + migración de versiones via script |

---

## 17. Próximo paso

Cerrado este diseño, el siguiente entregable es un **plan de implementación detallado de la Fase 1 (Núcleo conversacional)** con tareas verificables, ordenadas, con criterios de aceptación por cada una.

Por qué arrancar planificando Fase 1 y no todas las fases:
- Es la fase que toca el modelo de datos, decisión más cara de revertir después.
- Las fases 2–5 dependen del schema y los contratos que salgan de aquí.
- Planificar en bloques de una fase respeta el principio "cimientos antes de muros".

Ese plan se generará con la skill `superpowers:writing-plans` cuando se decida arrancar la implementación.

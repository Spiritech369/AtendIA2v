# AtendIA v2 — Fase 3c.2: Router determinístico + flow v1 (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT) — Design

**Status:** Approved 2026-05-06. Pending implementation plan (writing-plans skill).
**Branch:** `feat/phase-3c2-router-flow-modes`
**Predecessor:** Phase 3c.1 (datos reales, tag `phase-3c1-datos-reales`)
**Successor planned:** Phase 3d (follow-ups + outbound multimedia + templates)

---

## 1. Objetivo

Trasladar el v1 prompt de Dinamo (`docs/Prompt master.txt`) a la arquitectura AtendIA v2 con paridad funcional completa: 6 modos conversacionales (PLAN, SALES, DOC, OBSTACLE, RETENTION, SUPPORT), routing determinístico per-turn, integración real de OpenAI Vision para clasificación de imágenes y validación de documentos, y persistencia estructurada de campos extraídos.

El piloto de Dinamo debe poder correr end-to-end con 3c.2 mergeado: PLAN MODE asigna plan, SALES MODE cotiza con datos reales del catálogo (3c.1), DOC MODE recibe imágenes y las clasifica con Vision, OBSTACLE/RETENTION manejan objeciones temporales y de cierre, y SUPPORT sirve preguntas generales vía los FAQs ingestados en 3c.1.

---

## 2. Decisiones de diseño (resumen)

| # | Decisión | Elección | Alternativas descartadas |
|---|---|---|---|
| 1 | Routing | **100% determinístico** — keywords + state + tipo de mensaje | Router LLM puro; híbrido det+LLM |
| 2 | Lista de keywords (OBSTACLE/RETENTION) | **`tenant_pipelines.definition.flow_mode_rules` JSONB** | Hardcoded en código |
| 3 | SUPPORT mode | **Fallback explícito** (último rule) | Estado null/missing |
| 4 | `funnel_stage` (PLAN→SALES→DOC→CLOSE) | **Derivado por función pura sobre `extracted_data`** | Campo persistido con transiciones |
| 5 | Vision API | **Incluida en 3c.2** (DOC MODE real) | Diferida a 3c.3 |
| 6 | Vision timing | **Paralelo con NLU** vía `asyncio.gather` | Secuencial; bloqueante |
| 7 | Vision input | **Sin hint sesgado** (`expected_doc` removido) | Hint para "mejor clasificación" |
| 8 | Composer architecture | **6 prompts grandes por modo (Option A)** — refactor de `composer_prompts.py` | Acciones finas; híbrido modo+acción |
| 9 | Field schema | **Pydantic `ExtractedFields` hardcoded** en código | JSONB config-driven; híbrido |
| 10 | Persistencia de extracted | **Conversation-scoped único** (`conversation_state.extracted_data`) | Bicapa Customer-sticky + Conversation |
| 11 | Tracking de docs | **Flags booleanos `docs_*`** + función `next_pending_doc()` | Lista ordenada mutable; scalar `next_doc` |
| 12 | NLU intents | **Sin cambios** (5 actuales) — `pending_confirmation` maneja binarias; mode prompts manejan objeciones internamente | +OBJECTION, +CONFIRM, +DENY |
| 13 | Multi-message | **`max_messages=2`** (status quo) | 1 / 3 |
| 14 | Normalización de input | **Solo en router keyword matching** (lowercase + strip accents, ambos lados) | NLU/Composer también |
| 15 | Brand facts | **`tenant_branding.default_messages.brand_facts` JSONB**, inyectado solo en modos que lo usan | Inyectado en todo prompt |
| 16 | Handoff | **`HandoffSummary` Pydantic** persistido en `human_handoffs.payload JSONB` | Texto libre |
| 17 | Follow-ups (3h/12h/24h reminders) | **Out of scope** — defer a Phase 3d | Incluido en 3c.2 |

---

## 3. Arquitectura

### 3.1 Diagrama del turno

```
┌──────────────────────────────┐
│  Webhook (Meta Cloud API)    │  ← inbound message (text or text+attachment)
└──────────┬───────────────────┘
           │
           │ Message{text?, attachments?}
           ▼
┌──────────────────────────────┐
│  ConversationRunner.run_turn │
└──────────┬───────────────────┘
           │
           ├──── 1. Load pipeline + state (existing)
           │
           ├──── 2. asyncio.gather:
           │     ┌──────────────┐  ┌────────────────────┐
           │     │ NLU.classify │  │ Vision.classify_   │
           │     │ (text)       │  │ image (if attach)  │
           │     └──────┬───────┘  └─────────┬──────────┘
           │            │                    │
           │            ▼                    ▼
           │     NLUResult            VisionResult
           │
           ├──── 3. Merge entities into state_obj
           │
           ├──── 4. Router (deterministic):
           │     pick_flow_mode(rules, state, nlu, vision, normalized_text)
           │     → "PLAN" | "SALES" | "DOC" | "OBSTACLE" |
           │       "RETENTION" | "SUPPORT"
           │
           ├──── 5. Mode-specific prep (tools, if needed):
           │     if mode == "SALES": resolve sku via search_catalog
           │     if mode == "SALES": run quote()
           │     if mode == "SUPPORT": run lookup_faq() with embedding
           │     if mode == "DOC": vision_result already computed
           │     other modes: no tools
           │
           ├──── 6. Compose:
           │     prompt = MODE_PROMPTS[mode]
           │     ComposerInput(mode, action_payload, extracted_data,
           │                   tone, brand_facts, vision_result, ...)
           │     → ComposerOutput(messages: list[str])
           │
           ├──── 7. Persist turn_trace
           │     (incluye flow_mode, vision_cost_usd, vision_latency_ms)
           │
           └──── 8. Enqueue outbound (existing)
```

### 3.2 Capas tocadas

| Capa | Cambios |
|---|---|
| `contracts/` | Nuevo: `ExtractedFields` Pydantic, `FlowMode` enum, `HandoffSummary` Pydantic, `Attachment` en `Message`, `VisionResult` |
| `db/models/` | `turn_traces.flow_mode` (varchar), `turn_traces.vision_cost_usd` (numeric), nada en `tenant_pipelines` (solo el JSONB cambia su shape) |
| `db/migrations/` | Migración 015 (`flow_mode + vision_cost_usd`) |
| `runner/` | `flow_router.py` nuevo (router determinístico), refactor `conversation_runner.py` (paralelo NLU+Vision, dispatch por modo), refactor `composer_prompts.py` (6 modos en vez de ACTION_GUIDANCE) |
| `tools/` | `vision.py` nuevo (wrapper OpenAI Vision), `image_classifier.py` nuevo (clasificador con prompt fijo), normalización helper |
| `webhooks/` | Soportar attachments en payload Meta — descargar media via Meta API, anexar URL/bytes a `Message` |
| `state_machine/` | `funnel_stage()` función derivada, `pending_confirmation` lógica para sí/no |

---

## 4. Schema changes

### 4.1 Migración 015 — `turn_traces` extensions

```python
def upgrade() -> None:
    # Modo elegido por el router este turno (PLAN/SALES/DOC/...)
    op.add_column(
        "turn_traces",
        sa.Column("flow_mode", sa.String(20), nullable=True),
    )
    # Costo de Vision API este turno (separado de tool_cost_usd
    # porque dashboards distinguen embeddings vs vision)
    op.add_column(
        "turn_traces",
        sa.Column("vision_cost_usd", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "turn_traces",
        sa.Column("vision_latency_ms", sa.Integer, nullable=True),
    )

def downgrade() -> None:
    op.drop_column("turn_traces", "vision_latency_ms")
    op.drop_column("turn_traces", "vision_cost_usd")
    op.drop_column("turn_traces", "flow_mode")
```

### 4.2 Pipeline JSONB shape

`tenant_pipelines.definition` se extiende sin migración (es JSONB):

```json
{
  "version": 2,
  "stages": [...legacy, kept for compat...],
  "flow_mode_rules": [
    {"id": "doc_attached", "trigger": {"type": "has_attachment"}, "mode": "DOC"},
    {"id": "obstacle", "trigger": {"type": "keyword_in_text",
                                    "list": ["mañana", "ahorita", "al rato",
                                             "luego", "cuando llegue", "luego te mando"]},
     "mode": "OBSTACLE"},
    {"id": "retention", "trigger": {"type": "keyword_in_text",
                                     "list": ["gracias", "ok gracias",
                                              "gracias por la info"]},
     "mode": "RETENTION"},
    {"id": "plan_required",
     "trigger": {"type": "field_missing", "field": "plan_credito"},
     "mode": "PLAN"},
    {"id": "sales_default",
     "trigger": {"type": "field_present_and_intent",
                 "field": "plan_credito",
                 "intents": ["ask_price", "buy", "ask_info"]},
     "mode": "SALES"},
    {"id": "fallback", "trigger": {"type": "always"}, "mode": "SUPPORT"}
  ],
  "doc_priority": ["ine", "comprobante", "estados_de_cuenta", "nomina"],
  "docs_per_plan": {
    "Nómina Tarjeta": ["ine", "comprobante", "estados_de_cuenta", "nomina"],
    "Nómina Recibos": ["ine", "comprobante", "nomina"],
    "Pensionados":    ["ine", "comprobante", "estados_de_cuenta", "imss"],
    "Negocio SAT":    ["ine", "comprobante", "estados_de_cuenta", "constancia_sat", "factura"],
    "Sin Comprobantes": ["ine", "comprobante"]
  }
}
```

### 4.3 `tenant_branding.default_messages.brand_facts` JSONB

```json
{
  "brand_facts": {
    "catalog_url": "https://dinamomotos.com/catalogo.html",
    "wa_catalog_link": "https://wa.me/c/5218128889241",
    "address": "Benito Juárez 801, Centro Monterrey",
    "human_agent_name": "Francisco",
    "buro_max_amount": "$50 mil",
    "approval_time_hours": "24",
    "delivery_time_days": "3-7",
    "post_completion_form": "https://forms.gle/U1MEueL63vgftiuZ8"
  }
}
```

---

## 5. Router determinístico

### 5.1 Algoritmo

```python
def pick_flow_mode(
    *,
    rules: list[FlowModeRule],          # del pipeline JSONB
    state: ConversationState,            # incl. extracted_data
    nlu: NLUResult,                      # intent + entities
    vision: VisionResult | None,         # None si no había attachment
    inbound_text: str,
) -> FlowMode:
    normalized = normalize_for_router(inbound_text)  # lower + strip accents
    for rule in rules:
        if matches(rule.trigger, state, nlu, vision, normalized):
            return rule.mode
    raise RuntimeError("flow_mode_rules must end with always-true fallback")
```

### 5.2 Tipos de trigger

```python
class TriggerType(str, Enum):
    HAS_ATTACHMENT = "has_attachment"        # vision is not None
    KEYWORD_IN_TEXT = "keyword_in_text"      # any keyword in normalized_text
    FIELD_MISSING = "field_missing"          # extracted_data[field] is empty
    FIELD_PRESENT = "field_present"          # extracted_data[field] is set
    FIELD_PRESENT_AND_INTENT = "field_present_and_intent"
    INTENT_IS = "intent_is"                  # nlu.intent in list
    PENDING_CONFIRMATION = "pending_confirmation"  # state.pending_confirmation set
    ALWAYS = "always"                        # fallback
```

Triggers son combinables vía orden — el primero que matchea gana. La regla "always" debe ser la última.

### 5.3 Normalización

```python
def normalize_for_router(text: str) -> str:
    """Lowercase + strip accents. Used ONLY for keyword comparison;
    NLU/Composer receive original text."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))
```

Las listas de keywords en el JSONB también se normalizan al cargarlas — comparación es contra `normalized_text` y `normalized_keyword`.

---

## 6. Composer architecture (6 prompts por modo)

### 6.1 Refactor de `composer_prompts.py`

`ACTION_GUIDANCE: dict[str, str]` se reemplaza por:

```python
MODE_PROMPTS: dict[FlowMode, str] = {
    FlowMode.PLAN: """\
Acción: PLAN MODE.

PASOS internos (sigue el primero que aplique a `extracted_data`):

PASO 0 — Si NO hay turnos previos (turn_number == 1) y `antigüedad_meses`
está vacía: emite micro-cotización inicial...

PASO 1 — Si `antigüedad_meses` está vacía: pregunta antigüedad.

PASO 2 — Si `antigüedad_meses < 6`: mensaje de pausa, trigger handoff,
STOP.

PASO 3 — Si `antigüedad_meses >= 6` y `tipo_credito` vacío: muestra opciones 1-5.

PASO 4 — Si `tipo_credito` y `plan_credito` asignados: pide INE como primer
documento (incluyendo guía URL de fotos).

DISAMBIGUATION:
- Cliente dice "depósito"/"banco": pregunta si recibe recibos físicos.
- Cliente dice "efectivo": pregunta si con recibos.
- Cliente dice "negocio": pregunta si dado de alta SAT.

NO INVENTES PRECIOS. NO mencionas modelos de moto en este modo.
""",

    FlowMode.SALES: """\
Acción: SALES MODE.

action_payload contiene SOLO una de estas tres formas:
- {status:"ok", name, price_lista_mxn, price_contado_mxn, planes_credito, ficha_tecnica}
- {status:"no_data", hint}
- {status:"objection", type:"caro"|"sin_buro"} (cuando NLU detectó objeción)

Si status='ok':
- Da precio de contado en MXN, formato $32,900.
- Menciona el plan correspondiente al `plan_credito` del cliente:
  enganche, pago_quincenal, plazo.
- "Puedes liquidar antes sin penalización" (signature phrase).
- "Si me mandas documentos hoy, la entregamos esta semana" (cierre).

Si status='no_data': pide que el cliente confirme el modelo de moto.

Si status='objection.caro': "Te entiendo. Pero míralo así: todos los días
gastas en transporte y ese dinero se va. Con la moto pagas algo que es tuyo..."

Si status='objection.sin_buro': "Revisamos buró flexible hasta {buro_max_amount}.
La mayoría de los que avanzan no tenían buró perfecto."

NO INVENTES PRECIOS distintos a los del payload.
""",

    FlowMode.DOC: """\
Acción: DOC MODE.

action_payload incluye:
- vision_result: {category: "ine"|"comprobante"|"recibo_nomina"|...|"moto"|"unrelated", confidence}
- expected_doc: cual doc estabamos esperando (next_pending_doc del estado)
- pending_after: lista de docs aún pendientes después de procesar este

Lógica:
1) Si `vision_result.category == expected_doc`: confirma con "[doc] ✅",
   pide el siguiente de `pending_after[0]` si hay, o anuncia que ya está
   completa la papelería + manda el link `post_completion_form`.

2) Si vision_result.category != expected_doc pero ES UN doc legítimo
   (ine/comprobante/etc.): "[doc recibido] ✅" pero también
   "Aún necesito [expected_doc], ¿lo tienes a la mano?"

3) Si vision_result.category in ["unrelated", "moto"]:
   "Recibí tu foto pero no es un documento que necesite ahorita.
   ¿Me mandas tu [expected_doc]? Era el siguiente paso."
   No marques nada como recibido.

4) Si vision_result.confidence < 0.6: "Esa imagen no la veo bien clara,
   ¿puedes mandarla en mejor calidad?"

NO inventes que recibiste un doc que no llegó.
""",

    FlowMode.OBSTACLE: """\
Acción: OBSTACLE MODE.

El cliente pospuso. Identifica el doc específico que le cuesta:
"¿Cuál es el que más te cuesta conseguir, el comprobante de domicilio
o las nóminas?"

Si el cliente menciona un doc específico, sigue el árbol del v1:
- Comprobante: sugiere alternativas (luz/agua/gas/internet).
  Si no tiene → handoff a {human_agent_name}.
- Nóminas: pregunta si las da el patrón en papel/correo. Si no
  → "es tu derecho pedirlas a recursos humanos". Si tiene que
  pedirlas → handoff con fecha estimada.

Si tiene SOLO algunos docs: "No hay problema, mándame la INE y lo que
tengas, avanzamos." (Aceptar parciales para crear compromiso.)

NO INVENTES procesos no en este prompt.
""",

    FlowMode.RETENTION: """\
Acción: RETENTION MODE.

El cliente dijo "gracias" pero NO confirmó pérdida de interés.
Texto fijo (parametrizado por tono):

"Perfecto, para no dejarlo en el aire: normalmente cuando alguien dice
'gracias' es porque quiere revisarlo con calma o tiene una duda que no
quiere dejar pasar. ¿Qué parte te gustaría aclarar o prefieres verlo
después?"

Trigger interno: marcar `retention_attempt=true` en extracted_data.
""",

    FlowMode.SUPPORT: """\
Acción: SUPPORT MODE.

action_payload puede incluir `faq_match`: una respuesta del catálogo
de FAQs ingestadas en 3c.1 (vía lookup_faq). Si llega:
- Adapta la `respuesta` al tono informal mexicano. NO inventes datos.

Si no hay match (action_payload.status == "no_data"):
- Si el tema es BURO/ENGANCHE/DOCS/UBICACIÓN/TIEMPOS, usa los
  brand_facts inyectados. Ejemplos:
  - "Buró" → "Revisamos buró, flexible hasta {buro_max_amount}."
  - "Enganche" → "10% nómina tarjeta, 15% recibos/SAT, 20% sin comprobantes."
  - "Tiempos" → "Buró {approval_time_hours}h, entrega {delivery_time_days} días."
  - "Ubicación" → "{address}. Pregunta por {human_agent_name}."

Si nada de lo anterior aplica: redirige con frase tipo
"Déjame revisar y te confirmo en un momento."

Después de responder, si el cliente NO está en plan_credito assigned:
agregar al final "y tú, ¿cómo recibes tu sueldo?" para regresarlo al funnel.
""",
}
```

Cada prompt es 200-400 palabras. La estructura interna es **explícita en pasos numerados** para que el LLM con temperature=0 sepa exactamente qué rama tomar.

### 6.2 `build_composer_prompt` refactor

```python
def build_composer_prompt(input: ComposerInput) -> list[dict[str, str]]:
    mode_block = MODE_PROMPTS[input.flow_mode]
    # Inyectar brand_facts solo en modos que lo usan
    needs_facts = input.flow_mode in {FlowMode.SUPPORT, FlowMode.PLAN, FlowMode.DOC}
    facts_block = render_brand_facts(input.brand_facts) if needs_facts else ""

    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        bot_name=input.tone.bot_name,
        ...
        mode_guidance=mode_block,
        brand_facts=facts_block,                # nuevo
        action_payload=_render_action_payload(input.action_payload),  # 3c.1
        ...
    )
    return [{"role": "system", "content": system_content},
            *_render_history(input.history)]
```

### 6.3 Snapshot fixtures

Por cada modo, 4-5 fixtures cubriendo los principales `extracted_data` states:
- `mode_PLAN_state_initial.txt` (sin antigüedad ni plan)
- `mode_PLAN_state_antiguedad_set.txt` (solo antigüedad)
- `mode_PLAN_state_plan_assigned.txt` (todo asignado, pidiendo INE)
- `mode_SALES_state_quote_ok.txt` (action_payload.status='ok')
- `mode_SALES_state_no_data.txt`
- `mode_SALES_state_objection_caro.txt`
- `mode_DOC_state_match.txt` (vision dijo lo que esperabamos)
- `mode_DOC_state_unrelated_image.txt`
- `mode_DOC_state_papeleria_completa.txt`
- `mode_OBSTACLE_state_initial.txt`
- `mode_RETENTION_state_initial.txt`
- `mode_SUPPORT_state_buro_question.txt` (con brand_facts)
- `mode_SUPPORT_state_faq_match.txt` (action_payload con FAQ del catálogo)

~13 fixtures total.

---

## 7. Vision API integration

### 7.1 `core/atendia/tools/vision.py`

Wrapper análogo a `embeddings.py`:

```python
VISION_PRICE_PER_1M_INPUT_TOKENS: Decimal = Decimal("2.50")     # gpt-4o vision
VISION_PRICE_PER_1M_OUTPUT_TOKENS: Decimal = Decimal("10.00")
DEFAULT_VISION_MODEL: str = "gpt-4o"

async def classify_image(
    *,
    client: AsyncOpenAI,
    image_url: str,
    model: str = DEFAULT_VISION_MODEL,
) -> tuple[VisionResult, int, int, Decimal]:
    """Classify image into doc/moto/unrelated categories.

    Returns (result, tokens_in, tokens_out, cost_usd).
    Result schema: {category, confidence, metadata}.
    NO `expected_doc` parameter — classification is unbiased.
    """
```

El prompt de classify_image es un system+user message que instruye al modelo a categorizar en:
- `ine` (con metadata: ambos_lados/un_lado, legible)
- `comprobante` (luz/agua/gas/internet, fecha del recibo)
- `recibo_nomina` (fecha, periodo)
- `estado_cuenta` (institución, fecha)
- `constancia_sat` / `factura_compra` / `imss`
- `moto` (foto de motocicleta)
- `unrelated` (selfie, screenshot, otro)

JSON structured output con strict mode (igual que NLU en 3a).

### 7.2 VisionResult contract

```python
class VisionCategory(str, Enum):
    INE = "ine"
    COMPROBANTE = "comprobante"
    RECIBO_NOMINA = "recibo_nomina"
    ESTADO_CUENTA = "estado_cuenta"
    CONSTANCIA_SAT = "constancia_sat"
    FACTURA = "factura"
    IMSS = "imss"
    MOTO = "moto"
    UNRELATED = "unrelated"

class VisionResult(BaseModel):
    category: VisionCategory
    confidence: float   # [0, 1]
    metadata: dict      # category-specific (e.g., {"ambos_lados": true})
```

### 7.3 Webhook attachment handling

Meta Cloud API webhook con `image` viene así:

```json
{
  "type": "image",
  "image": {
    "id": "MEDIA_ID",
    "mime_type": "image/jpeg",
    "sha256": "...",
    "caption": "..."
  }
}
```

Flujo:
1. Webhook detecta `type=image` → llama a Meta Graph API `/MEDIA_ID` para obtener URL temporal (1h TTL).
2. Webhook descarga los bytes y los guarda en un blob storage (Phase 3c.2: solo guardar URL temporal en `messages.attachments`; storage permanente puede ser 3d).
3. Construye `Message(attachments=[Attachment(media_id, mime_type, url)])`.
4. Runner ve `message.attachments` y dispara `classify_image`.

### 7.4 Cost tracking

`turn_traces.vision_cost_usd` (separado de `tool_cost_usd`) — dashboards distinguen embeddings (3c.1) vs vision (3c.2).

Acumulación a `conversation_state.total_cost_usd`: vision_cost + nlu_cost + composer_cost + tool_cost.

---

## 8. Field extraction & state

### 8.1 `ExtractedFields` Pydantic contract

```python
# core/atendia/contracts/extracted_fields.py

class TipoCredito(str, Enum):
    NOMINA_TARJETA = "Nómina Tarjeta"
    NOMINA_RECIBOS = "Nómina Recibos"
    PENSIONADOS = "Pensionados"
    NEGOCIO_SAT = "Negocio SAT"
    SIN_COMPROBANTES = "Sin Comprobantes"

class PlanCredito(str, Enum):
    PLAN_10 = "10%"
    PLAN_15 = "15%"
    PLAN_20 = "20%"

class ExtractedFields(BaseModel):
    """Canonical conversation-scoped state. Lives in
    `conversation_state.extracted_data` JSONB."""

    # Personal
    antigüedad_meses: int | None = None
    nombre: str | None = None

    # Plan
    tipo_credito: TipoCredito | None = None
    plan_credito: PlanCredito | None = None

    # Sales
    modelo_moto: str | None = None
    tipo_moto: str | None = None  # categoría (Motoneta/Chopper/etc.)

    # Docs (flags)
    docs_ine: bool = False
    docs_comprobante: bool = False
    docs_estados_de_cuenta: bool = False
    docs_nomina: bool = False
    docs_constancia_sat: bool = False
    docs_factura: bool = False
    docs_imss: bool = False
    papeleria_completa: bool = False

    # Flags conversacionales
    retention_attempt: bool = False
    cita_dia: str | None = None  # ISO date string
```

NLU extrae a este shape. Cada `entities` key del NLUResult mapea 1:1 a un field. Validación Pydantic.

### 8.2 `funnel_stage()` derivado

```python
def funnel_stage(extracted: ExtractedFields) -> str:
    if extracted.papeleria_completa:
        return "close"
    if extracted.modelo_moto:
        return "doc"
    if extracted.plan_credito:
        return "sales"
    return "plan"
```

### 8.3 `next_pending_doc()` derivado

```python
def next_pending_doc(
    extracted: ExtractedFields,
    plan_credito: PlanCredito | None,
    docs_per_plan: dict[str, list[str]],
) -> str | None:
    if plan_credito is None:
        return None  # plan no asignado → no pidamos docs aún
    required = docs_per_plan.get(plan_credito.value, [])
    for doc in required:
        if not getattr(extracted, f"docs_{doc}", False):
            return doc
    return None  # papelería completa
```

Ambas funciones puras, testeables sin DB.

### 8.4 `pending_confirmation` para sí/no binarios

`conversation_state.pending_confirmation` (varchar, ya existe Phase 1) se usa así:

- Cuando un mode prompt hace pregunta binaria ("¿es tu nómina en tarjeta?"), el composer **además del mensaje**, devuelve `pending_confirmation_set: "is_nomina_tarjeta"` que el runner persiste.
- Al siguiente turno, si `inbound.text` matchea regex de confirmación (`["sí","si","claro","ok","yes"]`) y `pending_confirmation` está set, el router lo trata como "yes a is_nomina_tarjeta" → en PLAN MODE asigna `tipo_credito=Nómina Tarjeta, plan_credito=10%`, limpia `pending_confirmation`.
- Análogo para "no".

Esto evita inflar el enum de NLU intents.

---

## 9. Handoff estructurado

### 9.1 `HandoffSummary` contract

```python
# core/atendia/contracts/handoff_summary.py

class HandoffReason(str, Enum):
    OUTSIDE_24H = "outside_24h_window"
    COMPOSER_FAILED = "composer_failed"
    OBSTACLE_BLOCKER = "obstacle_no_solution"
    USER_SENT_DONE_DOCS = "user_signaled_papeleria_completa"
    PAPELERIA_COMPLETA = "papeleria_completa_form_pending"
    LOW_ANTIGUEDAD = "antiguedad_lt_6m"

class HandoffSummary(BaseModel):
    reason: HandoffReason
    nombre: str | None = None
    modelo_moto: str | None = None
    plan_credito: str | None = None
    enganche_estimado: str | None = None
    docs_recibidos: list[str]
    docs_pendientes: list[str]
    last_inbound_message: str
    suggested_next_action: str
    funnel_stage: str  # derivado al momento del handoff
    cita_dia: str | None = None
```

Persistido en `human_handoffs.payload` JSONB (campo ya existe).

### 9.2 Reglas de creación

- En cualquier modo donde el composer pida handoff (vía guidance dentro del prompt o por error explícito).
- Cuando OBSTACLE detecta un blocker irresoluble.
- Cuando el flujo llega a CLOSE (form de cierre se envía pero también un humano debe confirmar visita).
- Cuando aparece error en composer/NLU (fallback ya existe en 3a/b).

---

## 10. Tests strategy

### 10.1 Coverage objetivos

- Router determinístico (`flow_router.py`): 100% — cada tipo de trigger, cada combinación con state.
- Mode prompts: snapshots por estado (~13 fixtures).
- Vision wrapper: respx mocks (4 tests análogos a embeddings).
- `classify_image`: respx + verifica VisionResult schema.
- `next_pending_doc`, `funnel_stage`: tests puros sin DB.
- Runner integration: 5-6 tests E2E con FakeNLU + FakeVision + RecordingComposer cubriendo cada modo.
- Live tests (gated): RUN_LIVE_LLM_TESTS=1 para classify_image con imágenes reales (INE de prueba, foto de moto, selfie). Costo ~$0.03 por corrida.

### 10.2 Coverage gate

Mantener ≥85% (ya está en 91% post-3c.1). Esperado: los nuevos archivos tienen ≥90% individual.

---

## 11. Cost estimate

Por turno típico:

| Componente | Costo | Nota |
|---|---|---|
| NLU (gpt-4o-mini) | $0.000088 | 3a/b actual |
| Composer (gpt-4o) | $0.001580 | 3b actual |
| Embeddings (lookup_faq, search_catalog) | $0.000-0.0001 | solo en SUPPORT/SALES |
| Vision (classify_image) | $0.000 — 0.005 | solo cuando hay imagen |
| **Total** | **~$0.0017 - $0.007** | text-only vs imagen |

Por cliente promedio (asumiendo 30 turnos del journey, 4 imágenes):
- 26 turnos text-only × $0.0017 = $0.044
- 4 turnos con imagen × $0.007 = $0.028
- **Total por cliente: ~$0.072**

Piloto con 50 clientes/día = **~$3.6 USD/día**. Sostenible.

---

## 12. Riesgos & mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| Vision clasifica mal una INE como "unrelated" | Media | Confidence threshold + retry con prompt más específico; UI fallback "no se ve clara, ¿puedes mandarla mejor?" |
| Router prioriza OBSTACLE cuando no aplica (cliente dice "luego" en otro contexto) | Media | Lista de keywords curada, ampliable per-tenant; fallback a SUPPORT acepta el segundo intento si el cliente continúa |
| Mode prompt enorme degrada calidad de Composer | Baja | Snapshot tests + live tests por modo; prompts ≤400 palabras |
| Cliente envía 10 imágenes en spam → costo de Vision se dispara | Baja | Rate-limit por conversación: max 5 Vision calls/hora |
| `pending_confirmation` queda stale (cliente nunca contestó) | Baja | Auto-clear después de N turnos sin match |
| Conflicto con Phase 3a/b stages legacy | Media | Mantener `stages` en JSONB pero desactivado en runner; tests de regresión 3a/b deben seguir pasando |

---

## 13. Acceptance criteria

- [ ] Migración 015 aplicada y reversible.
- [ ] `flow_router.py` con tests unit por trigger type.
- [ ] `vision.py` + `image_classifier.py` con respx tests + 1 live test gated.
- [ ] `composer_prompts.py` refactor a `MODE_PROMPTS`; 13 snapshot fixtures pasando.
- [ ] `ExtractedFields` Pydantic + `funnel_stage`/`next_pending_doc` con tests puros.
- [ ] Webhook acepta attachments de Meta y los pasa al runner.
- [ ] Runner integra paralelo NLU+Vision; persiste `flow_mode` y `vision_cost_usd` en `turn_traces`.
- [ ] `pending_confirmation` soporta sí/no binarios.
- [ ] `HandoffSummary` Pydantic persistido en `human_handoffs.payload`.
- [ ] Brand facts en `tenant_branding.default_messages.brand_facts` consumidos por modos relevantes.
- [ ] 6 E2E integration tests con FakeNLU/FakeVision/RecordingComposer cubren cada modo.
- [ ] Live smoke test (RUN_LIVE_LLM_TESTS=1) verifica los 6 modos contra Dinamo real.
- [ ] Coverage ≥85%, lint clean, mypy clean (modulo el error pre-existente en `tools/__init__.py`).
- [ ] README.md status actualizado.

---

## 14. Out of scope (defer to Phase 3d)

- Follow-ups programados (3h/12h/24h): scheduler worker, templates, reglas de cancelación.
- Outbound multimedia: enviar imágenes/PDFs al cliente (catalog visual, recibos firmados).
- Templates fuera de 24h: re-engagement con mensajes pre-aprobados.
- Persistencia permanente de imágenes recibidas (blob storage). En 3c.2 las URLs son temporales (1h TTL de Meta).
- Customer-level sticky state (re-load de `tipo_credito` entre conversaciones).
- Frontend para visualizar `HandoffSummary` (Phase 4).
- Catalog disambiguation cuando ≥2 hits comparten alias (carry-over de 3c.1, ahora con prioridad correcta para 3c.2).

---

## 15. Plan de implementación

A escribir mediante `superpowers:writing-plans` — siguiente paso post-aprobación de este design doc.

Estimación previa: ~30 tareas distribuidas en 8 bloques análogos al plan de 3c.1.

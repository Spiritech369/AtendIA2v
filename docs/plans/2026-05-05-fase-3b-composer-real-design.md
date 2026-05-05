# AtendIA v2 — Fase 3b: Composer real con `gpt-4o` — Diseño

> **Estado:** diseño aprobado, pendiente de plan de implementación.
> **Fecha:** 2026-05-05
> **Autor:** brainstorm conjunto (Frank + Claude)
> **Reemplaza:** `outbound_dispatcher._PHASE2_TEXTS` (textos canned por acción) como fuente de redacción.

---

## 1. Contexto y objetivo

Phase 3a sustituyó `KeywordNLU` por `OpenAINLU` (gpt-4o-mini con structured outputs). El bot ahora **entiende** correctamente lo que dice el cliente. Pero sigue **respondiendo** con los textos fijos de Phase 2 (`_PHASE2_TEXTS`), lo cual hace que el bot suene a "FAQ con keywords".

**Objetivo Phase 3b**: que el bot **redacte** sus respuestas con `gpt-4o` manteniendo el flujo determinista intacto. El orquestador decide la acción (sin LLM); el Composer la redacta dentro de bounds (con LLM).

**Alcance acordado** (decisión 1, opción c):
- Composer real para mensajes intra-24h.
- Detección de fuera-de-24h → crea `human_handoffs` row, NO envía nada.
- NO incluye templates aprobados de Meta (Phase 3d).
- NO incluye datos reales de catálogo/FAQs (Phase 3c).

---

## 2. Decisiones tomadas en el brainstorm

| # | Decisión | Elección | Alternativas descartadas |
|---|---|---|---|
| 1 | Alcance Phase 3b | **Composer intra-24h + detect fuera-de-24h → handoff humano** | Solo intra-24h (silencio fuera); intra + templates aprobados completos |
| 2 | Cobertura de acciones | **4 libres + 2 con instrucción "no inventes" + 1 canned con placeholder** | Todas redactadas (riesgo alucinación de precios); solo las 4 seguras |
| 3 | Output shape | **`list[str]` cap 2 default, 3 máx** | Single string; lista sin cap |
| 4 | Tono — placement | **Solo `tenant_branding.voice` JSONB (eliminar `pipeline.tone`)** | Solo en pipeline; híbrido con override por stage |
| 5 | Falla del LLM | **Canned fallback + crear `human_handoffs` row para visibilidad** | Solo canned; solo silencio + handoff; mensaje "te respondemos pronto" + retry async |
| 6a | Historial al Composer | **`pipeline.composer.history_turns` separado, default 2** | Reusar `nlu.history_turns`; hardcoded |
| 6b | Tools sin datos en 3b | **Stubs devuelven `{status: "no_data", hint: "..."}`; Composer siempre recibe output de tool** | Sin tools (action ID solo); flag `requires_data` en payload |
| 7 | Modelo | **`gpt-4o`, `temperature=0`** | gpt-4o-mini; otro |
| 8 | API key | **Global (mismo `ATENDIA_V2_OPENAI_API_KEY` que NLU)** | Per-tenant |
| 9 | Cost tracking | **Llenar `turn_traces.composer_*` desde día 1** | Defer a Phase 4 |
| 10 | Reintentos | **`(500, 2000)` ms via `composer_retry_delays_ms` (separado de NLU)** | Mismo valor que NLU; sin reintentos |
| 11 | Tests | **`respx` mocks + 1 live test gated `RUN_LIVE_LLM_TESTS=1`** | Solo mocks; live siempre |
| 12 | Toggle | **`composer_provider: "openai" \| "canned"` env var, default `canned`** | Sin toggle; per-tenant |

### Asunciones aplicadas (no requirieron pregunta — reuso del patrón Phase 3a):

- Validación bounds en `UsageMetadata.cost_usd` (≥0) — propagamos S1 del code review de T9.
- Excepciones taxonomy: `_RETRIABLE` (timeout, conn, 5xx, rate-limit) ∪ `_NON_RETRIABLE` (auth, bad-req, 422 catchall, ValidationError) — extraídas a módulo compartido `runner/_openai_errors.py`.
- Schema strict-mode para structured outputs: el output `{messages: list[str]}` cumple invariantes (required = properties keys, additionalProperties=false, no untyped Any).
- Snapshot test del system prompt — patrón T14 de Phase 3a.

---

## 3. Arquitectura

```
┌─────────────────────────┐
│  meta_routes.py         │
│  - build_nlu(settings)  │
│  + build_composer(...)  │  ◀── NEW
└────────┬────────────────┘
         │ inbound text
         ▼
┌─────────────────────────────────┐
│  ConversationRunner             │
│  1. NLU.classify          ◀── existing (3a)
│  2. process_turn          ◀── existing
│  3. resolve action        ◀── existing
│  4. invoke tool stub      ◀── NEW (β payload)
│  5. 24h check             ◀── NEW
│      ├─ inside: Composer.compose
│      └─ outside: human_handoff INSERT, no compose
│  6. enqueue_messages list ◀── NEW (changes outbound_dispatcher)
│  7. persist trace+costs   ◀── extends existing
└─────────────────────────────────┘
```

### 3.1 Archivos nuevos

- `core/atendia/runner/composer_protocol.py` — `ComposerProvider` Protocol + `ComposerInput`/`ComposerOutput` BaseModels.
- `core/atendia/runner/composer_canned.py` — `CannedComposer` que adapta `_PHASE2_TEXTS` al Protocol.
- `core/atendia/runner/composer_openai.py` — `OpenAIComposer` con `gpt-4o` + retry + canned fallback inyectable.
- `core/atendia/runner/composer_prompts.py` — system prompt template + `ACTION_GUIDANCE` dict + `build_composer_prompt(...)`.
- `core/atendia/runner/_openai_errors.py` — `_RETRIABLE` / `_NON_RETRIABLE` tuples compartidas (reuso de Phase 3a).
- `core/atendia/runner/_template_helpers.py` — `render_template`, `_render_history` movidos desde `nlu_prompts.py` para reuso.
- `core/atendia/contracts/tone.py` — `Tone(BaseModel)` con 6 campos.
- `core/atendia/db/migrations/versions/011_drop_pipeline_tone.py` — Alembic data-only migration.
- `core/scripts/seed_dinamo_voice.py` — script para poblar `tenant_branding.voice` con valores de Dinamo.
- `core/tests/runner/test_composer_canned.py`
- `core/tests/runner/test_composer_openai.py`
- `core/tests/runner/test_composer_prompts.py`
- `core/tests/runner/test_composer_protocol.py`
- `core/tests/runner/test_composer_live.py` (gated)
- `core/tests/contracts/test_tone.py`
- `core/tests/fixtures/composer/greet_dinamo_system.txt`

### 3.2 Archivos modificados

- `core/atendia/runner/conversation_runner.py` — invoca tool stub, hace 24h check, llama Composer, enquea N mensajes, persiste `composer_*` columns + acumula cost.
- `core/atendia/runner/outbound_dispatcher.py` — refactor a `enqueue_messages(messages: list[str], ...)`. `_PHASE2_TEXTS` se elimina (queda solo en `CannedComposer`).
- `core/atendia/runner/nlu_protocol.py` — añade `UsageMetadata.fallback_used: bool = False` (backward-compat).
- `core/atendia/runner/nlu_openai.py` — pasa `fallback_used=False` en happy path, `True` en error path; importa `_RETRIABLE`/`_NON_RETRIABLE` desde el módulo compartido.
- `core/atendia/runner/nlu_prompts.py` — re-exporta helpers desde `_template_helpers` para no romper imports existentes.
- `core/atendia/runner/nlu/pricing.py` — agrega `gpt-4o` y `gpt-4o-2024-08-06` al `MODEL_PRICING`.
- `core/atendia/contracts/pipeline_definition.py` — agrega `ComposerConfig` (paralelo a `NLUConfig`); elimina `tone: dict` field.
- `contracts/pipeline_definition.schema.json` — actualiza al schema sin `tone`, con `composer.history_turns`.
- `core/atendia/webhooks/meta_routes.py` — agrega `build_composer(settings)` factory; pasa el composer al runner.
- `core/atendia/config.py` — agrega `composer_provider`, `composer_model`, `composer_timeout_s`, `composer_retry_delays_ms`, `composer_max_messages`.
- `core/atendia/tools/quote.py`, `lookup_faq.py`, `search_catalog.py` — devuelven `ToolNoDataResult` en vez de strings vacíos.
- `core/atendia/contracts/event.py` — verificar que `EventType.ESCALATION_REQUESTED` existe (si no, agregar).
- `core/tests/runner/test_outbound_dispatcher.py` — reescribir para nueva firma `enqueue_messages(messages: list[str], ...)`.
- `core/tests/integration/test_inbound_to_runner.py` — agregar 2 tests E2E (Composer mocked happy + fuera-de-24h handoff).
- `.env.example` — agregar las 5 variables nuevas de Composer.

### 3.3 Lo que no se toca

- NLU (Phase 3a queda intacta).
- State machine / orquestador (sigue determinista).
- Webhook signing, dedup, status callbacks.
- Realtime WS / Pub/Sub.
- Templates de Meta (Phase 3d).
- Catálogo / FAQs reales (Phase 3c).

---

## 4. Schema de tono

Nuevo archivo `core/atendia/contracts/tone.py`:

```python
from typing import Literal
from pydantic import BaseModel, Field


class Tone(BaseModel):
    register: Literal["informal_mexicano", "formal_es", "neutral_es"] = "neutral_es"
    use_emojis: Literal["never", "sparingly", "frequent"] = "sparingly"
    max_words_per_message: int = Field(default=40, ge=10, le=120)
    bot_name: str = "Asistente"
    forbidden_phrases: list[str] = Field(default_factory=list)
    signature_phrases: list[str] = Field(default_factory=list)
```

Lectura desde DB: `Tone.model_validate(row.voice or {})` (defaults si JSONB vacío).
Escritura: `tone.model_dump()`.

### 4.1 Seed para Dinamo

```sql
UPDATE tenant_branding
SET voice = '{
  "register": "informal_mexicano",
  "use_emojis": "sparingly",
  "max_words_per_message": 40,
  "bot_name": "Dinamo",
  "forbidden_phrases": ["estimado cliente", "le saluda atentamente", "cordialmente"],
  "signature_phrases": ["¡qué onda!", "te paso", "ahí va"]
}'::jsonb
WHERE tenant_id = '<UUID-DINAMO>';
```

Empaquetado en `core/scripts/seed_dinamo_voice.py` con `--tenant-id <uuid>` y `--dry-run`.

### 4.2 Migración del campo `pipeline.tone`

- **Alembic 011**: `op.execute("UPDATE tenant_pipelines SET definition = definition - 'tone'")`. Reversible.
- **Pydantic `PipelineDefinition`**: quita `tone: dict`. Backward compat: si fixtures viejas pasan `"tone": {...}`, Pydantic lo ignora (model_config no tiene `extra="forbid"`).
- **Pre-condition**: el seed de Dinamo's voice se ejecuta ANTES de Alembic 011 para no perder datos de tono que estuvieran en el pipeline JSONB.

---

## 5. Interfaz `ComposerProvider`

```python
# composer_protocol.py
from typing import Protocol
from pydantic import BaseModel, Field
from atendia.contracts.tone import Tone
from atendia.runner.nlu_protocol import UsageMetadata  # reuse


class ComposerInput(BaseModel):
    action: str
    action_payload: dict = Field(default_factory=dict)
    current_stage: str
    last_intent: str | None = None
    extracted_data: dict = Field(default_factory=dict)
    history: list[tuple[str, str]] = Field(default_factory=list)
    tone: Tone
    max_messages: int = Field(default=2, ge=1, le=3)


class ComposerOutput(BaseModel):
    messages: list[str] = Field(min_length=1, max_length=3)


class ComposerProvider(Protocol):
    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]: ...
```

`UsageMetadata` extendido con `fallback_used: bool = False` (backward compat con NLU consumers).

### 5.1 `CannedComposer` (fallback + default)

```python
class CannedComposer:
    _TEXTS: dict[str, str] = {
        "greet": "¡Hola! Soy tu asistente. ¿En qué te puedo ayudar?",
        "ask_field": "Me podrías compartir más detalles?",
        "lookup_faq": "Déjame revisar nuestra información para responderte.",
        "ask_clarification": "Disculpa, no te entendí del todo. ¿Podrías reformular?",
        "quote": "El precio depende del modelo y opciones. ¿Cuál te interesa? Te paso el costo exacto.",
        "explain_payment_options": "Aceptamos efectivo, transferencia y crédito. ¿Cuál te conviene?",
        "close": "¡Perfecto! Te paso el siguiente paso para cerrar.",
    }

    async def compose(self, *, input: ComposerInput) -> tuple[ComposerOutput, UsageMetadata | None]:
        text = self._TEXTS.get(
            input.action,
            "Disculpa, déjame consultar y te paso la info.",
        )
        return ComposerOutput(messages=[text]), None
```

### 5.2 `OpenAIComposer`

- Recibe `fallback: ComposerProvider` opcional (default `CannedComposer()`).
- Loop `(0, *retry_delays_ms)` con `_RETRIABLE`/`_NON_RETRIABLE` semántica.
- Output JSON schema strict-mode construido per-call: `{messages: array<string>, min: 1, max: input.max_messages, additionalProperties: false}`.
- En error path: invoca `self._fallback.compose(input)`, devuelve esos messages con `UsageMetadata(model=self._model, tokens_in=0, ..., fallback_used=True)`.

---

## 6. Prompts

`core/atendia/runner/composer_prompts.py` con cuatro bloques editables:

1. `SYSTEM_PROMPT_TEMPLATE` — instrucciones generales + tono inyectado.
2. `ACTION_GUIDANCE: dict[str, str]` — bloque condicional por acción. **Ediciones para cambiar comportamiento del Composer pasan principalmente por aquí.**
3. `HISTORY_FORMAT` + `ROLE_LABELS` — render de turnos previos (Spanish labels).
4. `OUTPUT_INSTRUCTIONS` — reglas sobre el JSON de salida.

Helpers `render_template`, `_render_history`, `_render_fields` se mueven a `_template_helpers.py` y se importan desde ambos `nlu_prompts.py` y `composer_prompts.py`.

### 6.1 Tokens estimados (Dinamo, 2 turnos historial)

| Componente | Tokens |
|---|---|
| System | ~350 |
| Historial 2 turnos | ~100 |
| Output (1-2 mensajes × 40 palabras) | ~80 |
| **Total** | **~530 tokens/turno** |

Costo `gpt-4o`: $2.50 input / $10.00 output por 1M:
- Input: 450 × $2.50/1M = **$0.001125**
- Output: 80 × $10.00/1M = **$0.000800**
- **Total: ~$0.0019 / turno** ≈ **$0.057 / conversación de 30 turnos** ≈ **$57 / 1.000 conversaciones**

(NLU + Composer combinados: ~$0.060/conversación, ~$60/mil conversaciones.)

---

## 7. Tool stubs con placeholder data (decisión 6b = β)

Contrato:

```python
class ToolNoDataResult(BaseModel):
    status: Literal["no_data"] = "no_data"
    hint: str
```

Stubs actualizados (`quote`, `lookup_faq`, `search_catalog`):

```python
def quote(*, tenant_id, product_id, options) -> ToolNoDataResult:
    return ToolNoDataResult(hint="catalog not connected; cannot quote")
```

Conexión en runner:

```python
if action in {"quote", "lookup_faq", "search_catalog"}:
    tool_result = TOOL_REGISTRY[action](tenant_id=tenant_id, ...)
    action_payload = tool_result.model_dump(mode="json")
elif action == "ask_field":
    missing = next(
        (f for f in current_stage_def.required_fields
         if f.name not in extracted_data), None,
    )
    if missing:
        action_payload = {
            "field_name": missing.name,
            "field_description": missing.description,
        }
elif action == "close":
    action_payload = {"payment_link": None}  # populated when 3c brings real payments
```

---

## 8. Outbound dispatcher refactor + 24h handoff

### 8.1 `outbound_dispatcher.enqueue_messages`

```python
async def enqueue_messages(
    arq_redis, *, messages: list[str], tenant_id, to_phone_e164,
    conversation_id, turn_number, action,
) -> list[str]:
    job_ids = []
    for i, text in enumerate(messages):
        msg = OutboundMessage(
            tenant_id=str(tenant_id), to_phone_e164=to_phone_e164, text=text,
            idempotency_key=f"out:{conversation_id}:{turn_number}:{i}:{uuid4().hex[:6]}",
            metadata={"action": action, "message_index": i, "of": len(messages)},
        )
        job_ids.append(await enqueue_outbound(arq_redis, msg))
    return job_ids
```

### 8.2 24h check + handoff (en runner)

```python
last_activity_at = (await self._session.execute(
    text("SELECT last_activity_at FROM conversations WHERE id = :cid"),
    {"cid": conversation_id},
)).scalar()
inside_24h = (datetime.now(timezone.utc) - last_activity_at) < timedelta(hours=24)

if not inside_24h and action in COMPOSED_ACTIONS:
    await self._session.execute(
        text("INSERT INTO human_handoffs (conversation_id, tenant_id, reason, status) "
             "VALUES (:cid, :tid, 'outside_24h_window', 'pending')"),
        {"cid": conversation_id, "tid": tenant_id},
    )
    await self._emitter.emit(
        conversation_id=conversation_id, tenant_id=tenant_id,
        event_type=EventType.ESCALATION_REQUESTED,
        payload={"reason": "outside_24h_window"},
    )
    composer_output = None; composer_usage = None
else:
    composer_output, composer_usage = await self._composer.compose(input=composer_input)
    # On fallback (composer_usage.fallback_used == True): also create handoff row
    if composer_usage and composer_usage.fallback_used:
        await self._session.execute(
            text("INSERT INTO human_handoffs (conversation_id, tenant_id, reason, status) "
                 "VALUES (:cid, :tid, 'composer_failed', 'pending')"),
            {"cid": conversation_id, "tid": tenant_id},
        )
        await self._emitter.emit(
            conversation_id=conversation_id, tenant_id=tenant_id,
            event_type=EventType.ERROR_OCCURRED,
            payload={"where": "composer", "fallback": "canned"},
        )

if composer_output:
    await enqueue_messages(arq_redis, messages=composer_output.messages, ...)
```

---

## 9. Reintentos, errores y cost tracking

### 9.1 Settings nuevas

```python
composer_provider: Literal["openai", "canned"] = "canned"
composer_model: str = "gpt-4o"
composer_timeout_s: float = 8.0
composer_retry_delays_ms: list[int] = [500, 2000]
composer_max_messages: int = Field(default=2, ge=1, le=3)
```

### 9.2 Excepciones — reuso del módulo compartido

`core/atendia/runner/_openai_errors.py`:

```python
from openai import (
    APIConnectionError, APIStatusError, APITimeoutError,
    AuthenticationError, BadRequestError, InternalServerError, RateLimitError,
)
from pydantic import ValidationError

_RETRIABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)
_NON_RETRIABLE = (AuthenticationError, BadRequestError, ValidationError, APIStatusError)
```

### 9.3 Pricing

```python
MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini":            (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o-mini-2024-07-18": (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o":                 (Decimal("2.500"), Decimal("10.000")),  # NEW
    "gpt-4o-2024-08-06":      (Decimal("2.500"), Decimal("10.000")),  # NEW
}
```

### 9.4 Cost accumulation en `conversation_state`

Igual patrón que T21 (NLU). Después del Composer:

```python
if composer_usage and composer_usage.cost_usd > 0:
    await self._session.execute(
        text("UPDATE conversation_state SET total_cost_usd = total_cost_usd + :c "
             "WHERE conversation_id = :cid"),
        {"c": composer_usage.cost_usd, "cid": conversation_id},
    )
```

---

## 10. Tests

| Archivo | Casos |
|---|---|
| `test_composer_protocol.py` | Defaults, validation (empty/4 messages reject), structural Protocol satisfaction |
| `test_composer_canned.py` | 7 acciones × 1 assert (texto contiene substring esperado) |
| `test_composer_prompts.py` | render, snapshot greet+Dinamo, missing_field substitution, action_guidance "no inventes" |
| `test_composer_openai.py` | Happy, retry-then-success, retry-exhaustion-→-fallback, no-retry-401/400/422/Validation, tone passthrough, max_messages enforced, schema invariants |
| `test_composer_live.py` | Live (gated): greet contiene saludo + word cap respetado, **quote NO inventa precio (regex `\d{4,6}` ausente)** |
| `test_tone.py` | Defaults + range validations |
| `test_outbound_dispatcher.py` | Enqueue 1/2/3 messages, idempotency keys únicos, COMPOSED_ACTIONS taxonomy |
| `test_inbound_to_runner.py` (extiende) | E2E con Composer OpenAI mocked + 24h handoff (last_activity_at = now - 25h) |

Cobertura: ≥85% (gate actual).

---

## 11. Plan de rollout

1. Mergear con `composer_provider="canned"` por default → producción no cambia.
2. Smoke local: `RUN_LIVE_LLM_TESTS=1 uv run pytest tests/runner/test_composer_live.py`.
3. Correr `seed_dinamo_voice.py` en staging y producción.
4. Setear `ATENDIA_V2_COMPOSER_PROVIDER=openai` en staging, monitorear 24h.
5. Flip toggle en producción para Dinamo. Monitorear:
   - `SELECT AVG(composer_cost_usd), AVG(composer_latency_ms) FROM turn_traces WHERE created_at > NOW() - INTERVAL '1 hour'`
   - Frecuencia de eventos `ERROR_OCCURRED:where=composer`
   - Frecuencia de `human_handoffs.reason='composer_failed'`
6. Rollback: `composer_provider=canned`, sin redeploy.

---

## 12. Criterios de aceptación

| # | Criterio | Verificación |
|---|---|---|
| 1 | Suite completa pasa | `pytest -q` |
| 2 | Coverage ≥85% | `pytest --cov-fail-under=85` |
| 3 | Live smoke pasa, no inventa precios | `RUN_LIVE_LLM_TESTS=1 pytest tests/runner/test_composer_live.py` |
| 4 | Snapshot prompt estable | `test_composer_system_prompt_snapshot_greet_dinamo` |
| 5 | 24h handoff funciona end-to-end | integration test con `last_activity_at = now-25h` |
| 6 | Fallback canned funciona cuando OpenAI cae | integration test con respx 503×3 |
| 7 | Costo medido ≈ $0.002/turno | `SELECT AVG(composer_cost_usd) FROM turn_traces WHERE created_at > NOW() - INTERVAL '1 hour'` |
| 8 | Manual smoke en staging, 5 conversaciones reales | cualitativo (nadie suena a FAQ) |

---

## 13. Fuera de alcance (YAGNI)

- Templates aprobados de Meta para outside-24h (Phase 3d).
- Catálogo + FAQs reales con embeddings (Phase 3c).
- Multi-mensaje con typing indicator entre bubbles (sumar `delay_ms` en `OutboundMessage`).
- Per-tenant API keys (BYOK enterprise).
- Per-stage tone override.
- A/B testing de prompts.
- Auto-redact de información sensible (tarjetas, IDs) que el cliente mande — futuro security pass.

---

## 14. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| LLM inventa precios pese a la instrucción | Test live `test_live_composer_quote_does_not_invent_price` corre antes de cada release; regex `\d{4,6}` cazaría una cifra |
| Latencia agregada (NLU + Composer) supera 3s P95 | Default timings: NLU ~600ms + Composer ~1.2s + retries solo ante fallo → P95 esperado ~2s. Si falla, fallback canned es instantáneo |
| Costo se dispara por conversaciones largas | `total_cost_usd` por conversación monitoreable; si una conversación supera $X, se dispara alerta (Phase 4) |
| LLM viola `max_words_per_message` | El system prompt lo instrucciona y `gpt-4o` con `temperature=0` lo respeta; tests live verifican; en peor caso el cliente recibe mensaje largo, no falla |
| `tenant_branding.voice` queda vacío en producción | Default de `Tone()` cubre todos los campos; el bot suena "neutral en español" en vez de "Dinamo informal" pero funciona |
| `pipeline.tone` se elimina y alguna fixture vieja se rompe | Pydantic ignora campos extra por default; tests existentes con `tone: {}` siguen pasando |
| Múltiples mensajes desorganizan el `turn_number` o el orden de delivery | `idempotency_key` incluye `:turn_number:i`; `metadata.message_index` queda persistido para debug |

---

## 15. Próximo paso

Generar plan de implementación detallado vía `superpowers:writing-plans`. Plan se commiteará como `docs/plans/04-fase-3b-composer-real.md` siguiendo la convención numérica.

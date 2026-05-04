# AtendIA v2 — Fase 3a: NLU real con `gpt-4o-mini` — Diseño

> **Estado:** diseño aprobado, pendiente de plan de implementación.
> **Fecha:** 2026-05-03
> **Autor:** brainstorm conjunto (Frank + Claude)
> **Reemplaza:** `KeywordNLU` como fuente de clasificación en producción.

---

## 1. Contexto y objetivo

La Fase 1 dejó la máquina de estados funcional sin LLM (`CannedNLU` para fixtures, `KeywordNLU` como fallback de producción). La Fase 2 conectó la transmisión real con WhatsApp Cloud API. **Phase 3a** sustituye `KeywordNLU` por un clasificador real basado en `gpt-4o-mini` con structured outputs, manteniendo todo el resto del sistema deterministicamente igual.

**Objetivo:** que el bot **entienda correctamente** lo que dice el cliente — intent, entidades, sentimiento, ambigüedad — sin todavía cambiar cómo redacta respuestas (Composer sigue con textos canned por acción) ni introducir tools reales o migración de Dinamo.

**Alcance acordado**: solo NLU. El Composer real (`gpt-4o`), tools reales y migración de Dinamo a DB son sub-fases 3b y 3c, fuera de este diseño.

---

## 2. Decisiones tomadas en el brainstorm

| # | Decisión | Elección | Alternativas descartadas |
|---|---|---|---|
| 1 | Alcance de Phase 3 | **Solo NLU** | NLU + Composer; Phase 3 completa con Dinamo |
| 2 | Modelo | **`gpt-4o-mini` + structured outputs (JSON schema)** | gpt-4o; Claude Haiku |
| 3 | Catálogo de entidades | **Extender `required_fields` a `{name, description}` + `optional_fields` opcional** | Tabla aparte por tenant; solo `required_fields`; entidades libres |
| 4 | Falla del LLM | **2 reintentos (500ms, 2000ms) → si fallan, `intent=unclear` con `ambiguities=["nlu_error:<exc>"]`** | Fail-fast inmediato; fallback a `KeywordNLU` |
| 5 | Contexto histórico | **Configurable en `pipeline.nlu.history_turns`. Default 2; Dinamo arranca en 4** | 0 turnos; 2 turnos hardcoded; tabla aparte |
| 6 | API key | **Global (`ATENDIA_V2_OPENAI_API_KEY`)** | Per-tenant; híbrido |
| 7 | Cost tracking | **Llenar columnas `nlu_*` de `turn_traces` desde el día 1** | Defer a Phase 4 |
| 8 | Tests | **Mocks con `respx` + 1 test live tras flag `RUN_LIVE_LLM_TESTS=1`** | Solo mocks; tests live siempre |
| 9 | Provider abstraction | **`Protocol NLUProvider` con `async classify(...)`** — refactor de los 3 providers | Drop-in con misma firma `feed`/`next` |
| 10 | Override per-tenant del prompt | **NO en este sprint** (queda como extensión futura `pipeline.nlu.system_prompt_override`) | Per-tenant desde el día 1 |
| 11 | Toggle de provider en producción | **Env var global `nlu_provider="openai" \| "keyword"`** | Columna por tenant |

---

## 3. Arquitectura

```
┌────────────────────────┐
│  meta_routes.py        │
│  (webhook handler)     │
└────────┬───────────────┘
         │ inbound text
         ▼
┌────────────────────────┐    ┌──────────────────┐
│  ConversationRunner    │───▶│  OpenAINLU       │  ◀── NUEVO
│  - fetch history N     │    │  (gpt-4o-mini)   │
│  - call NLU            │    │  classify(...)   │
│  - state machine       │◀───│  → (NLUResult,   │
│  - persist trace+costo │    │      Usage)      │
└────────────────────────┘    └──────────────────┘
                                       │ on failure (retries exhausted)
                                       ▼
                        NLUResult(intent=unclear,
                                  ambiguities=[nlu_error:<exc>])
```

### 3.1 Archivos nuevos

- `core/atendia/runner/nlu_protocol.py` — `Protocol NLUProvider` con `async classify(...)`.
- `core/atendia/runner/nlu_openai.py` — implementación con `AsyncOpenAI` + structured outputs.
- `core/atendia/runner/nlu_prompts.py` — system prompt template, history format, output instructions (editable en un solo lugar).
- `core/atendia/runner/nlu/pricing.py` — tabla estática `model → (input_price, output_price)` y `compute_cost(...)`.
- `core/tests/runner/test_nlu_openai.py` — unit tests con `respx`.
- `core/tests/runner/test_nlu_prompts.py` — render template + snapshot del system prompt.
- `core/tests/runner/test_nlu_live.py` — 1 smoke test gated por `RUN_LIVE_LLM_TESTS=1`.
- `core/tests/fixtures/nlu/qualify_system.txt` — snapshot del prompt renderizado.
- `core/tests/fixtures/nlu/smoke_dinamo.yaml` — 25 mensajes etiquetados para validación cualitativa.
- `scripts/upgrade_dinamo_pipeline_to_v4.py` — seed que actualiza el JSONB del pipeline activo de Dinamo al schema v4 con descripciones y bloque `nlu`.
- `core/atendia/db/migrations/versions/010_turn_traces_index.py` — index `(tenant_id, created_at)` en `turn_traces`.

### 3.2 Archivos modificados

- `core/atendia/contracts/pipeline_definition.py` — `FieldSpec` (Union string | object con normalización), `optional_fields`, `NLUConfig`.
- `contracts/pipeline_definition.schema.json` — JSON Schema canónico actualizado.
- `core/atendia/runner/conversation_runner.py` — fetch de historial; tipa `nlu_provider: NLUProvider`; lee `(NLUResult, UsageMetadata|None)`; popula columnas `nlu_*` y `total_cost_usd`.
- `core/atendia/runner/nlu_keywords.py` — refactor para implementar `classify(...)`.
- `core/atendia/runner/nlu_canned.py` — refactor para implementar `classify(...)`.
- `core/atendia/webhooks/meta_routes.py` — factory `build_nlu(settings)` que elige provider según `settings.nlu_provider`.
- `core/atendia/config.py` — campos: `openai_api_key`, `nlu_model`, `nlu_provider`, `nlu_timeout_s`, `nlu_retry_delays_ms`.
- `core/pyproject.toml` — agrega `openai>=1.50`.
- Tests existentes que usan `nlu.feed()/next()` — actualizados a `await nlu.classify(...)`.

### 3.3 Lo que no se toca

- Schema de `turn_traces` (las columnas `nlu_*` ya existen sin uso).
- Orchestrator (sigue determinista).
- Tools.
- `outbound_dispatcher` (Composer canned sigue intacto).
- Webhook signing, dedup, status callbacks.
- Realtime / WebSocket / Redis pub/sub.

---

## 4. Schema de pipeline v4

### 4.1 Cambios

```jsonc
{
  "version": 4,
  "nlu": {
    "history_turns": 4   // default 2; Dinamo en 4
  },
  "stages": [
    {
      "id": "qualify",
      "required_fields": [
        { "name": "interes_producto",
          "description": "Modelo de motocicleta o categoría que le interesa al cliente (ej: 150Z, scooter, deportiva)" },
        { "name": "ciudad",
          "description": "Ciudad donde reside el cliente, en México" }
      ],
      "optional_fields": [
        { "name": "nombre", "description": "Nombre del cliente" },
        { "name": "presupuesto_max", "description": "Tope máximo en MXN (numérico)" }
      ],
      "actions_allowed": [...],
      "transitions": [...]
    }
  ]
}
```

### 4.2 Backward compatibility

Pydantic v2 `field_validator` normaliza:

- `"ciudad"` (string suelto) → `FieldSpec(name="ciudad", description="")`.
- `{"name": "ciudad", "description": "..."}` → tal cual.

Resultado: cero migración de datos para tests/fixtures existentes. El schema canónico (`contracts/pipeline_definition.schema.json`) usa `oneOf [string, object]`. El test `test_schema_consistency.py` valida que ambos schemas (canonical vs Pydantic-generated) sigan coincidiendo.

### 4.3 Consecuencia operacional

El LLM extrae **únicamente** las claves enumeradas en `required_fields ∪ optional_fields` del stage actual. Cualquier otro dato que mencione el cliente queda fuera de `extracted_data`. Esto es deliberado: si querés capturar "qué tipo de uso le va a dar a la moto", lo agregás como `optional_fields`. Cero alucinación de claves.

### 4.4 Migración del pipeline de Dinamo

`scripts/upgrade_dinamo_pipeline_to_v4.py`:

1. Lee la fila activa de `tenant_pipelines` para Dinamo.
2. Para cada stage, transforma `required_fields: ["x", "y"]` a `[{"name":"x","description":"..."}, {"name":"y","description":"..."}]` con descripciones definidas en el script (revisión humana).
3. Agrega bloque `nlu: {"history_turns": 4}` a nivel raíz.
4. Inserta una nueva fila con `version=N+1`, `active=true`. La vieja queda con `active=false` para auditoría/rollback.

---

## 5. Interfaz `NLUProvider` y `OpenAINLU`

### 5.1 Protocol

```python
# core/atendia/runner/nlu_protocol.py
from typing import Protocol
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import FieldSpec

class UsageMetadata(BaseModel):
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int

class NLUProvider(Protocol):
    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],   # [(direction, text), ...] newest last
    ) -> tuple[NLUResult, UsageMetadata | None]: ...
```

`KeywordNLU` y `CannedNLU` también lo implementan; devuelven `(result, None)` porque no consumen tokens.

### 5.2 OpenAINLU

```python
class OpenAINLU:
    def __init__(self, *, api_key, model="gpt-4o-mini",
                 retry_delays_ms=(500, 2000), timeout_s=8.0):
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0,
                                   timeout=timeout_s)
        self._model = model
        self._delays = [0, *retry_delays_ms]

    async def classify(self, *, text, current_stage, required_fields,
                       optional_fields, history) -> tuple[NLUResult, UsageMetadata]:
        messages = build_prompt(text, current_stage, required_fields,
                                optional_fields, history)
        last_exc = None
        t0 = time.perf_counter()
        for delay in self._delays:
            if delay: await asyncio.sleep(delay / 1000)
            try:
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_schema",
                                     "json_schema": NLU_JSON_SCHEMA},
                    temperature=0,
                )
                result = NLUResult.model_validate_json(
                    resp.choices[0].message.content
                )
                usage = UsageMetadata(
                    model=resp.model,
                    tokens_in=resp.usage.prompt_tokens,
                    tokens_out=resp.usage.completion_tokens,
                    cost_usd=compute_cost(resp.model,
                                          resp.usage.prompt_tokens,
                                          resp.usage.completion_tokens),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result, usage
            except (APITimeoutError, APIConnectionError, RateLimitError,
                    InternalServerError, ValidationError) as e:
                last_exc = e
                continue
            except (AuthenticationError, BadRequestError) as e:
                last_exc = e
                break    # NO retry on auth or 400
        # Retries exhausted or non-retryable error
        return _error_result(last_exc), _zero_usage(model=self._model,
                                                   latency_ms=int((time.perf_counter() - t0)*1000))
```

`_error_result(exc)` retorna `NLUResult(intent=unclear, confidence=0.0, ambiguities=[f"nlu_error:{type(exc).__name__}"])`.

---

## 6. Prompts (módulo editable)

`core/atendia/runner/nlu_prompts.py` es la única fuente de verdad. Tres bloques editables:

### 6.1 SYSTEM_PROMPT_TEMPLATE

```
Eres un clasificador de intenciones para un asistente de ventas por WhatsApp.
Tu única tarea es analizar el último mensaje del cliente y devolver un JSON
estricto que cumpla el schema. NO redactas respuestas. NO sugieres acciones.

Stage actual de la conversación: {{stage}}

Campos requeridos para avanzar (extrae si el cliente los menciona, explícita
o implícitamente, en el último mensaje):
{{required_fields_block}}

Campos opcionales (extrae si aparecen; no los inventes si no aparecen):
{{optional_fields_block}}

{{output_instructions}}
```

### 6.2 HISTORY_FORMAT y ROLE_LABELS

```python
HISTORY_FORMAT = "[{{role}}] {{text}}"
ROLE_LABELS = {"inbound": "cliente", "outbound": "asistente"}
```

### 6.3 OUTPUT_INSTRUCTIONS

```
Reglas de salida:
- Si tu confianza global sobre la intent es < 0.7, marca un string descriptivo
  en "ambiguities" (ej: "intent_borderline_buy_vs_ask_price").
- NO inventes valores. Si el cliente no dijo un dato, NO lo incluyas en entities.
- Para entities numéricas, devuelve número (no string).
- intent: greeting | ask_info | ask_price | buy | schedule | complain |
          off_topic | unclear.
- sentiment: positive, neutral, negative.
- confidence: número 0.0–1.0 sobre tu certeza de la intent.
```

### 6.4 Renderizado

Helper interno `render_template(template, **vars)` con regex `r"\{\{\s*(\w+)\s*\}\}"`. Si queda algún placeholder sin sustituir, lanza `RuntimeError`. Sin Jinja u otro engine: el archivo debe leerse como prompt plano.

### 6.5 Tokens y costo estimados (Dinamo, 4 turnos, en español)

| Componente | Tokens |
|---|---|
| System (con catálogo de campos) | ~250 |
| Historial 4 turnos | ~200 |
| Mensaje actual | ~30 |
| Output JSON | ~80 |
| **Total** | **~560 / turno** |

Costo: input 480 × $0.15/1M + output 80 × $0.60/1M ≈ **$0.00012 / turno** ≈ **$0.0036 / conversación de 30 turnos** ≈ **$3.60 / 1.000 conversaciones**.

---

## 7. Reintentos, errores y cost tracking

### 7.1 Excepciones y comportamiento

| Excepción OpenAI | Reintenta | Razón |
|---|---|---|
| `APITimeoutError` | sí | timeout local, suele ser transitorio |
| `APIConnectionError` | sí | red caída temporalmente |
| `RateLimitError` (429) | sí | OpenAI throttling |
| `InternalServerError` (5xx) | sí | issue del lado de OpenAI |
| `pydantic.ValidationError` al parsear | sí | structured outputs degradado |
| `AuthenticationError` (401) | **no** | API key mala; reintentar no ayuda |
| `BadRequestError` (400) | **no** | schema o prompt mal armados; reintentar repite el bug |

Tras agotar reintentos o caer en una excepción no-reintentable: `intent=unclear`, `ambiguities=["nlu_error:<ExcType>"]`. El orquestador (vía `is_ambiguous`) responde con `ask_clarification` — el cliente recibe "disculpa, ¿podrías reformular?" en el peor caso.

### 7.2 Observabilidad de errores

`ConversationRunner.run_turn()` detecta `ambiguities` que empiezan con `"nlu_error:"` y emite un evento `EventType.ERROR_OCCURRED` con `payload={"where": "nlu", "exc_type": "...", "retry_count": N}`. Aparece en `events`, en pub/sub y eventualmente en el panel realtime.

### 7.3 Cost tracking — `pricing.py`

```python
MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # USD por 1M tokens (input, output) — verificado al 2026-05
    "gpt-4o-mini":            (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o-mini-2024-07-18": (Decimal("0.150"), Decimal("0.600")),
}

def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    if model not in MODEL_PRICING:
        return Decimal("0")
    in_p, out_p = MODEL_PRICING[model]
    return ((Decimal(tokens_in) * in_p +
             Decimal(tokens_out) * out_p) / Decimal("1000000"))\
           .quantize(Decimal("0.000001"))
```

### 7.4 Persistencia

`ConversationRunner` llena en cada turno:

```python
trace.nlu_model       = usage.model
trace.nlu_tokens_in   = usage.tokens_in
trace.nlu_tokens_out  = usage.tokens_out
trace.nlu_cost_usd    = usage.cost_usd
trace.nlu_latency_ms  = usage.latency_ms
```

Y suma en `conversation_state`:

```sql
UPDATE conversation_state
SET total_cost_usd = total_cost_usd + :nlu_cost_usd
WHERE conversation_id = :cid
```

### 7.5 Index nuevo

Migración `010_turn_traces_index.py`:

```python
op.create_index(
    "ix_turn_traces_tenant_created",
    "turn_traces",
    ["tenant_id", "created_at"],
)
```

Habilita queries del tipo "costo total y P95 de latencia por tenant en el último día" sin escaneo completo.

---

## 8. Configuración

`core/atendia/config.py` agrega:

```python
class Settings(BaseSettings):
    # ... existentes ...
    openai_api_key: str = Field(default="")
    nlu_model: str = Field(default="gpt-4o-mini")
    nlu_provider: Literal["openai", "keyword"] = Field(default="keyword")
    nlu_timeout_s: float = Field(default=8.0)
    nlu_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
```

Prefix `ATENDIA_V2_` por convención existente. `.env.example` documenta cada variable.

---

## 9. Tests

| Archivo | Tipo | Casos |
|---|---|---|
| `test_nlu_openai.py` | unit (mock respx) | happy path, confidence baja, retry exitoso, todos los reintentos fallan, 401 sin retry, modelo devuelve JSON inválido, costos correctos |
| `test_nlu_prompts.py` | unit | render template, error si quedan placeholders, snapshot byte-idéntico de un prompt fijo |
| `test_nlu_keyword.py` | unit | refactor menor: `await nlu.classify(...)` en vez de `feed/next` |
| `test_canned_nlu.py` | unit | refactor menor |
| `test_conversation_runner.py` | unit | cambios mecánicos por la nueva firma; tests sobre cost tracking en `turn_traces` |
| `test_inbound_to_runner.py` | integration | sigue verde con `OpenAINLU` mockeado; nuevo caso: 503 en todos los reintentos → evento `ERROR_OCCURRED` emitido |
| `test_nlu_live.py` | live (gated) | smoke real contra OpenAI: clasifica una intent obvia, confidence > 0.7, costo > 0 |

**Cobertura objetivo**: ≥ 85% (gate actual). El nuevo código debería entrar al ~95% por su simplicidad.

**CI**: `RUN_LIVE_LLM_TESTS` queda OFF en GitHub Actions. Local-only smoke check.

---

## 10. Plan de rollout

Pasos secuenciales, todos reversibles:

1. **Code merge** con `nlu_provider="keyword"` por default — producción no cambia, las nuevas rutas existen pero no se usan.
2. **Provisión de API key** en `.env` de prod (`ATENDIA_V2_OPENAI_API_KEY`).
3. **Smoke test** local con `RUN_LIVE_LLM_TESTS=1`.
4. **Activar** `nlu_provider=openai` en prod.
5. **Monitoreo** durante 24–48h: latencia P95, tasa de `nlu_error:*`, costo agregado.
6. **Rollback** instantáneo si algo se rompe: `nlu_provider=keyword`, sin redeploy.

---

## 11. Criterios de aceptación

| # | Criterio | Verificación |
|---|---|---|
| 1 | Clasifica intents correctamente en 25 conversaciones smoke | Fixture `tests/fixtures/nlu/smoke_dinamo.yaml`; intent + confidence > 0.7 |
| 2 | Extracción respeta el catálogo del stage | Test integration: "soy de CDMX" en `qualify` → `extracted_data.ciudad == "CDMX"`; "soy ingeniero" → no agrega clave nueva |
| 3 | Confidence < 0.7 dispara `ask_clarification` | Test e2e con OpenAI mockeado a 0.5 |
| 4 | Si OpenAI cae, conversación sigue funcionando | Test integration: 503 × 3 → `intent=unclear`, evento `ERROR_OCCURRED`, mensaje de clarificación dispatcheado |
| 5 | `turn_traces.nlu_cost_usd` y `conversation_state.total_cost_usd` se llenan | Test integration |
| 6 | Cobertura ≥ 85% | `pytest --cov` |
| 7 | Smoke en staging con número WhatsApp real, 5 conversaciones manuales completas | Manual; cualitativo |
| 8 | Costo medido ≈ estimado (~$0.0001/turno) | `SELECT AVG(nlu_cost_usd) FROM turn_traces WHERE created_at > NOW() - INTERVAL '1 hour'` |

---

## 12. Fuera de alcance (YAGNI)

- **Composer real** (`gpt-4o`) — Phase 3b.
- **Tools reales** con queries a `tenant_catalogs`/`tenant_faqs` — Phase 3c.
- **Migración de catálogo y FAQs de Dinamo a DB** + embeddings — Phase 3c.
- **Override per-tenant** del system prompt o retry config.
- **Endpoint REST** para ver `turn_traces` desde frontend — Phase 4.
- **Métricas agregadas** (Grafana, dashboards) — Phase 4.
- **Soporte de múltiples API keys** o BYOK — futuro si lo pide un tenant enterprise.
- **Cache de respuestas idénticas** del NLU — improbable que justifique la complejidad dado el costo.

---

## 13. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| OpenAI cambia formato de structured outputs | Schema versionado por nuestro lado; tests live tras flag detectan deriva |
| El prompt se afina mucho y se vuelve frágil | Snapshot test del prompt + version control |
| Costo se dispara por conversación atascada en loop | Cap de turnos por conversación ya existente; `total_cost_usd` por conversación monitoreable |
| API key se filtra en logs | Prohibido logear `Settings`; tests verifican que `repr(settings)` no contiene la key (TODO en plan) |
| Latencia agregada (NLU + Composer canned) supera 2s | NLU solo: ~400–800ms P95 esperado; Composer canned es <10ms |
| Inconsistencia entre `KeywordNLU` y `OpenAINLU` durante rollout parcial | Feature flag global, no per-conversación: una sola ruta activa a la vez |

---

## 14. Próximo paso

Cerrado este diseño, el siguiente entregable es el **plan de implementación detallado** con tareas verificables y commits por bloque, generado vía `superpowers:writing-plans`. El plan se commiteará como `docs/plans/03-fase-3a-nlu-real.md`, manteniendo la convención numérica de los planes existentes (Phase 1 = 01, Phase 2 = 02, Phase 3a = 03).

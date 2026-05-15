# DebugPanel completion (C2) — design

> **Estado:** approved (2026-05-15)
> **Reemplaza:** parte del item C2 en `docs/ESTADO-Y-GAPS.md` §2.3
> **Próximo:** implementation plan vía writing-plans skill

---

## 0. TL;DR

El audit decía "DebugPanel v2 cubre ~40% de v1". Tras leer el código
real, lo que está aterrizado es **mucho más** que eso (~1500 LOC en
turn-traces components). Migración 045 ya añadió los 5 campos clave
(`router_trigger`, `raw_llm_response`, `agent_id`, `kb_evidence`,
`rules_evaluated`).

Faltan **8 items**, todos pequeños:

| # | Item | Tipo | Datos fuente |
|---|---|---|---|
| 1 | History count ("turno 5 de 12") | frontend | derivable de `turn_number` |
| 2 | Agent name + role en StepComposer | frontend | join con `agents` (ya tenemos `agent_id`) |
| 3 | Actions panel (lista quote/lookup_faq/...) | frontend | `composer_output.action_payload` |
| 4 | Per-step latency breakdown | frontend | `*_latency_ms` fields ya existen, regroup |
| 5 | LLM provider explícito (openai/canned/fallback) | **backend + frontend** | migración 048 |
| 6 | Cleaned text (lo que el bot vio vs lo que el cliente escribió) | **backend + frontend** | migración 048 |
| 7 | Prompt template breakdown (% Identidad/Guardrails/Brand/KB) | frontend | parsea `composer_input.messages` |
| 8 | Tool calls timeline rich | frontend | `tool_calls[]` ya existe |

**Costo estimado:** 1.5 sesiones (~3-4h).

---

## 1. Contexto: qué hay hoy

### 1.1 Backend
`turn_traces` (Phase 1 + migraciones 010, 014, 045) ya tiene:

```python
# Identidad
id, conversation_id, tenant_id, turn_number, created_at

# Inbound
inbound_message_id, inbound_text

# NLU
nlu_input, nlu_output, nlu_model, nlu_tokens_in, nlu_tokens_out,
nlu_cost_usd, nlu_latency_ms

# Estado
state_before, state_after, stage_transition

# Composer
composer_input, composer_output, composer_model, composer_tokens_in,
composer_tokens_out, composer_cost_usd, composer_latency_ms

# Vision
vision_cost_usd, vision_latency_ms

# Tools (vía relación tool_calls[])
tool_cost_usd, tool_calls: list[ToolCallRow]

# Routing + agente (migración 045)
flow_mode, router_trigger, raw_llm_response, agent_id, kb_evidence,
rules_evaluated

# Outbound
outbound_messages

# Totales
total_cost_usd, total_latency_ms

# Errores
errors, bot_paused
```

Lo que falta persistir:
- `composer_provider` — "openai" | "canned" | "fallback" — el adapter que efectivamente respondió
- `inbound_text_cleaned` — el texto tras normalización (strip de markers, lowercase, etc.) que el NLU realmente vio

### 1.2 Frontend
`frontend/src/features/turn-traces/` (1500 LOC):

```
api.ts                                 105 LOC — TurnTraceDetail interface
components/
  FlowModeBadge.tsx                     48 LOC ✅ items 1-relacionado
  TurnTraceList.tsx                    106 LOC
  TurnTraceInspector.tsx                81 LOC
  TurnStoryView.tsx                    342 LOC ✅ steps inbound/nlu/mode/knowledge/composer/transition
  TurnPanels.tsx                       581 LOC ✅ Anomaly/Entity/Knowledge/StateDiff/Latency/Cost/Error/FactPack/Rules/Agent/RawJson
lib/
  turnStory.ts                         169 LOC — buildTurnStory()
  turnAnalysis.ts                      447 LOC — classifyEntities/diffState/extractKnowledge/etc.
```

`DebugPanel.tsx` (132 LOC, en `features/conversations/`) compone todo
lo anterior con un layout vertical de scroll-area.

### 1.3 Audit fail-mode actual
> "v2 tiene 132+303 — cubre ~40%"

Esa medición contaba solo `DebugPanel.tsx (132) + TurnTraceSections (303)`
y omitía `TurnPanels (581) + TurnStoryView (342) + turnAnalysis (447) +
turnStory (169)`. La cobertura real es ~85% del wishlist de v1; las
asperezas son las 8 piezas de este doc.

---

## 2. Arquitectura del cambio

### 2.1 Backend (migración 048)

**Una migración aditiva** (sin destructivo):

```python
# atendia/db/migrations/versions/048_turn_traces_provider_cleaned.py
"""048_turn_traces_provider_cleaned

Adds two nullable columns to turn_traces for C2 DebugPanel coverage:

* composer_provider — which adapter served this turn ("openai",
  "canned", "fallback"). Helps operators distinguish "the LLM said X"
  from "the LLM was unreachable and the canned reply fired".

* inbound_text_cleaned — the normalized text the NLU actually saw
  (after diacritic strip, lowercase, markdown removal). Side-by-side
  with inbound_text in the story lets operators spot cases where the
  cleanup itself altered meaning.
"""
op.add_column(
    "turn_traces",
    sa.Column("composer_provider", sa.String(20), nullable=True),
)
op.add_column(
    "turn_traces",
    sa.Column("inbound_text_cleaned", sa.Text, nullable=True),
)
op.create_check_constraint(
    "ck_turn_traces_composer_provider",
    "turn_traces",
    "composer_provider IS NULL OR composer_provider IN ('openai', 'canned', 'fallback')",
)
```

**Runner instrumentation** (2 sitios en `conversation_runner.py`):

```python
# Wherever we currently call build_composer(settings).compose(...):
output, usage = await composer.compose(input=...)
+ provider = _composer_provider_for(composer)  # tiny helper that
+                                              # returns the adapter
+                                              # short-name

# Wherever we currently store inbound_text:
+ cleaned = _clean_inbound_text(inbound.text)
# (existing _clean is already used by NLU; just persist what it produced)
```

`_composer_provider_for` reads the class name:
- `OpenAIComposer` → `"openai"`
- `CannedComposer` → `"canned"`
- `OpenAIComposer` with `_fallback` triggered → `"fallback"` (already
  tracked internally via `UsageMetadata.fallback_used`)

### 2.2 Frontend

**Una nueva file y mejoras a 3 archivos existentes**:

```
src/features/turn-traces/
  api.ts                       # add 2 fields to TurnTraceDetail
  lib/turnAnalysis.ts          # +4 new analyzers
    analyzeActions(trace)
    analyzeLatencyPerStep(trace)
    analyzePromptTemplate(trace)
    analyzeToolCalls(trace)
  components/
    TurnPanels.tsx             # +4 new panel exports
      ActionsPanel
      LatencyPerStepBar         # replaces / augments LatencyStackedBar
      PromptTemplateBreakdown
      ToolCallsTimeline
    TurnStoryView.tsx          # tweaks to StepInbound + StepComposer
                                 (history count, agent name, cleaned text,
                                  provider badge)
```

**`DebugPanel.tsx`** absorbs the new panels — 4 new sections in the
vertical scroll, separated by `<Separator />` like the existing ones.

### 2.3 Data flow

```
turn_traces row (DB)
  │
  ├─ GET /api/v1/turn-traces/:id (existing route)
  │   → TurnTraceDetail (api.ts) — now with 2 extra fields
  │
  └─ frontend
      │
      ├─ buildTurnStory(trace) → StoryStep[]  # adds providerBadge to composer step
      │   → TurnStoryView                      # adds history count to inbound, agent to composer
      │
      ├─ analyzeActions(trace) → ActionItem[]
      │   → <ActionsPanel />
      │
      ├─ analyzeLatencyPerStep(trace) → StepLatency[]
      │   → <LatencyPerStepBar />
      │
      ├─ analyzePromptTemplate(trace) → PromptSection[]
      │   → <PromptTemplateBreakdown />
      │
      └─ analyzeToolCalls(trace) → ToolCallTimelineItem[]
          → <ToolCallsTimeline />
```

---

## 3. Specs por item

### Item 1 — History count ("turno 5 de 12")

**Donde:** `TurnStoryView.StepInbound` (top of the story).

**Datos:** `trace.turn_number` (ya disponible) + total turns of
conversation. Hoy el detail endpoint no devuelve el total — necesita
una de dos:

- **Opción A** (no backend): el componente recibe `totalTurns` como
  prop desde DebugPanel, que ya tiene la lista vía `turnTracesApi.list`.
- **Opción B** (backend): añadir `conversation_turn_count` al detail
  response. 1 línea en `turn_traces_routes.py`.

**Elegimos A** — el DebugPanel ya está en contexto de la conversación
y puede pasar el total.

**Render:** un chip discreto sobre el primer card del story:

```
[5 / 12]   • 12:34 PM
```

### Item 2 — Agent name + role en StepComposer

**Donde:** `TurnStoryView.StepComposer` (cabecera del card).

**Datos:** `trace.agent_id` (existente). Necesitamos `name` y `role`.

- **Opción A** (extra query): fetch `/agents/:id` cuando hay `agent_id`.
- **Opción B** (extender list response): el detail endpoint ya hace
  join con agents? Verificar.
- **Opción C** (sin agente): si `agent_id` es null, mostrar nada.

**Elegimos A** — query separado con stale-time grande (los nombres
de agente no cambian seguido). React Query cachea, así que abrir
varios turnos del mismo agente solo dispara 1 fetch.

**Render:** justo debajo del "El bot respondió":

```
🤖 Bot respondió · Mariana (Ventas)
   gpt-4o · 1.2s · $0.0042
```

### Item 3 — Actions panel

**Donde:** Nuevo `<ActionsPanel />` en TurnPanels, debajo de KnowledgePanel.

**Datos:** `composer_output.action_payload` — un dict con shape variable.
Ejemplos reales del codebase:
- `quote`: `{plan, monto_mensual, plazo_meses, ...}`
- `lookup_faq`: `{faq_id, question, answer, score}`
- `book_appointment`: `{advisor_id, scheduled_at, ...}`

**Render:** lista con chip por acción + JSON expandible:

```
ACCIONES (2)
┌─────────────────────────────────────┐
│ ⚡ quote                              │
│   plan=Premium · monto=$2,400 · 12m  │
│   [Ver detalle]                       │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ 🔍 lookup_faq · score 0.91           │
│   "¿Qué documentos necesito?"        │
└─────────────────────────────────────┘
```

### Item 4 — Per-step latency breakdown

**Donde:** Reemplaza el `LatencyStackedBar` actual con `LatencyPerStepBar`.

**Datos:**
- `nlu_latency_ms`
- `vision_latency_ms`
- `composer_latency_ms`
- `tool_calls[].latency_ms` (suma)
- diferencia con `total_latency_ms` = "overhead" (DB + Redis + transport)

**Render:** una barra horizontal segmentada con leyenda:

```
LATENCIA (2,847ms total)
NLU      ▓░░░░░░░░░  342ms  12%
Vision   ░░░░░░░░░░    0ms   0%
Composer ▓▓▓▓▓▓▓▓░░ 1,820ms  64%
Tools    ▓▓░░░░░░░░  421ms  15%
Overhead ▓░░░░░░░░░  264ms   9%
```

### Item 5 — LLM provider explícito

**Donde:** Badge en `TurnStoryView.StepComposer` header.

**Datos (post-migración 048):** `trace.composer_provider`.

**Render:**
- `openai` → badge azul claro
- `canned` → badge amarillo "Canned"
- `fallback` → badge ámbar "Fallback (LLM falló)"
- `null` (rows legacy) → no render

### Item 6 — Cleaned text

**Donde:** `TurnStoryView.StepInbound` — debajo del texto original.

**Datos (post-migración 048):** `trace.inbound_text_cleaned`.

**Render:**
- Si `cleaned !== original`: mostrar "Texto limpiado" en un secondary card
- Si `cleaned === original`: no mostrar nada (no clutter)

```
[Cliente] «Hola, quiero el credito de la TC ... »
          → Limpio: «hola quiero el credito de la tc»
```

### Item 7 — Prompt template breakdown

**Donde:** Nuevo `<PromptTemplateBreakdown />` en TurnPanels.

**Datos:** `composer_input.messages` — array OpenAI-style. El sistema
prompt es siempre el `[0]`. Lo parseamos por marcadores:

```
# Marcadores actuales en composer_prompts.py
"### IDENTIDAD"
"### MARCO DE LA CONVERSACIÓN"
"### REGLAS QUE NO PUEDES ROMPER"
"### CONOCIMIENTO DEL TENANT"
"### CONTEXTO DEL CLIENTE"
"### MODO ACTUAL"
"### ACCIÓN A REALIZAR"
```

Cada sección → bar con su % del prompt en tokens.

**Render:**
```
ANATOMÍA DEL PROMPT (3,420 tokens)
Identidad           ▓▓░░░░░░░░  18%   615
Reglas              ▓▓▓░░░░░░░  31%  1,060
Conocimiento        ▓▓▓▓░░░░░░  38%  1,300
Contexto cliente    ▓░░░░░░░░░   8%   274
Otros               ▓░░░░░░░░░   5%   171
```

Tokens se estiman por `chars / 4` (heurística OpenAI estándar) — no
es exacto pero suficiente para ver dominancia.

### Item 8 — Tool calls timeline rich

**Donde:** Nuevo `<ToolCallsTimeline />` en TurnPanels.

**Datos:** `trace.tool_calls[]` (ya disponible).

**Render:** timeline horizontal con cada call:

```
HERRAMIENTAS (3)
[search_catalog]   421ms ✓
  ├─ input: {query:"motoneta", limit:5}
  └─ output: 3 hits, top score=0.94

[quote]             87ms ✓
  ├─ input: {sku:"adventure-150", plazo:12}
  └─ output: $2,400 monthly

[lookup_faq]       213ms ✗ error
  └─ error: "No FAQ matched 'horario sucursal'"
```

---

## 4. Tests

### 4.1 Backend (1 test)

`tests/api/test_turn_traces_routes.py::test_detail_returns_composer_provider_and_cleaned_text`

Seed un trace con los 2 campos nuevos, fetch `/turn-traces/:id`,
assert ambos están en la respuesta.

### 4.2 Frontend (5 tests)

`tests/features/turn-traces/`:

- `ActionsPanel.test.tsx` — renderea con 2 actions; renderea empty
  state si `action_payload` vacío.
- `LatencyPerStepBar.test.tsx` — todos los slices presentes; ratios
  suman 100%.
- `PromptTemplateBreakdown.test.tsx` — parsea un prompt con 3 marcadores;
  empty state si solo hay text plano.
- `ToolCallsTimeline.test.tsx` — renderea 1 success + 1 error.
- `TurnStoryView.test.tsx` — extends existing; assert history count
  chip + agent name + cleaned text + provider badge aparecen.

---

## 5. Migration & rollback

**Apply:** `uv run alembic upgrade head` aplica 048 (1-2s).

**Rollback:** la migración tiene `downgrade()` que dropea las 2 columnas + check constraint. Datos en columnas se pierden pero como son
nullable, las apps siguen funcionando con `NULL`.

**Legacy rows:** todas las rows existentes tienen los 2 campos en `NULL`.
Frontend detecta `null` → no renderea el badge/cleaned section.

---

## 6. No-goals (explícitos)

Items que el audit pedía pero **NO** entran en C2:

- ❌ A14 ("Why did the agent say X" deep-link desde mensaje outbound) —
  pertenece a Sprint A14 según ESTADO-Y-GAPS. Lo dejamos como
  follow-up "cheap glue" post-C2.
- ❌ `flow_steps JSONB` (Approach C en el brainstorm) — scope creep.
- ❌ Per-action drilling page (separate route por action) — overkill.

---

## 7. Riesgos + mitigaciones

| Riesgo | Mitigación |
|---|---|
| Migration 048 falla en prod por timing | Aditiva pura, sin DDL bloqueante. Test en CI primero |
| `composer_provider` mal detectado para casos edge | El helper `_composer_provider_for` lee la clase; cualquier nueva clase de composer cae en `null` (degrada limpio) |
| `inbound_text_cleaned` añade ~200 bytes/turn → bloat | Trade-off aceptable: 200 bytes × 100k turns/mes = 20 MB/mes |
| Frontend renders panels que no tienen datos | Cada panel tiene empty-state explícito, igual que paneles existentes |

---

## 8. Working contract (de ESTADO-Y-GAPS §11)

- Una pieza por sesión: este doc cierra C2 entero o explica qué cortó.
- TDD: test RED → implementación GREEN → verificación con `pytest -v` antes de claim.
- Verificación antes de completar: re-correr suite, leer output, después afirmar.

---

## 9. Siguiente paso

Invocar `writing-plans` skill para descomponer en pasos atómicos
ordenados que ejecutar con TDD.

# AtendIA v2 — Fase 3b: Composer real (`gpt-4o`) — Plan de Implementación

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Reemplazar `_PHASE2_TEXTS` (textos canned por acción) por un `OpenAIComposer` que redacta con `gpt-4o`, mantiene tono per-tenant, devuelve `list[str]` (1-3 mensajes), llena `turn_traces.composer_*`, escala a `human_handoffs` cuando OpenAI falla o cuando estamos fuera de la ventana de 24h, y deja el contrato Composer↔Tools listo para Phase 3c.

**Architecture:** `ComposerProvider` Protocol con dos implementaciones: `CannedComposer` (legacy + fallback) y `OpenAIComposer` (gpt-4o + structured outputs + retry + fallback inyectable). Tono leído desde `tenant_branding.voice` JSONB validado vs `Tone(BaseModel)`. Tool stubs (quote/lookup_faq/search_catalog) devuelven `ToolNoDataResult` con `hint` que el Composer recibe en `action_payload`. Outbound dispatcher refactorizado a `enqueue_messages(messages: list[str], ...)`. 24h check vía `conversations.last_activity_at`.

**Tech Stack:** Python 3.12 · OpenAI SDK ≥1.50 (gpt-4o) · Pydantic 2.9+ · respx (mocks) · pytest-asyncio. Reuso del scaffolding de Phase 3a (pricing, retry helpers, prompt templates).

**Diseño aprobado:** [`docs/plans/2026-05-05-fase-3b-composer-real-design.md`](./2026-05-05-fase-3b-composer-real-design.md).

**Pre-requisitos del entorno:**
- Working tree limpio en branch dedicado (`feat/phase-3b-composer-real`).
- Postgres v2 + Redis v2 corriendo (ya están de Phase 3a).
- Migraciones al día: `9a35558e5d5f` (T3 de Phase 3a).
- `cd core && uv run pytest -q` pasa con 139 tests + 2 skipped.

**Convenciones:**
- TDD: cada feature arranca con un test que falla.
- Commits chicos por bloque lógico.
- Sin `--no-verify`, sin saltarse hooks.

---

## Mapa de tareas

| Bloque | Tareas | Foco |
|---|---|---|
| **A.** Setup + helpers compartidos | T1–T4 | Settings, pricing gpt-4o, refactor de helpers + errors |
| **B.** Tone | T5–T7 | Pydantic `Tone`, seed Dinamo, eliminar `pipeline.tone` |
| **C.** Tool stubs con placeholder | T8 | `ToolNoDataResult`, actualizar 3 stubs |
| **D.** Composer Protocol + Canned | T9–T10 | Contract + fallback baseline |
| **E.** Composer Prompts | T11–T13 | Templates + `build_composer_prompt` + snapshot |
| **F.** OpenAIComposer | T14–T19 | Happy path + retries + fallback + schema |
| **G.** Outbound dispatcher refactor | T20–T21 | `enqueue_messages` + tests |
| **H.** Runner integration | T22–T25 | Tool dispatch + 24h check + Composer call + cost |
| **I.** Webhook factory + integration | T26–T27 | `build_composer` + E2E tests |
| **J.** Live + verificación final | T28–T30 | Live smoke + coverage gate + README/memory |

**Total: 30 tareas. Estimado: 4–5 días (1 dev).**

---

# Bloque A — Setup + helpers compartidos

## Task 1: Extender `Settings` con campos de Composer

**Files:**
- Modify: `core/atendia/config.py`
- Modify: `core/tests/test_config.py`
- Modify: `.env.example`

**Step 1: Agregar test que falla**

Append to `core/tests/test_config.py`:

```python
def test_composer_provider_default_is_canned():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.composer_provider == "canned"
    assert s.composer_model == "gpt-4o"
    assert s.composer_timeout_s == 8.0
    assert s.composer_retry_delays_ms == [500, 2000]
    assert s.composer_max_messages == 2
```

**Step 2: Verificar fallo**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/test_config.py::test_composer_provider_default_is_canned -v
```

Expected: FAIL — `'Settings' object has no attribute 'composer_provider'`.

**Step 3: Editar `core/atendia/config.py`**

Agregar después de los campos `nlu_*`:

```python
composer_provider: Literal["openai", "canned"] = Field(default="canned")
composer_model: str = Field(default="gpt-4o")
composer_timeout_s: float = Field(default=8.0)
composer_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
composer_max_messages: int = Field(default=2, ge=1, le=3)
```

**Step 4: Test pasa**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/test_config.py -v
```

Expected: 2 PASS.

**Step 5: Actualizar `.env.example`**

Agregar al bloque `# Phase 3a — NLU` un nuevo bloque:

```
# Phase 3b — Composer
ATENDIA_V2_COMPOSER_PROVIDER=canned       # change to "openai" to enable real Composer
ATENDIA_V2_COMPOSER_MODEL=gpt-4o
ATENDIA_V2_COMPOSER_TIMEOUT_S=8.0
ATENDIA_V2_COMPOSER_RETRY_DELAYS_MS=[500,2000]
ATENDIA_V2_COMPOSER_MAX_MESSAGES=2
```

**Step 6: Commit**

```bash
git add core/atendia/config.py core/tests/test_config.py .env.example
git commit -m "feat(config): add Composer settings (provider toggle, model, timeouts)"
```

---

## Task 2: Agregar `gpt-4o` al `MODEL_PRICING`

**Files:**
- Modify: `core/atendia/runner/nlu/pricing.py`
- Modify: `core/tests/runner/test_pricing.py`

**Step 1: Test que falla**

Append:

```python
def test_compute_cost_gpt_4o_known():
    # 450 prompt + 80 completion at $2.50/$10.00 per 1M
    cost = compute_cost("gpt-4o", tokens_in=450, tokens_out=80)
    # 450 * 2.5 / 1_000_000 + 80 * 10 / 1_000_000 = 0.001125 + 0.000800 = 0.001925
    assert cost == Decimal("0.001925")


@pytest.mark.parametrize("model_id", ["gpt-4o", "gpt-4o-2024-08-06"])
def test_pricing_gpt_4o_dated_alias(model_id):
    assert MODEL_PRICING[model_id] == MODEL_PRICING["gpt-4o"]
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_pricing.py -v
```

Expected: 2 fails — `'gpt-4o'` not in `MODEL_PRICING`.

**Step 3: Editar `pricing.py`**

```python
MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini":            (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o-mini-2024-07-18": (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o":                 (Decimal("2.500"), Decimal("10.000")),
    "gpt-4o-2024-08-06":      (Decimal("2.500"), Decimal("10.000")),
}
```

**Step 4: Test pasa**

```bash
cd core && uv run pytest tests/runner/test_pricing.py -v
```

Expected: 8 PASS (6 previous + 2 new).

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu/pricing.py core/tests/runner/test_pricing.py
git commit -m "feat(nlu/pricing): add gpt-4o pricing for Composer"
```

---

## Task 3: Extraer `_RETRIABLE`/`_NON_RETRIABLE` a módulo compartido

**Files:**
- Create: `core/atendia/runner/_openai_errors.py`
- Modify: `core/atendia/runner/nlu_openai.py`
- (No new tests — refactor only; existing nlu_openai tests must still pass)

**Step 1: Crear `core/atendia/runner/_openai_errors.py`**

```python
"""Shared OpenAI exception taxonomy for NLU and Composer.

Use as:
    try:
        ...
    except _RETRIABLE as e:
        # retry with backoff
    except _NON_RETRIABLE as e:
        # fail fast, fall back

Note on order: catch _RETRIABLE FIRST, _NON_RETRIABLE second.
RateLimitError/InternalServerError are subclasses of APIStatusError;
listing _NON_RETRIABLE first would route 429/5xx to the fail-fast path.
"""
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from pydantic import ValidationError


_RETRIABLE = (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    InternalServerError,
)

_NON_RETRIABLE = (
    AuthenticationError,
    BadRequestError,
    ValidationError,
    APIStatusError,
)
```

**Step 2: Refactor `nlu_openai.py`**

Replace the inline tuples with:

```python
from atendia.runner._openai_errors import _NON_RETRIABLE, _RETRIABLE
```

Drop the local definitions and the long openai/pydantic import block (keep only what's still used: `AsyncOpenAI`).

**Step 3: Verify**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py -v
```

Expected: all 14 PASS, no regressions.

**Step 4: Commit**

```bash
git add core/atendia/runner/_openai_errors.py core/atendia/runner/nlu_openai.py
git commit -m "refactor(runner): extract OpenAI error taxonomy to shared module"
```

---

## Task 4: Extraer template helpers a módulo compartido

**Files:**
- Create: `core/atendia/runner/_template_helpers.py`
- Modify: `core/atendia/runner/nlu_prompts.py`

**Step 1: Crear `core/atendia/runner/_template_helpers.py`**

Move from `nlu_prompts.py`:
- `_PLACEHOLDER_RE` regex
- `render_template(template, **vars)` function
- `_render_history(history)` function

```python
"""Template helpers shared by NLU and Composer prompts.

`render_template`: substitute {{name}} placeholders. Raise on missing.
`_render_history`: render conversation history to chat-completions messages.
"""
import re

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, **vars: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in vars:
            raise RuntimeError(
                f"unsubstituted placeholder {{{{ {key} }}}} in template"
            )
        return str(vars[key])
    return _PLACEHOLDER_RE.sub(_sub, template)


# Imported by both nlu_prompts and composer_prompts.
ROLE_LABELS = {
    "inbound": "cliente",
    "outbound": "asistente",
}


def _render_history(history: list[tuple[str, str]],
                    history_format: str = "[{{role}}] {{text}}") -> list[dict[str, str]]:
    """Convert [(direction, text), ...] into chat-completions messages.

    inbound → role 'user', outbound → role 'assistant'. Bracketed Spanish label
    inside content uses ROLE_LABELS for transparency.
    """
    out: list[dict[str, str]] = []
    for direction, text in history:
        role = "user" if direction == "inbound" else "assistant"
        label = ROLE_LABELS.get(direction, direction)
        rendered = render_template(history_format, role=label, text=text)
        out.append({"role": role, "content": rendered})
    return out
```

**Step 2: Update `nlu_prompts.py`**

Replace local `_PLACEHOLDER_RE`, `render_template`, `_render_history` with:

```python
from atendia.runner._template_helpers import (
    ROLE_LABELS,
    _render_history,
    render_template,
)
```

(Keep `HISTORY_FORMAT`, `SYSTEM_PROMPT_TEMPLATE`, `OUTPUT_INSTRUCTIONS`, `_render_fields`, `build_prompt` — these stay in `nlu_prompts.py`.)

**Step 3: Verify**

```bash
cd core && uv run pytest tests/runner/test_nlu_prompts.py -v
```

Expected: 12 PASS, no regressions.

**Step 4: Commit**

```bash
git add core/atendia/runner/_template_helpers.py core/atendia/runner/nlu_prompts.py
git commit -m "refactor(runner): extract template helpers to shared module"
```

---

# Bloque B — Tone

## Task 5: Pydantic `Tone` model

**Files:**
- Create: `core/atendia/contracts/tone.py`
- Create: `core/tests/contracts/test_tone.py`

**Step 1: Tests**

Create `core/tests/contracts/test_tone.py`:

```python
import pytest
from pydantic import ValidationError

from atendia.contracts.tone import Tone


def test_tone_defaults():
    t = Tone()
    assert t.register == "neutral_es"
    assert t.use_emojis == "sparingly"
    assert t.max_words_per_message == 40
    assert t.bot_name == "Asistente"
    assert t.forbidden_phrases == []
    assert t.signature_phrases == []


def test_tone_register_validates():
    with pytest.raises(ValidationError):
        Tone(register="japanese")  # type: ignore[arg-type]


def test_tone_use_emojis_validates():
    with pytest.raises(ValidationError):
        Tone(use_emojis="always")  # type: ignore[arg-type]


def test_tone_max_words_range_low():
    with pytest.raises(ValidationError):
        Tone(max_words_per_message=5)


def test_tone_max_words_range_high():
    with pytest.raises(ValidationError):
        Tone(max_words_per_message=200)


def test_tone_from_dinamo_dict():
    t = Tone.model_validate({
        "register": "informal_mexicano",
        "use_emojis": "sparingly",
        "max_words_per_message": 40,
        "bot_name": "Dinamo",
        "forbidden_phrases": ["estimado cliente"],
        "signature_phrases": ["¡qué onda!"],
    })
    assert t.bot_name == "Dinamo"
    assert "estimado cliente" in t.forbidden_phrases
```

**Step 2: Verify failure**

```bash
cd core && uv run pytest tests/contracts/test_tone.py -v
```

Expected: import error — module doesn't exist.

**Step 3: Implement `core/atendia/contracts/tone.py`**

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

**Step 4: Verify**

```bash
cd core && uv run pytest tests/contracts/test_tone.py -v
```

Expected: 6 PASS.

**Step 5: Commit**

```bash
git add core/atendia/contracts/tone.py core/tests/contracts/test_tone.py
git commit -m "feat(contracts): add Tone model with 6-field schema"
```

---

## Task 6: Eliminar `pipeline.tone` del schema

**Files:**
- Modify: `core/atendia/contracts/pipeline_definition.py`
- Modify: `contracts/pipeline_definition.schema.json`
- Modify: `core/tests/contracts/test_pipeline_definition.py`

**Step 1: Update existing test**

In `test_pipeline_definition.py`, find tests that build a `PipelineDefinition` with `tone={...}` and remove the `tone` arg. Pydantic ignores extra fields by default (`model_config` doesn't have `extra="forbid"`), so existing dicts that include `tone` keep working — but we need to verify field is gone.

Add a new test:

```python
def test_pipeline_definition_does_not_have_tone_field():
    """Phase 3b: tone moved to tenant_branding.voice; pipeline.tone removed."""
    p = PipelineDefinition(
        version=4,
        stages=[StageDefinition(id="x", actions_allowed=[], transitions=[])],
        fallback="x",
    )
    # tone should not be a field on the model
    assert "tone" not in p.model_fields


def test_pipeline_definition_ignores_legacy_tone_input():
    """Backward compat: old pipelines with tone:{} still parse, field is dropped."""
    p = PipelineDefinition.model_validate({
        "version": 4,
        "tone": {"register": "informal"},  # legacy
        "stages": [{"id": "x", "actions_allowed": [], "transitions": []}],
        "fallback": "x",
    })
    assert "tone" not in p.model_fields
```

**Step 2: Verify failure**

```bash
cd core && uv run pytest tests/contracts/test_pipeline_definition.py -v
```

Expected: existing tests pass (pydantic ignores extras), but `test_pipeline_definition_does_not_have_tone_field` fails because `tone` IS still a field.

**Step 3: Update `pipeline_definition.py`**

Remove `tone: dict` from `PipelineDefinition`:

```python
class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    composer: "ComposerConfig" = Field(default_factory=lambda: ComposerConfig())  # T7
    stages: list[StageDefinition] = Field(min_length=1)
    fallback: str
    # tone field removed in Phase 3b — moved to tenant_branding.voice
```

(Note: `composer` field is added in Task 7. For T6 alone, just remove `tone`.)

For T6 specifically:

```python
class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    stages: list[StageDefinition] = Field(min_length=1)
    fallback: str
```

(Note: this changes the field order; `tone` was between `stages` and `fallback`. Remove it.)

**Step 4: Update canonical JSON Schema**

Edit `contracts/pipeline_definition.schema.json`:
- Remove `"tone"` from `required` array.
- Remove `"tone"` from `properties`.

**Step 5: Update existing tests**

Find tests that assert `p.tone == {...}` — remove those assertions. Find tests that pass `"tone": {...}` in dict input — leave them (Pydantic ignores extras).

Run:

```bash
cd core && uv run pytest tests/contracts -v
```

Expected: all PASS, including the new T6 tests.

**Step 6: Commit**

```bash
git add core/atendia/contracts/pipeline_definition.py contracts/pipeline_definition.schema.json core/tests/contracts/test_pipeline_definition.py
git commit -m "feat(contracts): remove pipeline.tone (moves to tenant_branding.voice)"
```

---

## Task 7: Agregar `ComposerConfig` al pipeline schema

**Files:**
- Modify: `core/atendia/contracts/pipeline_definition.py`
- Modify: `contracts/pipeline_definition.schema.json`
- Modify: `core/tests/contracts/test_pipeline_definition.py`

**Step 1: Tests**

Append to `test_pipeline_definition.py`:

```python
from atendia.contracts.pipeline_definition import ComposerConfig


def test_composer_config_defaults():
    cfg = ComposerConfig()
    assert cfg.history_turns == 2


def test_composer_config_validates_range():
    with pytest.raises(ValidationError):
        ComposerConfig(history_turns=11)
    with pytest.raises(ValidationError):
        ComposerConfig(history_turns=-1)


def test_pipeline_with_composer_block():
    p = PipelineDefinition.model_validate({
        "version": 4,
        "composer": {"history_turns": 4},
        "stages": [{"id": "x", "actions_allowed": [], "transitions": []}],
        "fallback": "x",
    })
    assert p.composer.history_turns == 4


def test_pipeline_default_composer_block():
    p = PipelineDefinition.model_validate({
        "version": 4,
        "stages": [{"id": "x", "actions_allowed": [], "transitions": []}],
        "fallback": "x",
    })
    assert p.composer.history_turns == 2
```

**Step 2: Verify failure**

```bash
cd core && uv run pytest tests/contracts/test_pipeline_definition.py -v -k composer
```

Expected: import error — `ComposerConfig` doesn't exist.

**Step 3: Implement**

In `pipeline_definition.py`, add (place after `NLUConfig`):

```python
class ComposerConfig(BaseModel):
    history_turns: int = Field(default=2, ge=0, le=10)
```

Update `PipelineDefinition`:

```python
class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    composer: ComposerConfig = Field(default_factory=ComposerConfig)
    stages: list[StageDefinition] = Field(min_length=1)
    fallback: str
    # ... validators stay
```

**Step 4: Update canonical JSON Schema**

Add to `contracts/pipeline_definition.schema.json`:

```json
"properties": {
  ...
  "composer": { "$ref": "#/$defs/ComposerConfig" },
  ...
},
"$defs": {
  ...
  "ComposerConfig": {
    "type": "object",
    "properties": {
      "history_turns": { "type": "integer", "minimum": 0, "maximum": 10, "default": 2 }
    }
  }
}
```

**Step 5: Tests pass**

```bash
cd core && uv run pytest tests/contracts -v
```

Expected: 4 new tests PASS, all previous PASS.

**Step 6: Commit**

```bash
git add core/atendia/contracts/pipeline_definition.py contracts/pipeline_definition.schema.json core/tests/contracts/test_pipeline_definition.py
git commit -m "feat(contracts): add ComposerConfig.history_turns to pipeline schema"
```

---

# Bloque C — Tool stubs

## Task 8: `ToolNoDataResult` y actualización de stubs

**Files:**
- Modify: `core/atendia/tools/quote.py`
- Modify: `core/atendia/tools/lookup_faq.py`
- Modify: `core/atendia/tools/search_catalog.py`
- Possibly modify: `core/atendia/tools/base.py` (or wherever the result types live)
- Create: `core/tests/tools/test_no_data_results.py`

**Step 1: Pre-flight**

Read the existing 3 stubs to see their current signatures and return types:

```bash
cd core && grep -A5 "^def \(quote\|lookup_faq\|search_catalog\)" atendia/tools/*.py
```

If they return `None` or strings, update them.

**Step 2: Tests**

Create `core/tests/tools/test_no_data_results.py`:

```python
from uuid import uuid4

from atendia.tools.lookup_faq import lookup_faq
from atendia.tools.quote import quote
from atendia.tools.search_catalog import search_catalog


def test_quote_returns_no_data_result():
    r = quote(tenant_id=uuid4(), product_id="X", options={})
    assert r.status == "no_data"
    assert "catalog" in r.hint.lower() or "price" in r.hint.lower()


def test_lookup_faq_returns_no_data_result():
    r = lookup_faq(tenant_id=uuid4(), question="x")
    assert r.status == "no_data"


def test_search_catalog_returns_no_data_result():
    r = search_catalog(tenant_id=uuid4(), query="x", filters={})
    assert r.status == "no_data"


def test_no_data_result_has_status_literal_no_data():
    """The status field is Literal['no_data'] for type-narrowing safety."""
    from atendia.tools.base import ToolNoDataResult  # or wherever it lives
    r = ToolNoDataResult(hint="x")
    assert r.status == "no_data"
```

**Step 3: Verify failure**

```bash
cd core && uv run pytest tests/tools/test_no_data_results.py -v
```

Expected: import error — `ToolNoDataResult` doesn't exist.

**Step 4: Add `ToolNoDataResult` to `core/atendia/tools/base.py`**

Find the file (it should exist; check `core/atendia/tools/`). If `base.py` doesn't exist, create it. Add:

```python
from typing import Literal

from pydantic import BaseModel


class ToolNoDataResult(BaseModel):
    status: Literal["no_data"] = "no_data"
    hint: str
```

**Step 5: Update the 3 stubs**

`core/atendia/tools/quote.py`:

```python
from uuid import UUID

from atendia.tools.base import ToolNoDataResult


def quote(*, tenant_id: UUID, product_id: str, options: dict) -> ToolNoDataResult:
    return ToolNoDataResult(hint="catalog not connected; cannot quote yet")
```

`core/atendia/tools/lookup_faq.py`:

```python
from uuid import UUID

from atendia.tools.base import ToolNoDataResult


def lookup_faq(*, tenant_id: UUID, question: str, top_k: int = 3) -> ToolNoDataResult:
    return ToolNoDataResult(hint="faqs not connected; redirect")
```

`core/atendia/tools/search_catalog.py`:

```python
from uuid import UUID

from atendia.tools.base import ToolNoDataResult


def search_catalog(*, tenant_id: UUID, query: str, filters: dict) -> ToolNoDataResult:
    return ToolNoDataResult(hint="catalog not connected; redirect")
```

If existing tests reference the old return types, update them.

**Step 6: Tests pass**

```bash
cd core && uv run pytest tests/tools tests/contracts -v
```

Expected: 4 new tests PASS, no regressions.

**Step 7: Commit**

```bash
git add core/atendia/tools core/tests/tools/test_no_data_results.py
git commit -m "feat(tools): stubs return ToolNoDataResult with hint for Composer"
```

---

# Bloque D — Composer Protocol + Canned

## Task 9: `ComposerProvider` Protocol + `ComposerInput`/`ComposerOutput`

**Files:**
- Create: `core/atendia/runner/composer_protocol.py`
- Modify: `core/atendia/runner/nlu_protocol.py` (add `fallback_used` to `UsageMetadata`)
- Create: `core/tests/runner/test_composer_protocol.py`
- Modify: `core/tests/runner/test_nlu_protocol.py` (add test for fallback_used default)

**Step 1: Update `UsageMetadata`**

Edit `core/atendia/runner/nlu_protocol.py`:

```python
class UsageMetadata(BaseModel):
    model: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)   # NEW: enforce non-negative
    latency_ms: int = Field(ge=0)
    fallback_used: bool = False        # NEW
```

Append to `core/tests/runner/test_nlu_protocol.py`:

```python
def test_usage_metadata_fallback_used_default_false():
    u = UsageMetadata(
        model="x", tokens_in=0, tokens_out=0,
        cost_usd=Decimal("0"), latency_ms=0,
    )
    assert u.fallback_used is False


def test_usage_metadata_negative_cost_rejected():
    with pytest.raises(ValidationError):
        UsageMetadata(
            model="x", tokens_in=0, tokens_out=0,
            cost_usd=Decimal("-0.01"), latency_ms=0,
        )
```

**Step 2: Create composer_protocol.py and tests**

Create `core/tests/runner/test_composer_protocol.py`:

```python
import pytest
from pydantic import ValidationError

from atendia.contracts.tone import Tone
from atendia.runner.composer_protocol import (
    ComposerInput, ComposerOutput, ComposerProvider,
)


def test_composer_input_minimal():
    inp = ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    )
    assert inp.action == "greet"
    assert inp.action_payload == {}
    assert inp.history == []
    assert inp.max_messages == 2


def test_composer_input_max_messages_validates():
    with pytest.raises(ValidationError):
        ComposerInput(action="x", current_stage="x", tone=Tone(), max_messages=4)
    with pytest.raises(ValidationError):
        ComposerInput(action="x", current_stage="x", tone=Tone(), max_messages=0)


def test_composer_output_rejects_empty():
    with pytest.raises(ValidationError):
        ComposerOutput(messages=[])


def test_composer_output_rejects_too_many():
    with pytest.raises(ValidationError):
        ComposerOutput(messages=["a", "b", "c", "d"])


def test_composer_output_accepts_1_to_3():
    assert ComposerOutput(messages=["a"]).messages == ["a"]
    assert len(ComposerOutput(messages=["a", "b"]).messages) == 2
    assert len(ComposerOutput(messages=["a", "b", "c"]).messages) == 3


async def test_protocol_satisfied_by_dummy():
    class Dummy:
        async def compose(self, *, input):
            return ComposerOutput(messages=["x"]), None

    composer: ComposerProvider = Dummy()
    out, usage = await composer.compose(input=ComposerInput(
        action="x", current_stage="x", tone=Tone(),
    ))
    assert out.messages == ["x"]
    assert usage is None
```

Run:

```bash
cd core && uv run pytest tests/runner/test_composer_protocol.py -v
```

Expected: import errors.

**Step 3: Implement `composer_protocol.py`**

```python
"""ComposerProvider Protocol + Pydantic models for input/output."""
from typing import Protocol

from pydantic import BaseModel, Field

from atendia.contracts.tone import Tone
from atendia.runner.nlu_protocol import UsageMetadata


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

**Step 4: Tests pass**

```bash
cd core && uv run pytest tests/runner/test_composer_protocol.py tests/runner/test_nlu_protocol.py -v
```

Expected: PASS all (5 new + nlu_protocol updates).

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_protocol.py core/atendia/runner/nlu_protocol.py core/tests/runner/test_composer_protocol.py core/tests/runner/test_nlu_protocol.py
git commit -m "feat(runner): add ComposerProvider Protocol and Input/Output models"
```

---

## Task 10: `CannedComposer`

**Files:**
- Create: `core/atendia/runner/composer_canned.py`
- Create: `core/tests/runner/test_composer_canned.py`

**Step 1: Tests**

```python
import pytest

from atendia.contracts.tone import Tone
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_protocol import ComposerInput


@pytest.mark.parametrize("action,expected_substring", [
    ("greet", "hola"),
    ("ask_field", "detalles"),
    ("lookup_faq", "revisar"),
    ("ask_clarification", "no te entendí"),
    ("quote", "precio"),
    ("explain_payment_options", "efectivo"),
    ("close", "siguiente paso"),
])
async def test_canned_composer_returns_text_for_action(action, expected_substring):
    composer = CannedComposer()
    out, usage = await composer.compose(input=ComposerInput(
        action=action, current_stage="x", tone=Tone(),
    ))
    assert len(out.messages) == 1
    assert expected_substring.lower() in out.messages[0].lower()
    assert usage is None


async def test_canned_composer_handles_unknown_action():
    composer = CannedComposer()
    out, usage = await composer.compose(input=ComposerInput(
        action="unknown_action_xyz", current_stage="x", tone=Tone(),
    ))
    assert len(out.messages) == 1
    assert "consultar" in out.messages[0].lower()
    assert usage is None
```

Run:

```bash
cd core && uv run pytest tests/runner/test_composer_canned.py -v
```

Expected: import error.

**Step 2: Implement**

Create `core/atendia/runner/composer_canned.py`:

```python
"""Canned Composer: returns hardcoded text per action.

Used as:
- Default when composer_provider="canned" (Phase 2 behavior preserved).
- Fallback when OpenAIComposer's retries exhaust.
"""
from atendia.runner.composer_protocol import (
    ComposerInput, ComposerOutput, UsageMetadata,
)


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

    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        text = self._TEXTS.get(
            input.action,
            "Disculpa, déjame consultar y te paso la info.",
        )
        return ComposerOutput(messages=[text]), None
```

**Step 3: Tests pass**

```bash
cd core && uv run pytest tests/runner/test_composer_canned.py -v
```

Expected: 8 PASS (7 parametrized + 1 unknown).

**Step 4: Commit**

```bash
git add core/atendia/runner/composer_canned.py core/tests/runner/test_composer_canned.py
git commit -m "feat(runner): CannedComposer implements ComposerProvider"
```

---

# Bloque E — Composer Prompts

## Task 11: Templates editables + render

**Files:**
- Create: `core/atendia/runner/composer_prompts.py`
- Create: `core/tests/runner/test_composer_prompts.py`

**Step 1: Tests for the constants**

```python
import pytest

from atendia.runner.composer_prompts import (
    ACTION_GUIDANCE,
    OUTPUT_INSTRUCTIONS,
    SYSTEM_PROMPT_TEMPLATE,
)


def test_system_prompt_has_required_placeholders():
    for ph in [
        "{{bot_name}}", "{{register}}", "{{use_emojis}}", "{{max_words}}",
        "{{forbidden_phrases}}", "{{signature_phrases}}", "{{stage}}",
        "{{last_intent}}", "{{extracted_data}}", "{{action_guidance}}",
        "{{output_instructions}}",
    ]:
        assert ph in SYSTEM_PROMPT_TEMPLATE


def test_action_guidance_has_all_7_actions():
    expected = {
        "greet", "ask_field", "lookup_faq", "ask_clarification",
        "quote", "explain_payment_options", "close",
    }
    assert expected.issubset(ACTION_GUIDANCE.keys())


def test_action_guidance_quote_says_no_inventes():
    assert "NO INVENTES PRECIOS" in ACTION_GUIDANCE["quote"].upper()


def test_action_guidance_lookup_faq_redirects():
    assert "redirige" in ACTION_GUIDANCE["lookup_faq"].lower()


def test_output_instructions_mentions_messages_format():
    assert "messages" in OUTPUT_INSTRUCTIONS
    assert "{{max_messages}}" in OUTPUT_INSTRUCTIONS
    assert "{{max_words}}" in OUTPUT_INSTRUCTIONS
```

**Step 2: Verify failure**

Expected: module doesn't exist.

**Step 3: Implement `composer_prompts.py`**

```python
"""
Prompts del Composer (gpt-4o).

Editas:
  1. SYSTEM_PROMPT_TEMPLATE — instrucciones generales + tono.
  2. ACTION_GUIDANCE        — bloque condicional por acción.
  3. HISTORY_FORMAT         — formato de turnos previos.
  4. OUTPUT_INSTRUCTIONS    — reglas sobre el JSON de salida.

Helpers (render_template, _render_history) viven en _template_helpers.
"""
SYSTEM_PROMPT_TEMPLATE = """\
Eres {{bot_name}}, un asistente de ventas por WhatsApp. Tu tarea es REDACTAR
la respuesta al cliente — NO decides qué hacer (eso ya lo decidió el sistema).

Tono y estilo:
- Registro: {{register}}.
- Emojis: {{use_emojis}}.
- Máximo {{max_words}} palabras por mensaje.
- NUNCA uses estas frases: {{forbidden_phrases}}.
- Frases típicas que puedes usar cuando encajen naturalmente: {{signature_phrases}}.

Estado de la conversación:
- Stage actual: {{stage}}
- Última intent del cliente: {{last_intent}}
- Datos extraídos hasta ahora: {{extracted_data}}

{{action_guidance}}

{{output_instructions}}
"""

ACTION_GUIDANCE: dict[str, str] = {
    "greet": (
        "Acción: SALUDAR. Saluda brevemente y ofrece ayuda. "
        "NO preguntes datos todavía."
    ),
    "ask_field": (
        "Acción: PEDIR DATO. Necesitas que el cliente te diga el campo "
        "'{{missing_field}}' ({{missing_field_description}}). Pregúntalo "
        "naturalmente, en una sola frase."
    ),
    "ask_clarification": (
        "Acción: PEDIR ACLARACIÓN. El sistema NO entendió bien el último "
        "mensaje. Pídele al cliente que reformule o aclare. NO inventes contexto."
    ),
    "explain_payment_options": (
        "Acción: EXPLICAR OPCIONES DE PAGO. Las opciones genéricas son "
        "efectivo, transferencia y crédito (financiamiento). Menciónalas "
        "brevemente y pregunta cuál prefiere."
    ),
    "lookup_faq": (
        "Acción: BUSCAR EN FAQ. NO TIENES BASE DE FAQS CONECTADA todavía. "
        "Redirige diciendo que lo consultas y le respondes en breve. "
        "NO inventes ninguna respuesta. Mensaje sugerido tipo: "
        "'Déjame revisar y te confirmo en un momento.'"
    ),
    "quote": (
        "Acción: COTIZAR. NO TIENES CATÁLOGO DE PRECIOS CONECTADO todavía. "
        "Redirige diciendo que vas a consultar el precio exacto y se lo pasas. "
        "NO INVENTES PRECIOS. NUNCA des una cifra. Mensaje sugerido tipo: "
        "'Déjame consultar el precio exacto y te lo paso en un momentito.'"
    ),
    "close": (
        "Acción: CERRAR. El cliente acordó comprar. Pasa al siguiente paso "
        "concreto. Si tienes payment_link en action_payload, inclúyelo. "
        "Si no, di que en breve le mandas el link."
    ),
}

HISTORY_FORMAT = "[{{role}}] {{text}}"

OUTPUT_INSTRUCTIONS = """\
Reglas de salida:
- Devuelve un objeto JSON {"messages": [...]}.
- "messages" es una lista de 1 a {{max_messages}} mensajes cortos.
- Cada mensaje es una cadena, máximo {{max_words}} palabras.
- Si 1 mensaje basta, devuelve 1. Solo divide en 2-3 si es natural en chat
  (saludo + pregunta, por ejemplo).
- NO uses Markdown. NO uses comillas innecesarias. Solo texto plano de chat.
"""
```

**Step 4: Tests pass**

```bash
cd core && uv run pytest tests/runner/test_composer_prompts.py -v
```

Expected: 5 PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_prompts.py core/tests/runner/test_composer_prompts.py
git commit -m "feat(runner): add Composer prompt templates and ACTION_GUIDANCE"
```

---

## Task 12: `build_composer_prompt`

**Files:**
- Modify: `core/atendia/runner/composer_prompts.py`
- Modify: `core/tests/runner/test_composer_prompts.py`

**Step 1: Tests**

Append:

```python
from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput


def test_build_composer_prompt_basic_structure():
    msgs = build_composer_prompt(ComposerInput(
        action="greet",
        current_stage="greeting",
        tone=Tone(bot_name="Dinamo", register="informal_mexicano"),
        history=[("inbound", "hola"), ("outbound", "qué onda")],
    ))
    assert msgs[0]["role"] == "system"
    assert "Dinamo" in msgs[0]["content"]
    assert "informal_mexicano" in msgs[0]["content"]
    assert "SALUDAR" in msgs[0]["content"]
    # History rendered as user/assistant chat messages (not user message at end!)
    assert any(m["role"] == "user" and "hola" in m["content"] for m in msgs)
    assert any(m["role"] == "assistant" and "qué onda" in m["content"] for m in msgs)


def test_build_composer_prompt_quote_includes_no_inventes():
    msgs = build_composer_prompt(ComposerInput(
        action="quote",
        current_stage="quote",
        tone=Tone(),
    ))
    assert "NO INVENTES PRECIOS" in msgs[0]["content"]


def test_build_composer_prompt_ask_field_substitutes_field_name():
    msgs = build_composer_prompt(ComposerInput(
        action="ask_field",
        action_payload={
            "field_name": "ciudad",
            "field_description": "Ciudad del cliente",
        },
        current_stage="qualify",
        tone=Tone(),
    ))
    assert "ciudad" in msgs[0]["content"]
    assert "Ciudad del cliente" in msgs[0]["content"]


def test_build_composer_prompt_renders_forbidden_phrases():
    msgs = build_composer_prompt(ComposerInput(
        action="greet", current_stage="greeting",
        tone=Tone(forbidden_phrases=["estimado cliente"]),
    ))
    assert "estimado cliente" in msgs[0]["content"]


def test_build_composer_prompt_no_history_no_user_message():
    """Composer prompt does NOT append a user message at the end (NLU does;
    Composer doesn't need one because the action is the prompt)."""
    msgs = build_composer_prompt(ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
```

**Step 2: Verify failure**

Expected: `build_composer_prompt` not defined.

**Step 3: Implement**

Append to `composer_prompts.py`:

```python
from atendia.runner._template_helpers import (
    _render_history,
    render_template,
)
from atendia.runner.composer_protocol import ComposerInput


def _render_extracted(extracted: dict) -> str:
    if not extracted:
        return "(ninguno todavía)"
    return ", ".join(f"{k}={v}" for k, v in extracted.items())


def build_composer_prompt(input: ComposerInput) -> list[dict[str, str]]:
    """Assemble the chat-completions message list for gpt-4o."""
    guidance_template = ACTION_GUIDANCE.get(
        input.action, "Acción: " + input.action.upper(),
    )
    # Render guidance — substitute payload fields if present.
    guidance_vars = {
        "missing_field": str(input.action_payload.get("field_name", "")),
        "missing_field_description": str(input.action_payload.get("field_description", "")),
    }
    # Find any placeholders in guidance_template; only substitute those that are present
    # in guidance_vars. Unknown placeholders raise — we want to know about typos.
    import re
    needed = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", guidance_template))
    if not needed:
        guidance = guidance_template
    else:
        # Fill any missing keys with "" so render_template doesn't raise.
        for k in needed:
            guidance_vars.setdefault(k, "")
        guidance = render_template(guidance_template, **guidance_vars)

    output_instructions = render_template(
        OUTPUT_INSTRUCTIONS,
        max_messages=str(input.max_messages),
        max_words=str(input.tone.max_words_per_message),
    )

    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        bot_name=input.tone.bot_name,
        register=input.tone.register,
        use_emojis=input.tone.use_emojis,
        max_words=str(input.tone.max_words_per_message),
        forbidden_phrases=", ".join(input.tone.forbidden_phrases) or "(ninguna)",
        signature_phrases=", ".join(input.tone.signature_phrases) or "(ninguna)",
        stage=input.current_stage,
        last_intent=input.last_intent or "(ninguna)",
        extracted_data=_render_extracted(input.extracted_data),
        action_guidance=guidance,
        output_instructions=output_instructions,
    )

    return [
        {"role": "system", "content": system_content},
        *_render_history(input.history, history_format=HISTORY_FORMAT),
    ]
```

**Step 4: Tests pass**

```bash
cd core && uv run pytest tests/runner/test_composer_prompts.py -v
```

Expected: 10 PASS (5 from T11 + 5 new).

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_prompts.py core/tests/runner/test_composer_prompts.py
git commit -m "feat(runner): build_composer_prompt assembles system+history (no user msg)"
```

---

## Task 13: Snapshot test for greet+Dinamo system prompt

**Files:**
- Create: `core/tests/fixtures/composer/greet_dinamo_system.txt`
- Modify: `core/tests/runner/test_composer_prompts.py`

**Step 1: Generate the fixture**

```bash
mkdir -p "core/tests/fixtures/composer"

cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run python -c "
from pathlib import Path
from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput

m = build_composer_prompt(ComposerInput(
    action='greet',
    current_stage='greeting',
    tone=Tone(
        register='informal_mexicano',
        use_emojis='sparingly',
        max_words_per_message=40,
        bot_name='Dinamo',
        forbidden_phrases=['estimado cliente', 'le saluda atentamente'],
        signature_phrases=['¡qué onda!', 'te paso'],
    ),
))
Path('tests/fixtures/composer/greet_dinamo_system.txt').write_text(
    m[0]['content'], encoding='utf-8', newline='',
)
"
```

Inspect:

```bash
cat tests/fixtures/composer/greet_dinamo_system.txt
```

**Step 2: Add snapshot test**

Append to `test_composer_prompts.py`:

```python
from pathlib import Path

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "composer"


def test_composer_system_prompt_snapshot_greet_dinamo():
    """Byte-equality snapshot guard for the Dinamo greet system prompt.

    Intentional edits to SYSTEM_PROMPT_TEMPLATE / ACTION_GUIDANCE will
    fail this test. Regenerate via:

        uv run python -c "
        from pathlib import Path
        from atendia.contracts.tone import Tone
        from atendia.runner.composer_prompts import build_composer_prompt
        from atendia.runner.composer_protocol import ComposerInput
        m = build_composer_prompt(ComposerInput(
            action='greet', current_stage='greeting',
            tone=Tone(
                register='informal_mexicano', use_emojis='sparingly',
                max_words_per_message=40, bot_name='Dinamo',
                forbidden_phrases=['estimado cliente', 'le saluda atentamente'],
                signature_phrases=['¡qué onda!', 'te paso'],
            ),
        ))
        Path('tests/fixtures/composer/greet_dinamo_system.txt').write_text(
            m[0]['content'], encoding='utf-8', newline='',
        )
        "
    """
    expected = (_FIXTURES / "greet_dinamo_system.txt").read_text(encoding="utf-8")
    msgs = build_composer_prompt(ComposerInput(
        action="greet",
        current_stage="greeting",
        tone=Tone(
            register="informal_mexicano",
            use_emojis="sparingly",
            max_words_per_message=40,
            bot_name="Dinamo",
            forbidden_phrases=["estimado cliente", "le saluda atentamente"],
            signature_phrases=["¡qué onda!", "te paso"],
        ),
    ))
    assert msgs[0]["content"] == expected
```

**Step 3: Verify**

```bash
cd core && uv run pytest tests/runner/test_composer_prompts.py::test_composer_system_prompt_snapshot_greet_dinamo -v
```

Expected: PASS.

**Step 4: Validation experiment** — temporarily change one word in SYSTEM_PROMPT_TEMPLATE; run; confirm test FAILS with diff; revert; confirm PASS.

**Step 5: Commit**

```bash
git add core/tests/fixtures/composer/greet_dinamo_system.txt core/tests/runner/test_composer_prompts.py
git commit -m "test(composer): snapshot test for greet+Dinamo system prompt"
```

---

# Bloque F — OpenAIComposer

## Task 14: `OpenAIComposer` skeleton + happy path

**Files:**
- Create: `core/atendia/runner/composer_openai.py`
- Create: `core/tests/runner/test_composer_openai.py`

**Step 1: Test for happy path**

Create `core/tests/runner/test_composer_openai.py`:

```python
import json
from decimal import Decimal

import pytest
import respx
from httpx import Response

from atendia.contracts.tone import Tone
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerInput


def _ok_composer_response(messages=None, model="gpt-4o", tokens_in=450, tokens_out=80):
    payload = {"messages": messages or ["¡Qué onda!", "¿En qué te ayudo?"]}
    return Response(
        200,
        json={
            "id": "chatcmpl-cmp", "object": "chat.completion", "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        },
    )


@respx.mock
async def test_compose_happy_path_returns_messages_and_usage():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response(
            messages=["¡Qué onda, Frank!", "¿Te ayudo con tu moto?"],
        )
    )
    composer = OpenAIComposer(api_key="sk-test")
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert out.messages == ["¡Qué onda, Frank!", "¿Te ayudo con tu moto?"]
    assert usage is not None
    assert usage.tokens_in == 450
    assert usage.tokens_out == 80
    assert usage.cost_usd == Decimal("0.001925")
    assert usage.fallback_used is False
    assert usage.model == "gpt-4o"
```

**Step 2: Verify failure**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py -v
```

Expected: import error.

**Step 3: Implement happy path** (NO retry yet)

Create `core/atendia/runner/composer_openai.py`:

```python
"""OpenAI Composer (gpt-4o) with strict structured outputs.

Happy path only in T14; T15+ adds retry + fallback.
"""
import json
import time
from decimal import Decimal

from openai import AsyncOpenAI

from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import (
    ComposerInput, ComposerOutput, UsageMetadata,
)
from atendia.runner.nlu.pricing import compute_cost


def _composer_schema(max_messages: int) -> dict:
    """Strict-mode-compliant JSON schema for ComposerOutput."""
    return {
        "name": "composer_output",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": max_messages,
                },
            },
            "required": ["messages"],
            "additionalProperties": False,
        },
    }


class OpenAIComposer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        timeout_s: float = 8.0,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._model = model

    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        messages = build_composer_prompt(input)
        json_schema = _composer_schema(input.max_messages)
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
        output = ComposerOutput.model_validate(raw)
        usage = UsageMetadata(
            model=resp.model,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            cost_usd=compute_cost(
                resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens,
            ),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            fallback_used=False,
        )
        return output, usage
```

**Step 4: Test passes**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py::test_compose_happy_path_returns_messages_and_usage -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_openai.py core/tests/runner/test_composer_openai.py
git commit -m "feat(composer): OpenAIComposer happy path with structured outputs"
```

---

## Task 15: Schema invariants (strict-mode tests)

**Files:**
- Modify: `core/tests/runner/test_composer_openai.py`

**Step 1: Tests**

Append:

```python
def test_composer_schema_required_matches_properties():
    from atendia.runner.composer_openai import _composer_schema
    schema = _composer_schema(2)["schema"]
    assert set(schema["required"]) == set(schema["properties"].keys())
    assert schema["additionalProperties"] is False


def test_composer_schema_max_items_respects_input():
    from atendia.runner.composer_openai import _composer_schema
    assert _composer_schema(1)["schema"]["properties"]["messages"]["maxItems"] == 1
    assert _composer_schema(2)["schema"]["properties"]["messages"]["maxItems"] == 2
    assert _composer_schema(3)["schema"]["properties"]["messages"]["maxItems"] == 3


def test_composer_schema_min_items_is_1():
    from atendia.runner.composer_openai import _composer_schema
    assert _composer_schema(2)["schema"]["properties"]["messages"]["minItems"] == 1
```

**Step 2: Run**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py -v
```

Expected: 4 PASS.

**Step 3: Commit**

```bash
git add core/tests/runner/test_composer_openai.py
git commit -m "test(composer): assert strict-mode schema invariants"
```

---

## Task 16: Retry + fallback (the meaty task)

**Files:**
- Modify: `core/atendia/runner/composer_openai.py`
- Modify: `core/tests/runner/test_composer_openai.py`

**Step 1: Tests**

Append:

```python
@respx.mock
async def test_compose_retries_on_503_then_succeeds():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[
            Response(503, json={"error": {"message": "boom"}}),
            _ok_composer_response(),
        ]
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(50,))
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 2
    assert usage is not None
    assert usage.fallback_used is False
    assert usage.cost_usd > Decimal("0")


@respx.mock
async def test_compose_falls_back_to_canned_on_exhaustion():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {"message": "down"}})
    )
    fallback = CannedComposer()
    composer = OpenAIComposer(
        api_key="sk-test", retry_delays_ms=(10, 20), fallback=fallback,
    )
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    # Output is the canned text
    assert "hola" in out.messages[0].lower()
    # Usage signals fallback
    assert usage is not None
    assert usage.fallback_used is True
    assert usage.tokens_in == 0
    assert usage.cost_usd == Decimal("0")


@respx.mock
async def test_compose_does_not_retry_on_401():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(401, json={"error": {"message": "bad key"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1
    assert usage.fallback_used is True


@respx.mock
async def test_compose_does_not_retry_on_400():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(400, json={"error": {"message": "bad req"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1
    assert usage.fallback_used is True


@respx.mock
async def test_compose_does_not_retry_on_422():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(422, json={"error": {"message": "unprocessable"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1
    assert usage.fallback_used is True


@respx.mock
async def test_compose_treats_malformed_json_as_validation_error():
    """Output JSON that doesn't satisfy ComposerOutput → ValidationError → fail fast → fallback."""
    bad = Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": '{"messages": []}'},  # empty list, violates min_length
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=bad,
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1   # ValidationError is non-retriable
    assert usage.fallback_used is True
```

**Step 2: Verify failures**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py -v
```

Expected: most fail — implementation lacks retry + fallback.

**Step 3: Implement retry + fallback**

Replace `OpenAIComposer.__init__` and `compose` in `composer_openai.py`:

```python
import asyncio

from atendia.runner._openai_errors import _NON_RETRIABLE, _RETRIABLE
from atendia.runner.composer_canned import CannedComposer


class OpenAIComposer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        timeout_s: float = 8.0,
        retry_delays_ms: tuple[int, ...] = (500, 2000),
        fallback: "ComposerProvider | None" = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._model = model
        self._delays = (0, *retry_delays_ms)
        self._fallback = fallback or CannedComposer()

    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        messages = build_composer_prompt(input)
        json_schema = _composer_schema(input.max_messages)
        t0 = time.perf_counter()
        last_exc: Exception | None = None

        for delay_ms in self._delays:
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
            try:
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_schema", "json_schema": json_schema},
                    temperature=0,
                )
                raw = json.loads(resp.choices[0].message.content)
                output = ComposerOutput.model_validate(raw)
                usage = UsageMetadata(
                    model=resp.model,
                    tokens_in=resp.usage.prompt_tokens,
                    tokens_out=resp.usage.completion_tokens,
                    cost_usd=compute_cost(
                        resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens,
                    ),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    fallback_used=False,
                )
                return output, usage
            except _RETRIABLE as e:
                last_exc = e
                continue
            except _NON_RETRIABLE as e:
                last_exc = e
                break

        # Exhausted or non-retriable: fall back to canned, signal via fallback_used.
        canned_output, _ = await self._fallback.compose(input=input)
        usage = UsageMetadata(
            model=self._model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            fallback_used=True,
        )
        return canned_output, usage
```

**Step 4: Tests pass**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py -v
```

Expected: 10 PASS (4 from T14-T15 + 6 new).

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_openai.py core/tests/runner/test_composer_openai.py
git commit -m "feat(composer): retry transient errors + fallback to CannedComposer"
```

---

## Task 17: Test that tone is passed to prompt

**Files:**
- Modify: `core/tests/runner/test_composer_openai.py`

**Step 1: Test using respx route capture**

```python
@respx.mock
async def test_compose_passes_tone_to_prompt():
    """Tone fields appear literally in the system prompt sent to OpenAI."""
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response()
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting",
        tone=Tone(
            bot_name="DinamoBot",
            register="informal_mexicano",
            forbidden_phrases=["frase_prohibida_z"],
        ),
    ))
    # Inspect the captured request body
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    system = req_body["messages"][0]["content"]
    assert "DinamoBot" in system
    assert "informal_mexicano" in system
    assert "frase_prohibida_z" in system
```

**Step 2: Run**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py::test_compose_passes_tone_to_prompt -v
```

Expected: PASS.

**Step 3: Commit**

```bash
git add core/tests/runner/test_composer_openai.py
git commit -m "test(composer): tone fields propagate to system prompt"
```

---

## Task 18: Test that max_messages caps schema correctly

**Files:**
- Modify: `core/tests/runner/test_composer_openai.py`

**Step 1: Test**

```python
@respx.mock
async def test_compose_request_uses_max_messages_in_schema():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response()
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
        max_messages=3,
    ))
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    schema = req_body["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["messages"]["maxItems"] == 3
```

**Step 2: Run + commit**

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py -v
git add core/tests/runner/test_composer_openai.py
git commit -m "test(composer): max_messages propagates to JSON schema"
```

---

## Task 19: Test for `quote` action with no_data payload

**Files:**
- Modify: `core/tests/runner/test_composer_openai.py`

```python
@respx.mock
async def test_compose_quote_with_no_data_includes_no_inventes():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response(messages=["Déjame consultar y te paso el precio."])
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(input=ComposerInput(
        action="quote",
        action_payload={"status": "no_data", "hint": "catalog not connected"},
        current_stage="quote",
        extracted_data={"interes_producto": "150Z"},
        tone=Tone(),
    ))
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    system = req_body["messages"][0]["content"]
    assert "NO INVENTES PRECIOS" in system
    assert "150Z" in system  # extracted_data shows up
```

Run + commit:

```bash
cd core && uv run pytest tests/runner/test_composer_openai.py -v
git add core/tests/runner/test_composer_openai.py
git commit -m "test(composer): quote action injects no-invent guidance + state"
```

---

# Bloque G — Outbound dispatcher

## Task 20: Refactor `outbound_dispatcher` to `enqueue_messages`

**Files:**
- Modify: `core/atendia/runner/outbound_dispatcher.py`
- Modify: `core/tests/runner/test_outbound_dispatcher.py`

**Step 1: Update tests**

The current tests probably test `text_for_action` and `dispatch`. Replace them.

```python
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from atendia.runner.outbound_dispatcher import (
    COMPOSED_ACTIONS, SKIP_ACTIONS, enqueue_messages,
)


@pytest.fixture
def fake_arq():
    """Return a fake arq pool that records enqueue calls."""
    pool = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def patch_enqueue_outbound(monkeypatch):
    """Replace the queue.enqueue.enqueue_outbound with a recorder."""
    calls = []

    async def fake_enqueue(arq_redis, msg):
        calls.append(msg)
        return f"job-{len(calls)}"

    monkeypatch.setattr("atendia.runner.outbound_dispatcher.enqueue_outbound", fake_enqueue)
    return calls


async def test_enqueue_messages_one_message(fake_arq, patch_enqueue_outbound):
    job_ids = await enqueue_messages(
        fake_arq,
        messages=["¡Hola!"],
        tenant_id=uuid4(), to_phone_e164="+5215551234567",
        conversation_id=uuid4(), turn_number=1, action="greet",
    )
    assert len(job_ids) == 1
    assert len(patch_enqueue_outbound) == 1
    assert patch_enqueue_outbound[0].text == "¡Hola!"


async def test_enqueue_messages_two_messages(fake_arq, patch_enqueue_outbound):
    job_ids = await enqueue_messages(
        fake_arq,
        messages=["¡Hola!", "¿En qué te ayudo?"],
        tenant_id=uuid4(), to_phone_e164="+5215551234567",
        conversation_id=uuid4(), turn_number=1, action="greet",
    )
    assert len(job_ids) == 2
    assert len(patch_enqueue_outbound) == 2
    assert patch_enqueue_outbound[0].text == "¡Hola!"
    assert patch_enqueue_outbound[1].text == "¿En qué te ayudo?"


async def test_enqueue_messages_idempotency_keys_unique(fake_arq, patch_enqueue_outbound):
    cid = uuid4()
    await enqueue_messages(
        fake_arq, messages=["a", "b"],
        tenant_id=uuid4(), to_phone_e164="+x",
        conversation_id=cid, turn_number=1, action="greet",
    )
    keys = [m.idempotency_key for m in patch_enqueue_outbound]
    assert keys[0] != keys[1]
    assert "1:0" in keys[0]
    assert "1:1" in keys[1]


async def test_enqueue_messages_metadata_includes_index(fake_arq, patch_enqueue_outbound):
    await enqueue_messages(
        fake_arq, messages=["a", "b"],
        tenant_id=uuid4(), to_phone_e164="+x",
        conversation_id=uuid4(), turn_number=2, action="greet",
    )
    assert patch_enqueue_outbound[0].metadata == {"action": "greet", "message_index": 0, "of": 2}
    assert patch_enqueue_outbound[1].metadata == {"action": "greet", "message_index": 1, "of": 2}


def test_composed_actions_taxonomy():
    assert "greet" in COMPOSED_ACTIONS
    assert "ask_field" in COMPOSED_ACTIONS
    assert "lookup_faq" in COMPOSED_ACTIONS
    assert "ask_clarification" in COMPOSED_ACTIONS
    assert "quote" in COMPOSED_ACTIONS
    assert "explain_payment_options" in COMPOSED_ACTIONS
    assert "close" in COMPOSED_ACTIONS
    assert "escalate_to_human" in SKIP_ACTIONS
    assert "schedule_followup" in SKIP_ACTIONS
    # No overlap
    assert COMPOSED_ACTIONS.isdisjoint(SKIP_ACTIONS)
```

Delete old tests for `text_for_action` and `dispatch` if they exist.

**Step 2: Replace `outbound_dispatcher.py`**

```python
"""Enqueue outbound messages onto the arq queue.

Phase 3b: dispatcher no longer holds canned text. The Composer (canned or
OpenAI) produces the messages; the dispatcher just enqueues them.
"""
from uuid import UUID, uuid4

from arq.connections import ArqRedis

from atendia.channels.base import OutboundMessage
from atendia.queue.enqueue import enqueue_outbound


COMPOSED_ACTIONS: set[str] = {
    "greet", "ask_field", "lookup_faq", "ask_clarification",
    "quote", "explain_payment_options", "close",
}

SKIP_ACTIONS: set[str] = {
    "escalate_to_human", "schedule_followup", "book_appointment", "search_catalog",
}


async def enqueue_messages(
    arq_redis: ArqRedis,
    *,
    messages: list[str],
    tenant_id: UUID,
    to_phone_e164: str,
    conversation_id: UUID,
    turn_number: int,
    action: str,
) -> list[str]:
    """Enqueue N OutboundMessage jobs (one per message)."""
    job_ids: list[str] = []
    for i, text in enumerate(messages):
        msg = OutboundMessage(
            tenant_id=str(tenant_id),
            to_phone_e164=to_phone_e164,
            text=text,
            idempotency_key=f"out:{conversation_id}:{turn_number}:{i}:{uuid4().hex[:6]}",
            metadata={"action": action, "message_index": i, "of": len(messages)},
        )
        job_ids.append(await enqueue_outbound(arq_redis, msg))
    return job_ids
```

**Step 3: Update callers**

Find `dispatch_outbound` callers (only `meta_routes.py` and possibly `runner_routes.py`). They'll be updated in T26 (factory). For now, the callers may break — the runner integration in Bloque H wires it correctly.

If `meta_routes.py` calls `dispatch_outbound`, leave it temporarily — T26 fixes it. To avoid CI red, you can `pytest.mark.skip` the relevant integration test temporarily.

**Step 4: Tests pass**

```bash
cd core && uv run pytest tests/runner/test_outbound_dispatcher.py -v
```

Expected: 6 PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/outbound_dispatcher.py core/tests/runner/test_outbound_dispatcher.py
git commit -m "refactor(outbound): enqueue_messages replaces dispatch + _PHASE2_TEXTS"
```

---

## Task 21: Verify no orphaned `_PHASE2_TEXTS` references

**Files:** none new — verification + minor cleanup.

**Step 1: Search**

```bash
cd core && grep -rn "_PHASE2_TEXTS\|text_for_action" atendia/ tests/ --include="*.py"
```

Expected: only refs inside `composer_canned.py` (which copied the texts).

**Step 2: If any other refs found, remove or update them.**

If existing tests in `test_inbound_to_runner.py` reference `dispatch` directly, mark them skipped with `awaiting T26`.

**Step 3: Run full runner suite**

```bash
cd core && uv run pytest tests/runner -v
```

Expected: PASS or only DB-dependent failures (which we'll fix in Bloque H).

**Step 4: Commit (if any changes)**

```bash
# only if changes were made
git add ...
git commit -m "chore(outbound): clean up legacy _PHASE2_TEXTS references"
```

---

# Bloque H — Runner integration

## Task 22: Runner — fetch tone and fetch tool stub payload

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- Modify: `core/tests/runner/test_conversation_runner.py`

**Step 1: Test**

In `test_conversation_runner.py`, add a test that asserts:
- The runner reads `tenant_branding.voice` and parses to `Tone`.
- For action `quote`, the runner calls the tool stub and stores the result in a local var (we'll use this in T23 to pass to Composer).

This test depends on DB; if Docker is up, it runs. If not, mark skip.

**Step 2: Implement**

In `conversation_runner.py`, after computing `state_obj` but before the `process_turn` call (since process_turn doesn't use tone or tool), add:

```python
# Phase 3b: load tone from tenant_branding.voice (defaults if missing).
voice_row = (await self._session.execute(
    text("SELECT voice FROM tenant_branding WHERE tenant_id = :t"),
    {"t": tenant_id},
)).fetchone()
from atendia.contracts.tone import Tone
tone = Tone.model_validate(voice_row[0] if voice_row else {})
```

After `process_turn`:

```python
# Phase 3b: invoke tool stub for data-needing actions.
from atendia.tools.quote import quote
from atendia.tools.lookup_faq import lookup_faq
from atendia.tools.search_catalog import search_catalog

action_payload: dict = {}
if decision.action == "quote":
    payload = quote(tenant_id=tenant_id, product_id="", options={})
    action_payload = payload.model_dump(mode="json")
elif decision.action == "lookup_faq":
    payload = lookup_faq(tenant_id=tenant_id, question=inbound.text)
    action_payload = payload.model_dump(mode="json")
elif decision.action == "search_catalog":
    payload = search_catalog(tenant_id=tenant_id, query=inbound.text, filters={})
    action_payload = payload.model_dump(mode="json")
elif decision.action == "ask_field":
    missing = next(
        (f for f in current_stage_def.required_fields
         if f.name not in {k for k, _ in (extracted_jsonb or {}).items()}),
        None,
    )
    if missing:
        action_payload = {
            "field_name": missing.name,
            "field_description": missing.description,
        }
elif decision.action == "close":
    action_payload = {"payment_link": None}
```

(Note: `current_stage_def` comes from the existing T20-Phase3a code; reuse it.)

**Step 3: Run + commit**

```bash
cd core && uv run pytest tests/runner -v
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "feat(runner): fetch tenant tone and invoke tool stubs for data-actions"
```

---

## Task 23: Runner — 24h check + Composer call + cost tracking

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- Modify: `core/tests/runner/test_conversation_runner.py`

**Step 1: Constructor change**

```python
def __init__(
    self, session: AsyncSession,
    nlu_provider: NLUProvider,
    composer_provider: ComposerProvider,
) -> None:
    self._session = session
    self._nlu = nlu_provider
    self._composer = composer_provider
    self._emitter = EventEmitter(session)
```

Update existing test fixtures to pass a `CannedComposer()`.

**Step 2: After tool stub dispatch (from T22), add 24h check + Composer call**

```python
from datetime import timedelta

# 24h window check.
last_activity_at = (await self._session.execute(
    text("SELECT last_activity_at FROM conversations WHERE id = :cid"),
    {"cid": conversation_id},
)).scalar()
inside_24h = (
    last_activity_at is None
    or (datetime.now(timezone.utc) - last_activity_at) < timedelta(hours=24)
)

composer_output: ComposerOutput | None = None
composer_usage: UsageMetadata | None = None

if not inside_24h and decision.action in COMPOSED_ACTIONS:
    # Outside 24h: no compose, no enqueue. Create handoff for visibility.
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
elif decision.action in COMPOSED_ACTIONS:
    # Inside 24h, action produces text: invoke Composer.
    history_for_composer = history[-pipeline.composer.history_turns * 2:]
    composer_input = ComposerInput(
        action=decision.action,
        action_payload=action_payload,
        current_stage=current_stage,
        last_intent=nlu.intent.value,
        extracted_data={k: v.value for k, v in state_obj.extracted_data.items()},
        history=history_for_composer,
        tone=tone,
        max_messages=2,  # could pull from settings, hardcoded for now
    )
    composer_output, composer_usage = await self._composer.compose(input=composer_input)

    if composer_usage and composer_usage.fallback_used:
        # Composer fell back to canned: client gets canned response,
        # but we flag for human review.
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
```

**Step 3: Persist composer fields to TurnTrace**

Modify the `TurnTrace(...)` construction to include:

```python
trace = TurnTrace(
    # ... existing fields ...
    composer_input=(composer_input.model_dump(mode="json") if composer_output else None),
    composer_output=(composer_output.model_dump(mode="json") if composer_output else None),
    composer_model=(composer_usage.model if composer_usage else None),
    composer_tokens_in=(composer_usage.tokens_in if composer_usage else None),
    composer_tokens_out=(composer_usage.tokens_out if composer_usage else None),
    composer_cost_usd=(composer_usage.cost_usd if composer_usage else None),
    composer_latency_ms=(composer_usage.latency_ms if composer_usage else None),
    # ... rest existing ...
)
```

**Step 4: Accumulate cost in conversation_state**

After persisting trace:

```python
# Accumulate composer cost (NLU cost is already accumulated in T21 of Phase 3a).
if composer_usage and composer_usage.cost_usd > 0:
    await self._session.execute(
        text("UPDATE conversation_state SET total_cost_usd = total_cost_usd + :c "
             "WHERE conversation_id = :cid"),
        {"c": composer_usage.cost_usd, "cid": conversation_id},
    )
```

**Step 5: Return composer_output for caller**

Change `run_turn` return to include the composer output, OR have the runner enqueue messages directly. Cleaner: enqueue in the runner.

Add `arq_pool: ArqRedis` to `__init__` or pass as a method arg. **Decision**: pass as a method arg to `run_turn` to keep `__init__` lean. Update caller in `meta_routes.py` (T26).

```python
async def run_turn(
    self,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    inbound: Message,
    turn_number: int,
    arq_pool: ArqRedis | None = None,  # NEW
) -> TurnTrace:
    # ... existing code ...

    # Enqueue composer output if produced.
    if composer_output and arq_pool is not None:
        await enqueue_messages(
            arq_pool, messages=composer_output.messages,
            tenant_id=tenant_id, to_phone_e164=...,  # need to fetch from conversation
            conversation_id=conversation_id, turn_number=turn_number,
            action=decision.action,
        )

    return trace
```

For `to_phone_e164`: fetch from `customers` join, or accept as param. Cleanest: accept as param.

```python
async def run_turn(
    self,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    inbound: Message,
    turn_number: int,
    arq_pool: ArqRedis | None = None,
    to_phone_e164: str | None = None,
) -> TurnTrace:
```

**Step 6: Tests**

Add to `test_conversation_runner.py`:

```python
async def test_runner_composer_called_for_composed_action(...):
    """When action is in COMPOSED_ACTIONS, Composer.compose is called."""
    # Use a fake composer that records calls
    pass


async def test_runner_24h_handoff_on_old_conversation(...):
    """If last_activity_at > 24h ago, no compose + handoff row created."""
    pass


async def test_runner_total_cost_includes_composer(...):
    """conversation_state.total_cost_usd accumulates both nlu+composer cost."""
    pass


async def test_runner_handoff_on_composer_fallback(...):
    """When composer_usage.fallback_used=True, human_handoffs row created."""
    pass
```

**Step 7: Run tests**

```bash
cd core && uv run pytest tests/runner -v
```

**Step 8: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "feat(runner): integrate Composer with 24h check, fallback handoff, cost"
```

---

## Task 24: Verify `EventType.ESCALATION_REQUESTED` exists

**Files:**
- Possibly modify: `core/atendia/contracts/event.py`

**Step 1: Check**

```bash
cd core && grep -n "ESCALATION_REQUESTED" atendia/contracts/event.py
```

If found: skip this task, just commit nothing.

If not found, add:

```python
class EventType(str, Enum):
    # ... existing ...
    ESCALATION_REQUESTED = "escalation_requested"
```

**Step 2: Verify migrations don't have a CHECK constraint that would reject the new enum**

```bash
cd core && grep -rn "event_type\|escalation" atendia/db/migrations/
```

If a constraint exists, add an Alembic migration to drop/recreate it with the new value. (Likely the `events.type` column is a `String`, not an enum-typed PG column — verify.)

**Step 3: Test**

If you added the enum value, write a smoke test:

```python
def test_escalation_requested_event_type_exists():
    from atendia.contracts.event import EventType
    assert EventType.ESCALATION_REQUESTED.value == "escalation_requested"
```

**Step 4: Commit (if changes)**

```bash
git add core/atendia/contracts/event.py
git commit -m "feat(events): add EventType.ESCALATION_REQUESTED"
```

---

## Task 25: Run broader regression check

**Step 1: Run full suite**

```bash
cd core && uv run pytest -q tests/contracts tests/state_machine tests/test_config.py tests/runner tests/tools tests/webhooks tests/integration tests/scripts
```

Expected: all PASS or only the integration test with `meta_routes.py` calls failing (those are fixed in T26).

**Step 2: Identify and skip integration tests pending T26**

If `tests/integration/test_inbound_to_runner.py` fails because `meta_routes.py` calls the old `dispatch`, mark with:

```python
pytestmark = pytest.mark.skip(reason="awaiting T26 webhook factory wiring composer")
```

**Step 3: Commit (if skip needed)**

```bash
git add core/tests/integration/test_inbound_to_runner.py
git commit -m "test(integration): skip pending T26 webhook composer wiring"
```

---

# Bloque I — Webhook factory + integration

## Task 26: `build_composer` factory + meta_routes wire

**Files:**
- Modify: `core/atendia/webhooks/meta_routes.py`
- Create: `core/tests/webhooks/test_build_composer_factory.py`

**Step 1: Tests**

```python
from atendia.config import Settings
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_openai import OpenAIComposer
from atendia.webhooks.meta_routes import build_composer


def test_build_composer_returns_canned_when_provider_canned():
    s = Settings(_env_file=None, composer_provider="canned")  # type: ignore
    assert isinstance(build_composer(s), CannedComposer)


def test_build_composer_returns_openai_when_provider_openai():
    s = Settings(
        _env_file=None,  # type: ignore
        composer_provider="openai",
        openai_api_key="sk-test",
    )
    composer = build_composer(s)
    assert isinstance(composer, OpenAIComposer)


def test_build_composer_passes_through_settings():
    s = Settings(
        _env_file=None,  # type: ignore
        composer_provider="openai",
        openai_api_key="sk-test",
        composer_model="gpt-4o",
        composer_timeout_s=4.0,
        composer_retry_delays_ms=[100, 500],
    )
    composer = build_composer(s)
    assert isinstance(composer, OpenAIComposer)
    assert composer._model == "gpt-4o"
    assert composer._delays == (0, 100, 500)
```

**Step 2: Implement**

In `meta_routes.py`, add:

```python
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerProvider


def build_composer(settings) -> ComposerProvider:
    if settings.composer_provider == "openai":
        return OpenAIComposer(
            api_key=settings.openai_api_key,
            model=settings.composer_model,
            timeout_s=settings.composer_timeout_s,
            retry_delays_ms=tuple(settings.composer_retry_delays_ms),
        )
    return CannedComposer()
```

**Step 3: Wire into `_persist_inbound`**

Find the existing `nlu = build_nlu(settings)` line. After it, add:

```python
composer = build_composer(settings)
runner = ConversationRunner(session, nlu, composer)  # NEW signature
```

Replace the existing `dispatch_outbound(...)` call with the runner's enqueue (which T23 wired):

```python
trace = await runner.run_turn(
    conversation_id=conv_id,
    tenant_id=tenant_id,
    inbound=inbound_canonical,
    turn_number=next_turn,
    arq_pool=arq_pool,
    to_phone_e164=m.from_phone_e164,
)
# Note: enqueue happens inside run_turn now (T23). The old dispatch_outbound
# call below this should be removed.
```

Remove the old block that imports `dispatch as dispatch_outbound` from `outbound_dispatcher` and calls it.

**Step 4: Unskip integration test (T25's skip)**

Remove the `pytestmark = pytest.mark.skip(...)` from `test_inbound_to_runner.py`.

**Step 5: Run + commit**

```bash
cd core && uv run pytest tests/webhooks tests/integration -v
git add core/atendia/webhooks/meta_routes.py core/tests/webhooks/test_build_composer_factory.py core/tests/integration/test_inbound_to_runner.py
git commit -m "feat(webhooks): build_composer factory + wire Composer into runner"
```

---

## Task 27: E2E integration tests for Composer (mocked + 24h)

**Files:**
- Modify: `core/tests/integration/test_inbound_to_runner.py`

**Step 1: Tests**

Add 2 new tests (paralelos to T22/T24 of Phase 3a):

```python
def _ok_composer_response(messages, model="gpt-4o", tokens_in=450, tokens_out=80):
    """Composer mocked completion response."""
    return Response(
        200,
        json={
            "id": "x", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps({"messages": messages})},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        },
    )


@respx.mock
def test_inbound_with_openai_composer_mocked(monkeypatch, setup_tenant_with_pipeline):
    """Phase 3b T22: full inbound → NLU + Composer both mocked → outbound enqueued."""
    monkeypatch.setenv("ATENDIA_V2_NLU_PROVIDER", "openai")
    monkeypatch.setenv("ATENDIA_V2_COMPOSER_PROVIDER", "openai")
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()

    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=[
        _ok_nlu_response(intent="greeting"),  # NLU call
        _ok_composer_response(messages=["¡Qué onda, Frank!", "¿Te ayudo con tu moto?"]),
    ])

    # ... post webhook ...
    # assert resp.status_code == 200

    # Verify trace has composer_*
    # Query: SELECT composer_model, composer_cost_usd, composer_output FROM turn_traces ...
    # Assert: composer_model == "gpt-4o", composer_cost_usd > 0, composer_output["messages"] == [...]


def test_inbound_outside_24h_creates_handoff_no_outbound(setup_tenant_with_pipeline):
    """Phase 3b T24: last_activity_at = now - 25h → no compose, handoff created."""
    # Manually set conversations.last_activity_at = now - timedelta(hours=25)
    # Post webhook
    # Assert: HTTP 200
    # Assert: human_handoffs has row with reason='outside_24h_window'
    # Assert: events has ESCALATION_REQUESTED row
    # Assert: composer was NOT called (no outbound, no composer_* in turn_trace)
```

**Step 2: Run + commit**

```bash
cd core && uv run pytest tests/integration -v
git add core/tests/integration/test_inbound_to_runner.py
git commit -m "test(integration): Composer happy path + 24h handoff E2E"
```

---

# Bloque J — Live + verificación final

## Task 28: Live test gated by `RUN_LIVE_LLM_TESTS`

**Files:**
- Create: `core/tests/runner/test_composer_live.py`

```python
"""Live OpenAI Composer smoke test — gated by RUN_LIVE_LLM_TESTS=1.

Costs ~$0.005 per run. Requires ATENDIA_V2_OPENAI_API_KEY.
"""
import os
import re
from decimal import Decimal

import pytest

from atendia.contracts.tone import Tone
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerInput


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI calls",
)


@pytest.mark.asyncio
async def test_live_composer_dinamo_greet():
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    composer = OpenAIComposer(api_key=api_key)
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting",
        tone=Tone(
            register="informal_mexicano", bot_name="Dinamo",
            signature_phrases=["¡qué onda!"], use_emojis="sparingly",
        ),
    ))
    assert 1 <= len(out.messages) <= 2
    text_combined = " ".join(out.messages).lower()
    assert any(g in text_combined for g in ["hola", "qué onda", "buenas"])
    assert all(len(m.split()) <= 50 for m in out.messages)
    assert usage.cost_usd > Decimal("0")
    assert usage.fallback_used is False


@pytest.mark.asyncio
async def test_live_composer_quote_does_not_invent_price():
    """The most important live test of Phase 3b: ensure gpt-4o doesn't hallucinate
    prices when action_payload says no_data."""
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    composer = OpenAIComposer(api_key=api_key)
    out, _ = await composer.compose(input=ComposerInput(
        action="quote",
        action_payload={"status": "no_data", "hint": "no catalog"},
        current_stage="quote",
        extracted_data={"interes_producto": "150Z"},
        tone=Tone(register="informal_mexicano", bot_name="Dinamo"),
    ))
    text_combined = " ".join(out.messages)
    # Must not contain a 4-6 digit number (price-shaped).
    assert not re.search(r"\$\s?\d{4,}|\b\d{4,6}\b", text_combined), \
        f"composer invented a price: {text_combined!r}"
    # Should mention consultar/revisar (redirect language).
    assert any(w in text_combined.lower() for w in ["consultar", "revisar", "confirmo"])
```

**Step 2: Verify gate works (without flag, 2 SKIPPED)**

```bash
cd core && uv run pytest tests/runner/test_composer_live.py -v
```

Expected: 2 SKIPPED.

**Step 3: Commit**

```bash
git add core/tests/runner/test_composer_live.py
git commit -m "test(composer): live smoke test gated, includes no-invent-price check"
```

---

## Task 29: Coverage gate + lint + mypy

**Step 1: Coverage**

```bash
cd core && uv run pytest --cov=atendia --cov-fail-under=85 --cov-report=term-missing tests/contracts tests/state_machine tests/test_config.py tests/runner tests/tools tests/webhooks tests/integration tests/scripts
```

Expected: PASS, coverage ≥85%.

If coverage drops below 85%, identify uncovered paths in `composer_openai.py` (likely the retry+fallback branches need a missed test) and add coverage.

**Step 2: Lint**

```bash
cd core && uv run ruff check . 2>&1 | tail -20
```

Fix any new violations introduced by Phase 3b (unused imports, line length).

**Step 3: mypy**

```bash
cd core && uv run mypy atendia 2>&1 | tail -30
```

Document new errors. Fix any introduced by Phase 3b. Pre-existing errors out of scope.

**Step 4: Commit (if changes)**

```bash
git add ...
git commit -m "chore: bring Phase 3b to coverage/lint/mypy gates"
```

---

## Task 30: Seed Dinamo voice + drop pipeline.tone migration + README

**Files:**
- Create: `core/scripts/seed_dinamo_voice.py`
- Create: `core/atendia/db/migrations/versions/011_drop_pipeline_tone.py`
- Modify: `README.md`
- Modify: `core/README.md`
- Update memory: `project_overview.md`

**Step 1: Seed script**

Create `core/scripts/seed_dinamo_voice.py`:

```python
"""Seed tenant_branding.voice for Dinamo with the agreed-on tone.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_voice \
        --tenant-id <uuid> [--dry-run]
"""
import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import text


DINAMO_VOICE = {
    "register": "informal_mexicano",
    "use_emojis": "sparingly",
    "max_words_per_message": 40,
    "bot_name": "Dinamo",
    "forbidden_phrases": ["estimado cliente", "le saluda atentamente", "cordialmente"],
    "signature_phrases": ["¡qué onda!", "te paso", "ahí va"],
}


async def _main(tenant_id: UUID, dry_run: bool) -> int:
    from atendia.db.session import _get_factory
    factory = _get_factory()
    async with factory() as session:
        existing = (await session.execute(
            text("SELECT 1 FROM tenant_branding WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).fetchone()
        if not existing:
            print(f"No tenant_branding row for {tenant_id}", file=sys.stderr)
            return 1
        print(f"Setting voice for tenant {tenant_id}:")
        print(json.dumps(DINAMO_VOICE, indent=2, ensure_ascii=False))
        if dry_run:
            print("[dry run] not writing")
            return 0
        await session.execute(
            text("UPDATE tenant_branding SET voice = :v::jsonb WHERE tenant_id = :t"),
            {"v": json.dumps(DINAMO_VOICE), "t": tenant_id},
        )
        await session.commit()
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.tenant_id, args.dry_run)))
```

(Place at `core/atendia/scripts/seed_dinamo_voice.py` for importable module path, paralleling T25 of Phase 3a.)

**Step 2: Alembic migration to drop pipeline.tone**

```bash
cd core && uv run alembic revision -m "drop pipeline tone field"
```

Edit the generated file. Use the random hash for `revision`, the prior head's hash for `down_revision`. Body:

```python
def upgrade() -> None:
    op.execute("UPDATE tenant_pipelines SET definition = definition - 'tone'")


def downgrade() -> None:
    op.execute("UPDATE tenant_pipelines SET definition = definition || jsonb_build_object('tone', '{}'::jsonb) WHERE NOT (definition ? 'tone')")
```

**Step 3: Apply + verify reversibility**

```bash
cd core && uv run alembic upgrade head
cd core && uv run alembic downgrade -1
cd core && uv run alembic upgrade head
```

**Step 4: README updates**

Update `README.md` Phase 3b status:

```markdown
- ✅ **Phase 3b** — Composer real (`gpt-4o`) con `list[str]`, tono per-tenant, 24h handoff, fallback canned
```

Update `core/README.md` env vars section with `ATENDIA_V2_COMPOSER_*`.

**Step 5: Memory update**

Edit `C:\Users\Sprt\.claude\projects\C--Users-Sprt-Documents-Proyectos-IA-AtendIA-v2\memory\project_overview.md`:

```markdown
- ✅ Phase 3b: Composer real (gpt-4o) — completed YYYY-MM-DD; commit history on branch `feat/phase-3b-composer-real`. Phase 3b scope: <N> tests, <%> coverage. Live smoke test gated by `RUN_LIVE_LLM_TESTS=1`.
```

**Step 6: Run full final suite**

```bash
cd core && uv run pytest --cov=atendia --cov-fail-under=85 -q
```

Expected: PASS.

**Step 7: Commits**

```bash
git add core/atendia/scripts/seed_dinamo_voice.py
git commit -m "feat(scripts): seed_dinamo_voice for tenant_branding.voice"

git add core/atendia/db/migrations/versions/011_*.py
git commit -m "feat(db): drop pipeline.tone (moved to tenant_branding.voice)"

git add README.md core/README.md
git commit -m "docs: mark Phase 3b (Composer real) as complete"
```

---

## Verificación final

| # | Criterio | Verificación |
|---|---|---|
| 1 | Suite completa pasa | `pytest -q` |
| 2 | Coverage ≥85% | `pytest --cov-fail-under=85` |
| 3 | Live smoke pasa, no inventa precios | `RUN_LIVE_LLM_TESTS=1 pytest tests/runner/test_composer_live.py` |
| 4 | Snapshot prompt estable | `test_composer_system_prompt_snapshot_greet_dinamo` |
| 5 | 24h handoff E2E | integration test pasa |
| 6 | Fallback canned funciona | integration test 503×3 pasa |
| 7 | Costo medido ≈ $0.002/turno | `SELECT AVG(composer_cost_usd) FROM turn_traces ...` |
| 8 | Manual smoke en staging, 5 conversaciones reales | cualitativo |

Cumplido todo, **Phase 3b queda lista** para mergear y activar via `composer_provider=openai`.

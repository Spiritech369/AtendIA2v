# AtendIA v2 — Fase 3a: NLU real (`gpt-4o-mini`) — Plan de Implementación

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Reemplazar `KeywordNLU` por un clasificador real basado en `gpt-4o-mini` con structured outputs, que entiende intent + entities + sentiment + ambigüedad y carga costos en `turn_traces` desde el primer turno.

**Architecture:** Refactor del runner para hablar contra un `Protocol NLUProvider` con tres implementaciones (`OpenAINLU` nueva, `KeywordNLU`/`CannedNLU` adaptadas). Configuración por env var (`nlu_provider`, API key, modelo, retry timings). Schema de pipeline v4 con `FieldSpec {name, description}` backward-compatible y bloque `nlu: {history_turns}`. Sin Composer, sin tools reales, sin migración de datos de Dinamo.

**Tech Stack:** Python 3.12 · OpenAI SDK ≥1.50 · Pydantic 2.9+ · respx (mocks) · pytest-asyncio. Resto del stack ya instalado.

**Diseño aprobado:** [`docs/plans/2026-05-03-fase-3a-nlu-real-design.md`](./2026-05-03-fase-3a-nlu-real-design.md).

**Pre-requisitos del entorno:**
- Working tree limpio en `main` o branch dedicado.
- Postgres v2 corriendo (puerto 5433) y migraciones al día (`uv run alembic upgrade head`).
- Redis v2 corriendo (puerto 6380).
- Python 3.12 + `uv` instalado.
- `pyproject.toml` y tests actuales pasan (`cd core && uv run pytest`).
- (Solo para Task 26) cuenta de OpenAI con API key válida si querés correr `RUN_LIVE_LLM_TESTS=1`.

**Convenciones:**
- TDD: cada feature arranca con un test que falla.
- Commits chicos por bloque lógico.
- Sin `--no-verify`, sin saltarse hooks.

---

## Mapa de tareas

| Bloque | Tareas | Foco |
|---|---|---|
| **A.** Setup | T1–T3 | Dependencias, settings, índice DB |
| **B.** Schema de pipeline v4 | T4–T7 | `FieldSpec`, `NLUConfig`, backward compat, JSON Schema canónico |
| **C.** Pricing | T8 | Tabla de precios y `compute_cost` |
| **D.** Protocol `NLUProvider` | T9 | Contrato común |
| **E.** Refactor providers existentes | T10–T11 | `CannedNLU`, `KeywordNLU` |
| **F.** Prompts module | T12–T14 | Templates editables, render, build_prompt, snapshot |
| **G.** `OpenAINLU` | T15–T19 | Happy path, reintentos, errores, validación |
| **H.** Runner integration | T20–T22 | Historial, cost tracking, integration tests |
| **I.** Factory + webhook | T23–T24 | Toggle de provider, integración E2E |
| **J.** Migración pipeline Dinamo | T25 | Script de upgrade JSONB |
| **K.** Live + verificación final | T26–T28 | Smoke real, gate de cobertura |

**Total: 28 tareas. Estimado: 3–4 días (1 dev).**

---

# Bloque A — Setup

## Task 1: Agregar dependencia `openai` y verificar instalación

**Files:**
- Modify: `core/pyproject.toml` (sección `dependencies`)
- Modify: `core/uv.lock` (regenerado)

**Step 1: Editar `core/pyproject.toml`**

Agregar `"openai>=1.50.0",` a `dependencies` (después de `"pyjwt>=2.12.1",`).

**Step 2: Sincronizar y verificar import**

```bash
cd core && uv sync && uv run python -c "from openai import AsyncOpenAI; print('OK')"
```

Expected: `OK`.

**Step 3: Verificar que `openai>=1.50.0` soporta structured outputs JSON schema**

```bash
cd core && uv run python -c "
from openai.types.chat import ChatCompletion
from openai import AsyncOpenAI
print('SDK ready')
"
```

Expected: `SDK ready`.

**Step 4: Commit**

```bash
git add core/pyproject.toml core/uv.lock
git commit -m "chore(core): add openai SDK dependency for Phase 3a"
```

---

## Task 2: Extender `Settings` con campos del NLU

**Files:**
- Modify: `core/atendia/config.py`
- Test: `core/tests/test_config.py` (crear si no existe)

**Step 1: Test que el default de `nlu_provider` es `keyword`**

Crear (o modificar) `core/tests/test_config.py`:

```python
from atendia.config import Settings


def test_nlu_provider_default_is_keyword():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.nlu_provider == "keyword"
    assert s.nlu_model == "gpt-4o-mini"
    assert s.nlu_timeout_s == 8.0
    assert s.nlu_retry_delays_ms == [500, 2000]
    assert s.openai_api_key == ""
```

**Step 2: Correr el test, verificar que falla**

```bash
cd core && uv run pytest tests/test_config.py -v
```

Expected: FAIL — `'Settings' object has no attribute 'nlu_provider'`.

**Step 3: Editar `core/atendia/config.py`**

Agregar campos:

```python
from typing import Literal

class Settings(BaseSettings):
    # ... campos existentes ...
    openai_api_key: str = Field(default="")
    nlu_model: str = Field(default="gpt-4o-mini")
    nlu_provider: Literal["openai", "keyword"] = Field(default="keyword")
    nlu_timeout_s: float = Field(default=8.0)
    nlu_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
```

**Step 4: Correr test**

```bash
cd core && uv run pytest tests/test_config.py -v
```

Expected: PASS.

**Step 5: Actualizar `.env.example`** (raíz del repo)

Agregar al final:

```
# Phase 3a — NLU
ATENDIA_V2_OPENAI_API_KEY=
ATENDIA_V2_NLU_MODEL=gpt-4o-mini
ATENDIA_V2_NLU_PROVIDER=keyword       # cambiar a "openai" para activar el NLU real
ATENDIA_V2_NLU_TIMEOUT_S=8.0
ATENDIA_V2_NLU_RETRY_DELAYS_MS=[500,2000]
```

**Step 6: Commit**

```bash
git add core/atendia/config.py core/tests/test_config.py .env.example
git commit -m "feat(config): add NLU settings (provider toggle, model, timeouts)"
```

---

## Task 3: Migración Alembic — index `(tenant_id, created_at)` en `turn_traces`

**Files:**
- Create: `core/atendia/db/migrations/versions/010_turn_traces_index.py`

**Step 1: Generar revisión vacía**

```bash
cd core && uv run alembic revision -m "turn_traces tenant_id created_at index"
```

(Esto crea un archivo con un slug; renombrarlo manualmente a `010_turn_traces_index.py` para mantener la convención numérica.)

**Step 2: Editar el archivo**

```python
"""turn_traces tenant_id created_at index

Revision ID: 010_turn_traces_index
Revises: 009_followups_handoffs
Create Date: 2026-05-03

"""
from alembic import op

revision = "010_turn_traces_index"
down_revision = "009_followups_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_turn_traces_tenant_created",
        "turn_traces",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_turn_traces_tenant_created", table_name="turn_traces")
```

**Step 3: Aplicar la migración**

```bash
cd core && uv run alembic upgrade head
```

Expected: salida con `Running upgrade 009_followups_handoffs -> 010_turn_traces_index, ...`.

**Step 4: Verificar el índice**

```bash
docker exec -it atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "\d turn_traces" | grep ix_turn_traces_tenant_created
```

Expected: línea `"ix_turn_traces_tenant_created" btree (tenant_id, created_at)`.

**Step 5: Verificar reversibilidad**

```bash
cd core && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: ambos comandos sin errores.

**Step 6: Commit**

```bash
git add core/atendia/db/migrations/versions/010_turn_traces_index.py
git commit -m "feat(db): add (tenant_id, created_at) index on turn_traces"
```

---

# Bloque B — Schema de pipeline v4

## Task 4: Modelo `FieldSpec` con backward-compat validator

**Files:**
- Modify: `core/atendia/contracts/pipeline_definition.py`
- Test: `core/tests/contracts/test_pipeline_definition.py`

**Step 1: Test que `FieldSpec` acepta string y dict**

Agregar a `core/tests/contracts/test_pipeline_definition.py`:

```python
from atendia.contracts.pipeline_definition import FieldSpec


def test_field_spec_from_string():
    f = FieldSpec.model_validate("ciudad")
    assert f.name == "ciudad"
    assert f.description == ""


def test_field_spec_from_dict():
    f = FieldSpec.model_validate({"name": "ciudad", "description": "Ciudad del cliente"})
    assert f.name == "ciudad"
    assert f.description == "Ciudad del cliente"


def test_field_spec_rejects_invalid_name():
    import pytest
    with pytest.raises(ValueError):
        FieldSpec.model_validate({"name": "BadName!", "description": ""})
```

**Step 2: Correr test, verificar que falla**

```bash
cd core && uv run pytest tests/contracts/test_pipeline_definition.py::test_field_spec_from_string -v
```

Expected: FAIL — `cannot import name 'FieldSpec'`.

**Step 3: Implementar `FieldSpec` en `core/atendia/contracts/pipeline_definition.py`**

Insertar antes de `StageDefinition`:

```python
import re
from pydantic import BaseModel, Field, field_validator, model_validator


_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FieldSpec(BaseModel):
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _name_pattern(cls, v: str) -> str:
        if not _FIELD_NAME_RE.match(v):
            raise ValueError(f"invalid field name {v!r} — must match {_FIELD_NAME_RE.pattern}")
        return v

    @model_validator(mode="before")
    @classmethod
    def _accept_string(cls, data):
        if isinstance(data, str):
            return {"name": data, "description": ""}
        return data
```

**Step 4: Correr todos los tests del módulo**

```bash
cd core && uv run pytest tests/contracts/test_pipeline_definition.py -v
```

Expected: PASS para los nuevos tests + tests previos que ya existían.

**Step 5: Commit**

```bash
git add core/atendia/contracts/pipeline_definition.py core/tests/contracts/test_pipeline_definition.py
git commit -m "feat(contracts): add FieldSpec with str/dict backward compat"
```

---

## Task 5: Modelo `NLUConfig` y campos nuevos en `StageDefinition` y `PipelineDefinition`

**Files:**
- Modify: `core/atendia/contracts/pipeline_definition.py`
- Test: `core/tests/contracts/test_pipeline_definition.py`

**Step 1: Tests para `NLUConfig` y los nuevos campos**

Agregar:

```python
from atendia.contracts.pipeline_definition import (
    NLUConfig, PipelineDefinition, StageDefinition,
)


def test_nlu_config_defaults():
    cfg = NLUConfig()
    assert cfg.history_turns == 2


def test_nlu_config_validates_range():
    import pytest
    with pytest.raises(ValueError):
        NLUConfig(history_turns=11)
    with pytest.raises(ValueError):
        NLUConfig(history_turns=-1)


def test_stage_with_optional_fields_and_field_specs():
    s = StageDefinition.model_validate({
        "id": "qualify",
        "required_fields": [{"name": "ciudad", "description": "Ciudad"}],
        "optional_fields": ["nombre"],
        "actions_allowed": ["ask_field"],
        "transitions": [],
    })
    assert s.required_fields[0].name == "ciudad"
    assert s.required_fields[0].description == "Ciudad"
    assert s.optional_fields[0].name == "nombre"
    assert s.optional_fields[0].description == ""


def test_pipeline_with_nlu_block():
    p = PipelineDefinition.model_validate({
        "version": 4,
        "nlu": {"history_turns": 4},
        "stages": [{"id": "qualify", "actions_allowed": [], "transitions": []}],
        "tone": {},
        "fallback": "x",
    })
    assert p.nlu.history_turns == 4
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/contracts/test_pipeline_definition.py -v -k "nlu_config or optional_fields or pipeline_with_nlu"
```

Expected: FAIL.

**Step 3: Implementar**

En `core/atendia/contracts/pipeline_definition.py`:

```python
class NLUConfig(BaseModel):
    history_turns: int = Field(default=2, ge=0, le=10)


class StageDefinition(BaseModel):
    id: str
    required_fields: list[FieldSpec] = Field(default_factory=list)
    optional_fields: list[FieldSpec] = Field(default_factory=list)
    actions_allowed: list[str]
    transitions: list[Transition]
    timeout_hours: int | None = None
    timeout_action: str | None = None


class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    stages: list[StageDefinition] = Field(min_length=1)
    tone: dict = Field(default_factory=dict)
    fallback: str
```

(Si ya existían `StageDefinition`/`PipelineDefinition`, fusionar en lugar de duplicar.)

**Step 4: Correr tests**

```bash
cd core && uv run pytest tests/contracts/test_pipeline_definition.py -v
```

Expected: PASS todos.

**Step 5: Verificar que el resto de la suite sigue pasando** (la backward compat de `FieldSpec` lo asegura)

```bash
cd core && uv run pytest -x --ff -q
```

Expected: PASS toda la suite.

**Step 6: Commit**

```bash
git add core/atendia/contracts/pipeline_definition.py core/tests/contracts/test_pipeline_definition.py
git commit -m "feat(contracts): add NLUConfig and optional_fields to pipeline schema v4"
```

---

## Task 6: Actualizar JSON Schema canónico

**Files:**
- Modify: `contracts/pipeline_definition.schema.json`

**Step 1: Editar el schema canónico**

Reemplazar el contenido de `contracts/pipeline_definition.schema.json` con:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://atendia.io/contracts/pipeline_definition.schema.json",
  "title": "PipelineDefinition",
  "type": "object",
  "required": ["version", "stages", "tone", "fallback"],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "nlu": { "$ref": "#/$defs/NLUConfig" },
    "stages": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/StageDefinition" }
    },
    "tone": { "type": "object" },
    "fallback": { "type": "string" }
  },
  "$defs": {
    "FieldSpec": {
      "oneOf": [
        { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
        {
          "type": "object",
          "required": ["name"],
          "properties": {
            "name": { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
            "description": { "type": "string", "maxLength": 200 }
          }
        }
      ]
    },
    "NLUConfig": {
      "type": "object",
      "properties": {
        "history_turns": { "type": "integer", "minimum": 0, "maximum": 10, "default": 2 }
      }
    },
    "StageDefinition": {
      "type": "object",
      "required": ["id", "actions_allowed", "transitions"],
      "properties": {
        "id": { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
        "required_fields": { "type": "array", "items": { "$ref": "#/$defs/FieldSpec" } },
        "optional_fields": { "type": "array", "items": { "$ref": "#/$defs/FieldSpec" } },
        "actions_allowed": { "type": "array", "items": { "type": "string" } },
        "transitions": { "type": "array", "items": { "$ref": "#/$defs/Transition" } },
        "timeout_hours": { "type": ["integer", "null"], "minimum": 1 },
        "timeout_action": { "type": ["string", "null"] }
      }
    },
    "Transition": {
      "type": "object",
      "required": ["to", "when"],
      "properties": {
        "to": { "type": "string" },
        "when": { "type": "string" }
      }
    }
  }
}
```

**Step 2: Correr `test_schema_consistency`**

```bash
cd core && uv run pytest tests/contracts/test_schema_consistency.py -v
```

Expected: PASS — los `required` del canonical son subset de los `required` de Pydantic.

**Step 3: Commit**

```bash
git add contracts/pipeline_definition.schema.json
git commit -m "feat(contracts): update canonical pipeline schema to v4"
```

---

## Task 7: Actualizar smoke test y fixtures de pipeline para usar `version: 4` opcional

**Files:**
- (Opcional) Verificar que ningún test/fixture/seed depende de `version` específico.

**Step 1: Buscar referencias hardcoded a `version`**

```bash
cd core && uv run python -c "
import json, glob
for f in glob.glob('tests/**/*.py', recursive=True) + glob.glob('scripts/*.py'):
    with open(f) as fh:
        data = fh.read()
    if '\"version\"' in data and '3' in data:
        print(f)
"
```

(El comando es heurístico; revisar manualmente cada archivo encontrado.)

**Step 2: Decisión**

Si todos los tests siguen pasando con `version` arbitraria (cosa que ya estaba antes), no se modifica nada y se cierra el task como **no-op verificado**. Solo se documenta en el commit.

**Step 3: Commit (vacío si no hay cambios)**

```bash
# Si hubo cambios:
git add core/tests core/scripts
git commit -m "test(contracts): no breaking changes from pipeline v4 schema"

# Si no hubo cambios, salta este step y sigue al siguiente bloque.
```

---

# Bloque C — Pricing

## Task 8: Módulo `pricing.py` y función `compute_cost`

**Files:**
- Create: `core/atendia/runner/nlu/__init__.py`
- Create: `core/atendia/runner/nlu/pricing.py`
- Test: `core/tests/runner/test_pricing.py`

**Step 1: Crear estructura del paquete**

```bash
mkdir -p "core/atendia/runner/nlu"
touch "core/atendia/runner/nlu/__init__.py"
```

**Step 2: Test**

Crear `core/tests/runner/test_pricing.py`:

```python
from decimal import Decimal

import pytest

from atendia.runner.nlu.pricing import MODEL_PRICING, compute_cost


def test_compute_cost_gpt_4o_mini_known():
    # 480 prompt + 80 completion ≈ $0.000120
    cost = compute_cost("gpt-4o-mini", tokens_in=480, tokens_out=80)
    assert cost == Decimal("0.000120")


def test_compute_cost_unknown_model_returns_zero():
    cost = compute_cost("some-model-that-does-not-exist", 1000, 500)
    assert cost == Decimal("0")


def test_compute_cost_zero_tokens():
    assert compute_cost("gpt-4o-mini", 0, 0) == Decimal("0.000000")


def test_pricing_table_has_canonical_model():
    assert "gpt-4o-mini" in MODEL_PRICING


@pytest.mark.parametrize("model_id", ["gpt-4o-mini", "gpt-4o-mini-2024-07-18"])
def test_pricing_dated_aliases_match(model_id):
    assert MODEL_PRICING[model_id] == MODEL_PRICING["gpt-4o-mini"]
```

**Step 3: Correr test, verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_pricing.py -v
```

Expected: FAIL — `cannot import name 'MODEL_PRICING'`.

**Step 4: Implementar `core/atendia/runner/nlu/pricing.py`**

```python
"""Static pricing table for LLM models used by the NLU.

Prices in USD per 1M tokens, verified at 2026-05.
Update when OpenAI announces price changes.
"""
from decimal import Decimal


MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # (input_price_per_1M, output_price_per_1M)
    "gpt-4o-mini":            (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o-mini-2024-07-18": (Decimal("0.150"), Decimal("0.600")),
}


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Return total USD cost for a single LLM call.

    Returns Decimal('0') if the model is unknown — caller should not crash
    on a model rename; the row in turn_traces will still capture token counts.
    """
    if model not in MODEL_PRICING:
        return Decimal("0")
    in_price, out_price = MODEL_PRICING[model]
    raw = (Decimal(tokens_in) * in_price + Decimal(tokens_out) * out_price) / Decimal("1000000")
    return raw.quantize(Decimal("0.000001"))
```

**Step 5: Correr test**

```bash
cd core && uv run pytest tests/runner/test_pricing.py -v
```

Expected: PASS todos.

**Step 6: Commit**

```bash
git add core/atendia/runner/nlu core/tests/runner/test_pricing.py
git commit -m "feat(nlu): add pricing module for LLM cost tracking"
```

---

# Bloque D — Protocol `NLUProvider`

## Task 9: Definir `NLUProvider` y `UsageMetadata`

**Files:**
- Create: `core/atendia/runner/nlu_protocol.py`
- Test: `core/tests/runner/test_nlu_protocol.py`

**Step 1: Test de tipo (estructural)**

Crear `core/tests/runner/test_nlu_protocol.py`:

```python
from decimal import Decimal

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.runner.nlu_protocol import NLUProvider, UsageMetadata


def test_usage_metadata_fields():
    u = UsageMetadata(
        model="gpt-4o-mini",
        tokens_in=100,
        tokens_out=50,
        cost_usd=Decimal("0.0001"),
        latency_ms=300,
    )
    assert u.tokens_in == 100
    assert u.cost_usd == Decimal("0.0001")


async def test_protocol_satisfied_by_dummy_class():
    """Ensure a class with the right shape satisfies NLUProvider via runtime
    structural check."""

    class Dummy:
        async def classify(
            self, *, text, current_stage, required_fields, optional_fields, history
        ):
            return (
                NLUResult(intent=Intent.GREETING, sentiment=Sentiment.NEUTRAL,
                          confidence=0.9),
                None,
            )

    nlu: NLUProvider = Dummy()  # static check: no error from mypy/pyright
    result, usage = await nlu.classify(
        text="hi", current_stage="greeting", required_fields=[],
        optional_fields=[], history=[],
    )
    assert result.intent == Intent.GREETING
    assert usage is None
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_nlu_protocol.py -v
```

Expected: FAIL — `cannot import name 'NLUProvider'`.

**Step 3: Implementar `core/atendia/runner/nlu_protocol.py`**

```python
"""Common interface for NLU providers.

Three implementations live in this package:
- OpenAINLU      — real LLM, used in production
- KeywordNLU     — keyword-based fallback for dev/tests
- CannedNLU      — fixture-driven for deterministic tests

All return (NLUResult, UsageMetadata | None). Mocks/fakes return None.
"""
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel

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
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]: ...
```

**Step 4: Correr test**

```bash
cd core && uv run pytest tests/runner/test_nlu_protocol.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu_protocol.py core/tests/runner/test_nlu_protocol.py
git commit -m "feat(nlu): add NLUProvider Protocol and UsageMetadata"
```

---

# Bloque E — Refactor providers existentes

## Task 10: Refactor `CannedNLU` a `async classify`

**Files:**
- Modify: `core/atendia/runner/nlu_canned.py`
- Test: `core/tests/runner/test_canned_nlu.py`

**Step 1: Test de la nueva firma**

Reemplazar contenido de `core/tests/runner/test_canned_nlu.py` (o crear si no existe):

```python
from pathlib import Path

import pytest

from atendia.contracts.nlu_result import Intent
from atendia.runner.nlu_canned import CannedNLU


@pytest.fixture
def fixture_path(tmp_path: Path) -> Path:
    p = tmp_path / "f.yaml"
    p.write_text(
        "nlu_results:\n"
        "  - intent: greeting\n"
        "    sentiment: neutral\n"
        "    confidence: 0.95\n"
        "    entities: {}\n"
        "    ambiguities: []\n",
        encoding="utf-8",
    )
    return p


async def test_canned_classify_returns_next_in_queue(fixture_path: Path):
    nlu = CannedNLU(fixture_path)
    result, usage = await nlu.classify(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    assert result.intent == Intent.GREETING
    assert usage is None


async def test_canned_classify_raises_when_exhausted(fixture_path: Path):
    nlu = CannedNLU(fixture_path)
    await nlu.classify(text="x", current_stage="x", required_fields=[],
                       optional_fields=[], history=[])
    with pytest.raises(IndexError):
        await nlu.classify(text="x", current_stage="x", required_fields=[],
                           optional_fields=[], history=[])
```

**Step 2: Correr test, verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_canned_nlu.py -v
```

Expected: FAIL — `'CannedNLU' object has no attribute 'classify'`.

**Step 3: Implementar nueva firma**

Reemplazar `core/atendia/runner/nlu_canned.py` con:

```python
from pathlib import Path

import yaml

from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_protocol import UsageMetadata


class CannedNLU:
    """Reads a list of NLUResult from a YAML file and returns them in order.

    Fixture-driven for deterministic tests. Returns UsageMetadata=None.
    """

    def __init__(self, fixture_path: Path) -> None:
        data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        self._queue = [NLUResult.model_validate(item) for item in data["nlu_results"]]
        self._idx = 0

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        if self._idx >= len(self._queue):
            raise IndexError("no more canned NLU results")
        result = self._queue[self._idx]
        self._idx += 1
        return result, None
```

**Step 4: Correr test**

```bash
cd core && uv run pytest tests/runner/test_canned_nlu.py -v
```

Expected: PASS.

**Step 5: Verificar que cualquier consumer existente compila — fix call sites si rompen**

```bash
cd core && uv run pytest -x -q
```

Si algún test consume `CannedNLU.next()`, actualizarlo a `await classify(...)`. Si rompe `ConversationRunner`, **se arregla en Task 20** (T13 es `build_prompt`, no el refactor del runner) — por ahora dejarlo roto si solo afecta a la integración del runner.

**Step 6: Commit**

```bash
git add core/atendia/runner/nlu_canned.py core/tests/runner/test_canned_nlu.py
git commit -m "refactor(nlu): CannedNLU implements NLUProvider.classify"
```

---

## Task 11: Refactor `KeywordNLU` a `async classify`

**Files:**
- Modify: `core/atendia/runner/nlu_keywords.py`
- Test: `core/tests/runner/test_nlu_keywords.py` (verificar nombre real, puede ser `test_keyword_nlu.py`)

**Step 1: Tests para la nueva firma** (preservar la lógica de keywords existente)

Editar el archivo de test correspondiente:

```python
from atendia.contracts.nlu_result import Intent
from atendia.runner.nlu_keywords import KeywordNLU


async def test_classify_greeting():
    nlu = KeywordNLU()
    result, usage = await nlu.classify(
        text="hola buenas", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    assert result.intent == Intent.GREETING
    assert result.confidence >= 0.85
    assert usage is None


async def test_classify_buy():
    nlu = KeywordNLU()
    result, _ = await nlu.classify(
        text="ya la quiero, dame el link",
        current_stage="quote", required_fields=[], optional_fields=[], history=[],
    )
    assert result.intent == Intent.BUY


async def test_classify_off_topic_default():
    nlu = KeywordNLU()
    result, _ = await nlu.classify(
        text="hace mucho calor en monterrey",
        current_stage="qualify", required_fields=[], optional_fields=[], history=[],
    )
    assert result.intent == Intent.OFF_TOPIC
```

**Step 2: Correr tests, verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_nlu_keywords.py -v
```

Expected: FAIL — `classify` no existe.

**Step 3: Implementar nueva firma en `core/atendia/runner/nlu_keywords.py`**

Reemplazar la clase `KeywordNLU`:

```python
class KeywordNLU:
    """Stateful keyword-based NLU. Fallback for dev/tests when OpenAI is off."""

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        return self._classify(text), None

    def _classify(self, text: str) -> NLUResult:
        # ... lógica de keywords existente sin cambios ...
```

(Importar `FieldSpec`, `UsageMetadata` arriba.)

**Step 4: Correr tests**

```bash
cd core && uv run pytest tests/runner/test_nlu_keywords.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu_keywords.py core/tests/runner/test_nlu_keywords.py
git commit -m "refactor(nlu): KeywordNLU implements NLUProvider.classify"
```

---

# Bloque F — Prompts module

## Task 12: Templates editables y `render_template`

**Files:**
- Create: `core/atendia/runner/nlu_prompts.py`
- Test: `core/tests/runner/test_nlu_prompts.py`

**Step 1: Tests del helper**

Crear `core/tests/runner/test_nlu_prompts.py`:

```python
import pytest

from atendia.runner.nlu_prompts import (
    HISTORY_FORMAT, OUTPUT_INSTRUCTIONS, ROLE_LABELS,
    SYSTEM_PROMPT_TEMPLATE, render_template,
)


def test_render_substitutes_placeholders():
    out = render_template("hello {{name}}, you are in {{stage}}", name="Frank", stage="qualify")
    assert out == "hello Frank, you are in qualify"


def test_render_raises_on_missing_placeholder():
    with pytest.raises(RuntimeError, match="unsubstituted placeholder"):
        render_template("hello {{name}}", other="x")


def test_render_ignores_extra_vars():
    out = render_template("hello {{name}}", name="x", extra="y")
    assert out == "hello x"


def test_role_labels_complete():
    assert "inbound" in ROLE_LABELS
    assert "outbound" in ROLE_LABELS


def test_template_constants_have_placeholders():
    assert "{{stage}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{required_fields_block}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{optional_fields_block}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{output_instructions}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{role}}" in HISTORY_FORMAT
    assert "{{text}}" in HISTORY_FORMAT
    assert "intent" in OUTPUT_INSTRUCTIONS  # sanity check
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_nlu_prompts.py -v
```

Expected: FAIL — module no existe.

**Step 3: Implementar `core/atendia/runner/nlu_prompts.py`**

```python
"""
Prompts del NLU (gpt-4o-mini).

Aquí editas:
  1. SYSTEM_PROMPT_TEMPLATE — instrucciones al modelo.
  2. HISTORY_FORMAT         — cómo se renderiza cada turno previo.
  3. OUTPUT_INSTRUCTIONS    — recordatorio del formato de salida.

Los placeholders entre {{ }} se sustituyen al construir la request.
"""
import re


# ============================================================
# 1. SYSTEM PROMPT — instrucciones generales
# ============================================================
SYSTEM_PROMPT_TEMPLATE = """\
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
"""


# ============================================================
# 2. HISTORY FORMAT
# ============================================================
HISTORY_FORMAT = "[{{role}}] {{text}}"

ROLE_LABELS = {
    "inbound": "cliente",
    "outbound": "asistente",
}


# ============================================================
# 3. OUTPUT INSTRUCTIONS
# ============================================================
OUTPUT_INSTRUCTIONS = """\
Reglas de salida:
- Si tu confianza global sobre la intent es < 0.7, marca un string descriptivo
  en "ambiguities" (ej: "intent_borderline_buy_vs_ask_price").
- NO inventes valores. Si el cliente no dijo un dato, NO lo incluyas en entities.
- Para entities numéricas, devuelve número (no string).
- intent: greeting | ask_info | ask_price | buy | schedule | complain |
          off_topic | unclear.
- sentiment: positive, neutral, negative.
- confidence: número 0.0–1.0 sobre tu certeza de la intent.
"""


_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, **vars: str) -> str:
    """Substitute {{name}} placeholders. Raise if any remain unfilled.

    Extra vars are ignored. Missing vars raise RuntimeError so a typo never
    silently leaves a placeholder in the prompt sent to the LLM.
    """
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in vars:
            raise RuntimeError(
                f"unsubstituted placeholder {{{{ {key} }}}} in template"
            )
        return str(vars[key])
    return _PLACEHOLDER_RE.sub(_sub, template)
```

**Step 4: Correr tests**

```bash
cd core && uv run pytest tests/runner/test_nlu_prompts.py -v
```

Expected: PASS todos.

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu_prompts.py core/tests/runner/test_nlu_prompts.py
git commit -m "feat(nlu): add editable prompt templates and render helper"
```

---

## Task 13: `build_prompt` — orquestador del prompt completo

**Files:**
- Modify: `core/atendia/runner/nlu_prompts.py`
- Test: `core/tests/runner/test_nlu_prompts.py`

**Step 1: Test del builder completo**

Agregar a `test_nlu_prompts.py`:

```python
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_prompts import build_prompt


def test_build_prompt_basic_structure():
    messages = build_prompt(
        text="me interesa la 150Z",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo de moto"),
            FieldSpec(name="ciudad", description="Ciudad del cliente"),
        ],
        optional_fields=[FieldSpec(name="nombre", description="Nombre")],
        history=[("inbound", "hola"), ("outbound", "hola, ¿en qué te ayudo?")],
    )

    assert messages[0]["role"] == "system"
    assert "qualify" in messages[0]["content"]
    assert "interes_producto" in messages[0]["content"]
    assert "Modelo de moto" in messages[0]["content"]
    assert "ciudad" in messages[0]["content"]
    assert "nombre" in messages[0]["content"]
    # Last message is the current user text
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "me interesa la 150Z"
    # History rendered between system and current message
    assert any("[cliente] hola" in m.get("content", "") for m in messages)
    assert any("[asistente] hola, ¿en qué te ayudo?" in m.get("content", "") for m in messages)


def test_build_prompt_empty_required_renders_ninguno():
    messages = build_prompt(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    assert "(ninguno)" in messages[0]["content"]


def test_build_prompt_empty_history_does_not_break():
    messages = build_prompt(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    # System + user
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
```

**Step 2: Correr test, verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_nlu_prompts.py -v -k build_prompt
```

Expected: FAIL — `cannot import name 'build_prompt'`.

**Step 3: Implementar `build_prompt`** (agregar al final de `nlu_prompts.py`)

```python
from atendia.contracts.pipeline_definition import FieldSpec


def _render_fields(fields: list[FieldSpec]) -> str:
    if not fields:
        return "(ninguno)"
    return "\n".join(
        f"- {f.name}: {f.description or '(sin descripción)'}"
        for f in fields
    )


def _render_history(history: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Convert [(direction, text), ...] into chat messages.

    inbound → role 'user', outbound → role 'assistant'. The label inside
    the content uses ROLE_LABELS for transparency in case the LLM sees
    the bracket annotations.
    """
    out: list[dict[str, str]] = []
    for direction, text in history:
        role = "user" if direction == "inbound" else "assistant"
        label = ROLE_LABELS.get(direction, direction)
        rendered = render_template(HISTORY_FORMAT, role=label, text=text)
        out.append({"role": role, "content": rendered})
    return out


def build_prompt(
    *,
    text: str,
    current_stage: str,
    required_fields: list[FieldSpec],
    optional_fields: list[FieldSpec],
    history: list[tuple[str, str]],
) -> list[dict[str, str]]:
    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        stage=current_stage,
        required_fields_block=_render_fields(required_fields),
        optional_fields_block=_render_fields(optional_fields),
        output_instructions=OUTPUT_INSTRUCTIONS,
    )
    return [
        {"role": "system", "content": system_content},
        *_render_history(history),
        {"role": "user", "content": text},
    ]
```

**Step 4: Correr tests**

```bash
cd core && uv run pytest tests/runner/test_nlu_prompts.py -v
```

Expected: PASS todos.

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu_prompts.py core/tests/runner/test_nlu_prompts.py
git commit -m "feat(nlu): build_prompt assembles system+history+user messages"
```

---

## Task 14: Snapshot test del system prompt

**Files:**
- Create: `core/tests/fixtures/nlu/qualify_system.txt`
- Modify: `core/tests/runner/test_nlu_prompts.py`

**Step 1: Generar el snapshot manualmente**

Correr en una shell de Python:

```bash
cd core && uv run python -c "
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_prompts import build_prompt

m = build_prompt(
    text='dummy',
    current_stage='qualify',
    required_fields=[
        FieldSpec(name='interes_producto', description='Modelo de moto'),
        FieldSpec(name='ciudad', description='Ciudad del cliente'),
    ],
    optional_fields=[FieldSpec(name='nombre', description='Nombre del cliente')],
    history=[],
)
print(m[0]['content'])
" > tests/fixtures/nlu/qualify_system.txt
```

(Crear el directorio `tests/fixtures/nlu/` si no existe.)

**Step 2: Inspeccionar el archivo**

```bash
cd core && cat tests/fixtures/nlu/qualify_system.txt
```

Verificar manualmente que el contenido sea legible y correcto. Si hay algo raro, reportar antes de seguir.

**Step 3: Test que compara byte-a-byte**

Agregar a `test_nlu_prompts.py`:

```python
from pathlib import Path

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "nlu"


def test_system_prompt_snapshot_qualify():
    expected = (_FIXTURES / "qualify_system.txt").read_text(encoding="utf-8")
    messages = build_prompt(
        text="dummy",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo de moto"),
            FieldSpec(name="ciudad", description="Ciudad del cliente"),
        ],
        optional_fields=[FieldSpec(name="nombre", description="Nombre del cliente")],
        history=[],
    )
    # Strip trailing newline that the shell `print` may add
    assert messages[0]["content"] == expected.rstrip("\n")
```

**Step 4: Correr el test**

```bash
cd core && uv run pytest tests/runner/test_nlu_prompts.py::test_system_prompt_snapshot_qualify -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/tests/fixtures/nlu core/tests/runner/test_nlu_prompts.py
git commit -m "test(nlu): snapshot test for qualify-stage system prompt"
```

---

# Bloque G — `OpenAINLU`

## Task 15: Esqueleto + happy path con respx

**Files:**
- Create: `core/atendia/runner/nlu_openai.py`
- Create: `core/tests/runner/test_nlu_openai.py`

**Step 1: Test happy path**

Crear `core/tests/runner/test_nlu_openai.py`:

```python
import json
from decimal import Decimal

import pytest
import respx
from httpx import Response

from atendia.contracts.nlu_result import Intent, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_openai import OpenAINLU


def _ok_response(intent="ask_info", entities=None, confidence=0.9,
                 sentiment="neutral", ambiguities=None,
                 model="gpt-4o-mini", tokens_in=480, tokens_out=80):
    payload = {
        "intent": intent,
        "entities": entities or {},
        "confidence": confidence,
        "sentiment": sentiment,
        "ambiguities": ambiguities or [],
    }
    return Response(
        200,
        json={
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "created": 0,
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
async def test_classify_happy_path_returns_result_and_usage():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_response(
            intent="ask_price",
            entities={"interes_producto": {"value": "150Z", "confidence": 0.9, "source_turn": 0}},
        )
    )

    nlu = OpenAINLU(api_key="sk-test")
    result, usage = await nlu.classify(
        text="cuánto cuesta la 150Z?",
        current_stage="qualify",
        required_fields=[FieldSpec(name="interes_producto", description="Modelo")],
        optional_fields=[],
        history=[],
    )

    assert result.intent == Intent.ASK_PRICE
    assert result.entities["interes_producto"].value == "150Z"
    assert result.confidence == 0.9
    assert usage is not None
    assert usage.tokens_in == 480
    assert usage.tokens_out == 80
    assert usage.cost_usd == Decimal("0.000120")
    assert usage.latency_ms >= 0
    assert usage.model == "gpt-4o-mini"
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py::test_classify_happy_path_returns_result_and_usage -v
```

Expected: FAIL — module `nlu_openai` no existe.

**Step 3: Implementar `core/atendia/runner/nlu_openai.py` (happy path solamente, retries en task 16)**

```python
import asyncio
import time
from decimal import Decimal

from openai import AsyncOpenAI
from pydantic import ValidationError

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu.pricing import compute_cost
from atendia.runner.nlu_prompts import build_prompt
from atendia.runner.nlu_protocol import UsageMetadata


def _build_json_schema() -> dict:
    """Strict JSON schema for OpenAI structured outputs."""
    schema = NLUResult.model_json_schema()
    # OpenAI structured outputs requires additionalProperties: false on every object.
    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
    _walk(schema)
    return {"name": "nlu_result", "strict": True, "schema": schema}


_NLU_JSON_SCHEMA = _build_json_schema()


class OpenAINLU:
    """gpt-4o-mini classifier with structured outputs and retry."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        retry_delays_ms: tuple[int, ...] = (500, 2000),
        timeout_s: float = 8.0,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._model = model
        self._delays = (0, *retry_delays_ms)

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        messages = build_prompt(
            text=text,
            current_stage=current_stage,
            required_fields=required_fields,
            optional_fields=optional_fields,
            history=history,
        )
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": _NLU_JSON_SCHEMA},
            temperature=0,
        )
        result = NLUResult.model_validate_json(resp.choices[0].message.content)
        usage = UsageMetadata(
            model=resp.model,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            cost_usd=compute_cost(resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        return result, usage
```

**Step 4: Correr el happy path**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py::test_classify_happy_path_returns_result_and_usage -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu_openai.py core/tests/runner/test_nlu_openai.py
git commit -m "feat(nlu): OpenAINLU happy path with structured outputs"
```

---

## Task 16: Retry exitoso (1er intento falla, 2do OK)

**Files:**
- Modify: `core/atendia/runner/nlu_openai.py`
- Modify: `core/tests/runner/test_nlu_openai.py`

**Step 1: Test**

Agregar a `test_nlu_openai.py`:

```python
@respx.mock
async def test_classify_retries_on_503_then_succeeds():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[Response(503, json={"error": {"message": "boom"}}), _ok_response()]
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(50,))  # fast retry for tests
    result, usage = await nlu.classify(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    assert route.call_count == 2
    assert result.intent == Intent.ASK_INFO  # default in _ok_response
    assert usage is not None
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py::test_classify_retries_on_503_then_succeeds -v
```

Expected: FAIL — la implementación actual no reintenta.

**Step 3: Agregar el retry loop a `OpenAINLU.classify`**

Reemplazar el cuerpo del método:

```python
from openai import (
    APIConnectionError, APITimeoutError, AuthenticationError,
    BadRequestError, InternalServerError, RateLimitError,
)


_RETRIABLE = (
    APITimeoutError, APIConnectionError, RateLimitError,
    InternalServerError, ValidationError,
)
_NON_RETRIABLE = (AuthenticationError, BadRequestError)


async def classify(self, *, text, current_stage, required_fields,
                   optional_fields, history):
    messages = build_prompt(
        text=text, current_stage=current_stage,
        required_fields=required_fields, optional_fields=optional_fields,
        history=history,
    )
    t0 = time.perf_counter()
    last_exc: Exception | None = None
    for delay_ms in self._delays:
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": _NLU_JSON_SCHEMA},
                temperature=0,
            )
            result = NLUResult.model_validate_json(resp.choices[0].message.content)
            usage = UsageMetadata(
                model=resp.model,
                tokens_in=resp.usage.prompt_tokens,
                tokens_out=resp.usage.completion_tokens,
                cost_usd=compute_cost(
                    resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens,
                ),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
            return result, usage
        except _NON_RETRIABLE as e:
            last_exc = e
            break
        except _RETRIABLE as e:
            last_exc = e
            continue
    return self._error_result(last_exc), self._zero_usage(t0)


def _error_result(self, exc: Exception | None) -> NLUResult:
    name = type(exc).__name__ if exc else "Unknown"
    return NLUResult(
        intent=Intent.UNCLEAR,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.0,
        ambiguities=[f"nlu_error:{name}"],
    )


def _zero_usage(self, t0: float) -> UsageMetadata:
    return UsageMetadata(
        model=self._model,
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal("0"),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
```

**Step 4: Correr test**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py::test_classify_retries_on_503_then_succeeds -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/nlu_openai.py core/tests/runner/test_nlu_openai.py
git commit -m "feat(nlu): retry transient errors with configurable delays"
```

---

## Task 17: Retry exhaustion → `unclear`

**Files:**
- Modify: `core/tests/runner/test_nlu_openai.py`

**Step 1: Test**

Agregar:

```python
@respx.mock
async def test_classify_returns_unclear_when_all_retries_fail():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {"message": "down"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, usage = await nlu.classify(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    assert result.intent == Intent.UNCLEAR
    assert result.confidence == 0.0
    assert any(a.startswith("nlu_error:InternalServerError") for a in result.ambiguities)
    assert usage is not None
    assert usage.tokens_in == 0
    assert usage.cost_usd == Decimal("0")
```

**Step 2: Correr — debería ya pasar tras task 16**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py::test_classify_returns_unclear_when_all_retries_fail -v
```

Expected: PASS (verifica que la lógica de fallback funciona end-to-end).

**Step 3: Commit**

```bash
git add core/tests/runner/test_nlu_openai.py
git commit -m "test(nlu): exhaustion of retries falls back to unclear"
```

---

## Task 18: Sin reintento en `AuthenticationError`/`BadRequestError`

**Files:**
- Modify: `core/tests/runner/test_nlu_openai.py`

**Step 1: Tests**

Agregar:

```python
@respx.mock
async def test_classify_does_not_retry_on_401():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(401, json={"error": {"message": "bad key"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x", current_stage="x",
        required_fields=[], optional_fields=[], history=[],
    )
    assert route.call_count == 1
    assert result.intent == Intent.UNCLEAR
    assert any("AuthenticationError" in a for a in result.ambiguities)


@respx.mock
async def test_classify_does_not_retry_on_400():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(400, json={"error": {"message": "bad schema"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x", current_stage="x",
        required_fields=[], optional_fields=[], history=[],
    )
    assert route.call_count == 1
    assert any("BadRequestError" in a for a in result.ambiguities)
```

**Step 2: Correr — debería ya pasar tras task 16**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py -v -k "does_not_retry"
```

Expected: PASS ambos.

**Step 3: Commit**

```bash
git add core/tests/runner/test_nlu_openai.py
git commit -m "test(nlu): no retry on auth or 400 errors"
```

---

## Task 19: JSON malformado → reintenta y al final fallback

**Files:**
- Modify: `core/tests/runner/test_nlu_openai.py`

**Step 1: Test**

```python
@respx.mock
async def test_classify_treats_malformed_json_as_validation_error():
    bad = Response(
        200, json={
            "id": "x", "object": "chat.completion", "created": 0,
            "model": "gpt-4o-mini",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": '{"intent": "FAKE"}'},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[bad, bad, bad]
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x", current_stage="x",
        required_fields=[], optional_fields=[], history=[],
    )
    assert route.call_count == 3
    assert result.intent == Intent.UNCLEAR
    assert any("ValidationError" in a for a in result.ambiguities)
```

**Step 2: Correr**

```bash
cd core && uv run pytest tests/runner/test_nlu_openai.py::test_classify_treats_malformed_json_as_validation_error -v
```

Expected: PASS (la lógica ya está; este test la solidifica).

**Step 3: Commit**

```bash
git add core/tests/runner/test_nlu_openai.py
git commit -m "test(nlu): malformed JSON treated as validation error and retried"
```

---

# Bloque H — Runner integration

## Task 20: Refactor de `ConversationRunner` a `NLUProvider` + fetch de historial

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- Modify: `core/tests/runner/test_conversation_runner.py`

**Step 1: Test actualizado**

Editar `test_conversation_runner.py` para usar `await classify`:

```python
# Reemplazar el setup del runner con NLUProvider via Protocol.
# Usar CannedNLU en los tests (ya implementa classify después de Task 10).
# Verificar que ahora también pasa `history` y stage al provider via spy.
```

(Adaptar los tests existentes, que actualmente usan `CannedNLU`/`KeywordNLU` con la API vieja.)

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_conversation_runner.py -v
```

Expected: FAIL hasta que cambiemos `ConversationRunner`.

**Step 3: Modificar `core/atendia/runner/conversation_runner.py`**

- Cambiar la firma `__init__(self, session, nlu_provider: CannedNLU)` a `nlu_provider: NLUProvider`.
- Antes de llamar al NLU, fetch del historial (last N) desde `messages` table donde `conversation_id = :cid` ordenado `sent_at ASC`. N viene de `pipeline.nlu.history_turns`.
- Llamar `result, usage = await self._nlu.classify(text=inbound.text, current_stage=current_stage, required_fields=stage.required_fields, optional_fields=stage.optional_fields, history=history)`.
- En el insert/upsert de `TurnTrace`: poblar `nlu_model`, `nlu_tokens_in`, `nlu_tokens_out`, `nlu_cost_usd`, `nlu_latency_ms` desde `usage` si no es None.

**Step 4: Correr test**

```bash
cd core && uv run pytest tests/runner/test_conversation_runner.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "refactor(runner): use NLUProvider Protocol, fetch history, persist usage"
```

---

## Task 21: Acumular `total_cost_usd` en `conversation_state`

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- Modify: `core/tests/runner/test_conversation_runner.py`

**Step 1: Test**

Agregar a `test_conversation_runner.py`:

```python
async def test_total_cost_accumulates_across_turns(...):
    # Set up a conversation with two consecutive turns; mocked usage
    # returns cost 0.000050 each.
    # After both turns: conversation_state.total_cost_usd should equal 0.000100
    ...
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/runner/test_conversation_runner.py::test_total_cost_accumulates_across_turns -v
```

Expected: FAIL — el runner aún no actualiza `total_cost_usd`.

**Step 3: Implementar el UPDATE en el runner**

En el bloque que actualiza `conversation_state`, sumar:

```python
await self._session.execute(
    text("UPDATE conversation_state SET total_cost_usd = total_cost_usd + :c "
         "WHERE conversation_id = :cid"),
    {"c": usage.cost_usd if usage else 0, "cid": conversation_id},
)
```

**Step 4: Correr test**

```bash
cd core && uv run pytest tests/runner/test_conversation_runner.py::test_total_cost_accumulates_across_turns -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "feat(runner): accumulate per-turn nlu cost into conversation_state"
```

---

## Task 22: Integration test — runner+OpenAINLU con respx mock

**Files:**
- Modify: `core/tests/integration/test_inbound_to_runner.py`

**Step 1: Agregar test**

```python
@respx.mock
async def test_full_inbound_with_openai_nlu_mocked(...):
    # Set up a conversation with active pipeline v4 + nlu config.
    # Mock OpenAI to return a valid intent='ask_price' result.
    # Run the inbound handler with nlu_provider built as OpenAINLU.
    # Assert: turn_traces row has nlu_model, nlu_cost_usd > 0, etc.
```

**Step 2: Verificar PASS** (todo el código necesario ya existe tras task 21)

```bash
cd core && uv run pytest tests/integration/test_inbound_to_runner.py -v
```

Expected: PASS.

**Step 3: Commit**

```bash
git add core/tests/integration/test_inbound_to_runner.py
git commit -m "test(integration): inbound flow with OpenAINLU mocked"
```

---

# Bloque I — Factory + webhook

## Task 23: Factory `build_nlu(settings)` y wiring en `meta_routes.py`

**Files:**
- Modify: `core/atendia/webhooks/meta_routes.py`

**Step 1: Test que el factory devuelve el provider correcto**

Crear `core/tests/webhooks/test_build_nlu_factory.py`:

```python
from atendia.config import Settings
from atendia.webhooks.meta_routes import build_nlu
from atendia.runner.nlu_keywords import KeywordNLU
from atendia.runner.nlu_openai import OpenAINLU


def test_build_nlu_returns_keyword_when_provider_keyword():
    s = Settings(_env_file=None, nlu_provider="keyword")  # type: ignore[arg-type]
    assert isinstance(build_nlu(s), KeywordNLU)


def test_build_nlu_returns_openai_when_provider_openai():
    s = Settings(_env_file=None, nlu_provider="openai", openai_api_key="sk-test")  # type: ignore[arg-type]
    assert isinstance(build_nlu(s), OpenAINLU)
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/webhooks/test_build_nlu_factory.py -v
```

Expected: FAIL — `build_nlu` no existe.

**Step 3: Implementar en `meta_routes.py`**

```python
from atendia.runner.nlu_keywords import KeywordNLU
from atendia.runner.nlu_openai import OpenAINLU
from atendia.runner.nlu_protocol import NLUProvider


def build_nlu(settings: Settings) -> NLUProvider:
    if settings.nlu_provider == "openai":
        return OpenAINLU(
            api_key=settings.openai_api_key,
            model=settings.nlu_model,
            timeout_s=settings.nlu_timeout_s,
            retry_delays_ms=tuple(settings.nlu_retry_delays_ms),
        )
    return KeywordNLU()
```

Reemplazar el `KeywordNLU()` actual en `_persist_inbound` por `build_nlu(settings)`.

**Step 4: Correr tests**

```bash
cd core && uv run pytest tests/webhooks/test_build_nlu_factory.py -v
```

Expected: PASS.

**Step 5: Verificar suite completa**

```bash
cd core && uv run pytest -x -q
```

Expected: PASS toda la suite.

**Step 6: Commit**

```bash
git add core/atendia/webhooks/meta_routes.py core/tests/webhooks/test_build_nlu_factory.py
git commit -m "feat(webhooks): build_nlu factory selects provider via settings"
```

---

## Task 24: Integration test — falla del NLU emite `ERROR_OCCURRED` y dispara `ask_clarification`

**Files:**
- Modify: `core/tests/integration/test_inbound_to_runner.py`

**Step 1: Agregar test**

```python
@respx.mock
async def test_inbound_when_openai_fails_emits_error_event_and_clarification():
    # Mock OpenAI to return 503 always
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {}}),
    )
    # Set settings nlu_provider=openai
    # Hit the webhook with an inbound payload
    # Assert:
    #   - events table has a row with type=ERROR_OCCURRED, payload.where='nlu'
    #   - last outbound message is the canned 'ask_clarification' text
    ...
```

**Step 2: Correr y debuggear**

```bash
cd core && uv run pytest tests/integration/test_inbound_to_runner.py::test_inbound_when_openai_fails_emits_error_event_and_clarification -v
```

Expected: PASS. Si falla, revisar que el runner emita el event en función de `ambiguities[0].startswith("nlu_error:")`.

**Step 3: Si la lógica de emit ERROR_OCCURRED no estaba** — agregar al runner antes de retornar:

```python
if any(a.startswith("nlu_error:") for a in nlu_result.ambiguities):
    await self._emitter.emit(
        conversation_id=conversation_id, tenant_id=tenant_id,
        event_type=EventType.ERROR_OCCURRED,
        payload={"where": "nlu", "ambiguities": nlu_result.ambiguities},
    )
```

**Step 4: Correr**

```bash
cd core && uv run pytest tests/integration/test_inbound_to_runner.py -v
```

Expected: PASS todos.

**Step 5: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/integration/test_inbound_to_runner.py
git commit -m "feat(runner): emit ERROR_OCCURRED on nlu_error ambiguities"
```

---

# Bloque J — Migración pipeline Dinamo

## Task 25: Script `upgrade_dinamo_pipeline_to_v4.py`

**Files:**
- Create: `core/scripts/upgrade_dinamo_pipeline_to_v4.py`
- Test: `core/tests/scripts/test_upgrade_dinamo_pipeline.py`

**Step 1: Diseñar la transformación in-memory primero (testeable)**

Crear `core/tests/scripts/test_upgrade_dinamo_pipeline.py`:

```python
from atendia.scripts.upgrade_dinamo_pipeline_to_v4 import (
    upgrade_pipeline_jsonb,
    DINAMO_FIELD_DESCRIPTIONS,
)


def test_upgrade_string_fields_to_objects():
    old = {
        "version": 3,
        "stages": [{
            "id": "qualify",
            "required_fields": ["interes_producto", "ciudad"],
            "actions_allowed": [],
            "transitions": [],
        }],
        "tone": {},
        "fallback": "x",
    }
    new = upgrade_pipeline_jsonb(old)
    assert new["version"] == 4
    assert new["nlu"] == {"history_turns": 4}
    rfs = new["stages"][0]["required_fields"]
    assert rfs[0] == {"name": "interes_producto",
                      "description": DINAMO_FIELD_DESCRIPTIONS["interes_producto"]}
    assert rfs[1]["name"] == "ciudad"


def test_upgrade_idempotent_on_already_v4():
    already = {
        "version": 4,
        "nlu": {"history_turns": 4},
        "stages": [{
            "id": "qualify",
            "required_fields": [{"name": "interes_producto", "description": "..."}],
            "actions_allowed": [],
            "transitions": [],
        }],
        "tone": {}, "fallback": "x",
    }
    assert upgrade_pipeline_jsonb(already) == already
```

**Step 2: Verificar fallo**

```bash
cd core && uv run pytest tests/scripts/test_upgrade_dinamo_pipeline.py -v
```

Expected: FAIL — script no existe.

**Step 3: Implementar `core/scripts/upgrade_dinamo_pipeline_to_v4.py`**

```python
"""Upgrade Dinamo's tenant_pipelines row to schema v4.

Usage:
    PYTHONPATH=. uv run python scripts/upgrade_dinamo_pipeline_to_v4.py \\
        --tenant-id <uuid> [--dry-run]

Writes a NEW row with version=N+1, active=true. Old row becomes active=false.
"""
import argparse
import asyncio
import copy
import json
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import text

from atendia.config import get_settings
from atendia.db.session import async_session_factory


# Edited by humans: descriptions used by the NLU prompt.
DINAMO_FIELD_DESCRIPTIONS: dict[str, str] = {
    "interes_producto": "Modelo de motocicleta o categoría que le interesa al cliente (ej: 150Z, scooter, deportiva)",
    "ciudad": "Ciudad donde reside el cliente, en México",
    "nombre": "Nombre del cliente",
    "presupuesto_max": "Tope máximo en MXN (numérico)",
}


def upgrade_pipeline_jsonb(old: dict[str, Any]) -> dict[str, Any]:
    """Transform a pipeline JSONB to schema v4. Idempotent."""
    if old.get("version") == 4 and "nlu" in old:
        return old  # already migrated
    new = copy.deepcopy(old)
    new["version"] = 4
    new.setdefault("nlu", {"history_turns": 4})
    for stage in new.get("stages", []):
        for key in ("required_fields", "optional_fields"):
            specs = stage.get(key, [])
            stage[key] = [
                _coerce_field(s) for s in specs
            ]
    return new


def _coerce_field(s: Any) -> dict[str, str]:
    if isinstance(s, str):
        return {"name": s, "description": DINAMO_FIELD_DESCRIPTIONS.get(s, "")}
    return s


async def _main(tenant_id: UUID, dry_run: bool) -> int:
    settings = get_settings()
    async with async_session_factory() as session:
        row = (await session.execute(
            text("SELECT id, version, definition_jsonb FROM tenant_pipelines "
                 "WHERE tenant_id = :t AND active = true LIMIT 1"),
            {"t": tenant_id},
        )).fetchone()
        if not row:
            print(f"No active pipeline for tenant {tenant_id}", file=sys.stderr)
            return 1
        _id, current_version, definition = row
        new_def = upgrade_pipeline_jsonb(definition)
        new_version = current_version + 1
        print(f"Old version: {current_version}, new version: {new_version}")
        print(json.dumps(new_def, indent=2, ensure_ascii=False))
        if dry_run:
            print("[dry run] not writing")
            return 0
        await session.execute(
            text("UPDATE tenant_pipelines SET active = false WHERE id = :id"),
            {"id": _id},
        )
        await session.execute(
            text("INSERT INTO tenant_pipelines (tenant_id, version, definition_jsonb, active) "
                 "VALUES (:t, :v, :d::jsonb, true)"),
            {"t": tenant_id, "v": new_version, "d": json.dumps(new_def)},
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

**Step 4: Correr tests**

```bash
cd core && uv run pytest tests/scripts/test_upgrade_dinamo_pipeline.py -v
```

Expected: PASS.

**Step 5: Smoke en dev DB (opcional)** — `--dry-run` primero, ver el JSONB nuevo, luego sin flag.

```bash
cd core && PYTHONPATH=. uv run python scripts/upgrade_dinamo_pipeline_to_v4.py \
    --tenant-id <UUID-DE-DINAMO> --dry-run
```

**Step 6: Commit**

```bash
git add core/scripts/upgrade_dinamo_pipeline_to_v4.py core/tests/scripts
git commit -m "feat(scripts): upgrade Dinamo pipeline to schema v4"
```

---

# Bloque K — Live + verificación final

## Task 26: Live test gated por `RUN_LIVE_LLM_TESTS`

**Files:**
- Create: `core/tests/runner/test_nlu_live.py`

**Step 1: Crear el test**

```python
import os
from decimal import Decimal

import pytest

from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_openai import OpenAINLU


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI calls",
)


@pytest.mark.asyncio
async def test_live_classifies_buy_intent_in_spanish():
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY for live tests"
    nlu = OpenAINLU(api_key=api_key)
    result, usage = await nlu.classify(
        text="ya la quiero, dame el link de pago",
        current_stage="quote",
        required_fields=[FieldSpec(name="interes_producto", description="Modelo de moto")],
        optional_fields=[],
        history=[
            ("inbound", "cuánto cuesta la 150Z?"),
            ("outbound", "El precio es $32,000 MXN. ¿Te paso el link de pago?"),
        ],
    )
    assert result.intent == Intent.BUY
    assert result.confidence >= 0.7
    assert usage is not None
    assert usage.tokens_in > 0
    assert usage.cost_usd > Decimal("0")


@pytest.mark.asyncio
async def test_live_extracts_entities_in_qualify():
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    nlu = OpenAINLU(api_key=api_key)
    result, _ = await nlu.classify(
        text="me interesa la 150Z, soy de CDMX",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo de motocicleta"),
            FieldSpec(name="ciudad", description="Ciudad de residencia en México"),
        ],
        optional_fields=[],
        history=[],
    )
    assert "interes_producto" in result.entities
    assert "ciudad" in result.entities
    assert "150Z" in str(result.entities["interes_producto"].value)
    assert "CDMX" in str(result.entities["ciudad"].value).upper().replace(" ", "")
```

**Step 2: Correr local con flag**

```bash
cd core && RUN_LIVE_LLM_TESTS=1 ATENDIA_V2_OPENAI_API_KEY=sk-... uv run pytest tests/runner/test_nlu_live.py -v
```

Expected: PASS ambos. Si falla intermitentemente, ajustar el prompt o las expectativas (ej: aceptar `Intent.BUY` o `Intent.ASK_INFO` si la frase es ambigua).

**Step 3: Verificar que sin flag se skipean**

```bash
cd core && uv run pytest tests/runner/test_nlu_live.py -v
```

Expected: 2 tests skipped.

**Step 4: Commit**

```bash
git add core/tests/runner/test_nlu_live.py
git commit -m "test(nlu): live smoke test gated by RUN_LIVE_LLM_TESTS"
```

---

## Task 27: Suite completa + gate de cobertura

**Step 1: Correr full suite**

```bash
cd core && uv run pytest --cov=atendia --cov-report=term-missing --cov-fail-under=85
```

Expected: PASS, coverage ≥ 85%. Imprimir el detalle de líneas no cubiertas.

**Step 2: Si coverage < 85%, agregar tests específicos a las líneas faltantes** (típicamente edge cases en `OpenAINLU` o branches del runner). Iterar hasta que pase el gate.

**Step 3: Verificar lint y mypy**

```bash
cd core && uv run ruff check . && uv run mypy atendia
```

Expected: ambos sin errores.

**Step 4: Commit (si hubo cambios de tests/lints)**

```bash
git add core
git commit -m "test: bring coverage back to 85%+ with new NLU code paths"
```

---

## Task 28: Smoke manual en staging + actualización de README

**Step 1: Smoke local con `nlu_provider=openai`**

1. Setear `ATENDIA_V2_OPENAI_API_KEY` y `ATENDIA_V2_NLU_PROVIDER=openai` en `core/.env`.
2. Levantar la app: `cd core && uv run uvicorn atendia.main:app --reload --port 8001`.
3. Levantar arq worker: `cd core && uv run arq atendia.queue.worker.WorkerSettings`.
4. Mandar webhook simulado vía `scripts/smoke_test_phase2.py` o número real con ngrok.
5. Verificar en `turn_traces`: `nlu_model='gpt-4o-mini'`, `nlu_cost_usd > 0`, `nlu_latency_ms > 0`.

```sql
SELECT turn_number, inbound_text, nlu_output->'intent', nlu_cost_usd, nlu_latency_ms
FROM turn_traces ORDER BY created_at DESC LIMIT 5;
```

Expected: filas con costos llenados, intent reconocido correctamente.

**Step 2: Actualizar `README.md`** — cambiar status de Phase 3 a "Phase 3a ✅" e incluir link al diseño.

```markdown
- ✅ **Phase 3a** — NLU real (`gpt-4o-mini`) con structured outputs, retry, cost tracking
- ⏳ **Phase 3b** — Composer real (`gpt-4o`)
- ⏳ **Phase 3c** — Migración pipeline/catálogo/FAQs de Dinamo a DB con embeddings
```

**Step 3: Actualizar `core/README.md`** si menciona variables de entorno — agregar las nuevas (`ATENDIA_V2_OPENAI_API_KEY`, etc.).

**Step 4: Commit final**

```bash
git add README.md core/README.md
git commit -m "docs: mark Phase 3a (NLU real) as complete"
```

**Step 5: Tag (opcional)**

```bash
git tag phase-3a-nlu-real
```

---

## Verificación final del éxito de la fase

| # | Criterio | Comando / método |
|---|---|---|
| 1 | Suite completa pasa | `cd core && uv run pytest -q` |
| 2 | Coverage ≥ 85% | `cd core && uv run pytest --cov=atendia --cov-fail-under=85` |
| 3 | Lint y mypy limpios | `cd core && uv run ruff check . && uv run mypy atendia` |
| 4 | Live smoke test pasa | `cd core && RUN_LIVE_LLM_TESTS=1 ATENDIA_V2_OPENAI_API_KEY=sk-... uv run pytest tests/runner/test_nlu_live.py` |
| 5 | Costo medido en DB ~$0.0001/turno | `SELECT AVG(nlu_cost_usd) FROM turn_traces WHERE created_at > NOW() - INTERVAL '1 hour'` |
| 6 | Toggle `nlu_provider` funciona | Cambiar a `keyword` → conversación sigue funcionando con NLU offline |
| 7 | Falla simulada de OpenAI emite `ERROR_OCCURRED` y dispara `ask_clarification` | Test integration de Task 24 |

Cumplido todo lo anterior, **Phase 3a queda lista**. Los próximos pasos son Phase 3b (Composer real) y Phase 3c (migración real de Dinamo + embeddings).

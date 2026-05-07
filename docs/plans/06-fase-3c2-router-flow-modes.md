# AtendIA v2 — Fase 3c.2: Router determinístico + flow v1 (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT) — Plan de Implementación

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Trasladar el v1 prompt de Dinamo al runner de AtendIA v2 con paridad funcional: router determinístico per-turn que elige uno de 6 modos (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT), composer con un prompt grande por modo, y OpenAI Vision API integrada para clasificar imágenes en DOC MODE.

**Architecture:** El router determinístico evalúa una lista de `flow_mode_rules` (configuradas en `tenant_pipelines.definition` JSONB) cada turno; el primer match gana. NLU y Vision corren en paralelo via `asyncio.gather`. Composer recibe `flow_mode` + `extracted_data` + `brand_facts` + `vision_result` y selecciona uno de 6 prompts de modo. Estado canónico vive como `ExtractedFields` Pydantic en `conversation_state.extracted_data` (sin bicapa Customer-sticky, sin transitions persistidas).

**Tech Stack:** Python 3.12 · Postgres 15 + pgvector · OpenAI gpt-4o (Composer + Vision) + gpt-4o-mini (NLU) + text-embedding-3-large (búsqueda) · SQLAlchemy 2.0 + Pydantic v2 · respx (test mocks) · pytest-asyncio.

**Diseño aprobado:** [`docs/plans/2026-05-06-fase-3c2-router-flow-modes-design.md`](./2026-05-06-fase-3c2-router-flow-modes-design.md).

**Pre-requisitos del entorno:**
- Working tree limpio en branch `feat/phase-3c2-router-flow-modes` (ya creada).
- Phase 3c.1 mergeada (tag `phase-3c1-datos-reales`).
- Docker Desktop corriendo, postgres `pgvector/pgvector:0.8.2-pg15`, alembic head `c7d3762b4881`.
- Dinamo data ingerida (T15 de 3c.1). Si falta, correr:
  ```bash
  cd core && PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m atendia.scripts.ingest_dinamo_data \
      --tenant-id eb272fdc-0795-41ef-869c-801f3a2d4ffb --docs-dir ../docs
  ```
- `cd core && uv run pytest -q --ignore=tests/test_config_meta.py` pasa con 366 tests + 4 skips.
- `ATENDIA_V2_OPENAI_API_KEY` en `core/.env`.

**Convenciones:**
- TDD estricto. Cada feature arranca con un test que falla.
- Commits chicos por tarea. Sin `--no-verify`.
- Lint (ruff) + coverage (≥85%) gates al cierre. mypy se chequea pero no bloquea (problema pre-existente).

---

## Mapa de tareas

| Bloque | Tareas | Foco |
|---|---|---|
| **A.** Schema + contracts | T1–T5 | Migración 015 + Pydantic contracts (ExtractedFields, FlowMode, HandoffSummary, Attachment, VisionResult) |
| **B.** Vision API tooling | T6–T9 | `vision.py` wrapper + `classify_image` con structured output + tests |
| **C.** Router determinístico | T10–T13 | `flow_router.pick_flow_mode` + trigger types + normalización |
| **D.** Composer modes refactor | T14–T17 | Reemplazar `ACTION_GUIDANCE` por `MODE_PROMPTS` con 6 modos + snapshots |
| **E.** Webhook + Meta media | T18–T19 | Detectar attachments + fetch URL desde Meta API |
| **F.** Runner integration | T20–T22 | NLU+Vision paralelo + dispatch por modo + `pending_confirmation` |
| **G.** Brand facts + handoff | T23–T24 | `brand_facts` JSONB + `HandoffSummary` Pydantic |
| **H.** Tests + cierre | T25–T29 | E2E por modo + live smoke + lint/coverage + README + tag |

**Total: 29 tareas. Estimado: 5–7 días (1 dev).**

---

# Bloque A — Schema + contracts foundation

## Task 1: Migración 015 — `flow_mode` + `vision_cost_usd` + `vision_latency_ms`

**Files:**
- Create: `core/atendia/db/migrations/versions/015_turn_traces_flow_mode_vision.py`
- Modify: `core/atendia/db/models/turn_trace.py`

**Step 1: Generar revisión Alembic**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic revision -m "turn_traces flow_mode and vision cost"
```

Renombrar archivo generado a `015_turn_traces_flow_mode_vision.py`.

**Step 2: Editar el archivo**

```python
"""015_turn_traces_flow_mode_vision

Revision ID: <auto>
Revises: c7d3762b4881
Create Date: 2026-05-06 ...

Phase 3c.2 — adds:
  * `turn_traces.flow_mode VARCHAR(20)` — modo elegido por el router
  * `turn_traces.vision_cost_usd NUMERIC(10, 6)` — Vision API spent this turn
  * `turn_traces.vision_latency_ms INTEGER` — Vision API latency this turn
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<auto>"
down_revision: Union[str, Sequence[str], None] = "c7d3762b4881"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "turn_traces",
        sa.Column("flow_mode", sa.String(20), nullable=True),
    )
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

**Step 3: Aplicar + verificar reversibilidad**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run alembic upgrade head && \
  uv run alembic downgrade -1 && \
  uv run alembic upgrade head
```

Expected: las 3 operaciones tienen éxito.

**Step 4: Verificar columnas**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "\d turn_traces" | grep -E "flow_mode|vision"
```

Expected: 3 líneas con `flow_mode varchar(20)`, `vision_cost_usd numeric(10,6)`, `vision_latency_ms integer`, todas nullable.

**Step 5: Update `TurnTrace` model**

En `core/atendia/db/models/turn_trace.py`, agregar después de `tool_cost_usd`:

```python
    # Phase 3c.2: routing + vision
    flow_mode: Mapped[str | None] = mapped_column(String(20))
    vision_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    vision_latency_ms: Mapped[int | None] = mapped_column(Integer)
```

**Step 6: Smoke test**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run python -c "from atendia.db.models import TurnTrace; print(TurnTrace.__table__.c.flow_mode.type, TurnTrace.__table__.c.vision_cost_usd.type)"
```

Expected: `VARCHAR(20) NUMERIC(10, 6)`.

**Step 7: Run pytest (no debe romper nada de 3c.1)**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest -q --ignore=tests/test_config_meta.py
```

Expected: 366 passed, 4 skipped (pre-3c.2 baseline).

**Step 8: Commit**

```bash
git add core/atendia/db/migrations/versions/015_turn_traces_flow_mode_vision.py core/atendia/db/models/turn_trace.py
git commit -m "feat(db): turn_traces.flow_mode + vision_cost_usd + vision_latency_ms (migration 015)"
```

---

## Task 2: `ExtractedFields` Pydantic contract

**Files:**
- Create: `core/atendia/contracts/extracted_fields.py`
- Test: `core/tests/contracts/test_extracted_fields.py`

**Step 1: Test (TDD red)**

Crear `core/tests/contracts/test_extracted_fields.py`:

```python
"""ExtractedFields canonical conversation-scoped state contract.

Lives in conversation_state.extracted_data JSONB. NLU populates it,
the router reads it, the composer reads it. Hardcoded structure
(Phase 3c.2 has only Dinamo as tenant; refactor to JSONB-config when
a second vertical onboards).
"""
import pytest
from pydantic import ValidationError

from atendia.contracts.extracted_fields import (
    ExtractedFields,
    PlanCredito,
    TipoCredito,
)


def test_default_state_all_empty() -> None:
    """A fresh customer has nothing set."""
    state = ExtractedFields()
    assert state.tipo_credito is None
    assert state.plan_credito is None
    assert state.modelo_moto is None
    assert state.docs_ine is False
    assert state.docs_comprobante is False
    assert state.papeleria_completa is False
    assert state.antigüedad_meses is None


def test_tipo_credito_enum_values() -> None:
    """All 5 tipos del v1 prompt están en el enum."""
    assert TipoCredito.NOMINA_TARJETA == "Nómina Tarjeta"
    assert TipoCredito.NOMINA_RECIBOS == "Nómina Recibos"
    assert TipoCredito.PENSIONADOS == "Pensionados"
    assert TipoCredito.NEGOCIO_SAT == "Negocio SAT"
    assert TipoCredito.SIN_COMPROBANTES == "Sin Comprobantes"


def test_plan_credito_enum_values() -> None:
    """3 porcentajes del v1: 10%, 15%, 20%."""
    assert PlanCredito.PLAN_10 == "10%"
    assert PlanCredito.PLAN_15 == "15%"
    assert PlanCredito.PLAN_20 == "20%"


def test_invalid_tipo_credito_rejected() -> None:
    """Random strings rechazados con ValidationError."""
    with pytest.raises(ValidationError):
        ExtractedFields(tipo_credito="Pirata")  # type: ignore[arg-type]


def test_full_state_round_trip_through_json() -> None:
    """Pydantic serializa/deserializa para JSONB storage."""
    state = ExtractedFields(
        antigüedad_meses=24,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        plan_credito=PlanCredito.PLAN_10,
        modelo_moto="Adventure Elite 150 CC",
        docs_ine=True,
    )
    raw = state.model_dump(mode="json")
    assert raw["plan_credito"] == "10%"
    rebuilt = ExtractedFields.model_validate(raw)
    assert rebuilt.plan_credito == PlanCredito.PLAN_10


def test_partial_dict_validates() -> None:
    """Solo algunos campos también es válido (defaults aplican)."""
    state = ExtractedFields.model_validate({"antigüedad_meses": 12})
    assert state.antigüedad_meses == 12
    assert state.docs_ine is False
```

**Step 2: Verificar fallo (red)**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/contracts/test_extracted_fields.py -v
```

Expected: ImportError (`atendia.contracts.extracted_fields` no existe).

**Step 3: Implementar contrato**

Crear `core/atendia/contracts/extracted_fields.py`:

```python
"""Canonical conversation-scoped state for Dinamo (Phase 3c.2).

Lives in conversation_state.extracted_data JSONB. NLU writes here,
router and composer read. Hardcoded shape — Dinamo es el único tenant
en 3c.2; cuando se onboarde un segundo vertical, refactorizar a
JSONB-config (decisión #9 del design doc).
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict


class TipoCredito(str, Enum):
    """Cinco tipos de crédito del v1 prompt — uno por respuesta del menú."""

    NOMINA_TARJETA = "Nómina Tarjeta"
    NOMINA_RECIBOS = "Nómina Recibos"
    PENSIONADOS = "Pensionados"
    NEGOCIO_SAT = "Negocio SAT"
    SIN_COMPROBANTES = "Sin Comprobantes"


class PlanCredito(str, Enum):
    """Porcentaje de enganche según el plan asignado."""

    PLAN_10 = "10%"
    PLAN_15 = "15%"
    PLAN_20 = "20%"


class ExtractedFields(BaseModel):
    """Estado conversacional canónico.

    Convención: campos en español respetando el v1 prompt y los
    términos que la NLU ya conoce. Flags de docs siguen el patrón
    `docs_<key>: bool`; el helper next_pending_doc() (T3) los itera.
    """

    model_config = ConfigDict(use_enum_values=False)

    # Personal
    antigüedad_meses: int | None = None
    nombre: str | None = None

    # Plan (asignado en PLAN MODE)
    tipo_credito: TipoCredito | None = None
    plan_credito: PlanCredito | None = None

    # Sales (asignados en SALES MODE)
    modelo_moto: str | None = None
    tipo_moto: str | None = None  # categoría: "Motoneta", "Chopper", etc.

    # Docs (DOC MODE marca true al recibir/validar cada uno)
    docs_ine: bool = False
    docs_comprobante: bool = False
    docs_estados_de_cuenta: bool = False
    docs_nomina: bool = False
    docs_constancia_sat: bool = False
    docs_factura: bool = False
    docs_imss: bool = False
    papeleria_completa: bool = False

    # Conversacionales
    retention_attempt: bool = False
    cita_dia: str | None = None  # ISO date
```

**Step 4: Tests pasan (green)**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/contracts/test_extracted_fields.py -v
```

Expected: 6 PASS.

**Step 5: Commit**

```bash
git add core/atendia/contracts/extracted_fields.py core/tests/contracts/test_extracted_fields.py
git commit -m "feat(contracts): ExtractedFields canonical state with TipoCredito/PlanCredito enums"
```

---

## Task 3: `FlowMode` enum + `funnel_stage()` + `next_pending_doc()` helpers

**Files:**
- Create: `core/atendia/contracts/flow_mode.py`
- Create: `core/atendia/state_machine/derived.py`
- Test: `core/tests/state_machine/test_derived.py`

**Step 1: Tests (TDD red)**

Crear `core/tests/state_machine/test_derived.py`:

```python
"""Helpers derivados sobre ExtractedFields (Phase 3c.2).

funnel_stage() y next_pending_doc() son funciones puras, sin DB.
Toda la lógica de "dónde está el cliente" se deriva del estado
extraído — no se persiste por separado.
"""
import pytest

from atendia.contracts.extracted_fields import (
    ExtractedFields,
    PlanCredito,
    TipoCredito,
)
from atendia.state_machine.derived import funnel_stage, next_pending_doc


# Catálogo de docs requeridos por plan (debería vivir en pipeline JSONB
# en runtime; aquí lo hardcodeamos para los tests).
_DOCS_PER_PLAN = {
    "Nómina Tarjeta": ["ine", "comprobante", "estados_de_cuenta", "nomina"],
    "Nómina Recibos": ["ine", "comprobante", "nomina"],
    "Pensionados":    ["ine", "comprobante", "estados_de_cuenta", "imss"],
    "Negocio SAT":    ["ine", "comprobante", "estados_de_cuenta", "constancia_sat", "factura"],
    "Sin Comprobantes": ["ine", "comprobante"],
}


# ----- funnel_stage --------------------------------------------------

def test_funnel_stage_plan_when_no_plan_credito() -> None:
    """Cliente nuevo sin plan asignado → stage = plan."""
    s = ExtractedFields()
    assert funnel_stage(s) == "plan"


def test_funnel_stage_sales_when_plan_assigned() -> None:
    """Tiene plan_credito pero no modelo_moto → sales."""
    s = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    assert funnel_stage(s) == "sales"


def test_funnel_stage_doc_when_modelo_moto_set() -> None:
    """Tiene modelo_moto → ya cotizó → doc (recolectando papeles)."""
    s = ExtractedFields(plan_credito=PlanCredito.PLAN_10, modelo_moto="Adventure")
    assert funnel_stage(s) == "doc"


def test_funnel_stage_close_when_papeleria_completa() -> None:
    """Papelería lista → close (form de cierre)."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        modelo_moto="Adventure",
        papeleria_completa=True,
    )
    assert funnel_stage(s) == "close"


def test_funnel_stage_orden_de_precedencia_es_top_down() -> None:
    """Si papeleria_completa=true pero modelo_moto está vacío, sigue close.
    El orden de los if's: close > doc > sales > plan."""
    s = ExtractedFields(papeleria_completa=True)
    assert funnel_stage(s) == "close"


# ----- next_pending_doc ----------------------------------------------

def test_next_pending_doc_none_when_plan_not_assigned() -> None:
    """Sin plan_credito no sabemos qué pedir."""
    s = ExtractedFields()
    assert next_pending_doc(s, None, _DOCS_PER_PLAN) is None


def test_next_pending_doc_returns_first_missing() -> None:
    """Primer doc en orden de prioridad que aún no se ha recibido."""
    s = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    # Plan 10% (Nómina Tarjeta) requiere INE, comprobante, estados, nomina
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) == "ine"


def test_next_pending_doc_skips_received() -> None:
    """Salta docs ya recibidos."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        docs_ine=True,
    )
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) == "comprobante"


def test_next_pending_doc_handles_out_of_order_receipt() -> None:
    """Cliente mandó comprobante antes que INE → siguiente sigue siendo INE."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        docs_comprobante=True,  # llegó fuera de orden
    )
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) == "ine"


def test_next_pending_doc_returns_none_when_papeleria_completa() -> None:
    """Todos los docs requeridos del plan recibidos → None."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        docs_ine=True,
        docs_comprobante=True,
        docs_estados_de_cuenta=True,
        docs_nomina=True,
    )
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) is None


def test_next_pending_doc_minimal_plan_sin_comprobantes() -> None:
    """Plan 'Sin Comprobantes' solo requiere INE + comprobante de domicilio."""
    s = ExtractedFields(plan_credito=PlanCredito.PLAN_20)
    assert next_pending_doc(s, PlanCredito.PLAN_20, _DOCS_PER_PLAN) == "ine"

    s.docs_ine = True
    assert next_pending_doc(s, PlanCredito.PLAN_20, _DOCS_PER_PLAN) == "comprobante"

    s.docs_comprobante = True
    assert next_pending_doc(s, PlanCredito.PLAN_20, _DOCS_PER_PLAN) is None
```

**Step 2: Verificar fallo (red)**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/state_machine/test_derived.py -v
```

Expected: ImportError.

**Step 3: Implementar `FlowMode` enum**

Crear `core/atendia/contracts/flow_mode.py`:

```python
"""FlowMode — uno de los 6 modos del v1 prompt.

Decidido por el router determinístico cada turno. Determina cuál
de los 6 prompts del composer se usa.
"""
from enum import Enum


class FlowMode(str, Enum):
    """Los 6 modos conversacionales del v1 prompt."""

    PLAN = "PLAN"
    SALES = "SALES"
    DOC = "DOC"
    OBSTACLE = "OBSTACLE"
    RETENTION = "RETENTION"
    SUPPORT = "SUPPORT"
```

**Step 4: Implementar `derived.py`**

Crear `core/atendia/state_machine/derived.py`:

```python
"""Pure functions that derive flow signals from ExtractedFields.

No DB, no LLM. The runner calls these on every turn to decide what
the bot should do next.
"""
from atendia.contracts.extracted_fields import ExtractedFields, PlanCredito


def funnel_stage(extracted: ExtractedFields) -> str:
    """Where the customer is in the sales funnel.

    Returns one of {"plan", "sales", "doc", "close"}, derived purely
    from which fields are populated. Order of precedence (top-down):
      close > doc > sales > plan.

    `funnel_stage` is NOT persisted — it's recomputed whenever needed
    (composer prompts, analytics, handoff summaries).
    """
    if extracted.papeleria_completa:
        return "close"
    if extracted.modelo_moto:
        return "doc"
    if extracted.plan_credito:
        return "sales"
    return "plan"


def next_pending_doc(
    extracted: ExtractedFields,
    plan_credito: PlanCredito | None,
    docs_per_plan: dict[str, list[str]],
) -> str | None:
    """First document in priority order that hasn't been received.

    `docs_per_plan` is a dict mapping plan label (e.g. "Nómina Tarjeta")
    to the ordered list of required doc keys. Configurable per tenant
    via `tenant_pipelines.definition.docs_per_plan` JSONB.

    Returns None when no plan is assigned (we don't know what to ask
    yet) OR when all required docs have been received (papelería
    completa).
    """
    if plan_credito is None:
        return None
    # Find which plan label this enum maps to (depends on tipo_credito).
    # In practice the runner calls this with the resolved plan label
    # from extracted.tipo_credito → docs_per_plan lookup is by label.
    # For simplicity we accept the label dict and let the runner pick.
    # NB: docs_per_plan is keyed by tipo_credito.value, not plan_credito.
    # If the caller passes a tipo_credito-keyed dict, just iterate.
    for plan_label, required_docs in docs_per_plan.items():
        if not _plan_label_matches(plan_label, plan_credito, extracted):
            continue
        for doc in required_docs:
            if not getattr(extracted, f"docs_{doc}", False):
                return doc
        return None
    return None


def _plan_label_matches(
    plan_label: str,
    plan_credito: PlanCredito,
    extracted: ExtractedFields,
) -> bool:
    """Plans are identified by tipo_credito (5 labels), not plan_credito
    percentage (3 labels). The label match uses tipo_credito if set;
    otherwise we can't disambiguate."""
    if extracted.tipo_credito is None:
        return False
    return plan_label == extracted.tipo_credito.value
```

**Step 5: Tests pasan (green)**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/state_machine/test_derived.py -v
```

Expected: 11 PASS.

Note: si tests fallan porque `next_pending_doc` requiere `tipo_credito` además de `plan_credito`, **agregar `tipo_credito=TipoCredito.NOMINA_TARJETA`** etc. en los `ExtractedFields(...)` de los tests de `next_pending_doc`. La función necesita ambos para resolver el plan_label correcto.

**Step 6: Commit**

```bash
git add core/atendia/contracts/flow_mode.py core/atendia/state_machine/derived.py core/tests/state_machine/test_derived.py
git commit -m "feat(state): FlowMode enum + funnel_stage/next_pending_doc derived helpers"
```

---

## Task 4: `HandoffSummary` Pydantic contract

**Files:**
- Create: `core/atendia/contracts/handoff_summary.py`
- Test: `core/tests/contracts/test_handoff_summary.py`

**Step 1: Test**

```python
"""HandoffSummary persisted in human_handoffs.payload JSONB.

Frontend (Phase 4) and human agents read this to understand context
before responding. Eight reasons covering all v1 escalation triggers.
"""
import pytest
from pydantic import ValidationError

from atendia.contracts.handoff_summary import HandoffReason, HandoffSummary


def test_handoff_reasons_match_v1_triggers() -> None:
    """Los 6 motivos del v1 prompt + outside_24h + composer_failed."""
    expected = {
        "outside_24h_window",
        "composer_failed",
        "obstacle_no_solution",
        "user_signaled_papeleria_completa",
        "papeleria_completa_form_pending",
        "antiguedad_lt_6m",
    }
    actual = {r.value for r in HandoffReason}
    assert expected == actual


def test_handoff_summary_minimal() -> None:
    """Solo reason y last_inbound_message son requeridos."""
    h = HandoffSummary(
        reason=HandoffReason.ANTIGUEDAD_LT_6M,
        last_inbound_message="tengo 3 meses",
        suggested_next_action="Esperar a que cumpla 6 meses",
        funnel_stage="plan",
        docs_recibidos=[],
        docs_pendientes=[],
    )
    assert h.reason == HandoffReason.ANTIGUEDAD_LT_6M


def test_handoff_summary_round_trip_json() -> None:
    """JSONB serialization safe."""
    h = HandoffSummary(
        reason=HandoffReason.PAPELERIA_COMPLETA_FORM_PENDING,
        nombre="Juan",
        modelo_moto="Adventure 150 CC",
        plan_credito="10%",
        enganche_estimado="$3,140",
        docs_recibidos=["ine", "comprobante", "estados_de_cuenta", "nomina"],
        docs_pendientes=[],
        last_inbound_message="ya los mandé todos",
        suggested_next_action="Visita domicilio/trabajo",
        funnel_stage="close",
    )
    raw = h.model_dump(mode="json")
    rebuilt = HandoffSummary.model_validate(raw)
    assert rebuilt.reason == HandoffReason.PAPELERIA_COMPLETA_FORM_PENDING
    assert rebuilt.docs_recibidos == ["ine", "comprobante", "estados_de_cuenta", "nomina"]
```

**Step 2: Verificar fallo + Step 3: Implementar**

Crear `core/atendia/contracts/handoff_summary.py`:

```python
"""Structured payload for human_handoffs.payload JSONB (Phase 3c.2).

V1 prompt requires "Before assigning to @Francisco Esparza in ANY
scenario, ALWAYS add internal comment". This contract makes that
comment a typed payload instead of free text.
"""
from enum import Enum

from pydantic import BaseModel


class HandoffReason(str, Enum):
    """Por qué se escaló a humano."""

    OUTSIDE_24H_WINDOW = "outside_24h_window"
    COMPOSER_FAILED = "composer_failed"
    OBSTACLE_NO_SOLUTION = "obstacle_no_solution"
    USER_SIGNALED_PAPELERIA_COMPLETA = "user_signaled_papeleria_completa"
    PAPELERIA_COMPLETA_FORM_PENDING = "papeleria_completa_form_pending"
    ANTIGUEDAD_LT_6M = "antiguedad_lt_6m"


class HandoffSummary(BaseModel):
    """Pre-formatted context for the human agent.

    Persisted in human_handoffs.payload (JSONB column already exists
    from Phase 1). Frontend (Phase 4) renders this verbatim.
    """

    reason: HandoffReason
    nombre: str | None = None
    modelo_moto: str | None = None
    plan_credito: str | None = None
    enganche_estimado: str | None = None
    docs_recibidos: list[str] = []
    docs_pendientes: list[str] = []
    last_inbound_message: str
    suggested_next_action: str
    funnel_stage: str
    cita_dia: str | None = None
```

**Step 4: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/contracts/test_handoff_summary.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add core/atendia/contracts/handoff_summary.py core/tests/contracts/test_handoff_summary.py
git commit -m "feat(contracts): HandoffSummary Pydantic for human_handoffs.payload"
```

---

## Task 5: `Attachment` en `Message` + `VisionResult` contract

**Files:**
- Modify: `core/atendia/contracts/message.py`
- Create: `core/atendia/contracts/vision_result.py`
- Test: `core/tests/contracts/test_message_attachments.py`
- Test: `core/tests/contracts/test_vision_result.py`

**Step 1: Tests (Message attachments)**

Crear `core/tests/contracts/test_message_attachments.py`:

```python
"""Phase 3c.2 extension: Message can carry image/PDF attachments
from Meta Cloud API. The webhook fetches the URL from Meta Graph
API; the runner passes attachments to Vision."""
from datetime import UTC, datetime
from uuid import uuid4

from atendia.contracts.message import Attachment, Message, MessageDirection


def test_attachment_has_required_fields() -> None:
    a = Attachment(
        media_id="MEDIA_123",
        mime_type="image/jpeg",
        url="https://lookaside.fbsbx.com/whatsapp_business/...",
    )
    assert a.media_id == "MEDIA_123"
    assert a.mime_type.startswith("image/")


def test_message_attachments_default_empty() -> None:
    """Backward compat — text-only messages have no attachments."""
    m = Message(
        id=str(uuid4()),
        conversation_id=str(uuid4()),
        tenant_id=str(uuid4()),
        direction=MessageDirection.INBOUND,
        text="hola",
        sent_at=datetime.now(UTC),
    )
    assert m.attachments == []


def test_message_with_image_attachment() -> None:
    m = Message(
        id=str(uuid4()),
        conversation_id=str(uuid4()),
        tenant_id=str(uuid4()),
        direction=MessageDirection.INBOUND,
        text="aquí va mi INE",
        sent_at=datetime.now(UTC),
        attachments=[Attachment(
            media_id="WAID-456",
            mime_type="image/jpeg",
            url="https://...",
        )],
    )
    assert len(m.attachments) == 1
    assert m.attachments[0].media_id == "WAID-456"
```

**Step 2: Tests (VisionResult)**

Crear `core/tests/contracts/test_vision_result.py`:

```python
"""VisionResult — output del classifier de imágenes.

Sin sesgo: el clasificador NO recibe `expected_doc`; solo categoriza
en términos absolutos. La decisión "matchea lo que esperabamos" es
del runner.
"""
import pytest
from pydantic import ValidationError

from atendia.contracts.vision_result import VisionCategory, VisionResult


def test_vision_categories_cover_v1_doc_types() -> None:
    """Categorías esperadas cubren los 7 docs del v1 + moto + unrelated."""
    expected = {
        "ine", "comprobante", "recibo_nomina", "estado_cuenta",
        "constancia_sat", "factura", "imss",
        "moto", "unrelated",
    }
    actual = {c.value for c in VisionCategory}
    assert expected == actual


def test_vision_result_basic() -> None:
    r = VisionResult(category=VisionCategory.INE, confidence=0.92, metadata={})
    assert r.category == VisionCategory.INE


def test_vision_result_metadata_can_be_anything() -> None:
    """metadata es free-form dict (e.g., ambos_lados=True para INE)."""
    r = VisionResult(
        category=VisionCategory.INE,
        confidence=0.95,
        metadata={"ambos_lados": True, "legible": True},
    )
    assert r.metadata["ambos_lados"] is True


def test_vision_result_confidence_must_be_in_range() -> None:
    """confidence ∈ [0, 1]."""
    with pytest.raises(ValidationError):
        VisionResult(category=VisionCategory.MOTO, confidence=1.5, metadata={})
    with pytest.raises(ValidationError):
        VisionResult(category=VisionCategory.MOTO, confidence=-0.1, metadata={})
```

**Step 3: Implementar `Attachment` en `message.py`**

Edit `core/atendia/contracts/message.py` — agregar antes del `class Message`:

```python
class Attachment(BaseModel):
    """Adjunto de mensaje (Meta Cloud API: image/PDF/audio).

    `url` puede ser temporal (Meta lookaside, 1h TTL) o permanente
    (storage propio post-Phase 3d). El runner pasa el URL a Vision.
    """

    media_id: str
    mime_type: str
    url: str
    caption: str | None = None
```

Y agregar al `class Message`:

```python
    attachments: list[Attachment] = []
```

**Step 4: Implementar `VisionResult`**

Crear `core/atendia/contracts/vision_result.py`:

```python
"""Output of OpenAI Vision classifier (Phase 3c.2).

Clasificación absoluta — el clasificador no recibe contexto de qué
doc esperabamos (sin confirmation bias). El runner compara
result.category contra next_pending_doc() para decidir el flujo.
"""
from enum import Enum

from pydantic import BaseModel, Field


class VisionCategory(str, Enum):
    """Categorías que el classifier puede asignar.

    Las primeras 7 son tipos de doc del v1 prompt; "moto" y
    "unrelated" capturan los casos donde el cliente mandó algo
    fuera del flujo de papelería.
    """

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
    """Resultado del classifier de imágenes.

    `metadata` es libre porque cada categoría tiene atributos
    distintos (INE: ambos_lados, comprobante: fecha_dentro_60_dias, etc.).
    """

    category: VisionCategory
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict
```

**Step 5: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/contracts/test_message_attachments.py tests/contracts/test_vision_result.py -v
```

Expected: 7 PASS combinados.

**Step 6: Verificar regresión 3c.1 sigue verde**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/contracts -q
```

Expected: ~50 passed. (Pydantic backward compat: `attachments=[]` default no rompe construcciones existentes de Message.)

**Step 7: Commit**

```bash
git add core/atendia/contracts/message.py core/atendia/contracts/vision_result.py \
        core/tests/contracts/test_message_attachments.py core/tests/contracts/test_vision_result.py
git commit -m "feat(contracts): Attachment in Message + VisionResult for Phase 3c.2"
```

---

# Bloque B — Vision API tooling

## Task 6: `vision.py` wrapper — `classify_image()`

**Files:**
- Create: `core/atendia/tools/vision.py`
- Test (en T8): `core/tests/tools/test_vision.py`

**Step 1: Implementar `vision.py`**

Crear `core/atendia/tools/vision.py`:

```python
"""OpenAI Vision API wrapper (Phase 3c.2).

Clasifica imágenes en una de 9 categorías (7 docs + moto + unrelated)
para DOC MODE. Análogo a tools/embeddings.py — cost tracking
end-to-end, structured outputs (JSON schema) para determinismo.

Sin sesgo de `expected_doc`: clasificación absoluta.
"""
import json
import time
from decimal import Decimal

from openai import AsyncOpenAI

from atendia.contracts.vision_result import VisionCategory, VisionResult

# gpt-4o pricing as of 2026-05:
# - $2.50 per 1M input tokens (text + image)
# - $10.00 per 1M output tokens
VISION_PRICE_PER_1M_INPUT_TOKENS: Decimal = Decimal("2.50")
VISION_PRICE_PER_1M_OUTPUT_TOKENS: Decimal = Decimal("10.00")
DEFAULT_VISION_MODEL: str = "gpt-4o"


_VISION_JSON_SCHEMA = {
    "name": "vision_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": [c.value for c in VisionCategory],
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "metadata": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ambos_lados": {"type": "boolean"},
                    "legible": {"type": "boolean"},
                    "fecha_iso": {"type": ["string", "null"]},
                    "institucion": {"type": ["string", "null"]},
                    "modelo": {"type": ["string", "null"]},
                    "notas": {"type": ["string", "null"]},
                },
                "required": ["ambos_lados", "legible", "fecha_iso",
                             "institucion", "modelo", "notas"],
            },
        },
        "required": ["category", "confidence", "metadata"],
        "additionalProperties": False,
    },
}


_SYSTEM_PROMPT = """\
Eres un clasificador de imágenes para una concesionaria de motocicletas
en México. Recibes una imagen y devuelves JSON con tres campos:

  - category: una de [ine, comprobante, recibo_nomina, estado_cuenta,
              constancia_sat, factura, imss, moto, unrelated]
  - confidence: tu certeza en [0.0, 1.0]
  - metadata: dict con los siguientes campos (siempre todos, null si no aplica):
      * ambos_lados (bool): para INE, true si se ven ambos lados
      * legible (bool): true si el texto principal se lee con claridad
      * fecha_iso (str|null): fecha visible en formato ISO si aplica (recibos, comprobantes)
      * institucion (str|null): banco / SAT / IMSS / proveedor de servicio si aplica
      * modelo (str|null): modelo de moto si category == moto
      * notas (str|null): observación libre corta

Reglas:
- Sé objetivo: clasifica lo que VES en la imagen, no lo que crees que el usuario quiso mandar.
- "ine" solo si claramente es una credencial INE (México). Si es licencia o pasaporte → "unrelated".
- "comprobante" para recibos de luz/agua/gas/internet con dirección visible.
- "moto" para foto de motocicleta (no scooter eléctrico ni bici).
- "unrelated" para selfies, screenshots, paisajes, comida, cualquier otra cosa.
- confidence < 0.5 si la imagen está borrosa, oscura o muy alejada.
"""


async def classify_image(
    *,
    client: AsyncOpenAI,
    image_url: str,
    model: str = DEFAULT_VISION_MODEL,
) -> tuple[VisionResult, int, int, Decimal, int]:
    """Classify a single image.

    Returns (result, tokens_in, tokens_out, cost_usd, latency_ms).
    """
    started = time.perf_counter()
    resp = await client.chat.completions.create(  # type: ignore[call-overload]
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Clasifica esta imagen."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
        response_format={"type": "json_schema", "json_schema": _VISION_JSON_SCHEMA},
        temperature=0,
    )
    raw = json.loads(resp.choices[0].message.content)
    result = VisionResult.model_validate(raw)
    tokens_in = resp.usage.prompt_tokens
    tokens_out = resp.usage.completion_tokens
    cost = _compute_cost(tokens_in, tokens_out)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return result, tokens_in, tokens_out, cost, latency_ms


def _compute_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """gpt-4o vision pricing: $2.50/1M input + $10.00/1M output, quantized."""
    in_cost = Decimal(tokens_in) * VISION_PRICE_PER_1M_INPUT_TOKENS / Decimal("1000000")
    out_cost = Decimal(tokens_out) * VISION_PRICE_PER_1M_OUTPUT_TOKENS / Decimal("1000000")
    return (in_cost + out_cost).quantize(Decimal("0.000001"))
```

**Step 2: Smoke import**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run python -c "from atendia.tools.vision import classify_image, VISION_PRICE_PER_1M_INPUT_TOKENS; print('vision module ok', VISION_PRICE_PER_1M_INPUT_TOKENS)"
```

Expected: `vision module ok 2.50`.

**Step 3: Commit (sin tests todavía — vienen en T8)**

```bash
git add core/atendia/tools/vision.py
git commit -m "feat(tools): OpenAI Vision wrapper for image classification"
```

---

## Task 7: `image_classifier.py` (skip — la lógica vive en `vision.py`)

**Skip rationale:** Originalmente diseñé `image_classifier.py` separado del wrapper. Pero T6 ya consolida la clasificación + el wrapper en un solo módulo (`vision.py`) — un solo entry point `classify_image()`. La separación adicional sería YAGNI.

Marca esta tarea como **completada/saltada** sin commit.

---

## Task 8: Tests del wrapper Vision (respx mocks)

**Files:**
- Create: `core/tests/tools/test_vision.py`

**Step 1: Tests con respx**

```python
"""Tests for the OpenAI Vision wrapper.

Mock-based — live calls happen in T9 (gated by RUN_LIVE_LLM_TESTS).
"""
from decimal import Decimal

import pytest
import respx
from httpx import Response
from openai import AsyncOpenAI

from atendia.contracts.vision_result import VisionCategory
from atendia.tools.vision import (
    VISION_PRICE_PER_1M_INPUT_TOKENS,
    VISION_PRICE_PER_1M_OUTPUT_TOKENS,
    classify_image,
)


def _ok_vision_response(
    category: str = "ine",
    confidence: float = 0.92,
    tokens_in: int = 1500,
    tokens_out: int = 80,
    metadata: dict | None = None,
) -> Response:
    md = metadata if metadata is not None else {
        "ambos_lados": True, "legible": True,
        "fecha_iso": None, "institucion": None,
        "modelo": None, "notas": None,
    }
    return Response(
        200,
        json={
            "id": "chatcmpl-vision",
            "object": "chat.completion",
            "model": "gpt-4o-2024-08-06",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"category":"' + category +
                               '","confidence":' + str(confidence) +
                               ',"metadata":' + str(md).replace("'", '"').replace("True", "true").replace("False", "false").replace("None", "null") + "}",
                },
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
async def test_classify_image_returns_vision_result() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(category="ine", confidence=0.92),
    )
    client = AsyncOpenAI(api_key="sk-test")
    result, tin, tout, cost, latency = await classify_image(
        client=client, image_url="https://example.com/ine.jpg",
    )
    assert result.category == VisionCategory.INE
    assert result.confidence == pytest.approx(0.92)
    assert tin == 1500
    assert tout == 80
    assert latency >= 0


@respx.mock
async def test_classify_image_cost_calculation() -> None:
    """Costo = (1500 * 2.50/1M) + (80 * 10.00/1M) = $0.0038 + $0.0008 = $0.004550 (rounded)."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(tokens_in=1500, tokens_out=80),
    )
    client = AsyncOpenAI(api_key="sk-test")
    _, _, _, cost, _ = await classify_image(
        client=client, image_url="https://example.com/x.jpg",
    )
    expected = (
        Decimal(1500) * VISION_PRICE_PER_1M_INPUT_TOKENS / Decimal("1000000") +
        Decimal(80) * VISION_PRICE_PER_1M_OUTPUT_TOKENS / Decimal("1000000")
    ).quantize(Decimal("0.000001"))
    assert cost == expected


@respx.mock
async def test_classify_image_unrelated_category() -> None:
    """Selfies o screenshots → category="unrelated"."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(category="unrelated", confidence=0.97),
    )
    client = AsyncOpenAI(api_key="sk-test")
    result, _, _, _, _ = await classify_image(
        client=client, image_url="https://example.com/selfie.jpg",
    )
    assert result.category == VisionCategory.UNRELATED


@respx.mock
async def test_classify_image_metadata_passed_through() -> None:
    md = {"ambos_lados": True, "legible": True, "fecha_iso": "2025-12-15",
          "institucion": "CFE", "modelo": None, "notas": "recibo de luz"}
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(category="comprobante", metadata=md),
    )
    client = AsyncOpenAI(api_key="sk-test")
    result, _, _, _, _ = await classify_image(
        client=client, image_url="https://example.com/recibo.jpg",
    )
    assert result.category == VisionCategory.COMPROBANTE
    assert result.metadata["fecha_iso"] == "2025-12-15"
    assert result.metadata["institucion"] == "CFE"


def test_pricing_constants() -> None:
    """Pin pricing constants — fail loudly if upstream changes."""
    assert VISION_PRICE_PER_1M_INPUT_TOKENS == Decimal("2.50")
    assert VISION_PRICE_PER_1M_OUTPUT_TOKENS == Decimal("10.00")
```

**Step 2: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_vision.py -v
```

Expected: 5 PASS.

**Step 3: Commit**

```bash
git add core/tests/tools/test_vision.py
git commit -m "test(tools): respx-mock tests for Vision API wrapper (5 tests)"
```

---

## Task 9: Live test for `classify_image` (RUN_LIVE_LLM_TESTS gated)

**Files:**
- Create: `core/tests/tools/test_vision_live.py`
- Need image fixtures to test with — usar **URLs públicas estables** (no commiteamos imágenes al repo).

**Step 1: Identificar URLs estables**

URLs sugeridas (reemplazar si no están vigentes):
- INE de prueba pública: `https://www.gob.mx/cms/uploads/article/main_image/137254/ife_ine.jpg` (o cualquier muestra pública del INE)
- Foto de moto: una imagen estable del catálogo de Dinamo o de Wikipedia (`https://upload.wikimedia.org/.../honda.jpg`)
- Selfie/unrelated: una imagen genérica abierta

**Si las URLs no son estables**, alternativa: usar **base64 inline** con una imagen embebida. OpenAI Vision acepta `data:image/jpeg;base64,...` en `image_url.url`.

**Step 2: Test gated**

```python
"""Live OpenAI Vision tests — gated by RUN_LIVE_LLM_TESTS=1.

Costo ~$0.005 por test (3 tests = ~$0.015 por corrida completa).
"""
import os

import pytest

from atendia.config import get_settings
from atendia.contracts.vision_result import VisionCategory
from atendia.tools.vision import classify_image


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI Vision calls",
)


_INE_TEST_URL = "https://www.gob.mx/cms/uploads/article/main_image/137254/ife_ine.jpg"
_MOTO_TEST_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/2009_Honda_PCX_125_white.jpg/640px-2009_Honda_PCX_125_white.jpg"
_UNRELATED_TEST_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/640px-PNG_transparency_demonstration_1.png"


def _api_key() -> str:
    api_key = get_settings().openai_api_key
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY"
    return api_key


@pytest.mark.asyncio
async def test_live_classify_ine_public_image() -> None:
    """Imagen pública de INE → category=INE con confidence alta."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=_api_key())
    result, _, _, cost, _ = await classify_image(
        client=client, image_url=_INE_TEST_URL,
    )
    assert result.category == VisionCategory.INE
    assert result.confidence > 0.5
    assert cost > 0


@pytest.mark.asyncio
async def test_live_classify_moto_image() -> None:
    """Foto de moto → category=MOTO."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=_api_key())
    result, _, _, _, _ = await classify_image(
        client=client, image_url=_MOTO_TEST_URL,
    )
    assert result.category == VisionCategory.MOTO


@pytest.mark.asyncio
async def test_live_classify_unrelated_image() -> None:
    """Imagen abstracta/decorativa → category=UNRELATED."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=_api_key())
    result, _, _, _, _ = await classify_image(
        client=client, image_url=_UNRELATED_TEST_URL,
    )
    assert result.category == VisionCategory.UNRELATED
```

**Step 3: Run gated**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  RUN_LIVE_LLM_TESTS=1 uv run pytest tests/tools/test_vision_live.py -v
```

Expected: 3 PASS. **Si falla por URLs caducas**, actualizar URLs y re-correr. Si gpt-4o clasifica una imagen ambigua de forma diferente, ajustar la URL o relajar el assert (e.g., aceptar UNRELATED como segundo válido para algo abstracto).

**Step 4: Commit**

```bash
git add core/tests/tools/test_vision_live.py
git commit -m "test(tools): live Vision tests gated by RUN_LIVE_LLM_TESTS=1"
```

---

# Bloque C — Router determinístico

## Task 10: `flow_router.py` con `pick_flow_mode()` + trigger types

**Files:**
- Create: `core/atendia/runner/flow_router.py`
- Test (en T13): `core/tests/runner/test_flow_router.py`

**Step 1: Implementación inicial (sin tests todavía — vienen en T13)**

Crear `core/atendia/runner/flow_router.py`:

```python
"""Deterministic flow router (Phase 3c.2).

Cada turno, evalúa una lista de FlowModeRule del JSONB del pipeline
y devuelve el FlowMode correspondiente. Primer match gana. La regla
'always' debe ser la última (fallback SUPPORT).

NO LLM call — es matching de keywords + state. Costo: $0, latencia: <1ms.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atendia.contracts.extracted_fields import ExtractedFields
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.vision_result import VisionResult


class HasAttachmentTrigger(BaseModel):
    type: Literal["has_attachment"] = "has_attachment"


class KeywordInTextTrigger(BaseModel):
    type: Literal["keyword_in_text"] = "keyword_in_text"
    list: list[str]


class FieldMissingTrigger(BaseModel):
    type: Literal["field_missing"] = "field_missing"
    field: str


class FieldPresentTrigger(BaseModel):
    type: Literal["field_present"] = "field_present"
    field: str


class FieldPresentAndIntentTrigger(BaseModel):
    type: Literal["field_present_and_intent"] = "field_present_and_intent"
    field: str
    intents: list[str]


class IntentIsTrigger(BaseModel):
    type: Literal["intent_is"] = "intent_is"
    intents: list[str]


class PendingConfirmationTrigger(BaseModel):
    type: Literal["pending_confirmation"] = "pending_confirmation"


class AlwaysTrigger(BaseModel):
    type: Literal["always"] = "always"


Trigger = (
    HasAttachmentTrigger
    | KeywordInTextTrigger
    | FieldMissingTrigger
    | FieldPresentTrigger
    | FieldPresentAndIntentTrigger
    | IntentIsTrigger
    | PendingConfirmationTrigger
    | AlwaysTrigger
)


class FlowModeRule(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    trigger: Trigger = Field(discriminator="type")
    mode: FlowMode


def pick_flow_mode(
    *,
    rules: list[FlowModeRule],
    extracted: ExtractedFields,
    nlu: NLUResult,
    vision: VisionResult | None,
    inbound_text: str,
    pending_confirmation: str | None,
) -> FlowMode:
    """Return the first FlowMode whose rule matches.

    rules MUST end with an `AlwaysTrigger` rule, else this raises.
    """
    normalized = _normalize_for_router(inbound_text)
    for rule in rules:
        if _matches(rule.trigger, extracted, nlu, vision, normalized, pending_confirmation):
            return rule.mode
    raise RuntimeError("flow_mode_rules MUST end with an `always` fallback rule")


def _matches(
    trigger: Trigger,
    extracted: ExtractedFields,
    nlu: NLUResult,
    vision: VisionResult | None,
    normalized_text: str,
    pending_confirmation: str | None,
) -> bool:
    if isinstance(trigger, HasAttachmentTrigger):
        return vision is not None
    if isinstance(trigger, KeywordInTextTrigger):
        return any(_normalize_for_router(kw) in normalized_text for kw in trigger.list)
    if isinstance(trigger, FieldMissingTrigger):
        return _field_value(extracted, trigger.field) in (None, False, "", 0)
    if isinstance(trigger, FieldPresentTrigger):
        return _field_value(extracted, trigger.field) not in (None, False, "", 0)
    if isinstance(trigger, FieldPresentAndIntentTrigger):
        present = _field_value(extracted, trigger.field) not in (None, False, "", 0)
        return present and nlu.intent.value in trigger.intents
    if isinstance(trigger, IntentIsTrigger):
        return nlu.intent.value in trigger.intents
    if isinstance(trigger, PendingConfirmationTrigger):
        return pending_confirmation is not None and pending_confirmation != ""
    if isinstance(trigger, AlwaysTrigger):
        return True
    return False  # unreachable; defensive


def _field_value(extracted: ExtractedFields, name: str) -> Any:
    """Read field from ExtractedFields by name; return None if missing."""
    return getattr(extracted, name, None)


def _normalize_for_router(text: str) -> str:
    """Lowercase + strip accents. Used ONLY for router keyword
    comparison. NLU and Composer receive original text."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))
```

**Step 2: Smoke import**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run python -c "from atendia.runner.flow_router import pick_flow_mode, FlowModeRule, AlwaysTrigger; print('flow_router ok')"
```

Expected: `flow_router ok`.

**Step 3: Commit (módulo solo, tests en T13)**

```bash
git add core/atendia/runner/flow_router.py
git commit -m "feat(runner): flow_router with deterministic pick_flow_mode + 8 trigger types"
```

---

## Task 11: `normalize_for_router` helper (skip — ya en T10)

**Skip rationale:** la función `_normalize_for_router` ya está implementada y testeada implícitamente vía los tests de `pick_flow_mode` en T13. Si quieres extraerla a un módulo separado para reusar, hazlo en T13 cuando los tests del router descubran el patrón. Hoy es premature.

Sin commit.

---

## Task 12: (Vacío — fusionado con T13)

Sin commit.

---

## Task 13: Tests del router determinístico

**Files:**
- Create: `core/tests/runner/test_flow_router.py`

**Step 1: Tests por cada trigger type**

```python
"""Tests for the deterministic flow router (Phase 3c.2).

Cubre: cada uno de los 8 trigger types, normalización, orden de
precedencia, error si no hay fallback always.
"""
import pytest

from atendia.contracts.extracted_fields import (
    ExtractedFields,
    PlanCredito,
    TipoCredito,
)
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.vision_result import VisionCategory, VisionResult
from atendia.runner.flow_router import (
    AlwaysTrigger,
    FieldMissingTrigger,
    FieldPresentAndIntentTrigger,
    FieldPresentTrigger,
    FlowModeRule,
    HasAttachmentTrigger,
    IntentIsTrigger,
    KeywordInTextTrigger,
    PendingConfirmationTrigger,
    _normalize_for_router,
    pick_flow_mode,
)


def _nlu(intent: Intent = Intent.UNCLEAR) -> NLUResult:
    return NLUResult(
        intent=intent, entities={}, sentiment=Sentiment.NEUTRAL,
        confidence=0.9, ambiguities=[],
    )


def _vision(category: VisionCategory = VisionCategory.INE) -> VisionResult:
    return VisionResult(category=category, confidence=0.9, metadata={})


# ---- Single-trigger tests ----------------------------------------------

def test_has_attachment_triggers_doc() -> None:
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=_vision(), inbound_text="aquí va",
        pending_confirmation=None,
    )
    assert mode == FlowMode.DOC


def test_no_attachment_skips_doc_rule() -> None:
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="hola",
        pending_confirmation=None,
    )
    assert mode == FlowMode.SUPPORT


def test_keyword_match_with_accents_stripped() -> None:
    """'mañana' en keyword list debe matchear 'manana' en input (sin tilde)."""
    rules = [
        FlowModeRule(id="r1",
                     trigger=KeywordInTextTrigger(list=["mañana", "luego"]),
                     mode=FlowMode.OBSTACLE),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="te lo paso manana",
        pending_confirmation=None,
    )
    assert mode == FlowMode.OBSTACLE


def test_keyword_match_case_insensitive() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=KeywordInTextTrigger(list=["gracias"]),
                     mode=FlowMode.RETENTION),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="GRACIAS por la info",
        pending_confirmation=None,
    )
    assert mode == FlowMode.RETENTION


def test_field_missing_triggers_when_field_is_none() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=FieldMissingTrigger(field="plan_credito"),
                     mode=FlowMode.PLAN),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode == FlowMode.PLAN


def test_field_missing_skipped_when_field_present() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=FieldMissingTrigger(field="plan_credito"),
                     mode=FlowMode.PLAN),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    extracted = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    mode = pick_flow_mode(
        rules=rules, extracted=extracted,
        nlu=_nlu(), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode == FlowMode.SUPPORT


def test_field_present_and_intent_combined() -> None:
    """SALES requiere plan_credito set AND intent in [ask_price, buy]."""
    rules = [
        FlowModeRule(id="r1",
                     trigger=FieldPresentAndIntentTrigger(
                         field="plan_credito",
                         intents=["ask_price", "buy"]),
                     mode=FlowMode.SALES),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    extracted = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    # Caso 1: plan + ask_price → SALES
    mode1 = pick_flow_mode(
        rules=rules, extracted=extracted,
        nlu=_nlu(intent=Intent.ASK_PRICE), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode1 == FlowMode.SALES
    # Caso 2: plan pero intent unrelated → SUPPORT
    mode2 = pick_flow_mode(
        rules=rules, extracted=extracted,
        nlu=_nlu(intent=Intent.GREETING), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode2 == FlowMode.SUPPORT
    # Caso 3: sin plan, ask_price → SUPPORT
    mode3 = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(intent=Intent.ASK_PRICE), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode3 == FlowMode.SUPPORT


def test_pending_confirmation_trigger_for_binary_qa() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=PendingConfirmationTrigger(),
                     mode=FlowMode.PLAN),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="sí",
        pending_confirmation="is_nomina_tarjeta",
    )
    assert mode == FlowMode.PLAN


# ---- Precedence + safety -----------------------------------------------

def test_first_match_wins_over_later() -> None:
    """Doc rule first → DOC, even if KeywordInText would also match."""
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="r2",
                     trigger=KeywordInTextTrigger(list=["mañana"]),
                     mode=FlowMode.OBSTACLE),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=_vision(), inbound_text="te lo paso mañana",
        pending_confirmation=None,
    )
    assert mode == FlowMode.DOC


def test_missing_always_fallback_raises() -> None:
    """Defensive: si nadie matchea, raise."""
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
    ]
    with pytest.raises(RuntimeError, match="always"):
        pick_flow_mode(
            rules=rules, extracted=ExtractedFields(),
            nlu=_nlu(), vision=None, inbound_text="hola",
            pending_confirmation=None,
        )


# ---- Normalization helper ----------------------------------------------

def test_normalize_lowercases() -> None:
    assert _normalize_for_router("HOLA Mundo") == "hola mundo"


def test_normalize_strips_accents() -> None:
    assert _normalize_for_router("mañana") == "manana"
    assert _normalize_for_router("comprobante con ñ") == "comprobante con n"
```

**Step 2: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_flow_router.py -v
```

Expected: 12 PASS.

**Step 3: Commit**

```bash
git add core/tests/runner/test_flow_router.py
git commit -m "test(runner): comprehensive flow_router tests covering all 8 trigger types"
```

---

# Bloque D — Composer modes refactor

## Task 14: Update `SYSTEM_PROMPT_TEMPLATE` for `mode_guidance` + `brand_facts`

**Files:**
- Modify: `core/atendia/runner/composer_prompts.py`

**Step 1: Update template**

Editar `core/atendia/runner/composer_prompts.py`. El template actual hace referencia a `{{action_guidance}}` y `{{action_payload}}` (Phase 3c.1). Lo extendemos:

```python
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

Datos de la acción (action_payload — única fuente de verdad para precios,
respuestas y resultados; NUNCA uses números o nombres que no estén aquí):
{{action_payload}}

{{brand_facts_block}}

{{mode_guidance}}

{{output_instructions}}
"""
```

(Mantener compatibilidad: el bloque `brand_facts_block` puede estar vacío para modos que no lo necesiten.)

**Step 2: Helper `_render_brand_facts`**

Agregar:

```python
def _render_brand_facts(facts: dict | None) -> str:
    """Render brand_facts JSONB as a labeled block.

    Empty dict / None returns "" (block omitted from prompt).
    Used only by modes that need brand info (SUPPORT, DOC, CLOSE).
    """
    if not facts:
        return ""
    lines = [f"  - {k}: {v}" for k, v in facts.items()]
    return "Brand facts (info verificada del negocio):\n" + "\n".join(lines)
```

**Step 3: Update `build_composer_prompt`**

Pasar `brand_facts_block` al `render_template`:

```python
    needs_facts = input.flow_mode in {
        FlowMode.SUPPORT, FlowMode.DOC, FlowMode.PLAN, FlowMode.SALES,
    }
    brand_facts_block = (
        _render_brand_facts(input.brand_facts) if needs_facts else ""
    )

    system_content = render_template(
        SYSTEM_PROMPT_TEMPLATE,
        ...,
        brand_facts_block=brand_facts_block,
        ...,
    )
```

(`input.brand_facts` y `input.flow_mode` se agregan al `ComposerInput` en T16.)

**Step 4: Tests existentes (3c.1) deben seguir pasando**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_composer_prompts.py -v
```

Si los snapshots fallan: **es esperado** — el template cambió. Regeneraremos los fixtures en T17.

**Step 5: Commit (parcial — sin tests pasando aún)**

```bash
git add core/atendia/runner/composer_prompts.py
git commit -m "feat(composer): SYSTEM_PROMPT_TEMPLATE supports mode_guidance + brand_facts"
```

---

## Task 15: Replace `ACTION_GUIDANCE` with `MODE_PROMPTS` (6 modos)

**Files:**
- Modify: `core/atendia/runner/composer_prompts.py`

**Step 1: Borrar `ACTION_GUIDANCE` y su lógica**

En `composer_prompts.py`, **eliminar** el dict `ACTION_GUIDANCE` y todo el código que dependía de él para resolver acciones (Phase 3c.1).

**Step 2: Agregar `MODE_PROMPTS`**

```python
from atendia.contracts.flow_mode import FlowMode


MODE_PROMPTS: dict[FlowMode, str] = {
    FlowMode.PLAN: """\
Acción: PLAN MODE — calificar al cliente y asignar plan de crédito.

PASOS internos (ejecuta el primero que aplique según `extracted_data`):

PASO 0 — Si turn_number == 1 y antigüedad_meses está vacía:
  Mensaje fijo de hook (1-2 frases máximo):
  "Qué bueno que escribes. En Dínamo puedes arrancar con enganche
   desde $3,500 dependiendo de tu plan. ¿Cuánto tiempo llevas en
   tu empleo actual?"

PASO 1 — Si antigüedad_meses está vacía y NO es turn 1:
  Pregunta antigüedad: "Para ver qué plan te conviene, ¿cuánto
   llevas en tu empleo?"

PASO 2 — Si antigüedad_meses < 6:
  Mensaje de pausa: "Entendido, por el momento los planes para
   trabajadores menores a 6 meses están deshabilitados. Escríbeme
   cuando cumplas 6 meses y ese mismo día te armo tu plan."
  Marca este turno con suggested_handoff="antiguedad_lt_6m".

PASO 3 — Si antigüedad_meses >= 6 y tipo_credito vacío:
  Lista las opciones (1️⃣–5️⃣) y pide número:
  "1️⃣ Me depositan nómina en tarjeta
   2️⃣ Me pagan con recibos de nómina
   3️⃣ Soy pensionado
   4️⃣ Tengo negocio (SAT)
   5️⃣ Me pagan sin comprobantes
   Solo mándame el número."

PASO 4 — Si tipo_credito y plan_credito asignados:
  Confirma plan + pide INE como primer doc:
  "Perfecto, tu plan es {plan_credito} ({tipo_credito}). Para
   arrancar tu trámite, mándame primero tu INE por ambos lados,
   completa y bien iluminada."

DISAMBIGUATION (si el último mensaje del cliente fue ambiguo):
  - Cliente dijo "depósito"/"banco"/"estado de cuenta": pregunta
    "¿Te dan recibos de nómina? (sí/no)" — sí=Nómina Recibos,
    no=Sin Comprobantes.
  - "Efectivo": "¿Es con recibos o por fuera?" — con recibos=Nómina Recibos,
    por fuera=Sin Comprobantes.
  - "Negocio": "¿Está dado de alta en SAT?" — sí=Negocio SAT,
    no=Sin Comprobantes.
  En estos casos marca pending_confirmation_set con el campo apropiado.

PROHIBIDO:
- NO inventes precios. NO menciones modelos de moto en este modo
  (eso es SALES MODE).
- NO pidas más de un dato a la vez (un mensaje, una pregunta).
""",

    FlowMode.SALES: """\
Acción: SALES MODE — cotizar al cliente con datos REALES del catálogo.

action_payload contiene UNA de estas formas:
  - {status:"ok", name, price_lista_mxn, price_contado_mxn,
     planes_credito, ficha_tecnica}
  - {status:"no_data", hint}
  - {status:"objection", type:"caro"|"sin_buro"} (cuando el último
    mensaje fue una objeción detectada por el composer)

Si status='ok':
  Da el precio de contado en MXN (formato $32,900). Menciona el plan
  que corresponde al `plan_credito` del cliente (extracted_data):
  enganche, pago_quincenal, plazo. Cierra con:
    "Puedes liquidar antes sin penalización."
  Y termina con cierre comercial:
    "Si me mandas documentos hoy, la entregamos esta semana."

Si status='no_data':
  "¿Qué moto te interesa? Escríbeme el nombre exacto.
   Catálogo: {{brand_facts.catalog_url}}"

Si status='objection.caro' o 'objection.se_triplica':
  "Te entiendo. Pero míralo así: todos los días gastas en transporte
   y ese dinero se va. Con la moto pagas algo que es tuyo, lo usas
   diario y sigue teniendo valor. Además puedes liquidar cuando
   quieras. Calculadora: {{brand_facts.catalog_url}}"

Si status='objection.sin_buro':
  "Revisamos buró flexible hasta {{brand_facts.buro_max_amount}}.
   La mayoría de los que avanzan no tenían buró perfecto."

PROHIBIDO:
- NO INVENTES precios distintos a los del payload.
- NO menciones planes que no estén en planes_credito del payload.
- Máximo 2 mensajes (max_messages cap).
""",

    FlowMode.DOC: """\
Acción: DOC MODE — recibir, validar (vía Vision) y avanzar la papelería.

action_payload incluye:
  - vision_result: {category, confidence, metadata}
  - expected_doc: cuál doc esperabamos (next_pending_doc del estado)
  - pending_after: lista de docs que faltarían DESPUÉS de procesar éste

Lógica (ejecuta exactamente una rama):

1. vision_result.confidence < 0.6:
   "Esa imagen no la veo bien clara, ¿puedes mandarla en mejor calidad?"

2. vision_result.category == expected_doc (match esperado):
   Confirma con "[doc] ✅". Si pending_after no está vacío, pide el
   primero de pending_after. Si está vacío, anuncia papelería completa
   y manda link {{brand_facts.post_completion_form}}.

3. vision_result.category está en {ine, comprobante, recibo_nomina,
   estado_cuenta, constancia_sat, factura, imss} pero NO es expected_doc
   (cliente mandó otro doc legítimo fuera de orden):
   "[la_categoría_que_mandó] ✅. Aún necesito tu [expected_doc],
    ¿lo tienes a la mano?"
   Marca el doc recibido en extracted_data igual.

4. vision_result.category in {moto, unrelated}:
   "Recibí tu foto pero no es un documento que necesite ahorita.
    ¿Me mandas tu [expected_doc]? Era el siguiente paso."
   NO marques nada como recibido.

PROHIBIDO:
- NO inventes que recibiste un doc que no llegó.
- NO digas "INE recibida" si vision_result.category != "ine".
""",

    FlowMode.OBSTACLE: """\
Acción: OBSTACLE MODE — el cliente pospuso, identifica el blocker.

Primer turno en OBSTACLE:
  "Perfecto, ¿cuál es el que más te cuesta conseguir, el comprobante
   de domicilio o las nóminas?"

Si en turnos previos (history) el cliente ya identificó el blocker:

  COMPROBANTE:
    "El recibo de luz, agua, gas o internet funciona. ¿Tienes uno
     en casa o lo puedes descargar de la app?"
    Si dice que no tiene → marca suggested_handoff="obstacle_no_solution"
    + mensaje "Cuéntame en qué dirección vives y vemos qué opciones tienes."

  NÓMINAS:
    "¿Tu patrón te las da en papel o por correo? Puedes pedirlas a
     recursos humanos, es tu derecho."
    Si dice "tengo que pedirlas": "¿Cuándo crees que te las den?
    Así te marco ese día para que no se te olvide."
    + suggested_handoff="obstacle_no_solution"

Si el cliente dice "tengo SOLO algunos docs":
  "No hay problema, mándame la INE y lo que tengas ahorita y avanzamos.
   El resto lo pedimos después." (Acepta parciales para crear compromiso.)

PROHIBIDO:
- NO inventes procesos que no estén en este prompt.
""",

    FlowMode.RETENTION: """\
Acción: RETENTION MODE — el cliente dijo "gracias" pero no confirmó
desinterés. Intenta retener.

Mensaje fijo (parametrizar tono pero NO cambiar la idea):
  "Perfecto, para no dejarlo en el aire: normalmente cuando alguien
   dice 'gracias' es porque quiere revisarlo con calma o tiene una
   duda que no quiere dejar pasar. ¿Qué parte te gustaría aclarar
   o prefieres verlo después?"

Marca extracted_data.retention_attempt = true (el composer lo
registra en su output).
""",

    FlowMode.SUPPORT: """\
Acción: SUPPORT MODE — preguntas generales que no son SALES/PLAN/DOC.

action_payload puede incluir:
  - {matches: [{pregunta, respuesta, score}, ...]} (vino de lookup_faq)
  - {status: "no_data", ...}

Si matches NO está vacío:
  Usa la PRIMERA match (score más alto) como base de tu respuesta.
  Adapta al tono informal mexicano. NO inventes datos extra.
  Si la respuesta es una lista, enuméralala con bullets cortos.

Si status='no_data':
  Apóyate en brand_facts si el tema es:
    - "buró" → "Revisamos buró, flexible hasta {{brand_facts.buro_max_amount}}."
    - "enganche" → "10% nómina tarjeta, 15% recibos/SAT, 20% sin comprobantes."
    - "tiempos" → "Buró {{brand_facts.approval_time_hours}}h,
                   entrega {{brand_facts.delivery_time_days}} días."
    - "ubicación" → "{{brand_facts.address}}. Pregunta por {{brand_facts.human_agent_name}}."
    - "documentos" → "INE + comprobante <60 días. Lo demás depende de tu plan."

  Si nada de lo anterior aplica: redirige amable —
  "Déjame revisar y te confirmo en un momento."

Después de responder, si plan_credito NO está asignado, agrega al final
para regresar al funnel:
  "Y tú, ¿cómo recibes tu sueldo?"

PROHIBIDO:
- NO inventes información no presente en payload o brand_facts.
""",
}
```

**Step 2: Smoke verify**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run python -c "from atendia.runner.composer_prompts import MODE_PROMPTS; from atendia.contracts.flow_mode import FlowMode; print({k.value: len(v) for k,v in MODE_PROMPTS.items()})"
```

Expected: dict con los 6 modos y sus longitudes (cada uno ~200-400 palabras).

**Step 3: Commit**

```bash
git add core/atendia/runner/composer_prompts.py
git commit -m "feat(composer): replace ACTION_GUIDANCE with MODE_PROMPTS (6 mode-based prompts)"
```

---

## Task 16: Refactor `build_composer_prompt` for mode-based dispatch

**Files:**
- Modify: `core/atendia/runner/composer_prompts.py`
- Modify: `core/atendia/runner/composer_protocol.py`

**Step 1: Update `ComposerInput` schema**

Editar `core/atendia/runner/composer_protocol.py`. Agregar:

```python
class ComposerInput(BaseModel):
    # existing fields...

    # Phase 3c.2 additions:
    flow_mode: FlowMode  # decided by router this turn
    brand_facts: dict = {}  # tenant brand info, injected per mode
    vision_result: VisionResult | None = None
```

**Step 2: Update `build_composer_prompt`**

```python
def build_composer_prompt(input: ComposerInput) -> list[dict[str, str]]:
    """Build chat-completions message list for gpt-4o.

    Phase 3c.2 dispatches based on `flow_mode` instead of `action`.
    """
    mode_block = MODE_PROMPTS[input.flow_mode]

    needs_facts = input.flow_mode in {
        FlowMode.SUPPORT, FlowMode.DOC, FlowMode.PLAN, FlowMode.SALES,
    }
    brand_facts_block = (
        _render_brand_facts(input.brand_facts) if needs_facts else ""
    )

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
        action_payload=_render_action_payload(input.action_payload),
        brand_facts_block=brand_facts_block,
        mode_guidance=mode_block,
        output_instructions=output_instructions,
    )

    return [
        {"role": "system", "content": system_content},
        *_render_history(input.history, history_format=HISTORY_FORMAT),
    ]
```

**Step 3: Backward compatibility**

El campo `action` en `ComposerInput` se mantiene para **logging** en `turn_traces.composer_input` pero ya no se usa para resolver el prompt. Los callers deben empezar a pasar `flow_mode`.

**Step 4: Smoke**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run python -c "
from atendia.contracts.tone import Tone
from atendia.contracts.flow_mode import FlowMode
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput
m = build_composer_prompt(ComposerInput(
    action='greet', flow_mode=FlowMode.PLAN, current_stage='plan',
    tone=Tone(bot_name='Dinamo'),
))
print(m[0]['content'][:200])
"
```

Expected: imprime los primeros 200 chars del prompt PLAN.

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_prompts.py core/atendia/runner/composer_protocol.py
git commit -m "feat(composer): build_composer_prompt dispatches by flow_mode (Phase 3c.2)"
```

---

## Task 17: Snapshot fixtures para los 6 modos

**Files:**
- Create: `core/tests/fixtures/composer/mode_PLAN_state_initial.txt`
- Create: ...12 fixtures más (lista completa abajo)
- Modify: `core/tests/runner/test_composer_prompts.py`

**Step 1: Generate all fixtures script**

Crear un script `scripts/regen_mode_fixtures.py` (one-shot, no se commitea como production code; es una utilidad):

```python
"""Generate all mode snapshot fixtures.

Run once after MODE_PROMPTS changes:
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/regen_mode_fixtures.py
"""
from pathlib import Path

from atendia.contracts.extracted_fields import (
    ExtractedFields, PlanCredito, TipoCredito,
)
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput


_DINAMO_TONE = Tone(
    register="informal_mexicano", use_emojis="sparingly",
    max_words_per_message=40, bot_name="Dinamo",
    forbidden_phrases=["estimado cliente", "le saluda atentamente"],
    signature_phrases=["¡qué onda!", "te paso"],
)
_BRAND = {
    "catalog_url": "https://dinamomotos.com/catalogo.html",
    "address": "Benito Juárez 801, Centro Monterrey",
    "human_agent_name": "Francisco",
    "buro_max_amount": "$50 mil",
    "approval_time_hours": "24",
    "delivery_time_days": "3-7",
    "post_completion_form": "https://forms.gle/U1MEueL63vgftiuZ8",
}
_FIX_DIR = Path("tests/fixtures/composer")


def _write(name: str, msgs: list[dict[str, str]]) -> None:
    out = _FIX_DIR / f"{name}.txt"
    out.write_text(msgs[0]["content"], encoding="utf-8", newline="")
    print(f"wrote {out} ({len(msgs[0]['content'])} chars)")


def main() -> None:
    # PLAN MODE — 3 fixtures
    _write("mode_PLAN_state_initial",
        build_composer_prompt(ComposerInput(
            action="micro_cotizacion", flow_mode=FlowMode.PLAN,
            current_stage="plan",
            extracted_data={}, tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_PLAN_state_antiguedad_set",
        build_composer_prompt(ComposerInput(
            action="ask_tipo_credito", flow_mode=FlowMode.PLAN,
            current_stage="plan",
            extracted_data={"antigüedad_meses": "24"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_PLAN_state_plan_assigned",
        build_composer_prompt(ComposerInput(
            action="ask_doc_ine", flow_mode=FlowMode.PLAN,
            current_stage="plan",
            extracted_data={
                "antigüedad_meses": "24",
                "tipo_credito": "Nómina Tarjeta",
                "plan_credito": "10%",
            },
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))

    # SALES MODE — 3 fixtures
    _write("mode_SALES_state_quote_ok",
        build_composer_prompt(ComposerInput(
            action="quote", flow_mode=FlowMode.SALES,
            current_stage="sales",
            action_payload={
                "status": "ok",
                "sku": "adventure-elite-150-cc",
                "name": "Adventure Elite 150 CC",
                "category": "Motoneta",
                "price_lista_mxn": "31395",
                "price_contado_mxn": "29900",
                "planes_credito": {"plan_10": {"enganche": 3140,
                                                "pago_quincenal": 1247,
                                                "quincenas": 72}},
                "ficha_tecnica": {"motor_cc": 150},
            },
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_SALES_state_no_data",
        build_composer_prompt(ComposerInput(
            action="quote", flow_mode=FlowMode.SALES,
            current_stage="sales",
            action_payload={"status": "no_data",
                            "hint": "no catalog match for 'lambretta'"},
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_SALES_state_objection_caro",
        build_composer_prompt(ComposerInput(
            action="quote", flow_mode=FlowMode.SALES,
            current_stage="sales",
            action_payload={"status": "objection", "type": "caro"},
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))

    # DOC MODE — 3 fixtures
    _write("mode_DOC_state_match",
        build_composer_prompt(ComposerInput(
            action="confirm_doc", flow_mode=FlowMode.DOC,
            current_stage="doc",
            action_payload={
                "vision_result": {"category": "ine", "confidence": 0.95,
                                  "metadata": {"ambos_lados": True, "legible": True}},
                "expected_doc": "ine",
                "pending_after": ["comprobante", "estados_de_cuenta", "nomina"],
            },
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_DOC_state_unrelated_image",
        build_composer_prompt(ComposerInput(
            action="reject_unrelated", flow_mode=FlowMode.DOC,
            current_stage="doc",
            action_payload={
                "vision_result": {"category": "moto", "confidence": 0.92,
                                  "metadata": {"modelo": "Adventure 150"}},
                "expected_doc": "ine",
                "pending_after": [],  # nothing changes
            },
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_DOC_state_papeleria_completa",
        build_composer_prompt(ComposerInput(
            action="papeleria_completa", flow_mode=FlowMode.DOC,
            current_stage="doc",
            action_payload={
                "vision_result": {"category": "recibo_nomina", "confidence": 0.93,
                                  "metadata": {"fecha_iso": "2026-04-30"}},
                "expected_doc": "nomina",
                "pending_after": [],  # último doc requerido
            },
            extracted_data={
                "plan_credito": "10%", "modelo_moto": "Adventure",
                "docs_ine": "true", "docs_comprobante": "true",
                "docs_estados_de_cuenta": "true",
            },
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))

    # OBSTACLE, RETENTION, SUPPORT — 1-2 fixtures cada uno
    _write("mode_OBSTACLE_state_initial",
        build_composer_prompt(ComposerInput(
            action="address_obstacle", flow_mode=FlowMode.OBSTACLE,
            current_stage="plan",
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts={},
        )))
    _write("mode_RETENTION_state_initial",
        build_composer_prompt(ComposerInput(
            action="retention_pitch", flow_mode=FlowMode.RETENTION,
            current_stage="sales",
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE, brand_facts={},
        )))
    _write("mode_SUPPORT_state_buro_question",
        build_composer_prompt(ComposerInput(
            action="explain_topic", flow_mode=FlowMode.SUPPORT,
            current_stage="plan",
            action_payload={"status": "no_data", "hint": "no FAQ match"},
            extracted_data={},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_SUPPORT_state_faq_match",
        build_composer_prompt(ComposerInput(
            action="lookup_faq", flow_mode=FlowMode.SUPPORT,
            current_stage="plan",
            action_payload={
                "matches": [{
                    "pregunta": "¿Cuál es el tiempo de aprobación?",
                    "respuesta": "24 horas con documentación completa.",
                    "score": 0.93,
                }],
            },
            extracted_data={},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))


if __name__ == "__main__":
    main()
```

**Step 2: Run script**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/regen_mode_fixtures.py
```

Expected: 13 archivos en `tests/fixtures/composer/mode_*.txt`.

**Step 3: Snapshot tests**

Reemplazar el contenido de `core/tests/runner/test_composer_prompts.py` (o agregar al existente) con tests análogos al snapshot test que ya tenemos en 3c.1, uno por fixture:

```python
import pytest

# ... imports + _FIXTURES path como en 3c.1

@pytest.mark.parametrize("fixture_name,builder", [
    ("mode_PLAN_state_initial",
     lambda: build_composer_prompt(ComposerInput(
         action="micro_cotizacion", flow_mode=FlowMode.PLAN,
         current_stage="plan", extracted_data={},
         tone=_DINAMO_TONE, brand_facts=_BRAND,
     ))),
    ("mode_PLAN_state_antiguedad_set",
     lambda: build_composer_prompt(ComposerInput(
         action="ask_tipo_credito", flow_mode=FlowMode.PLAN,
         current_stage="plan",
         extracted_data={"antigüedad_meses": "24"},
         tone=_DINAMO_TONE, brand_facts=_BRAND,
     ))),
    # ... resto de los 13 ...
])
def test_mode_snapshot(fixture_name: str, builder) -> None:
    expected = (_FIXTURES / f"{fixture_name}.txt").read_text(encoding="utf-8")
    msgs = builder()
    assert msgs[0]["content"] == expected
```

**Step 4: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_composer_prompts.py -v
```

Expected: 13 PASS (más los previos no-mode tests que sigan vivos).

**Step 5: Commit**

```bash
git add core/tests/fixtures/composer/mode_*.txt \
        core/tests/runner/test_composer_prompts.py \
        core/scripts/regen_mode_fixtures.py
git commit -m "test(composer): 13 snapshot fixtures covering 6 modes × key states"
```

---

# Bloque E — Webhook + Meta media handling

## Task 18: Detect image attachments en Meta webhook + fetch URL

**Files:**
- Modify: `core/atendia/channels/meta_cloud_api.py` (or wherever payload parsing lives)
- Modify: `core/atendia/webhooks/meta_routes.py`
- Test: `core/tests/channels/test_meta_cloud_api_attachments.py`

**Step 1: Identificar el módulo donde vive parse_webhook**

```bash
grep -rn "def parse_webhook\|parse_inbound" core/atendia/channels/ | head
```

Encontrar la función que extrae el `text` del payload Meta. Vamos a extender para también extraer `attachments`.

**Step 2: Test (TDD red)**

```python
"""Phase 3c.2: webhook payload con image debe extraer Attachment."""
from atendia.channels.meta_cloud_api import parse_inbound_message


_PAYLOAD_WITH_IMAGE = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "WABA",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": "PID_X"},
                "messages": [{
                    "from": "5215555550999",
                    "id": "wamid.image_test",
                    "timestamp": "1714579200",
                    "type": "image",
                    "image": {
                        "id": "MEDIA_ABC",
                        "mime_type": "image/jpeg",
                        "sha256": "...",
                    },
                }],
            },
        }],
    }],
}


def test_parse_inbound_image_extracts_attachment() -> None:
    msg = parse_inbound_message(_PAYLOAD_WITH_IMAGE)
    assert msg.text == ""  # imagen sola, sin caption
    assert len(msg.attachments) == 1
    assert msg.attachments[0].media_id == "MEDIA_ABC"
    assert msg.attachments[0].mime_type == "image/jpeg"
    # url se rellena más tarde (T18 fetches from Meta API)
    assert msg.attachments[0].url == ""
```

**Step 3: Implementar extracción**

En `meta_cloud_api.py`, dentro de `parse_inbound_message` (o equivalente):

```python
def parse_inbound_message(payload: dict) -> Message:
    msg_node = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    msg_type = msg_node.get("type", "text")

    text = ""
    attachments: list[Attachment] = []

    if msg_type == "text":
        text = msg_node["text"]["body"]
    elif msg_type in {"image", "document", "audio", "video"}:
        media = msg_node[msg_type]
        text = msg_node.get(msg_type, {}).get("caption", "")
        attachments.append(Attachment(
            media_id=media["id"],
            mime_type=media["mime_type"],
            url="",  # se rellena en webhook handler tras fetch a Meta API
            caption=text or None,
        ))
    # ... otros tipos ignorados por ahora ...

    return Message(
        # ... existing fields ...
        text=text,
        attachments=attachments,
    )
```

**Step 4: Webhook handler — fetch URL desde Meta Graph API**

En `meta_routes.py`, después de parsear el mensaje, si tiene `attachments` con `url == ""`:

```python
if msg.attachments:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        for att in msg.attachments:
            r = await client.get(
                f"https://graph.facebook.com/{settings.meta_api_version}/{att.media_id}",
                headers={"Authorization": f"Bearer {settings.meta_access_token}"},
            )
            r.raise_for_status()
            att.url = r.json()["url"]
```

(Si `meta_api_version` o `meta_access_token` no están configurados, log warning y skip — graceful degradation en tests.)

**Step 5: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/channels/test_meta_cloud_api_attachments.py -v
```

Expected: 1 PASS.

**Step 6: Commit**

```bash
git add core/atendia/channels/meta_cloud_api.py core/atendia/webhooks/meta_routes.py \
        core/tests/channels/test_meta_cloud_api_attachments.py
git commit -m "feat(channels): parse image attachments from Meta webhook + fetch URL"
```

---

## Task 19: Pass attachments through al Message contract en runner

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`

**Step 1: Verify**

El `Message` ya tiene el campo `attachments` (T5). El runner solo necesita PASARLO. Si en el flujo actual del runner NO se construye el `Message` desde un payload (sino que se recibe ya construido), no hay cambio.

Si hay una construcción en algún punto donde se pierde, agregar `attachments=inbound.attachments`.

**Step 2: Smoke**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner -q
```

Expected: tests siguen verdes.

**Step 3: Commit (si no hubo cambios, skip esta tarea)**

```bash
# Si hubo edición:
git add core/atendia/runner/conversation_runner.py
git commit -m "feat(runner): preserve message attachments through run_turn"
```

---

# Bloque F — Runner integration

## Task 20: Parallel NLU + Vision via `asyncio.gather`

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`

**Step 1: Identify NLU call site**

En `run_turn`, hoy hay:

```python
nlu, usage = await self._nlu.classify(
    text=inbound.text,
    current_stage=current_stage,
    required_fields=current_stage_def.required_fields,
    optional_fields=current_stage_def.optional_fields,
    history=history,
)
```

**Step 2: Refactor a parallel**

```python
import asyncio
from atendia.tools.vision import classify_image

# ... dentro de run_turn, donde antes solo se llamaba a NLU:

nlu_task = self._nlu.classify(
    text=inbound.text,
    current_stage=current_stage,
    required_fields=current_stage_def.required_fields,
    optional_fields=current_stage_def.optional_fields,
    history=history,
)

vision_result: VisionResult | None = None
vision_cost_usd: Decimal = Decimal("0")
vision_latency_ms: int | None = None
vision_tokens_in: int = 0
vision_tokens_out: int = 0

if inbound.attachments:
    settings = get_settings()
    if settings.openai_api_key:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        vision_task = classify_image(
            client=client, image_url=inbound.attachments[0].url,
        )
        (nlu, usage), (
            vision_result, vision_tokens_in, vision_tokens_out,
            vision_cost_usd, vision_latency_ms,
        ) = await asyncio.gather(nlu_task, vision_task)
    else:
        nlu, usage = await nlu_task
else:
    nlu, usage = await nlu_task
```

**Step 3: Persistir a turn_trace**

Más abajo, en la creación del `TurnTrace(...)`:

```python
trace = TurnTrace(
    # ...,
    vision_cost_usd=vision_cost_usd if vision_cost_usd > 0 else None,
    vision_latency_ms=vision_latency_ms,
    flow_mode=...,  # se pone en T21
)
```

**Step 4: Acumular vision_cost_usd a conversation_state.total_cost_usd**

```python
if vision_cost_usd > 0:
    await self._session.execute(
        text("UPDATE conversation_state SET total_cost_usd = total_cost_usd + :c "
             "WHERE conversation_id = :cid"),
        {"c": vision_cost_usd, "cid": conversation_id},
    )
```

**Step 5: Smoke**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner -q
```

Expected: tests pasan (Vision se skipea cuando no hay attachments y ya hay test fixtures sin imágenes).

**Step 6: Commit**

```bash
git add core/atendia/runner/conversation_runner.py
git commit -m "feat(runner): parallel NLU + Vision via asyncio.gather; persist vision_cost_usd"
```

---

## Task 21: Mode-specific tool dispatch

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`

**Step 1: Reemplazar el dispatch actual (3c.1)**

El runner de 3c.1 hace `if decision.action == "quote": ...`. En 3c.2 reemplazamos por `if flow_mode == FlowMode.SALES: ...`.

```python
from atendia.runner.flow_router import pick_flow_mode

# Después de NLU + Vision, antes del composer:

# Construir ExtractedFields desde merged_extracted (puede haber overlap
# con campos no-canónicos; los desconocidos se ignoran via Pydantic).
ext_fields = ExtractedFields.model_validate(
    {k: v["value"] for k, v in merged_extracted.items()
     if k in ExtractedFields.model_fields},
)

flow_mode = pick_flow_mode(
    rules=pipeline.flow_mode_rules,
    extracted=ext_fields,
    nlu=nlu,
    vision=vision_result,
    inbound_text=inbound.text,
    pending_confirmation=pending_confirmation,
)

# Mode-specific tool dispatch
action_payload: dict = {}
tool_cost_usd: Decimal = Decimal("0")

if flow_mode == FlowMode.SALES:
    # Resolver SKU + cotizar (igual que en 3c.1 quote branch)
    interes = ext_fields.modelo_moto
    if interes:
        catalog_hits = await search_catalog(...)
        if isinstance(catalog_hits, list) and catalog_hits:
            quote_result = await quote(sku=catalog_hits[0].sku, ...)
            action_payload = quote_result.model_dump(mode="json")
        else:
            action_payload = ToolNoDataResult(hint=f"no match for {interes!r}").model_dump(mode="json")
    else:
        action_payload = ToolNoDataResult(hint="no modelo_moto extraído").model_dump(mode="json")

elif flow_mode == FlowMode.DOC:
    # Vision result + expected_doc + pending_after
    expected = next_pending_doc(ext_fields, ext_fields.plan_credito,
                                pipeline.docs_per_plan)
    pending_after = _docs_after(ext_fields, expected, pipeline.docs_per_plan)
    action_payload = {
        "vision_result": vision_result.model_dump(mode="json") if vision_result else None,
        "expected_doc": expected,
        "pending_after": pending_after,
    }

elif flow_mode == FlowMode.SUPPORT:
    # Embed message + lookup FAQ
    if settings.openai_api_key:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        embedding, _, emb_cost = await generate_embedding(client=client, text=inbound.text)
        tool_cost_usd += emb_cost
        faq_result = await lookup_faq(session=self._session, tenant_id=tenant_id,
                                      embedding=embedding, top_k=3)
        if isinstance(faq_result, list):
            action_payload = {"matches": [m.model_dump(mode="json") for m in faq_result]}
        else:
            action_payload = faq_result.model_dump(mode="json")

# PLAN, OBSTACLE, RETENTION → no tools, action_payload empty
```

**Step 2: Pasar `flow_mode` y `brand_facts` al ComposerInput**

Cargar `brand_facts` del `tenant_branding.default_messages.brand_facts`:

```python
brand_facts = (voice_row[0] if voice_row else {}).get("brand_facts", {}) if False else {}
# Ojo: en tu schema voice_row es solo voice. brand_facts vive en
# tenant_branding.default_messages, otra columna. Cargarla aparte:
branding_row = (await self._session.execute(
    text("SELECT default_messages FROM tenant_branding WHERE tenant_id = :t"),
    {"t": tenant_id},
)).fetchone()
brand_facts = (branding_row[0] or {}).get("brand_facts", {}) if branding_row else {}

composer_input = ComposerInput(
    action=mode_to_legacy_action(flow_mode),  # for compat in turn_trace
    flow_mode=flow_mode,
    action_payload=action_payload,
    extracted_data={k: v["value"] for k, v in merged_extracted.items()},
    history=history_for_composer,
    tone=tone,
    brand_facts=brand_facts,
    vision_result=vision_result,
    max_messages=2,
    current_stage=funnel_stage(ext_fields),  # derivado, no persistido
)
```

**Step 3: Persistir flow_mode al turn_trace**

```python
trace = TurnTrace(
    # ...,
    flow_mode=flow_mode.value,  # "PLAN" / "SALES" / etc.
    # ...
)
```

**Step 4: Smoke**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner -q
```

Si tests fallan por API breaks, ajustar fixtures (los tests de runner/test_conversation_runner.py van a necesitar `flow_mode=FlowMode.PLAN` en sus ComposerInputs).

**Step 5: Commit**

```bash
git add core/atendia/runner/conversation_runner.py
git commit -m "feat(runner): mode-specific tool dispatch + persist flow_mode in turn_trace"
```

---

## Task 22: `pending_confirmation` handling para sí/no binarios

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`

**Step 1: Lógica de confirm/deny en el runner**

Antes del flow_router, agregar:

```python
# Si hay pending_confirmation Y el mensaje es un sí/no claro,
# resolver y limpiar antes del routing.
_AFFIRMATIVE = {"si", "sí", "claro", "ok", "okay", "yes", "ya", "sip"}
_NEGATIVE = {"no", "nop", "nada", "para nada"}

normalized_inbound = inbound.text.strip().lower()
confirmation_resolved = False
if state_obj.pending_confirmation:
    if normalized_inbound in _AFFIRMATIVE:
        await _apply_confirmation(state_obj, "yes")
        confirmation_resolved = True
    elif normalized_inbound in _NEGATIVE:
        await _apply_confirmation(state_obj, "no")
        confirmation_resolved = True
    if confirmation_resolved:
        # Clear pending_confirmation
        await self._session.execute(
            text("UPDATE conversation_state SET pending_confirmation = NULL "
                 "WHERE conversation_id = :cid"),
            {"cid": conversation_id},
        )
```

**Step 2: `_apply_confirmation` helper**

Crear una función pequeña que mapee `pending_confirmation` keys → side effects en `extracted_data`:

```python
async def _apply_confirmation(state_obj, answer: str) -> None:
    """Translate a yes/no answer to a pending_confirmation into
    extracted_data updates. Side-effects mutation of state_obj."""
    pc = state_obj.pending_confirmation
    if pc == "is_nomina_tarjeta":
        if answer == "yes":
            state_obj.extracted_data["tipo_credito"] = "Nómina Tarjeta"
            state_obj.extracted_data["plan_credito"] = "10%"
        # answer="no" → fall through to PLAN MODE re-prompt
    elif pc == "is_nomina_recibos":
        if answer == "yes":
            state_obj.extracted_data["tipo_credito"] = "Nómina Recibos"
            state_obj.extracted_data["plan_credito"] = "15%"
    elif pc == "is_negocio_sat":
        if answer == "yes":
            state_obj.extracted_data["tipo_credito"] = "Negocio SAT"
            state_obj.extracted_data["plan_credito"] = "15%"
        else:
            state_obj.extracted_data["tipo_credito"] = "Sin Comprobantes"
            state_obj.extracted_data["plan_credito"] = "20%"
    # ... más casos según las disambiguations del PLAN MODE prompt ...
```

**Step 3: Composer set pending_confirmation**

Cuando el composer hace una pregunta binaria, su prompt debe instruirlo a INCLUIR un campo `pending_confirmation_set` en su output JSON. El runner lo lee y persiste:

```python
if composer_output and getattr(composer_output, "pending_confirmation_set", None):
    await self._session.execute(
        text("UPDATE conversation_state SET pending_confirmation = :pc "
             "WHERE conversation_id = :cid"),
        {"pc": composer_output.pending_confirmation_set, "cid": conversation_id},
    )
```

**NOTA:** Esto requiere extender `ComposerOutput`. Skip si quieres mantener composer simple en 3c.2 — la disambiguation se puede manejar puramente vía mode prompts que detecten "depósito"/"banco" en el texto del cliente y manejen sin pending_confirmation. **Recomendación: skipea pending_confirmation_set en 3c.2 e implementa solo la regla determinística** (si state.pending_confirmation set Y texto matchea sí/no, aplicar).

**Step 4: Tests**

Agregar 2-3 tests al `test_conversation_runner.py` cubriendo:
- pending_confirmation set + cliente dice "sí" → tipo_credito asignado, pc cleared
- pending_confirmation set + cliente dice algo no-yes/no → pc se mantiene, normal routing

**Step 5: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "feat(runner): pending_confirmation handling for binary yes/no questions"
```

---

# Bloque G — Brand facts + handoff

## Task 23: `brand_facts` JSONB en `tenant_branding.default_messages`

**Files:**
- Manual SQL (no migration — solo INSERT data into existing JSONB column)

**Step 1: Set brand_facts para Dinamo**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -c "
import asyncio, json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from atendia.config import get_settings

BRAND_FACTS = {
    'catalog_url': 'https://dinamomotos.com/catalogo.html',
    'wa_catalog_link': 'https://wa.me/c/5218128889241',
    'address': 'Benito Juárez 801, Centro Monterrey',
    'human_agent_name': 'Francisco',
    'buro_max_amount': '\$50 mil',
    'approval_time_hours': '24',
    'delivery_time_days': '3-7',
    'post_completion_form': 'https://forms.gle/U1MEueL63vgftiuZ8',
}

async def run():
    e = create_async_engine(get_settings().database_url)
    SL = async_sessionmaker(e, expire_on_commit=False)
    async with SL() as s:
        await s.execute(
            text(\"\"\"UPDATE tenant_branding
                    SET default_messages = jsonb_set(
                        COALESCE(default_messages, '{}'::jsonb),
                        '{brand_facts}',
                        CAST(:bf AS jsonb)
                    )
                    WHERE tenant_id = 'eb272fdc-0795-41ef-869c-801f3a2d4ffb'\"\"\"),
            {'bf': json.dumps(BRAND_FACTS)},
        )
        await s.commit()
    await e.dispose()
    print('brand_facts seeded')
asyncio.run(run())
"
```

**Step 2: Verify**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c \
  "SELECT default_messages->'brand_facts' FROM tenant_branding WHERE tenant_id = 'eb272fdc-0795-41ef-869c-801f3a2d4ffb';"
```

Expected: el JSON con todos los campos.

**Step 3: Commit (sin código, solo datos)**

No commit — los datos viven en la DB, no en el repo. Documenta el setup en el plan.

---

## Task 24: `HandoffSummary` Pydantic en `human_handoffs.payload`

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- (Helper if needed) `core/atendia/runner/handoff_helper.py`

**Step 1: Helper para construir HandoffSummary**

Crear `core/atendia/runner/handoff_helper.py`:

```python
"""Build HandoffSummary from current state for human escalation."""
from atendia.contracts.extracted_fields import ExtractedFields
from atendia.contracts.handoff_summary import HandoffReason, HandoffSummary
from atendia.state_machine.derived import funnel_stage


def build_handoff_summary(
    *,
    reason: HandoffReason,
    extracted: ExtractedFields,
    last_inbound_text: str,
    suggested_next_action: str,
    docs_per_plan: dict,
) -> HandoffSummary:
    """Snapshot del state al momento del handoff."""
    docs_received: list[str] = []
    docs_pending: list[str] = []
    if extracted.tipo_credito:
        plan_label = extracted.tipo_credito.value
        for doc in docs_per_plan.get(plan_label, []):
            if getattr(extracted, f"docs_{doc}", False):
                docs_received.append(doc)
            else:
                docs_pending.append(doc)

    enganche_estimado = None
    if extracted.plan_credito:
        # Approximate enganche from extracted price; the runner can
        # plug in real numbers from action_payload when available.
        enganche_estimado = f"{extracted.plan_credito.value} de enganche"

    return HandoffSummary(
        reason=reason,
        nombre=extracted.nombre,
        modelo_moto=extracted.modelo_moto,
        plan_credito=extracted.plan_credito.value if extracted.plan_credito else None,
        enganche_estimado=enganche_estimado,
        docs_recibidos=docs_received,
        docs_pendientes=docs_pending,
        last_inbound_message=last_inbound_text,
        suggested_next_action=suggested_next_action,
        funnel_stage=funnel_stage(extracted),
        cita_dia=extracted.cita_dia,
    )
```

**Step 2: Wire al runner — actualizar handoffs existentes**

En el runner, donde hoy se hace `INSERT INTO human_handoffs (... reason ...)` (sin payload), reemplazar por:

```python
summary = build_handoff_summary(
    reason=HandoffReason.OUTSIDE_24H_WINDOW,
    extracted=ext_fields,
    last_inbound_text=inbound.text,
    suggested_next_action="Continuar conversación con cliente fuera del 24h window",
    docs_per_plan=pipeline.docs_per_plan,
)
await self._session.execute(
    text("INSERT INTO human_handoffs (conversation_id, tenant_id, reason, status, payload) "
         "VALUES (:cid, :tid, :r, 'pending', CAST(:p AS jsonb))"),
    {
        "cid": conversation_id, "tid": tenant_id,
        "r": summary.reason.value,
        "p": summary.model_dump_json(),
    },
)
```

Aplicar el mismo patrón a los OTROS sites donde se crean handoffs (composer_failed, etc.).

**Step 3: Test**

```python
def test_build_handoff_summary_complete_flow() -> None:
    ext = ExtractedFields(
        nombre="Juan",
        plan_credito=PlanCredito.PLAN_10,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        modelo_moto="Adventure 150 CC",
        docs_ine=True,
        docs_comprobante=True,
    )
    docs_per_plan = {"Nómina Tarjeta": ["ine", "comprobante", "estados_de_cuenta", "nomina"]}
    summary = build_handoff_summary(
        reason=HandoffReason.PAPELERIA_COMPLETA_FORM_PENDING,
        extracted=ext,
        last_inbound_text="ya los mandé",
        suggested_next_action="Visita domicilio",
        docs_per_plan=docs_per_plan,
    )
    assert summary.docs_recibidos == ["ine", "comprobante"]
    assert summary.docs_pendientes == ["estados_de_cuenta", "nomina"]
    assert summary.funnel_stage == "doc"
    assert summary.modelo_moto == "Adventure 150 CC"
```

**Step 4: Commit**

```bash
git add core/atendia/runner/handoff_helper.py core/atendia/runner/conversation_runner.py \
        core/tests/runner/test_handoff_helper.py
git commit -m "feat(runner): structured HandoffSummary persisted in human_handoffs.payload"
```

---

# Bloque H — Tests + cierre

## Task 25: E2E integration tests por modo

**Files:**
- Create: `core/tests/integration/test_runner_modes.py`

**Step 1: Tests cubriendo cada modo end-to-end**

Crear 6 tests análogos a `test_runner_with_real_catalog.py` (3c.1 T21), uno por modo. Cada uno:
- Setup tenant + pipeline + conversation con `flow_mode_rules` apropiados
- Send mensaje que dispare el modo target
- Asegurar que `composer_input.flow_mode` es el esperado
- Asegurar que `action_payload` tiene la estructura esperada

```python
async def test_runner_dispatches_RETENTION_on_gracias() -> None:
    """Mensaje 'gracias' → flow_mode=RETENTION."""
    # ... setup ...
    inbound = Message(..., text="gracias por la info")
    trace = await runner.run_turn(...)
    assert trace.flow_mode == "RETENTION"

async def test_runner_dispatches_OBSTACLE_on_manana() -> None:
    """'mañana' (con tilde) → flow_mode=OBSTACLE."""
    inbound = Message(..., text="te lo paso mañana")
    trace = await runner.run_turn(...)
    assert trace.flow_mode == "OBSTACLE"

# ...4 más para PLAN/SALES/DOC/SUPPORT...
```

**Step 2: Tests pasan**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/integration/test_runner_modes.py -v
```

Expected: 6 PASS.

**Step 3: Commit**

```bash
git add core/tests/integration/test_runner_modes.py
git commit -m "test(integration): E2E runner dispatch per flow_mode (6 tests)"
```

---

## Task 26: Live smoke test de los 6 modos

**Files:**
- Create: `core/tests/runner/test_phase3c2_live.py`

**Step 1: Live tests gated**

Análogo a `test_phase3c_live.py` (3c.1) pero ahora un test por modo, validando que:
- gpt-4o no inventa precios cuando action_payload es real
- Los modos producen respuestas con palabras clave esperadas
- Vision para una imagen real de INE devuelve category=INE

Costo total estimado: ~$0.02 por corrida completa.

**Step 2: Run gated**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  RUN_LIVE_LLM_TESTS=1 uv run pytest tests/runner/test_phase3c2_live.py -v
```

**Step 3: Commit**

```bash
git add core/tests/runner/test_phase3c2_live.py
git commit -m "test(phase3c2): live smoke tests for all 6 flow modes"
```

---

## Task 27: Coverage gate + lint + mypy

**Step 1: Run all gates**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run ruff check --fix atendia/runner/flow_router.py atendia/runner/composer_prompts.py \
                          atendia/runner/conversation_runner.py atendia/runner/handoff_helper.py \
                          atendia/tools/vision.py atendia/contracts/flow_mode.py \
                          atendia/contracts/extracted_fields.py atendia/contracts/handoff_summary.py \
                          atendia/contracts/vision_result.py atendia/state_machine/derived.py && \
  uv run pytest --cov=atendia --cov-fail-under=85 -q \
        --ignore=tests/runner/test_phase3c_live.py \
        --ignore=tests/runner/test_phase3c2_live.py \
        --ignore=tests/runner/test_composer_live.py \
        --ignore=tests/runner/test_nlu_openai_live.py \
        --ignore=tests/test_config_meta.py \
        --ignore=tests/tools/test_vision_live.py
```

Expected: ruff clean, pytest 95%+ coverage.

**Step 2: Mypy on new files**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run mypy atendia/runner/flow_router.py atendia/tools/vision.py \
              atendia/contracts/flow_mode.py atendia/contracts/extracted_fields.py \
              atendia/contracts/handoff_summary.py atendia/contracts/vision_result.py \
              atendia/state_machine/derived.py
```

Expected: ≤1 error (el pre-existente en `tools/__init__.py`).

**Step 3: Commit lint fixes if needed**

```bash
git add core/...  # whatever ruff modified
git commit -m "chore(quality): T27 — coverage + lint + mypy hygiene for Phase 3c.2"
```

---

## Task 28: README + memory updates

**Files:**
- Modify: `README.md`
- Modify: `core/README.md`
- Update: `~/.claude/projects/.../memory/project_overview.md`

**Step 1: Update README.md status**

```markdown
- ⏳ **Phase 3c** — Migración real Dinamo + integraciones avanzadas
  - ✅ **3c.1** — Datos reales: catálogo + FAQs + planes (pgvector + halfvec)
  - ✅ **3c.2** — Router determinístico + flow v1 (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT) + Vision API
  - ⏳ **3c.3** — TBD (originalmente multimedia; 3c.2 ya cubre Vision)
- ⏳ **Phase 3d** — Follow-ups (3h/12h/24h reminders) + outbound multimedia + templates
```

Test count + coverage actualizados.

**Step 2: core/README.md**

Agregar sección "Phase 3c.2 — Flow modes":

```markdown
### Activar Phase 3c.2 — Router + flow modes

1. Asegurar que el tenant tiene `flow_mode_rules` y `docs_per_plan` en
   `tenant_pipelines.definition` JSONB (ver design doc para shape).
2. Asegurar que `tenant_branding.default_messages.brand_facts` tiene
   los facts del negocio (catalog_url, address, etc.).
3. Confirmar `OPENAI_API_KEY` en `core/.env` (Vision usa el mismo).

Smoke test:
   curl -X POST ... (ver test_runner_modes.py para fixture)
```

**Step 3: Memory update** — añadir entrada Phase 3c.2 completada en `project_overview.md`.

**Step 4: Commit**

```bash
git add README.md core/README.md
git commit -m "docs: mark Phase 3c.2 (router + flow modes + Vision) as complete"
```

---

## Task 29: Final verification + tag

**Step 1: Full pytest with coverage**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run pytest --cov=atendia --cov-fail-under=85 -q \
        --ignore=tests/runner/test_phase3c_live.py \
        --ignore=tests/runner/test_phase3c2_live.py \
        --ignore=tests/runner/test_composer_live.py \
        --ignore=tests/runner/test_nlu_openai_live.py \
        --ignore=tests/test_config_meta.py \
        --ignore=tests/tools/test_vision_live.py
```

Expected: PASS gate + ~400+ tests passed.

**Step 2: Tag**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2" && git tag phase-3c2-router-flow-modes
```

**Step 3: Commit log review**

```bash
git log feat/phase-3c1-datos-reales..feat/phase-3c2-router-flow-modes --oneline
```

Expected: ~29 commits, uno por tarea.

---

## Notas finales

- **Costo de live tests post-mergeo**: 1× completa = ~$0.05 USD (Vision + Composer + NLU). Correr antes de cada PR a main.
- **Punch-list traída de 3c.1**:
  - Catalog disambiguation (≥2 hits con mismo alias) — implementar como bonus en 3c.2 si el tiempo alcanza, o defer a 3c.3.
  - NLU entity tuning para frases casuales — observar en piloto post-3c.2.
  - Test cleanup (tenant Dinamo desaparece) — investigar al iniciar 3c.2 si vuelve a pasar.
- **Pre-3c.3**: redefinir alcance ahora que 3c.2 incluyó Vision. Candidatos: outbound multimedia, blob storage permanente, advanced memory features.

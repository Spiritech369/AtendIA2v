# AI Field Extraction → customer.attrs — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cablear el output del NLU (entidades con confidence) a `customer.attrs` con auto-apply ≥0.85, sugerencias pendientes para rango medio o overwrites, y UI para que el operador acepte/rechace.

**Architecture:** Tres piezas — (1) función pura `decide_action(...)` que aplica las reglas de overwrite y se cablea en `conversation_runner` después del merge de entidades; (2) nueva tabla `field_suggestions` + 3 endpoints; (3) `FieldSuggestionsPanel` componente arriba del grid del ContactPanel.

**Tech Stack:** Backend FastAPI + SQLAlchemy async + Alembic + pytest. Frontend React 19 + TS strict + TanStack Query + Vitest.

**Design doc:** `docs/plans/2026-05-13-ai-field-extraction-design.md`

---

## Task 1 — Migración + modelo `FieldSuggestion`

**Files:**
- Create: `core/atendia/db/migrations/versions/042_field_suggestions.py`
- Create: `core/atendia/db/models/field_suggestion.py`
- Modify: `core/atendia/db/models/__init__.py` (export new model)

**Step 1: Migration**

```python
"""042_field_suggestions

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
Create Date: 2026-05-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "g4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_suggestions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_number", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("suggested_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["tenant_users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('pending','accepted','rejected')",
                           name="ck_field_suggestions_status"),
    )
    op.create_index(
        "ix_field_suggestions_tenant_customer_status",
        "field_suggestions",
        ["tenant_id", "customer_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_field_suggestions_tenant_customer_status", table_name="field_suggestions")
    op.drop_table("field_suggestions")
```

**Step 2: Model**

```python
# core/atendia/db/models/field_suggestion.py
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class FieldSuggestion(Base):
    __tablename__ = "field_suggestions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    turn_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key: Mapped[str] = mapped_column(String(64))
    suggested_value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','rejected')",
                        name="ck_field_suggestions_status"),
    )
```

**Step 3: Export model**

Append to `core/atendia/db/models/__init__.py`:

```python
from atendia.db.models.field_suggestion import FieldSuggestion  # noqa: F401
```

(Verifico el patrón actual — quizás los modelos no se re-exportan ahí; en ese caso skip esta sub-step.)

**Step 4: Apply migration**

```powershell
$env:ATENDIA_V2_DATABASE_URL = "postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2"
cd "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\.claude\worktrees\beautiful-mirzakhani-55368f"
uv run alembic upgrade head
```

Expected: migration runs, no error.

**Step 5: Commit**

```bash
git add core/atendia/db/migrations/versions/042_field_suggestions.py core/atendia/db/models/field_suggestion.py
git commit -m "feat(db): migration 042 — field_suggestions table"
```

---

## Task 2 — Función pura `decide_action` + tests TDD

**Files:**
- Create: `core/atendia/runner/field_extraction_mapping.py`
- Create: `core/tests/runner/test_field_extraction_mapping.py`

**Step 1: Tests primero**

```python
# core/tests/runner/test_field_extraction_mapping.py
"""Tests for decide_action — pure decision logic for AI → attrs flow.

The decision rules are documented in
docs/plans/2026-05-13-ai-field-extraction-design.md.
"""
import pytest

from atendia.runner.field_extraction_mapping import (
    CONFIDENCE_AUTO_THRESHOLD,
    CONFIDENCE_SUGGESTION_MIN,
    ENTITY_TO_ATTR,
    Action,
    decide_action,
    map_entity_to_attr,
)


def test_map_entity_to_attr_known():
    assert map_entity_to_attr("brand") == "marca"
    assert map_entity_to_attr("modelo_interes") == "modelo_interes"
    assert map_entity_to_attr("plan") == "plan_credito"


def test_map_entity_to_attr_unknown_returns_none():
    assert map_entity_to_attr("random_thing") is None


def test_decide_auto_when_empty_attr_and_high_confidence():
    assert decide_action(current_value=None, new_value="Honda", confidence=0.92) == Action.AUTO
    assert decide_action(current_value="", new_value="Honda", confidence=0.85) == Action.AUTO


def test_decide_suggest_when_empty_and_medium_confidence():
    assert decide_action(current_value=None, new_value="Honda", confidence=0.70) == Action.SUGGEST
    assert decide_action(current_value=None, new_value="Honda", confidence=0.60) == Action.SUGGEST


def test_decide_skip_when_low_confidence():
    assert decide_action(current_value=None, new_value="Honda", confidence=0.59) == Action.SKIP
    assert decide_action(current_value=None, new_value="Honda", confidence=0.0) == Action.SKIP


def test_decide_noop_when_values_match():
    assert decide_action(current_value="Honda", new_value="Honda", confidence=0.99) == Action.NOOP


def test_decide_noop_handles_string_number_equality():
    # NLU often returns numbers as int; attrs JSONB stores as string. Compare normalized.
    assert decide_action(current_value="10", new_value=10, confidence=0.95) == Action.NOOP
    assert decide_action(current_value=10, new_value="10", confidence=0.95) == Action.NOOP


def test_decide_suggest_when_existing_differs_high_confidence():
    """Never overwrite an existing value without human approval — even at 0.95."""
    assert decide_action(current_value="Honda", new_value="Yamaha", confidence=0.95) == Action.SUGGEST


def test_decide_suggest_when_existing_differs_medium_confidence():
    assert decide_action(current_value="Honda", new_value="Yamaha", confidence=0.70) == Action.SUGGEST


def test_decide_skip_when_existing_differs_low_confidence():
    """If we wouldn't even suggest on an empty field, don't bother the operator."""
    assert decide_action(current_value="Honda", new_value="Yamaha", confidence=0.40) == Action.SKIP


def test_decide_skip_when_new_value_is_empty():
    assert decide_action(current_value=None, new_value=None, confidence=0.95) == Action.SKIP
    assert decide_action(current_value=None, new_value="", confidence=0.95) == Action.SKIP
```

**Step 2: Run → FAIL**

```powershell
uv run python -m pytest core/tests/runner/test_field_extraction_mapping.py -v
```

Expected: ModuleNotFoundError.

**Step 3: Implementation**

```python
# core/atendia/runner/field_extraction_mapping.py
"""Pure decision logic for promoting NLU entities to customer.attrs.

The runner imports `decide_action` and `map_entity_to_attr` to choose
between auto-applying, creating a suggestion, or skipping each entity
NLU produced. Rules are documented in
`docs/plans/2026-05-13-ai-field-extraction-design.md`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

CONFIDENCE_AUTO_THRESHOLD = 0.85
CONFIDENCE_SUGGESTION_MIN = 0.60

ENTITY_TO_ATTR: dict[str, str] = {
    "brand": "marca",
    "marca": "marca",
    "model": "modelo_interes",
    "modelo": "modelo_interes",
    "modelo_interes": "modelo_interes",
    "plan": "plan_credito",
    "credit_plan": "plan_credito",
    "plan_credito": "plan_credito",
    "credit_type": "tipo_credito",
    "income_type": "tipo_credito",
    "tipo_credito": "tipo_credito",
    "city": "city",
    "ciudad": "city",
    "estimated_value": "estimated_value",
    "valor_estimado": "estimated_value",
    "labor_seniority": "antiguedad_laboral_meses",
    "antiguedad_laboral_meses": "antiguedad_laboral_meses",
}


class Action(str, Enum):
    AUTO = "auto"      # apply directly to customer.attrs
    SUGGEST = "suggest"  # create a pending suggestion
    SKIP = "skip"      # do nothing
    NOOP = "noop"      # value already present and equal


def map_entity_to_attr(entity_key: str) -> str | None:
    """Return the canonical attr key for an NLU entity, or None if unknown."""
    return ENTITY_TO_ATTR.get(entity_key)


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return str(value).strip()


def decide_action(*, current_value: Any, new_value: Any, confidence: float) -> Action:
    """Decide what to do with an NLU-detected value for an attr.

    See the design doc for the full rules table. Summary:
    - empty + conf >= 0.85 → AUTO
    - empty + conf 0.60-0.84 → SUGGEST
    - empty + conf < 0.60 → SKIP
    - same value (normalized) → NOOP
    - different value + conf >= 0.60 → SUGGEST (never silent overwrite)
    - different value + conf < 0.60 → SKIP
    """
    new_norm = _norm(new_value)
    if new_norm is None:
        return Action.SKIP

    current_norm = _norm(current_value)

    if current_norm is not None and current_norm == new_norm:
        return Action.NOOP

    if current_norm is None:
        if confidence >= CONFIDENCE_AUTO_THRESHOLD:
            return Action.AUTO
        if confidence >= CONFIDENCE_SUGGESTION_MIN:
            return Action.SUGGEST
        return Action.SKIP

    # Different value already present
    if confidence >= CONFIDENCE_SUGGESTION_MIN:
        return Action.SUGGEST
    return Action.SKIP
```

**Step 4: Run → PASS**

```powershell
uv run python -m pytest core/tests/runner/test_field_extraction_mapping.py -v
```

Expected: 10 passed.

**Step 5: Commit**

```bash
git add core/atendia/runner/field_extraction_mapping.py core/tests/runner/test_field_extraction_mapping.py
git commit -m "feat(runner): decide_action pure logic for NLU → attrs promotion"
```

---

## Task 3 — Service `apply_ai_extractions` + tests

**Files:**
- Create: `core/atendia/runner/ai_extraction_service.py`
- Create: `core/tests/runner/test_ai_extraction_service.py`

**Step 1: Tests**

```python
# core/tests/runner/test_ai_extraction_service.py
"""apply_ai_extractions integration tests against real DB.

Seeds a tenant + customer with known attrs, calls the service with a
synthetic NLU output, and verifies the resulting customer.attrs and
field_suggestions rows.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.contracts.conversation_state import ExtractedField
from atendia.runner.ai_extraction_service import apply_ai_extractions


def _seed_tenant_customer(initial_attrs: dict | None = None) -> tuple[str, str, str]:
    """Return (tenant_id, customer_id, conversation_id)."""

    async def _do() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"aiext_{uuid4().hex[:8]}"},
                )
            ).scalar()
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, attrs) "
                        "VALUES (:t, :p, CAST(:a AS jsonb)) RETURNING id"
                    ),
                    {
                        "t": tid,
                        "p": f"+521555{uuid4().hex[:8]}",
                        "a": json.dumps(initial_attrs or {}),
                    },
                )
            ).scalar()
            conv_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, status, current_stage) "
                        "VALUES (:t, :c, 'active', 'new') RETURNING id"
                    ),
                    {"t": tid, "c": cust_id},
                )
            ).scalar()
        await engine.dispose()
        return str(tid), str(cust_id), str(conv_id)

    return asyncio.run(_do())


def _cleanup(tenant_id: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await engine.dispose()

    asyncio.run(_do())


def _read_attrs(customer_id: str) -> dict:
    async def _do() -> dict:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT attrs FROM customers WHERE id = :c"),
                    {"c": customer_id},
                )
            ).scalar_one()
        await engine.dispose()
        return row or {}

    return asyncio.run(_do())


def _read_suggestions(customer_id: str) -> list[dict]:
    async def _do() -> list[dict]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT key, suggested_value, confidence, status, evidence_text "
                        "FROM field_suggestions WHERE customer_id = :c "
                        "ORDER BY key"
                    ),
                    {"c": customer_id},
                )
            ).fetchall()
        await engine.dispose()
        return [dict(r._mapping) for r in rows]

    return asyncio.run(_do())


@pytest.fixture
def fresh_seed():
    tid, cid, conv = _seed_tenant_customer()
    yield tid, cid, conv
    _cleanup(tid)


@pytest.fixture
def seed_with_attrs():
    tid, cid, conv = _seed_tenant_customer({"plan_credito": "10", "marca": "Honda"})
    yield tid, cid, conv
    _cleanup(tid)


async def _run(tenant_id, customer_id, conv_id, entities, turn=1, inbound_text=None):
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        # The service expects an AsyncSession; we wrap with one for the test.
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            await apply_ai_extractions(
                session=session,
                tenant_id=tenant_id,
                customer_id=customer_id,
                conversation_id=conv_id,
                turn_number=turn,
                entities=entities,
                inbound_text=inbound_text,
            )
            await session.commit()
    await engine.dispose()


def test_auto_applies_to_empty_attrs(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.95, source_turn=1),
        "plan": ExtractedField(value="10", confidence=0.90, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))

    attrs = _read_attrs(cid)
    assert attrs["marca"] == "Honda"
    assert attrs["plan_credito"] == "10"

    sugg = _read_suggestions(cid)
    assert sugg == []  # no suggestions, all auto


def test_creates_suggestions_for_medium_confidence(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "model": ExtractedField(value="Civic", confidence=0.70, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities, inbound_text="creo que el Civic"))

    attrs = _read_attrs(cid)
    assert "modelo_interes" not in attrs

    sugg = _read_suggestions(cid)
    assert len(sugg) == 1
    assert sugg[0]["key"] == "modelo_interes"
    assert sugg[0]["suggested_value"] == "Civic"
    assert sugg[0]["status"] == "pending"
    assert sugg[0]["evidence_text"] == "creo que el Civic"


def test_creates_suggestion_on_overwrite_even_with_high_confidence(seed_with_attrs):
    """Don't silently change a value the operator already had."""
    tid, cid, conv = seed_with_attrs
    entities = {
        "brand": ExtractedField(value="Yamaha", confidence=0.98, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))

    attrs = _read_attrs(cid)
    assert attrs["marca"] == "Honda"  # unchanged

    sugg = _read_suggestions(cid)
    assert len(sugg) == 1
    assert sugg[0]["suggested_value"] == "Yamaha"
    assert sugg[0]["status"] == "pending"


def test_skips_low_confidence(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.30, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))
    assert _read_attrs(cid) == {}
    assert _read_suggestions(cid) == []


def test_noop_when_value_already_matches(seed_with_attrs):
    tid, cid, conv = seed_with_attrs
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.95, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))
    assert _read_attrs(cid)["marca"] == "Honda"
    assert _read_suggestions(cid) == []


def test_ignores_unknown_entities(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "weird_thing": ExtractedField(value="abc", confidence=0.99, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))
    assert _read_attrs(cid) == {}
    assert _read_suggestions(cid) == []
```

**Step 2: FAIL**

```powershell
uv run python -m pytest core/tests/runner/test_ai_extraction_service.py -v
```

**Step 3: Implementation**

```python
# core/atendia/runner/ai_extraction_service.py
"""Apply NLU-extracted entities to customer.attrs or to field_suggestions.

Called from conversation_runner after the per-turn NLU result is merged
into conversation_state.extracted_data. Stays a thin orchestrator over
the pure decision logic in field_extraction_mapping.decide_action.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.conversation_state import ExtractedField
from atendia.db.models.customer import Customer
from atendia.db.models.field_suggestion import FieldSuggestion
from atendia.runner.field_extraction_mapping import (
    Action,
    decide_action,
    map_entity_to_attr,
)

_log = logging.getLogger(__name__)


async def apply_ai_extractions(
    *,
    session: AsyncSession,
    tenant_id: UUID | str,
    customer_id: UUID | str,
    conversation_id: UUID | str | None,
    turn_number: int,
    entities: dict[str, ExtractedField],
    inbound_text: str | None = None,
) -> None:
    """Walk every entity, classify with decide_action, then persist.

    Reads customer.attrs once, applies all AUTO changes in a single
    UPDATE, then inserts FieldSuggestion rows for each SUGGEST case.
    """
    if not entities:
        return

    customer = (
        await session.execute(select(Customer).where(Customer.id == customer_id))
    ).scalar_one_or_none()
    if customer is None:
        _log.warning("apply_ai_extractions: customer %s not found", customer_id)
        return

    current_attrs: dict = dict(customer.attrs or {})
    next_attrs = dict(current_attrs)
    suggestions: list[FieldSuggestion] = []
    dirty = False

    for entity_key, field in entities.items():
        attr_key = map_entity_to_attr(entity_key)
        if attr_key is None:
            continue

        current = current_attrs.get(attr_key)
        action = decide_action(
            current_value=current,
            new_value=field.value,
            confidence=float(field.confidence),
        )

        if action == Action.AUTO:
            next_attrs[attr_key] = field.value
            dirty = True
        elif action == Action.SUGGEST:
            suggestions.append(
                FieldSuggestion(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    turn_number=turn_number,
                    key=attr_key,
                    suggested_value=str(field.value),
                    confidence=float(field.confidence),
                    evidence_text=inbound_text,
                    status="pending",
                )
            )
        # SKIP and NOOP: nothing to persist

    if dirty:
        customer.attrs = next_attrs
        session.add(customer)

    for sugg in suggestions:
        session.add(sugg)
```

**Step 4: Run tests → PASS**

```powershell
$env:ATENDIA_V2_DATABASE_URL = "postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2"
uv run python -m pytest core/tests/runner/test_ai_extraction_service.py -v
```

Expected: 6 passed.

**Step 5: Commit**

```bash
git add core/atendia/runner/ai_extraction_service.py core/tests/runner/test_ai_extraction_service.py
git commit -m "feat(runner): apply_ai_extractions service writes attrs or suggestions"
```

---

## Task 4 — Cablear en `conversation_runner.py`

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`

**Step 1: Localizar el sitio**

Después de `for k, field in nlu.entities.items(): state_obj.extracted_data[k] = field` (línea ~359).

**Step 2: Insertar la llamada**

Antes del bloque que persiste el state via SQL raw, agregar:

```python
# After NLU entities are merged into state_obj, cascade promotions
# into customer.attrs / field_suggestions. Same session so the change
# commits with the rest of the turn.
from atendia.runner.ai_extraction_service import apply_ai_extractions

# Customer id is on the conversation row; fetch once if not already
# loaded. (state_obj has tenant_id but not customer_id.)
customer_id_row = await self._session.execute(
    text("SELECT customer_id FROM conversations WHERE id = :cid"),
    {"cid": conversation_id},
)
customer_id = customer_id_row.scalar_one_or_none()
if customer_id is not None:
    try:
        await apply_ai_extractions(
            session=self._session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            turn_number=turn_number,
            entities=nlu.entities,
            inbound_text=inbound_text,
        )
    except Exception:
        # Never fail the turn because of an AI-side write — log and continue.
        logging.getLogger(__name__).exception(
            "apply_ai_extractions failed for conversation=%s", conversation_id
        )
```

**Step 3: Verificar que `inbound_text` ya está en scope**

```bash
grep -n "inbound_text" core/atendia/runner/conversation_runner.py | head -10
```

Si no está, derivarlo del request inbound. Si el runner sólo tiene el message id, leer el `messages.body`. Inspeccionar antes de implementar; si no es trivial, pasar `None` y aceptar suggestions sin evidence_text (degradado aceptable).

**Step 4: Smoke tests**

```bash
uv run python -m pytest core/tests/runner/ -q
```

Expected: existing tests siguen verdes. Si alguno falla por sesión adicional, ajustar.

**Step 5: Commit**

```bash
git add core/atendia/runner/conversation_runner.py
git commit -m "feat(runner): cascade NLU entities to customer.attrs after turn"
```

---

## Task 5 — Backend endpoints: list/accept/reject

**Files:**
- Create: `core/atendia/api/field_suggestions_routes.py`
- Modify: `core/atendia/main.py`
- Create: `core/tests/api/test_field_suggestions_routes.py`

**Step 1: Implementation**

```python
# core/atendia/api/field_suggestions_routes.py
"""Field suggestion endpoints — list + accept + reject.

Two routers because the list path is per-customer
(`/customers/:cid/field-suggestions`) while accept/reject are by
suggestion id (`/field-suggestions/:sid/accept`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.customer import Customer
from atendia.db.models.field_suggestion import FieldSuggestion
from atendia.db.session import get_db_session

customer_suggestions_router = APIRouter()
suggestion_actions_router = APIRouter()


class FieldSuggestionOut(BaseModel):
    id: UUID
    customer_id: UUID
    conversation_id: UUID | None
    turn_number: int | None
    key: str
    suggested_value: str
    confidence: Decimal
    evidence_text: str | None
    status: str
    created_at: datetime
    decided_at: datetime | None


@customer_suggestions_router.get("", response_model=list[FieldSuggestionOut])
async def list_field_suggestions(
    customer_id: UUID,
    status_filter: str = Query("pending", alias="status"),
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[FieldSuggestionOut]:
    rows = (
        await session.execute(
            select(FieldSuggestion)
            .where(
                FieldSuggestion.tenant_id == tenant_id,
                FieldSuggestion.customer_id == customer_id,
                FieldSuggestion.status == status_filter,
            )
            .order_by(FieldSuggestion.created_at.desc())
        )
    ).scalars().all()
    return [FieldSuggestionOut.model_validate(r, from_attributes=True) for r in rows]


async def _load_suggestion(
    session: AsyncSession, suggestion_id: UUID, tenant_id: UUID
) -> FieldSuggestion:
    row = (
        await session.execute(
            select(FieldSuggestion).where(
                FieldSuggestion.id == suggestion_id,
                FieldSuggestion.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "suggestion not found")
    if row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"suggestion is already {row.status}",
        )
    return row


@suggestion_actions_router.post("/{suggestion_id}/accept", response_model=FieldSuggestionOut)
async def accept_field_suggestion(
    suggestion_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> FieldSuggestionOut:
    sugg = await _load_suggestion(session, suggestion_id, tenant_id)
    customer = (
        await session.execute(
            select(Customer).where(Customer.id == sugg.customer_id)
        )
    ).scalar_one()
    next_attrs = dict(customer.attrs or {})
    next_attrs[sugg.key] = sugg.suggested_value
    customer.attrs = next_attrs
    sugg.status = "accepted"
    sugg.decided_at = datetime.now(timezone.utc)
    sugg.decided_by_user_id = user.user_id
    await session.commit()
    await session.refresh(sugg)
    return FieldSuggestionOut.model_validate(sugg, from_attributes=True)


@suggestion_actions_router.post("/{suggestion_id}/reject", response_model=FieldSuggestionOut)
async def reject_field_suggestion(
    suggestion_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> FieldSuggestionOut:
    sugg = await _load_suggestion(session, suggestion_id, tenant_id)
    sugg.status = "rejected"
    sugg.decided_at = datetime.now(timezone.utc)
    sugg.decided_by_user_id = user.user_id
    await session.commit()
    await session.refresh(sugg)
    return FieldSuggestionOut.model_validate(sugg, from_attributes=True)
```

**Step 2: Register routers in main**

In `core/atendia/main.py`:

```python
from atendia.api.field_suggestions_routes import (
    customer_suggestions_router,
    suggestion_actions_router,
)

# (later, with other include_router calls)
app.include_router(
    customer_suggestions_router,
    prefix="/api/v1/customers/{customer_id}/field-suggestions",
    tags=["field-suggestions"],
)
app.include_router(
    suggestion_actions_router,
    prefix="/api/v1/field-suggestions",
    tags=["field-suggestions"],
)
```

**Step 3: Tests**

```python
# core/tests/api/test_field_suggestions_routes.py
"""Tests for /customers/:cid/field-suggestions and /:sid/accept|reject."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_customer_with_suggestion(tenant_id: str) -> tuple[str, str]:
    """Return (customer_id, suggestion_id)."""

    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tenant_id, "p": f"+521555{uuid4().hex[:8]}"},
                )
            ).scalar()
            sid = (
                await conn.execute(
                    text(
                        "INSERT INTO field_suggestions "
                        "(tenant_id, customer_id, key, suggested_value, confidence, evidence_text) "
                        "VALUES (:t, :c, 'plan_credito', '10', 0.72, '...plan del 10%...') "
                        "RETURNING id"
                    ),
                    {"t": tenant_id, "c": cust_id},
                )
            ).scalar()
        await engine.dispose()
        return str(cust_id), str(sid)

    return asyncio.run(_do())


def test_list_pending_suggestions(client_operator):
    cust_id, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    resp = client_operator.get(f"/api/v1/customers/{cust_id}/field-suggestions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == sid
    assert body[0]["key"] == "plan_credito"
    assert body[0]["suggested_value"] == "10"
    assert body[0]["status"] == "pending"


def test_accept_writes_to_attrs_and_marks_accepted(client_operator):
    cust_id, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    # Verify attrs updated
    detail = client_operator.get(f"/api/v1/customers/{cust_id}").json()
    assert detail["attrs"]["plan_credito"] == "10"


def test_reject_marks_rejected_without_touching_attrs(client_operator):
    cust_id, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    detail = client_operator.get(f"/api/v1/customers/{cust_id}").json()
    assert "plan_credito" not in (detail["attrs"] or {})


def test_accept_idempotent_returns_409(client_operator):
    _, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    assert resp.status_code == 409


def test_tenant_isolation(client_operator, client_tenant_admin):
    _, sid = _seed_customer_with_suggestion(client_tenant_admin.tenant_id)
    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    assert resp.status_code == 404
```

**Step 4: Run**

```powershell
uv run python -m pytest core/tests/api/test_field_suggestions_routes.py -v
```

Expected: 5 passed.

**Step 5: Commit**

```bash
git add core/atendia/api/field_suggestions_routes.py core/atendia/main.py core/tests/api/test_field_suggestions_routes.py
git commit -m "feat(api): field_suggestions list/accept/reject endpoints"
```

---

## Task 6 — Frontend API + hook

**Files:**
- Modify: `frontend/src/features/conversations/api.ts` (agregar fieldSuggestionsApi)
- Create: `frontend/src/features/conversations/hooks/useFieldSuggestions.ts`
- Create: `frontend/tests/features/conversations/useFieldSuggestions.test.tsx`

**Step 1: API**

Agregar al final de `frontend/src/features/conversations/api.ts`:

```ts
export interface FieldSuggestion {
  id: string;
  customer_id: string;
  conversation_id: string | null;
  turn_number: number | null;
  key: string;
  suggested_value: string;
  confidence: string;
  evidence_text: string | null;
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  decided_at: string | null;
}

export const fieldSuggestionsApi = {
  list: async (customerId: string): Promise<FieldSuggestion[]> =>
    (
      await api.get<FieldSuggestion[]>(
        `/customers/${customerId}/field-suggestions`,
      )
    ).data,
  accept: async (suggestionId: string): Promise<FieldSuggestion> =>
    (
      await api.post<FieldSuggestion>(
        `/field-suggestions/${suggestionId}/accept`,
      )
    ).data,
  reject: async (suggestionId: string): Promise<FieldSuggestion> =>
    (
      await api.post<FieldSuggestion>(
        `/field-suggestions/${suggestionId}/reject`,
      )
    ).data,
};
```

**Step 2: Hook**

```ts
// frontend/src/features/conversations/hooks/useFieldSuggestions.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { fieldSuggestionsApi } from "@/features/conversations/api";

export function useFieldSuggestions(customerId: string | undefined) {
  return useQuery({
    queryKey: ["field-suggestions", customerId],
    queryFn: () => fieldSuggestionsApi.list(customerId!),
    enabled: !!customerId,
    refetchInterval: 60_000,
  });
}

export function useAcceptFieldSuggestion(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (suggestionId: string) =>
      fieldSuggestionsApi.accept(suggestionId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["field-suggestions", customerId] });
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
      toast.success("Sugerencia aplicada");
    },
    onError: (e) => toast.error("Error al aceptar", { description: e.message }),
  });
}

export function useRejectFieldSuggestion(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (suggestionId: string) =>
      fieldSuggestionsApi.reject(suggestionId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["field-suggestions", customerId] });
    },
    onError: (e) =>
      toast.error("Error al rechazar", { description: e.message }),
  });
}
```

**Step 3: Tests**

```tsx
// frontend/tests/features/conversations/useFieldSuggestions.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { fieldSuggestionsApi } from "@/features/conversations/api";
import {
  useAcceptFieldSuggestion,
  useFieldSuggestions,
  useRejectFieldSuggestion,
} from "@/features/conversations/hooks/useFieldSuggestions";

const customerId = "11111111-1111-1111-1111-111111111111";

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useFieldSuggestions", () => {
  it("lists suggestions for the given customer", async () => {
    const spy = vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([
      {
        id: "s1",
        customer_id: customerId,
        conversation_id: null,
        turn_number: 1,
        key: "plan_credito",
        suggested_value: "10",
        confidence: "0.85",
        evidence_text: null,
        status: "pending",
        created_at: "2026-05-13T00:00:00Z",
        decided_at: null,
      },
    ]);
    const { result } = renderHook(() => useFieldSuggestions(customerId), {
      wrapper: wrap(),
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.length).toBe(1);
    spy.mockRestore();
  });

  it("accept calls the accept endpoint", async () => {
    const spy = vi
      .spyOn(fieldSuggestionsApi, "accept")
      .mockResolvedValue({} as never);
    const { result } = renderHook(() => useAcceptFieldSuggestion(customerId), {
      wrapper: wrap(),
    });
    await act(async () => {
      await result.current.mutateAsync("s1");
    });
    expect(spy).toHaveBeenCalledWith("s1");
    spy.mockRestore();
  });

  it("reject calls the reject endpoint", async () => {
    const spy = vi
      .spyOn(fieldSuggestionsApi, "reject")
      .mockResolvedValue({} as never);
    const { result } = renderHook(() => useRejectFieldSuggestion(customerId), {
      wrapper: wrap(),
    });
    await act(async () => {
      await result.current.mutateAsync("s1");
    });
    expect(spy).toHaveBeenCalledWith("s1");
    spy.mockRestore();
  });
});
```

**Step 4: Run + verify**

```bash
cd frontend
pnpm exec vitest run tests/features/conversations/useFieldSuggestions.test.tsx
```

Expected: 3 passed.

**Step 5: Commit**

```bash
git add frontend/src/features/conversations/api.ts frontend/src/features/conversations/hooks/useFieldSuggestions.ts frontend/tests/features/conversations/useFieldSuggestions.test.tsx
git commit -m "feat(field-suggestions): frontend api + tanstack hooks"
```

---

## Task 7 — `FieldSuggestionsPanel` component

**Files:**
- Create: `frontend/src/features/conversations/components/FieldSuggestionsPanel.tsx`
- Create: `frontend/tests/features/conversations/FieldSuggestionsPanel.test.tsx`

**Step 1: Component**

```tsx
// frontend/src/features/conversations/components/FieldSuggestionsPanel.tsx
import { Check, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useAcceptFieldSuggestion,
  useFieldSuggestions,
  useRejectFieldSuggestion,
} from "@/features/conversations/hooks/useFieldSuggestions";

const FIELD_LABELS: Record<string, string> = {
  marca: "Marca",
  modelo_interes: "Producto",
  plan_credito: "Plan de crédito",
  tipo_credito: "Tipo de crédito",
  city: "Ubicación",
  estimated_value: "Valor estimado",
  antiguedad_laboral_meses: "Antigüedad laboral (meses)",
};

/**
 * Shows pending NLU-derived suggestions for a customer. Renders nothing
 * when there are zero pending — keeps the contact panel quiet by default.
 */
export function FieldSuggestionsPanel({
  customerId,
}: {
  customerId: string;
}) {
  const query = useFieldSuggestions(customerId);
  const accept = useAcceptFieldSuggestion(customerId);
  const reject = useRejectFieldSuggestion(customerId);

  if (!query.data || query.data.length === 0) return null;

  return (
    <div className="px-3 py-3 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-blue-600">
        <Sparkles className="h-3 w-3" />
        Sugerencias de IA ({query.data.length})
      </div>
      <div className="space-y-1.5">
        {query.data.map((s) => {
          const label = FIELD_LABELS[s.key] ?? s.key.replace(/_/g, " ");
          const confidencePct = Math.round(Number(s.confidence) * 100);
          return (
            <div
              key={s.id}
              className="rounded-md border border-blue-500/20 bg-blue-500/5 p-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium">{label}</div>
                  <div className="truncate font-mono text-[11px] text-blue-700">
                    {s.suggested_value}
                  </div>
                </div>
                <span className="shrink-0 rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 tabular-nums">
                  {confidencePct}%
                </span>
              </div>
              {s.evidence_text && (
                <div className="mt-1 line-clamp-2 text-[10px] italic text-muted-foreground">
                  «{s.evidence_text}»
                </div>
              )}
              <div className="mt-1.5 flex gap-1">
                <Button
                  size="sm"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => accept.mutate(s.id)}
                  disabled={accept.isPending}
                >
                  <Check className="mr-1 h-3 w-3" /> Aceptar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => reject.mutate(s.id)}
                  disabled={reject.isPending}
                >
                  <X className="mr-1 h-3 w-3" /> Rechazar
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

**Step 2: Tests**

```tsx
// frontend/tests/features/conversations/FieldSuggestionsPanel.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { fieldSuggestionsApi } from "@/features/conversations/api";
import { FieldSuggestionsPanel } from "@/features/conversations/components/FieldSuggestionsPanel";

const customerId = "11111111-1111-1111-1111-111111111111";

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const sample = {
  id: "s1",
  customer_id: customerId,
  conversation_id: null,
  turn_number: 1,
  key: "plan_credito",
  suggested_value: "10",
  confidence: "0.85",
  evidence_text: "Quiero el plan del 10%",
  status: "pending" as const,
  created_at: "2026-05-13T00:00:00Z",
  decided_at: null,
};

describe("FieldSuggestionsPanel", () => {
  it("renders nothing when there are no suggestions", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([]);
    const { container } = render(
      <FieldSuggestionsPanel customerId={customerId} />,
      { wrapper: wrap() },
    );
    await waitFor(() =>
      expect(fieldSuggestionsApi.list).toHaveBeenCalled(),
    );
    expect(container.textContent).toBe("");
  });

  it("renders a card per suggestion with label + confidence + evidence", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([sample]);
    render(<FieldSuggestionsPanel customerId={customerId} />, {
      wrapper: wrap(),
    });
    await waitFor(() => {
      expect(screen.getByText("Plan de crédito")).toBeInTheDocument();
    });
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText(/Quiero el plan del 10%/)).toBeInTheDocument();
  });

  it("clicking Aceptar calls the accept api", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([sample]);
    const acceptSpy = vi
      .spyOn(fieldSuggestionsApi, "accept")
      .mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(<FieldSuggestionsPanel customerId={customerId} />, {
      wrapper: wrap(),
    });
    await waitFor(() =>
      expect(screen.getByText("Plan de crédito")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /aceptar/i }));
    expect(acceptSpy).toHaveBeenCalledWith("s1");
  });

  it("clicking Rechazar calls the reject api", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([sample]);
    const rejectSpy = vi
      .spyOn(fieldSuggestionsApi, "reject")
      .mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(<FieldSuggestionsPanel customerId={customerId} />, {
      wrapper: wrap(),
    });
    await waitFor(() =>
      expect(screen.getByText("Plan de crédito")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /rechazar/i }));
    expect(rejectSpy).toHaveBeenCalledWith("s1");
  });
});
```

**Step 3: Run**

```bash
pnpm exec vitest run tests/features/conversations/FieldSuggestionsPanel.test.tsx
```

Expected: 4 passed.

**Step 4: Commit**

```bash
git add frontend/src/features/conversations/components/FieldSuggestionsPanel.tsx frontend/tests/features/conversations/FieldSuggestionsPanel.test.tsx
git commit -m "feat(field-suggestions): FieldSuggestionsPanel UI with accept/reject"
```

---

## Task 8 — Integrar en `ContactPanel` + smoke + merge

**Files:**
- Modify: `frontend/src/features/conversations/components/ContactPanel.tsx`

**Step 1: Import + render**

Agregar import:
```tsx
import { FieldSuggestionsPanel } from "@/features/conversations/components/FieldSuggestionsPanel";
```

En el árbol del panel (función `ContactPanel`), después de `<IntelligenceScoreSection />` y antes de `<ContactDetailGridSection />`, insertar:

```tsx
              <Separator />
              <FieldSuggestionsPanel customerId={customerId} />
```

**Step 2: TS + tests full**

```bash
cd frontend
pnpm exec tsc --noEmit
pnpm exec vitest run
```

Expected: ambos verdes.

**Step 3: Backend smoke**

```bash
$env:ATENDIA_V2_DATABASE_URL = "postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2"
uv run python -m pytest core/tests/runner/test_field_extraction_mapping.py core/tests/runner/test_ai_extraction_service.py core/tests/api/test_field_suggestions_routes.py -q
```

Expected: 21 tests verdes.

**Step 4: Lint**

```bash
pnpm exec biome check --write src/features/conversations/components/FieldSuggestionsPanel.tsx src/features/conversations/components/ContactPanel.tsx src/features/conversations/hooks/useFieldSuggestions.ts src/features/conversations/api.ts tests/features/conversations/useFieldSuggestions.test.tsx tests/features/conversations/FieldSuggestionsPanel.test.tsx
```

**Step 5: Commit + merge a main**

```bash
git add -A frontend/
git commit -m "feat(contact-panel): render FieldSuggestionsPanel above grid"

git update-ref refs/heads/main claude/beautiful-mirzakhani-55368f
git push origin main
```

---

## Criterios de éxito

- [ ] Migration 042 aplica sin error; downgrade limpio.
- [ ] `test_field_extraction_mapping.py` 10 tests verdes.
- [ ] `test_ai_extraction_service.py` 6 tests verdes contra DB real.
- [ ] `test_field_suggestions_routes.py` 5 tests verdes.
- [ ] Frontend: `useFieldSuggestions.test.tsx` (3) + `FieldSuggestionsPanel.test.tsx` (4) verdes.
- [ ] Total tests nuevos: 28. Suite frontend completa: 90 + 7 ≈ 97.
- [ ] Un mensaje real "Quiero el plan del 10%" + un NLU con confidence ≥ 0.85 → `customer.attrs.plan_credito = "10"` automático visible en `ContactPanel` sin refresh manual (la query del customer se invalida tras el turn… o tras polling de 30s).
- [ ] Una conversación con confidence 0.70 → la sugerencia aparece como card azul encima del grid; Aceptar la persiste a attrs y la elimina del panel; Rechazar la elimina sin modificar attrs.
- [ ] `tsc --noEmit` + `biome check` limpios.
- [ ] Branch mergeada a `main` + push.

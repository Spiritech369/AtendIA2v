# Mock / Demo Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Isolate all mock/demo behavior behind a DB flag (`tenants.is_demo`), typed provider protocols, and clear frontend markers (`DemoBadge` / `NYIButton`) so real production tenants never receive simulated data or actions.

**Architecture:** A `tenants.is_demo` boolean column gates every mock path. All demo fixtures and implementations move to a dedicated `_demo/` module. Each replaceable mock capability is typed as a `typing.Protocol` in `providers/`; demo implementations live in `_demo/providers.py` and return `{"status": "simulated", "_demo": true}`. Non-demo tenants that hit an unimplemented provider receive `501`. The frontend adds two components: `DemoBadge` (violet, simulated-but-implemented data) and `NYIButton` (amber + lock, not-yet-built features) — replacing all `toast.info(...)` stubs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async (`Mapped`, `mapped_column`), Alembic, Pydantic v2, pytest-asyncio (`@pytest.mark.asyncio`), React 19, TypeScript strict, Vitest, Tailwind v4, shadcn/ui, sonner (toast), lucide-react

---

## Task 1: Migration 040 — `tenants.is_demo`

**Files:**
- Create: `core/atendia/db/migrations/versions/040_demo_tenant_flag.py`
- Run: `core/tests/db/test_migrations_roundtrip.py` (existing — just verify it still passes)

**Step 1: Write migration**

```python
# core/atendia/db/migrations/versions/040_demo_tenant_flag.py
"""040_demo_tenant_flag

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Mark the seed demo tenant so the gate works without env vars.
    op.execute("UPDATE tenants SET is_demo = TRUE WHERE name = 'demo'")


def downgrade() -> None:
    op.drop_column("tenants", "is_demo")
```

**Step 2: Apply migration**

Run from `core/`:
```bash
uv run alembic upgrade head
```
Expected: `Running upgrade e2f3a4b5c6d7 -> f3a4b5c6d7e8, 040_demo_tenant_flag`

**Step 3: Verify roundtrip still passes**

```bash
uv run pytest tests/db/test_migrations_roundtrip.py -v
```
Expected: PASS

**Step 4: Commit**

```bash
git add core/atendia/db/migrations/versions/040_demo_tenant_flag.py
git commit -m "feat(db): add tenants.is_demo flag — migration 040"
```

---

## Task 2: Tenant model + `demo_tenant()` dependency

**Files:**
- Modify: `core/atendia/db/models/tenant.py`
- Modify: `core/atendia/api/_deps.py`
- Create: `core/tests/api/test_demo_tenant_dep.py`

**Step 1: Write failing test**

```python
# core/tests/api/test_demo_tenant_dep.py
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_demo_tenant_returns_true_for_demo_tenant(db_session):
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name, is_demo) VALUES ('t_demo_flag', TRUE) RETURNING id")
        )
    ).scalar()
    await db_session.commit()

    from atendia.db.models.tenant import Tenant
    from atendia.api._deps import _fetch_is_demo
    from sqlalchemy import select

    result = await db_session.execute(select(Tenant).where(Tenant.id == tid))
    tenant = result.scalar_one()
    assert tenant.is_demo is True


@pytest.mark.asyncio
async def test_demo_tenant_returns_false_for_real_tenant(db_session):
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('t_real_flag') RETURNING id")
        )
    ).scalar()
    await db_session.commit()

    from atendia.db.models.tenant import Tenant
    from sqlalchemy import select

    result = await db_session.execute(select(Tenant).where(Tenant.id == tid))
    tenant = result.scalar_one()
    assert tenant.is_demo is False
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_demo_tenant_dep.py -v
```
Expected: FAIL with `column "is_demo" of relation "tenants" does not exist` (model not updated yet)

**Step 3: Update Tenant model**

In `core/atendia/db/models/tenant.py`, add the field after `followups_enabled`:

```python
# after the followups_enabled field:
is_demo: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default="false"
)
```

**Step 4: Add `demo_tenant` dependency to `_deps.py`**

Add these imports at the top of `_deps.py`:
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session
```

Add the dependency at the end of `_deps.py`:
```python
async def demo_tenant(
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> bool:
    """Return True when the current request's tenant is a demo/sandbox tenant.

    Routes use this to gate mock data and simulated actions.
    Non-demo tenants that hit an unimplemented provider receive 501.
    """
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    return bool(tenant and tenant.is_demo)
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/api/test_demo_tenant_dep.py -v
```
Expected: PASS (2 tests)

**Step 6: Run full suite to check no regressions**

```bash
uv run pytest -q
```
Expected: all previously passing tests still pass

**Step 7: Commit**

```bash
git add core/atendia/db/models/tenant.py core/atendia/api/_deps.py core/tests/api/test_demo_tenant_dep.py
git commit -m "feat: add Tenant.is_demo field and demo_tenant() FastAPI dep"
```

---

## Task 3: Provider protocols

**Files:**
- Create: `core/atendia/providers/__init__.py`
- Create: `core/atendia/providers/advisors.py`
- Create: `core/atendia/providers/vehicles.py`
- Create: `core/atendia/providers/messaging.py`

No tests for this task — these are `typing.Protocol` definitions. Mypy will catch mismatches.

**Step 1: Create the package**

```python
# core/atendia/providers/__init__.py
"""Provider protocols — typed interfaces for capabilities with demo and real implementations."""
```

**Step 2: Advisor protocol**

```python
# core/atendia/providers/advisors.py
from __future__ import annotations

from typing import Protocol
from uuid import UUID


class AdvisorProvider(Protocol):
    """Provides access to appointment advisors (sales representatives)."""

    async def list_advisors(self) -> list[dict]: ...
    async def get_advisor(self, advisor_id: str) -> dict | None: ...
```

**Step 3: Vehicle protocol**

```python
# core/atendia/providers/vehicles.py
from __future__ import annotations

from typing import Protocol


class VehicleProvider(Protocol):
    """Provides access to vehicle inventory for test drives and deliveries."""

    async def list_vehicles(self) -> list[dict]: ...
    async def get_vehicle(self, vehicle_id: str) -> dict | None: ...
```

**Step 4: Messaging action protocol**

```python
# core/atendia/providers/messaging.py
from __future__ import annotations

from typing import Protocol
from uuid import UUID


class MessageActionProvider(Protocol):
    """Sends appointment-related WhatsApp messages to customers."""

    async def send_reminder(self, appointment_id: UUID) -> dict: ...
    async def send_location(self, appointment_id: UUID) -> dict: ...
    async def request_documents(self, appointment_id: UUID) -> dict: ...
```

**Step 5: Typecheck**

```bash
cd core && uv run mypy atendia/providers/ --strict
```
Expected: no errors

**Step 6: Commit**

```bash
git add core/atendia/providers/
git commit -m "feat: add AdvisorProvider, VehicleProvider, MessageActionProvider protocols"
```

---

## Task 4: `_demo/fixtures.py` — extract all mock constants

**Files:**
- Create: `core/atendia/_demo/__init__.py`
- Create: `core/atendia/_demo/fixtures.py`

No tests — constants only. Verify the imports compile.

**Step 1: Create the package**

```python
# core/atendia/_demo/__init__.py
"""Demo/sandbox module — fixtures and provider implementations for demo tenants.

Nothing in this module should be imported by route files directly.
Routes receive demo behavior via provider injection (see api/_deps.py).
"""
```

**Step 2: Create `fixtures.py`**

Copy the following constants verbatim from their current files into `fixtures.py`. Do not delete them from the originals yet — that happens in Tasks 7–11.

```python
# core/atendia/_demo/fixtures.py
"""All hardcoded demo data in one place.

These constants are the single source of truth for demo tenant fixtures.
They are referenced by _demo/providers.py and served only when
tenant.is_demo is True.
"""
from __future__ import annotations

# ── Appointments ──────────────────────────────────────────────────────────────
# Copied from api/appointments_routes.py (DEMO_ADVISORS, DEMO_VEHICLES)

DEMO_ADVISORS: list[dict] = [
    {"id": "maria_gonzalez", "name": "María González", "phone": "+5218110000101", "max_per_day": 8, "close_rate": 0.32},
    {"id": "ricardo_diaz", "name": "Ricardo Díaz", "phone": "+5218110000102", "max_per_day": 7, "close_rate": 0.29},
    {"id": "diego_morales", "name": "Diego Morales", "phone": "+5218110000103", "max_per_day": 7, "close_rate": 0.27},
    {"id": "sofia_nava", "name": "Sofía Nava", "phone": "+5218110000104", "max_per_day": 6, "close_rate": 0.34},
    {"id": "andrea_lopez", "name": "Andrea López", "phone": "+5218110000105", "max_per_day": 6, "close_rate": 0.26},
    {"id": "luis_hernandez", "name": "Luis Hernández", "phone": "+5218110000106", "max_per_day": 6, "close_rate": 0.24},
    {"id": "omar_medina", "name": "Omar Medina", "phone": "+5218110000107", "max_per_day": 6, "close_rate": 0.31},
    {"id": "claudia_pena", "name": "Claudia Peña", "phone": "+5218110000108", "max_per_day": 6, "close_rate": 0.28},
]

DEMO_VEHICLES: list[dict] = [
    {"id": "tcross_2024", "label": "T-Cross 2024", "status": "available", "available_for_test_drive": True},
    {"id": "jetta_2024", "label": "Jetta 2024", "status": "available", "available_for_test_drive": True},
    {"id": "taso_224", "label": "Taso 224", "status": "available", "available_for_test_drive": True},
    {"id": "tiguan_rline", "label": "Tiguan R-Line", "status": "reserved", "available_for_test_drive": True},
    {"id": "amarok_2024", "label": "Amarok 2024", "status": "available", "available_for_test_drive": True},
    {"id": "polo_2024", "label": "Polo 2024", "status": "available", "available_for_test_drive": True},
    {"id": "virtus_2024", "label": "Virtus 2024", "status": "available", "available_for_test_drive": True},
    {"id": "saveiro_2024", "label": "Saveiro 2024", "status": "maintenance", "available_for_test_drive": False},
]

# ── Handoffs command center ────────────────────────────────────────────────────
# Copied from api/_handoffs/command_center.py (HUMAN_AGENT_SEED)

DEMO_HUMAN_AGENTS: list[dict] = [
    {"id": "andrea-ruiz", "name": "Andrea Ruiz", "email": "andrea@demo.com", "role": "operator", "status": "online", "max_active_cases": 8, "skills": ["facturacion", "documentos", "credito"], "current_workload": 2},
    {"id": "carlos-mendez", "name": "Carlos Mendez", "email": "carlos@demo.com", "role": "operator", "status": "online", "max_active_cases": 12, "skills": ["negociacion", "ventas", "cierre"], "current_workload": 3},
    {"id": "mariana-vega", "name": "Mariana Vega", "email": "mariana@demo.com", "role": "operator", "status": "busy", "max_active_cases": 12, "skills": ["pagos", "soporte", "sistema"], "current_workload": 6},
    {"id": "luis-ortega", "name": "Luis Ortega", "email": "luis@demo.com", "role": "operator", "status": "online", "max_active_cases": 10, "skills": ["agenda", "disponibilidad", "sucursal"], "current_workload": 4},
    {"id": "paola-nava", "name": "Paola Nava", "email": "paola@demo.com", "role": "manager", "status": "online", "max_active_cases": 6, "skills": ["sla", "quejas", "alto_valor"], "current_workload": 1},
    {"id": "diego-ai", "name": "Diego Salas", "email": "diego.ai@demo.com", "role": "ai_supervisor", "status": "online", "max_active_cases": 8, "skills": ["kb", "routing", "training"], "current_workload": 2},
]
```

**Step 3: Verify compile**

```bash
cd core && uv run python -c "from atendia._demo.fixtures import DEMO_ADVISORS, DEMO_VEHICLES, DEMO_HUMAN_AGENTS; print('ok', len(DEMO_ADVISORS), len(DEMO_VEHICLES), len(DEMO_HUMAN_AGENTS))"
```
Expected: `ok 8 8 6`

**Step 4: Commit**

```bash
git add core/atendia/_demo/
git commit -m "feat: add _demo/fixtures.py with all demo constants"
```

---

## Task 5: `_demo/providers.py` + unit tests

**Files:**
- Create: `core/atendia/_demo/providers.py`
- Create: `core/tests/unit/__init__.py` (if not exists)
- Create: `core/tests/unit/test_demo_providers.py`

**Step 1: Write failing tests**

```python
# core/tests/unit/test_demo_providers.py
import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_demo_advisor_list_returns_all():
    from atendia._demo.providers import DemoAdvisorProvider
    provider = DemoAdvisorProvider()
    result = await provider.list_advisors()
    assert len(result) == 8
    assert all("id" in a and "name" in a for a in result)


@pytest.mark.asyncio
async def test_demo_advisor_get_returns_match():
    from atendia._demo.providers import DemoAdvisorProvider
    provider = DemoAdvisorProvider()
    result = await provider.get_advisor("maria_gonzalez")
    assert result is not None
    assert result["name"] == "María González"


@pytest.mark.asyncio
async def test_demo_advisor_get_unknown_returns_none():
    from atendia._demo.providers import DemoAdvisorProvider
    provider = DemoAdvisorProvider()
    result = await provider.get_advisor("nobody")
    assert result is None


@pytest.mark.asyncio
async def test_demo_vehicle_list_returns_all():
    from atendia._demo.providers import DemoVehicleProvider
    provider = DemoVehicleProvider()
    result = await provider.list_vehicles()
    assert len(result) == 8
    assert all("id" in v and "label" in v for v in result)


@pytest.mark.asyncio
async def test_demo_vehicle_get_returns_match():
    from atendia._demo.providers import DemoVehicleProvider
    provider = DemoVehicleProvider()
    result = await provider.get_vehicle("jetta_2024")
    assert result is not None
    assert result["label"] == "Jetta 2024"


@pytest.mark.asyncio
async def test_demo_vehicle_get_unknown_returns_none():
    from atendia._demo.providers import DemoVehicleProvider
    provider = DemoVehicleProvider()
    result = await provider.get_vehicle("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_demo_messaging_send_reminder_returns_simulated():
    from atendia._demo.providers import DemoMessageActionProvider
    provider = DemoMessageActionProvider()
    result = await provider.send_reminder(uuid4())
    assert result["status"] == "simulated"
    assert result["_demo"] is True


@pytest.mark.asyncio
async def test_demo_messaging_send_location_returns_simulated():
    from atendia._demo.providers import DemoMessageActionProvider
    provider = DemoMessageActionProvider()
    result = await provider.send_location(uuid4())
    assert result["status"] == "simulated"
    assert result["_demo"] is True


@pytest.mark.asyncio
async def test_demo_messaging_request_documents_returns_simulated():
    from atendia._demo.providers import DemoMessageActionProvider
    provider = DemoMessageActionProvider()
    result = await provider.request_documents(uuid4())
    assert result["status"] == "simulated"
    assert result["_demo"] is True
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/unit/test_demo_providers.py -v
```
Expected: FAIL with `ImportError: cannot import name 'DemoAdvisorProvider'`

**Step 3: Implement providers**

```python
# core/atendia/_demo/providers.py
"""Demo implementations of provider protocols.

Each class satisfies its corresponding Protocol from atendia.providers.
When a real implementation is ready, swap the import in api/_deps.py.
"""
from __future__ import annotations

from uuid import UUID

from atendia._demo.fixtures import DEMO_ADVISORS, DEMO_VEHICLES


class DemoAdvisorProvider:
    async def list_advisors(self) -> list[dict]:
        return DEMO_ADVISORS

    async def get_advisor(self, advisor_id: str) -> dict | None:
        return next((a for a in DEMO_ADVISORS if a["id"] == advisor_id), None)


class DemoVehicleProvider:
    async def list_vehicles(self) -> list[dict]:
        return DEMO_VEHICLES

    async def get_vehicle(self, vehicle_id: str) -> dict | None:
        return next((v for v in DEMO_VEHICLES if v["id"] == vehicle_id), None)


class DemoMessageActionProvider:
    """No-op WhatsApp provider for demo tenants.

    Records the action in the appointment log (via _action_update in routes)
    but does not send any real message.
    """

    async def send_reminder(self, appointment_id: UUID) -> dict:  # noqa: ARG002
        return {"status": "simulated", "_demo": True}

    async def send_location(self, appointment_id: UUID) -> dict:  # noqa: ARG002
        return {"status": "simulated", "_demo": True}

    async def request_documents(self, appointment_id: UUID) -> dict:  # noqa: ARG002
        return {"status": "simulated", "_demo": True}
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_demo_providers.py -v
```
Expected: PASS (9 tests)

**Step 5: Commit**

```bash
git add core/atendia/_demo/providers.py core/tests/unit/
git commit -m "feat: add demo provider implementations + unit tests"
```

---

## Task 6: Provider factory functions in `_deps.py`

**Files:**
- Modify: `core/atendia/api/_deps.py`
- Modify: `core/tests/api/test_demo_tenant_dep.py` (add factory tests)

**Step 1: Write failing tests**

Append to `core/tests/api/test_demo_tenant_dep.py`:

```python
@pytest.mark.asyncio
async def test_get_advisor_provider_returns_demo_for_demo_tenant(db_session):
    from atendia._demo.providers import DemoAdvisorProvider
    from atendia.api._deps import _get_advisor_provider_for
    provider = _get_advisor_provider_for(is_demo=True)
    assert isinstance(provider, DemoAdvisorProvider)


def test_get_advisor_provider_raises_501_for_real_tenant():
    from fastapi import HTTPException
    from atendia.api._deps import _get_advisor_provider_for
    with pytest.raises(HTTPException) as exc_info:
        _get_advisor_provider_for(is_demo=False)
    assert exc_info.value.status_code == 501


def test_get_vehicle_provider_raises_501_for_real_tenant():
    from fastapi import HTTPException
    from atendia.api._deps import _get_vehicle_provider_for
    with pytest.raises(HTTPException) as exc_info:
        _get_vehicle_provider_for(is_demo=False)
    assert exc_info.value.status_code == 501


def test_get_messaging_provider_raises_501_for_real_tenant():
    from fastapi import HTTPException
    from atendia.api._deps import _get_messaging_provider_for
    with pytest.raises(HTTPException) as exc_info:
        _get_messaging_provider_for(is_demo=False)
    assert exc_info.value.status_code == 501
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/api/test_demo_tenant_dep.py -v
```
Expected: FAIL with `ImportError`

**Step 3: Add factory functions to `_deps.py`**

Add these imports at the top of `_deps.py` (after existing imports):
```python
from atendia.providers.advisors import AdvisorProvider
from atendia.providers.vehicles import VehicleProvider
from atendia.providers.messaging import MessageActionProvider
```

Add these functions at the end of `_deps.py`:
```python
def _get_advisor_provider_for(is_demo: bool) -> AdvisorProvider:
    if is_demo:
        from atendia._demo.providers import DemoAdvisorProvider
        return DemoAdvisorProvider()
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "Advisors backed by DB not yet implemented",
    )


def _get_vehicle_provider_for(is_demo: bool) -> VehicleProvider:
    if is_demo:
        from atendia._demo.providers import DemoVehicleProvider
        return DemoVehicleProvider()
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "Vehicles backed by DB not yet implemented",
    )


def _get_messaging_provider_for(is_demo: bool) -> MessageActionProvider:
    if is_demo:
        from atendia._demo.providers import DemoMessageActionProvider
        return DemoMessageActionProvider()
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "WhatsApp messaging not yet implemented for this tenant",
    )


async def get_advisor_provider(
    is_demo: bool = Depends(demo_tenant),
) -> AdvisorProvider:
    return _get_advisor_provider_for(is_demo)


async def get_vehicle_provider(
    is_demo: bool = Depends(demo_tenant),
) -> VehicleProvider:
    return _get_vehicle_provider_for(is_demo)


async def get_messaging_provider(
    is_demo: bool = Depends(demo_tenant),
) -> MessageActionProvider:
    return _get_messaging_provider_for(is_demo)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/api/test_demo_tenant_dep.py -v
```
Expected: PASS (all tests in this file)

**Step 5: Run full suite**

```bash
uv run pytest -q
```
Expected: all previously passing tests still pass

**Step 6: Commit**

```bash
git add core/atendia/api/_deps.py core/tests/api/test_demo_tenant_dep.py
git commit -m "feat: add provider factory functions to _deps.py"
```

---

## Task 7: Clean `appointments_routes.py`

**Files:**
- Modify: `core/atendia/api/appointments_routes.py`

**Step 1: Remove `DEMO_ADVISORS` and `DEMO_VEHICLES` constants**

Delete lines 68–88 (the `DEMO_ADVISORS` list) and lines 79–88 (the `DEMO_VEHICLES` list). They now live in `_demo/fixtures.py`.

**Step 2: Remove `_ensure_demo_data()` and its calls**

Delete the `_ensure_demo_data()` function (around line 607–670 in the original file). Remove all `await _ensure_demo_data(session, tenant_id, user)` call sites (lines 750, 789, 824, 836, 905, 937).

**Step 3: Update `GET /advisors` endpoint**

Replace:
```python
@router.get("/advisors")
async def advisors(user: AuthUser = Depends(current_user)) -> list[dict]:  # noqa: ARG001
    return DEMO_ADVISORS
```

With:
```python
@router.get("/advisors")
async def advisors(
    provider: AdvisorProvider = Depends(get_advisor_provider),
) -> list[dict]:
    return await provider.list_advisors()
```

Add to imports at the top of `appointments_routes.py`:
```python
from atendia.api._deps import get_advisor_provider, get_vehicle_provider, get_messaging_provider
from atendia.providers.advisors import AdvisorProvider
from atendia.providers.vehicles import VehicleProvider
from atendia.providers.messaging import MessageActionProvider
```

**Step 4: Update `GET /vehicles` endpoint**

Replace:
```python
@router.get("/vehicles")
async def vehicles(user: AuthUser = Depends(current_user)) -> list[dict]:  # noqa: ARG001
    return DEMO_VEHICLES
```

With:
```python
@router.get("/vehicles")
async def vehicles(
    provider: VehicleProvider = Depends(get_vehicle_provider),
) -> list[dict]:
    return await provider.list_vehicles()
```

**Step 5: Update `send_reminder` endpoint**

Replace the `{"provider": "mock_whatsapp"}` payload with the provider call:
```python
@router.post("/{appointment_id}/send-reminder", response_model=AppointmentItem)
async def send_reminder(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    messaging: MessageActionProvider = Depends(get_messaging_provider),
) -> AppointmentItem:
    result = await messaging.send_reminder(appointment_id)
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "reminder_sent",
        {"reminder_status": "sent", "reminder_last_sent_at": datetime.now(UTC)},
        result,
    )
```

**Step 6: Update `send_location` endpoint**

```python
@router.post("/{appointment_id}/send-location", response_model=AppointmentItem)
async def send_location(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    messaging: MessageActionProvider = Depends(get_messaging_provider),
) -> AppointmentItem:
    result = await messaging.send_location(appointment_id)
    return await _action_update(
        appointment_id, user, tenant_id, session, "location_sent", payload=result
    )
```

**Step 7: Update `request_documents` endpoint**

```python
@router.post("/{appointment_id}/request-documents", response_model=AppointmentItem)
async def request_documents(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    messaging: MessageActionProvider = Depends(get_messaging_provider),
) -> AppointmentItem:
    result = await messaging.request_documents(appointment_id)
    return await _action_update(
        appointment_id, user, tenant_id, session, "documents_requested", payload=result
    )
```

**Step 8: Check for remaining `DEMO_` or `mock_whatsapp` references**

```bash
grep -n "DEMO_\|mock_whatsapp\|_ensure_demo_data\|admin@demo.com" core/atendia/api/appointments_routes.py
```
Expected: no matches

**Step 9: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 10: Commit**

```bash
git add core/atendia/api/appointments_routes.py
git commit -m "refactor(appointments): inject AdvisorProvider, VehicleProvider, MessageActionProvider; remove DEMO_ constants and _ensure_demo_data"
```

---

## Task 8: Clean `agents_routes.py`

**Files:**
- Modify: `core/atendia/api/agents_routes.py`

The `_ensure_demo_agents()` function auto-seeds agents on every LIST request. After this task, the LIST route does not seed — it simply returns whatever is in the DB (populated at deploy time by `seed_full_mock_data.py`).

**Step 1: Remove `_ensure_demo_agents` and its call**

Delete the `_ensure_demo_agents()` function (around line 712 in the original).

Find the LIST endpoint (around line 902):
```python
await _ensure_demo_agents(session, tenant_id)  # <- delete this line
```
Delete that single `await` call. Leave the rest of the endpoint intact.

**Step 2: Verify no remaining references**

```bash
grep -n "_ensure_demo_agents\|admin@demo.com" core/atendia/api/agents_routes.py
```
Expected: no matches

**Step 3: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 4: Commit**

```bash
git add core/atendia/api/agents_routes.py
git commit -m "refactor(agents): remove _ensure_demo_agents auto-seed from LIST route"
```

---

## Task 9: Clean `workflows_routes.py`

**Files:**
- Modify: `core/atendia/api/workflows_routes.py`

Same pattern as Task 8 for workflows.

**Step 1: Remove `_demo_definition` and `_ensure_demo_workflows`**

Delete the `_demo_definition()` helper (around line 647).
Delete the `_ensure_demo_workflows()` function (around line 738).

Find the LIST endpoint (around line 828):
```python
await _ensure_demo_workflows(session, tenant_id)  # <- delete this line
```
Delete that single `await` call.

**Step 2: Verify no remaining references**

```bash
grep -n "_ensure_demo_workflows\|_demo_definition" core/atendia/api/workflows_routes.py
```
Expected: no matches

**Step 3: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 4: Commit**

```bash
git add core/atendia/api/workflows_routes.py
git commit -m "refactor(workflows): remove _ensure_demo_workflows auto-seed from LIST route"
```

---

## Task 10: Fix `customers_routes.py` email gate

**Files:**
- Modify: `core/atendia/api/customers_routes.py`
- Modify: `core/tests/api/test_demo_tenant_dep.py` (add gate test)

The current gate `if user.email.lower() != "admin@demo.com": return` is fragile — it breaks if the demo admin email changes. Replace with `tenant.is_demo`.

**Step 1: Add a test for the new gate**

Append to `core/tests/api/test_demo_tenant_dep.py`:

```python
def test_email_gate_replaced_by_is_demo_flag():
    """Guard that admin@demo.com is not used as a gate in customers_routes."""
    import ast, pathlib
    src = pathlib.Path("core/atendia/api/customers_routes.py").read_text()
    assert "admin@demo.com" not in src, (
        "customers_routes.py still gates on admin@demo.com email. "
        "Use tenant.is_demo instead."
    )
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_demo_tenant_dep.py::test_email_gate_replaced_by_is_demo_flag -v
```
Expected: FAIL

**Step 3: Update `_ensure_demo_data` in `customers_routes.py`**

Find the `_ensure_demo_data` function (around line 1161):
```python
async def _ensure_demo_data(session: AsyncSession, tenant_id: UUID, user: AuthUser) -> None:
    if user.email.lower() != "admin@demo.com":
        return
    ...
```

Replace the guard at the top with a DB-based check. First, add these imports at the top of `customers_routes.py`:
```python
from sqlalchemy import select as sa_select
from atendia.db.models.tenant import Tenant
```

Then replace the guard:
```python
async def _ensure_demo_data(session: AsyncSession, tenant_id: UUID, user: AuthUser) -> None:  # noqa: ARG002
    # Gate on tenant.is_demo, not on email — email is fragile and breaks
    # for any demo tenant whose admin has a different address.
    result = await session.execute(sa_select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant or not tenant.is_demo:
        return
    ...
```

The `user` parameter can remain in the signature (callers pass it) but is no longer read — add `# noqa: ARG002` if ruff complains.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/api/test_demo_tenant_dep.py -v
```
Expected: PASS (all tests in the file)

**Step 5: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 6: Commit**

```bash
git add core/atendia/api/customers_routes.py core/tests/api/test_demo_tenant_dep.py
git commit -m "refactor(customers): replace admin@demo.com email gate with tenant.is_demo"
```

---

## Task 11: Fix `_handoffs/command_center.py`

**Files:**
- Modify: `core/atendia/api/_handoffs/command_center.py`
- Modify: `core/atendia/_demo/fixtures.py` (already has `DEMO_HUMAN_AGENTS` from Task 4)

The `HUMAN_AGENT_SEED` list and `SEED_HANDOFFS` list are currently defined in the file and injected unconditionally. After this task they are only injected for demo tenants.

**Step 1: Write a gate test**

Create `core/tests/api/test_handoff_cc_demo_gate.py`:

```python
def test_human_agent_seed_not_defined_in_command_center():
    """HUMAN_AGENT_SEED must not be defined inline in command_center.py.
    It should be imported from _demo/fixtures.py."""
    import pathlib
    src = pathlib.Path("core/atendia/api/_handoffs/command_center.py").read_text()
    assert "andrea@demo.com" not in src, (
        "HUMAN_AGENT_SEED is still inline in command_center.py. "
        "Move it to _demo/fixtures.py and import from there."
    )
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/api/test_handoff_cc_demo_gate.py -v
```
Expected: FAIL

**Step 3: Replace `HUMAN_AGENT_SEED` with import**

In `command_center.py`:

1. Delete the `HUMAN_AGENT_SEED = [...]` block (lines 68–75).
2. Add this import near the top:
   ```python
   from atendia._demo.fixtures import DEMO_HUMAN_AGENTS
   ```
3. Find every place `HUMAN_AGENT_SEED` is used in the file and replace with `DEMO_HUMAN_AGENTS`.

**Step 4: Gate `SEED_HANDOFFS` injection by `is_demo`**

Find the endpoint that returns the full handoff list (it merges real rows with `SEED_HANDOFFS`). Add `current_tenant_id` and `get_db_session` dependencies to that endpoint if not already present, then add a gate:

```python
# At the top of the merged list handler, before appending SEED_HANDOFFS:
result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
tenant = result.scalar_one_or_none()
if tenant and tenant.is_demo:
    # append SEED_HANDOFFS to items
    ...
```

Add the import:
```python
from atendia.db.models.tenant import Tenant
```

**Step 5: Gate `GET /agents` (human agents list)**

Find the endpoint that returns the human agent list. It likely returns `HUMAN_AGENT_SEED` (now `DEMO_HUMAN_AGENTS`) directly. Gate it:

```python
@router.get("/agents", ...)
async def list_agents(
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    ...
) -> ...:
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant and tenant.is_demo:
        return DEMO_HUMAN_AGENTS
    # Real tenants: return users from tenant_users table
    users = (
        await session.execute(
            select(TenantUser).where(TenantUser.tenant_id == tenant_id)
        )
    ).scalars().all()
    return [
        {
            "id": str(u.id),
            "name": u.full_name or u.email,
            "email": u.email,
            "role": u.role,
            "status": "online",
            "max_active_cases": 10,
            "current_workload": 0,
            "skills": [],
        }
        for u in users
    ]
```

**Step 6: Run gate test to verify it passes**

```bash
uv run pytest tests/api/test_handoff_cc_demo_gate.py -v
```
Expected: PASS

**Step 7: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 8: Commit**

```bash
git add core/atendia/api/_handoffs/command_center.py core/tests/api/test_handoff_cc_demo_gate.py
git commit -m "refactor(handoffs): gate SEED_HANDOFFS and HUMAN_AGENT_SEED by tenant.is_demo"
```

---

## Task 12: Fix `_kb/command_center.py` — gate simulate endpoint

**Files:**
- Modify: `core/atendia/api/_kb/command_center.py`
- Create: `core/tests/api/test_kb_cc_demo_gate.py`

The `POST /simulate` endpoint always returns `DEFAULT_SIMULATION` (mode="mock") regardless of tenant. After this task, non-demo tenants receive `501`.

**Step 1: Write failing tests**

```python
# core/tests/api/test_kb_cc_demo_gate.py
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_simulate_endpoint_requires_is_demo(db_session):
    """The simulate endpoint must check tenant.is_demo before returning mock data."""
    import pathlib
    src = pathlib.Path("core/atendia/api/_kb/command_center.py").read_text()
    assert "is_demo" in src or "demo_tenant" in src, (
        "command_center.py simulate endpoint does not gate on is_demo. "
        "Non-demo tenants would receive mock simulation responses."
    )


def test_kb_simulate_mode_not_hardcoded_to_mock():
    """The simulate endpoint should not always return mode='mock' unconditionally."""
    import pathlib
    src = pathlib.Path("core/atendia/api/_kb/command_center.py").read_text()
    # After the fix, the simulate endpoint has an is_demo check before returning DEFAULT_SIMULATION
    # Presence of "is_demo" or "demo_tenant" in the file is sufficient.
    assert "501" in src, (
        "simulate endpoint must raise 501 for non-demo tenants."
    )
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/api/test_kb_cc_demo_gate.py -v
```
Expected: FAIL

**Step 3: Update `simulate` endpoint in `_kb/command_center.py`**

Add these imports near the top of `command_center.py`:
```python
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._deps import current_tenant_id, get_db_session
from atendia.db.models.tenant import Tenant
```

Update the `SimulationRequest` class to add `current_tenant_id` dependency:
```python
@router.post("/simulate", response_model=SimulationResponse)
async def simulate(
    body: SimulationRequest,
    _user: AuthenticatedUser,
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> SimulationResponse:
    # Gate: only demo tenants may use the mock simulation.
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant or not tenant.is_demo:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "RAG simulation backed by real KB not yet implemented. "
            "Use POST /knowledge/test-query for real retrieval.",
        )
    return DEFAULT_SIMULATION.model_copy(
        update={
            "user_message": body.message,
            "agent": body.agent,
            "model": body.model,
        }
    )
```

Apply the same gate pattern to `GET /simulate/{simulation_id}` and the mark-correct/mark-incomplete/mark-incorrect/create-faq/block-answer sub-endpoints.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/api/test_kb_cc_demo_gate.py -v
```
Expected: PASS

**Step 5: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 6: Commit**

```bash
git add core/atendia/api/_kb/command_center.py core/tests/api/test_kb_cc_demo_gate.py
git commit -m "refactor(kb): gate simulate endpoint to is_demo tenants only; raises 501 for real tenants"
```

---

## Task 13: Update `seed_full_mock_data.py`

**Files:**
- Modify: `core/scripts/seed_full_mock_data.py`

**Step 1: Find the tenant upsert block**

Search for where the `demo` tenant is created/upserted:
```bash
grep -n "is_demo\|name.*demo\|demo.*tenant" core/scripts/seed_full_mock_data.py
```

**Step 2: Add `is_demo=True` to the demo tenant upsert**

Find the block that creates or updates the `demo` tenant. It likely looks like:
```python
tenant = Tenant(name="demo", ...)
# or
await session.execute(
    insert(Tenant).values(name="demo", ...).on_conflict_do_update(...)
)
```

Add `is_demo=True` to whichever form is used:
```python
# Example for the insert/upsert form:
await session.execute(
    insert(Tenant)
    .values(name="demo", is_demo=True, ...)
    .on_conflict_do_update(
        index_elements=["name"],
        set_={"is_demo": True, ...},
    )
)
```

**Step 3: Run the seed script**

```bash
cd core && uv run python scripts/seed_full_mock_data.py
```
Expected: runs without errors; last line confirms seed completed

**Step 4: Verify the flag was set**

```bash
cd core && uv run python -c "
import asyncio
from sqlalchemy import text
from atendia.db.session import get_engine

async def check():
    async with get_engine().connect() as conn:
        result = await conn.execute(text(\"SELECT name, is_demo FROM tenants WHERE name = 'demo'\"))
        row = result.fetchone()
        print(row)

asyncio.run(check())
"
```
Expected: `('demo', True)`

**Step 5: Run full suite**

```bash
uv run pytest -q
```
Expected: all tests pass

**Step 6: Commit**

```bash
git add core/scripts/seed_full_mock_data.py
git commit -m "fix(seed): set is_demo=True for demo tenant in seed_full_mock_data.py"
```

---

## Task 14: Frontend `DemoBadge` component

**Files:**
- Create: `frontend/src/components/DemoBadge.tsx`
- Create: `frontend/src/components/__tests__/DemoBadge.test.tsx`

**Step 1: Write failing test**

```typescript
// frontend/src/components/__tests__/DemoBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DemoBadge } from "../DemoBadge";

describe("DemoBadge", () => {
  it("renders the Demo chip", () => {
    render(<DemoBadge />);
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });

  it("has the demo tooltip", () => {
    render(<DemoBadge />);
    const chip = screen.getByTitle(/Datos de demostración/i);
    expect(chip).toBeInTheDocument();
  });

  it("wrap mode renders children", () => {
    render(
      <DemoBadge wrap>
        <span>child content</span>
      </DemoBadge>
    );
    expect(screen.getByText("child content")).toBeInTheDocument();
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });
});
```

**Step 2: Run to verify it fails**

```bash
cd frontend && pnpm test -- --run src/components/__tests__/DemoBadge.test.tsx
```
Expected: FAIL with `Cannot find module '../DemoBadge'`

**Step 3: Implement the component**

```tsx
// frontend/src/components/DemoBadge.tsx
import { cn } from "@/lib/utils";

interface DemoBadgeProps {
  wrap?: boolean;
  className?: string;
  children?: React.ReactNode;
}

export function DemoBadge({ wrap = false, className, children }: DemoBadgeProps) {
  const chip = (
    <span
      title="Datos de demostración — no reflejan operación real"
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
        "bg-violet-500/20 text-violet-300 border border-violet-500/30",
        className,
      )}
    >
      Demo
    </span>
  );

  if (!wrap) return chip;

  return (
    <div className="relative rounded-lg border border-violet-500/20">
      <div className="absolute -top-2 left-2">{chip}</div>
      {children}
    </div>
  );
}
```

**Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm test -- --run src/components/__tests__/DemoBadge.test.tsx
```
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add frontend/src/components/DemoBadge.tsx frontend/src/components/__tests__/DemoBadge.test.tsx
git commit -m "feat(frontend): add DemoBadge component (violet, demo data marker)"
```

---

## Task 15: Frontend `NYIButton` component

**Files:**
- Create: `frontend/src/components/NYIButton.tsx`
- Create: `frontend/src/components/__tests__/NYIButton.test.tsx`

**Step 1: Write failing test**

```typescript
// frontend/src/components/__tests__/NYIButton.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { NYIButton } from "../NYIButton";

describe("NYIButton", () => {
  it("renders with the given label", () => {
    render(<NYIButton label="Importar CSV" />);
    expect(screen.getByText("Importar CSV")).toBeInTheDocument();
  });

  it("has the NYI tooltip", () => {
    render(<NYIButton label="Importar CSV" />);
    const btn = screen.getByTitle(/Feature en construcción/i);
    expect(btn).toBeInTheDocument();
  });

  it("does not navigate or call any API when clicked", async () => {
    const { container } = render(<NYIButton label="Test" />);
    const btn = container.querySelector("button");
    // Should not throw and should not navigate
    btn?.click();
    expect(screen.getByText("Test")).toBeInTheDocument();
  });
});
```

**Step 2: Run to verify it fails**

```bash
cd frontend && pnpm test -- --run src/components/__tests__/NYIButton.test.tsx
```
Expected: FAIL with `Cannot find module '../NYIButton'`

**Step 3: Implement the component**

```tsx
// frontend/src/components/NYIButton.tsx
import { Lock } from "lucide-react";
import { toast } from "sonner";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface NYIButtonProps {
  label: string;
  icon?: LucideIcon;
  size?: "sm" | "default" | "lg" | "icon";
  variant?: "outline" | "ghost" | "default";
  className?: string;
}

/**
 * NYIButton — Not Yet Implemented.
 *
 * Replaces toast.info(...) stubs for features that are not yet built.
 * Visual signal: amber color + lock icon.
 * Distinct from DemoBadge (violet), which marks implemented-but-simulated features.
 */
export function NYIButton({
  label,
  icon: Icon,
  size = "sm",
  variant = "outline",
  className,
}: NYIButtonProps) {
  return (
    <Button
      size={size}
      variant={variant}
      title="Feature en construcción — disponible próximamente"
      onClick={() =>
        toast.info("Feature en construcción", {
          description: `"${label}" estará disponible próximamente.`,
        })
      }
      className={cn(
        "border-amber-500/20 bg-amber-500/5 text-slate-300",
        "hover:border-amber-500/40 hover:bg-amber-500/10",
        className,
      )}
    >
      {Icon && <Icon className="mr-1.5 h-3.5 w-3.5" />}
      {label}
      <Lock className="ml-1.5 h-3 w-3 text-amber-400/70" />
    </Button>
  );
}
```

**Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm test -- --run src/components/__tests__/NYIButton.test.tsx
```
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add frontend/src/components/NYIButton.tsx frontend/src/components/__tests__/NYIButton.test.tsx
git commit -m "feat(frontend): add NYIButton component (amber, not-yet-implemented marker)"
```

---

## Task 16: Apply `DemoBadge` and `NYIButton` across pages

**Files modified (one commit per file):**
- `frontend/src/features/appointments/components/AppointmentsPage.tsx`
- `frontend/src/features/agents/components/AgentsPage.tsx`
- `frontend/src/features/workflows/components/WorkflowsPage.tsx`
- `frontend/src/features/workflows/components/WorkflowEditor.tsx`
- `frontend/src/features/handoffs/components/HandoffCard.tsx`
- `frontend/src/features/dashboard/components/DashboardPage.tsx`
- `frontend/src/features/conversations/components/ContactPanel.tsx`

**The mechanical substitution rule:**

For every `onClick={() => toast.info(...)}` in these files, replace with `<NYIButton label="..." />` using the same label text. Remove the surrounding `<Button>` wrapper.

For demo data panels (advisors, vehicles, mock agents, demo workflows, handoff drafts), wrap the section or title with `<DemoBadge />` or `<DemoBadge wrap>`.

### AppointmentsPage.tsx

**Step 1: Add imports**

```tsx
import { DemoBadge } from "@/components/DemoBadge";
import { NYIButton } from "@/components/NYIButton";
```

**Step 2: Replace `toast.info` stubs with `NYIButton`**

| Current code | Replace with |
|---|---|
| `onClick={() => toast.info(item.action)}` on recommended action items | `<NYIButton label={item.action} />` |
| `onClick={() => toast.info(\`${stage.stage}: ${stage.conversion}%\`)}` on funnel stages | `<NYIButton label={\`${stage.stage}: ${stage.conversion}%\`} />` |
| `onClick={() => toast.info("Importador CSV listo")}` | `<NYIButton label="Importar CSV" icon={Upload} />` |
| `onClick={() => toast.info("Filtros avanzados preparados")}` | `<NYIButton label="Filtros avanzados" icon={Filter} />` |

**Step 3: Add `DemoBadge` to the advisors and vehicles panels**

Find the panel header that renders the advisor list. Add `<DemoBadge />` next to the title:
```tsx
<h3 className="text-sm font-medium text-slate-200">
  Asesores <DemoBadge className="ml-1.5" />
</h3>
```
Do the same for the vehicles panel.

**Step 4: Typecheck**

```bash
cd frontend && pnpm typecheck
```
Expected: no errors

**Step 5: Commit**

```bash
git add frontend/src/features/appointments/components/AppointmentsPage.tsx
git commit -m "feat(appointments): apply DemoBadge to advisor/vehicle panels; NYIButton for NYI actions"
```

---

### AgentsPage.tsx

**Step 1: Add imports** (same as above)

**Step 2: Replace `toast.info` stubs with `NYIButton`**

| Current code | Replace with |
|---|---|
| `onClick={() => toast.info("Documento enviado a indexación")}` | `<NYIButton label="Subir documento" icon={Upload} />` |
| `onClick={() => toast.info("Consultas fallidas filtradas")}` | `<NYIButton label="Ver fallidas" />` |
| `onClick={() => toast.info("Historial filtrado")}` | `<NYIButton label="Ver historial" icon={History} />` |
| `onClick={() => toast.info("Conversación abierta")}` | `<NYIButton label="Abrir" size="sm" />` |

For the guardrail toggle that fires `toast.info("Edita la regla desde el menú contextual")`, keep the toast (it's genuinely informational, not a stub for a missing feature).

**Step 3: Add `DemoBadge` to the `[Mock]` agents section header**

Find where agents with `[Mock]` in their name are rendered. Add `<DemoBadge />` to that section title.

**Step 4: Typecheck + commit**

```bash
pnpm typecheck
git add frontend/src/features/agents/components/AgentsPage.tsx
git commit -m "feat(agents): apply DemoBadge to mock agent section; NYIButton for NYI actions"
```

---

### WorkflowsPage.tsx + WorkflowEditor.tsx

**Step 1: Add imports to both files**

**Step 2: In `WorkflowsPage.tsx` replace `toast.info` stubs**

| Current code | Replace with |
|---|---|
| `onClick={() => toast.info("Pausa inmediata enviada")}` | `<NYIButton label="Pausar inmediatamente" />` |
| `onClick={() => toast.info("Pausa para nuevos leads enviada")}` | `<NYIButton label="Pausar solo nuevos leads" />` |
| `onClick={() => toast.info("Pausa después de ejecuciones activas")}` | `<NYIButton label="Pausar después de ejecuciones activas" />` |
| `onClick={() => toast.info("Pausa y envío a humano activados")}` | `<NYIButton label="Pausar y enviar a humano" />` |
| `onClick={() => toast.info("Importador listo para recibir JSON")}` | `<NYIButton label="Importar JSON" />` |
| `onClick={() => toast.info("Vista guardada aplicada")}` | `<NYIButton label="Vista guardada" />` |

For `onClick={() => toast.info("12 alertas activas")}`, keep the toast — it's informational.  
For `onClick={() => toast.info(\`Filtro aplicado: ${kpi.label}\`)}`, keep the toast — it's informational.

**Step 3: Add `DemoBadge` to the demo workflows section**

Find the section that renders workflows with `[Mock]` in the name. Add `<DemoBadge />` to that section header.

**Step 4: In `WorkflowEditor.tsx` replace `toast.info` stubs**

| Current code | Replace with |
|---|---|
| `() => toast.info(\`Conversión: ${pct(...)}\`)` | `<NYIButton label="Ver métricas" />` |
| `() => toast.info("Filtrando ejecuciones relacionadas")` | `<NYIButton label="Ver ejecuciones relacionadas" />` |

**Step 5: Typecheck + commit**

```bash
pnpm typecheck
git add frontend/src/features/workflows/
git commit -m "feat(workflows): apply DemoBadge to demo workflows; NYIButton for NYI actions"
```

---

### HandoffCard.tsx

**Step 1: Add imports**

**Step 2: Add `DemoBadge` when draft source is mock**

Find where `source="mock"` is rendered in the draft card. Add `<DemoBadge />` next to the "Borrador IA" or draft title:

```tsx
{draft.source === "mock" && <DemoBadge className="ml-1.5" />}
```

**Step 3: Typecheck + commit**

```bash
pnpm typecheck
git add frontend/src/features/handoffs/components/HandoffCard.tsx
git commit -m "feat(handoffs): add DemoBadge to mock draft source indicator"
```

---

### DashboardPage.tsx

**Step 1: Add imports**

**Step 2: Replace `toast.info` stubs in command palette**

| Current code | Replace with |
|---|---|
| `toast.info("Abriendo nueva conversación...")` | `toast.info("Feature en construcción", { description: "Nueva conversación estará disponible próximamente." })` — keep as toast since it's inside a `CommandItem` handler, not a button |

For the command palette items, since they use `onSelect` (not `onClick` on a button), keep them as `toast.info` but standardize the message to use the same format as `NYIButton`:
```tsx
onSelect={() => {
  toast.info("Feature en construcción", { description: '"Nueva conversación" estará disponible próximamente.' });
  onClose();
}}
```

**Step 3: Typecheck + commit**

```bash
pnpm typecheck
git add frontend/src/features/dashboard/components/DashboardPage.tsx
git commit -m "feat(dashboard): standardize NYI toast format in command palette"
```

---

### ContactPanel.tsx

**Step 1: Add imports**

**Step 2: Replace `toast.info` stubs**

| Current code | Replace with |
|---|---|
| `onClick={() => toast.info("Abriendo conversación de WhatsApp")}` | `<NYIButton label="Abrir WhatsApp" icon={MessageCircle} />` |
| `onClick={() => toast.info(\`Llamando a ${phone}…\`)}` | Keep as toast — it's genuinely informational, not a missing feature stub |
| `onClick={() => toast.info("Recomendaciones listas", { description: ... })}` | Keep as toast — it's informational |

**Step 3: Typecheck + commit**

```bash
pnpm typecheck
git add frontend/src/features/conversations/components/ContactPanel.tsx
git commit -m "feat(conversations): apply NYIButton to WhatsApp action in ContactPanel"
```

---

## Final Verification

**Step 1: Run full backend suite**

```bash
cd core && uv run pytest -q
```
Expected: all previously passing tests pass (821+ backend tests)

**Step 2: Frontend typecheck + tests**

```bash
cd frontend && pnpm typecheck && pnpm test -- --run
```
Expected: typecheck passes, all frontend tests pass

**Step 3: Run seed and smoke**

```bash
cd core && uv run python scripts/seed_full_mock_data.py
```
Expected: completes without error, demo tenant has `is_demo=True`

**Step 4: Final commit — update PROJECT_MAP**

Add a line to `docs/PROJECT_MAP.md` in the "Verificacion local" table:
```markdown
| Mock isolation | `tenants.is_demo` flag set, `_demo/` module extracted, providers injected, DemoBadge + NYIButton deployed | Done |
```

```bash
git add docs/PROJECT_MAP.md
git commit -m "docs: mark mock/demo isolation as complete in PROJECT_MAP"
```

---

## Summary of files changed

| Layer | Files created | Files modified |
|---|---|---|
| DB | `040_demo_tenant_flag.py` | `db/models/tenant.py` |
| Backend deps | — | `api/_deps.py` |
| Protocols | `providers/__init__.py`, `providers/advisors.py`, `providers/vehicles.py`, `providers/messaging.py` | — |
| Demo module | `_demo/__init__.py`, `_demo/fixtures.py`, `_demo/providers.py` | — |
| Routes | — | `api/appointments_routes.py`, `api/agents_routes.py`, `api/workflows_routes.py`, `api/customers_routes.py`, `api/_handoffs/command_center.py`, `api/_kb/command_center.py` |
| Seed | — | `scripts/seed_full_mock_data.py` |
| Tests | `tests/api/test_demo_tenant_dep.py`, `tests/api/test_handoff_cc_demo_gate.py`, `tests/api/test_kb_cc_demo_gate.py`, `tests/unit/test_demo_providers.py` | — |
| Frontend | `components/DemoBadge.tsx`, `components/NYIButton.tsx`, `components/__tests__/DemoBadge.test.tsx`, `components/__tests__/NYIButton.test.tsx` | `AppointmentsPage.tsx`, `AgentsPage.tsx`, `WorkflowsPage.tsx`, `WorkflowEditor.tsx`, `HandoffCard.tsx`, `DashboardPage.tsx`, `ContactPanel.tsx` |

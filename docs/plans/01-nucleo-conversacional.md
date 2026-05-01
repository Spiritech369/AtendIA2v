# AtendIA v2 — Fase 1: Núcleo Conversacional — Plan de Implementación

> **Para Claude:** SUB-SKILL REQUERIDA: Usar `superpowers:executing-plans` para implementar este plan tarea por tarea.

**Goal:** Construir el núcleo conversacional de AtendIA v2 sin LLM ni WhatsApp: modelo de datos completo en Postgres, máquina de estados parametrizada por tenant que ejecuta flujos de venta canned, tools tipadas con stubs, y suite de fixtures que validan que el motor procesa conversaciones predecibles correctamente.

**Architecture:** Paquete Python nuevo en `core/` (separado de `ai-engine/` v1). Base de datos Postgres separada `atendia_v2`. Pipeline definitions como JSONB en DB (data-driven, no código). Pydantic v2 para todos los contratos. SQLAlchemy 2.0 async para acceso a DB. Alembic para migraciones reversibles. Sin LLM, sin WhatsApp; entradas y salidas son JSON canned para esta fase.

**Tech Stack:** Python 3.12 · FastAPI 0.115+ · SQLAlchemy 2.0 async · asyncpg · Pydantic 2.9+ · Alembic · pytest + pytest-asyncio · uv (gestor de dependencias) · ruff (linter+format) · Postgres 15+ · Redis 7+.

**Pre-requisitos del entorno:**
- Python 3.12 instalado.
- Postgres 15+ corriendo localmente (puerto 5432 o 5433 si choca con v1).
- Redis 7+ corriendo localmente.
- `uv` instalado (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Acceso a este repo en una rama de trabajo: `git checkout -b feat/v2-nucleo-conversacional`.

**Decisiones de implementación fijas (modificables si se justifican antes de empezar):**
1. **Estructura:** monorepo, directorios nuevos `core/`, `contracts/`, `database/migrations-v2/`. No tocar `ai-engine/`, `gateway/`, `frontend/`, `database/migrations/` v1.
2. **DB:** Postgres separado `atendia_v2`. Connection string distinto al v1.
3. **Estilo de plan:** TDD estricto donde aplique. Cada tarea termina en commit verificado.

---

## Mapa de tareas

| Bloque | Tareas | Duración estimada |
|---|---|---|
| **A.** Setup del proyecto | T1–T6 | 1–2 días |
| **B.** Contratos canónicos (JSON Schema → Pydantic) | T7–T12 | 2 días |
| **C.** Schema Postgres + migraciones | T13–T22 | 3–4 días |
| **D.** State machine engine (sin LLM) | T23–T29 | 4–5 días |
| **E.** Tools tipadas con stubs | T30–T35 | 2 días |
| **F.** Conversation runner + persistencia de turn_traces | T36–T39 | 2–3 días |
| **G.** Fixtures + verificación E2E | T40–T44 | 2 días |
| **TOTAL** | **44 tareas** | **~16–20 días hábiles (3 semanas)** |

---

# Bloque A — Setup del proyecto

## Task 1: Crear estructura de directorios v2

**Files:**
- Create: `core/` (directorio)
- Create: `contracts/` (directorio)
- Create: `database/migrations-v2/` (directorio)
- Create: `core/.gitkeep`, `contracts/.gitkeep`, `database/migrations-v2/.gitkeep`

**Step 1: Crear directorios**

```bash
mkdir -p core contracts database/migrations-v2
touch core/.gitkeep contracts/.gitkeep database/migrations-v2/.gitkeep
```

**Step 2: Verificar que existen**

```bash
ls -la core contracts database/migrations-v2
```

Expected: tres directorios listados.

**Step 3: Commit**

```bash
git add core/.gitkeep contracts/.gitkeep database/migrations-v2/.gitkeep
git commit -m "chore(v2): scaffold core/, contracts/, migrations-v2/ directories"
```

---

## Task 2: Inicializar proyecto Python en `core/` con `uv`

**Files:**
- Create: `core/pyproject.toml`
- Create: `core/uv.lock` (generado)
- Create: `core/.python-version`
- Create: `core/README.md`

**Step 1: Inicializar proyecto**

```bash
cd core
uv init --name atendia-core --python 3.12
```

**Step 2: Editar `core/pyproject.toml`**

```toml
[project]
name = "atendia-core"
version = "0.1.0"
description = "AtendIA v2 - Núcleo conversacional"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.35",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "redis>=5.1.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.5.0",
    "python-dotenv>=1.0.1",
    "structlog>=24.4.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
    "datamodel-code-generator>=0.26.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "RUF"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 3: Sincronizar dependencias**

```bash
cd core
uv sync
```

Expected: `uv.lock` creado, `.venv/` creado, paquetes instalados.

**Step 4: Smoke test del entorno**

```bash
cd core
uv run python -c "import fastapi, sqlalchemy, pydantic, alembic; print('OK')"
```

Expected: `OK`

**Step 5: Commit**

```bash
git add core/pyproject.toml core/uv.lock core/.python-version
git commit -m "chore(core): initialize Python 3.12 project with uv"
```

---

## Task 3: Layout interno de `core/`

**Files:**
- Create: `core/atendia/__init__.py`
- Create: `core/atendia/config.py`
- Create: `core/atendia/db/__init__.py`
- Create: `core/atendia/contracts/__init__.py`
- Create: `core/atendia/state_machine/__init__.py`
- Create: `core/atendia/tools/__init__.py`
- Create: `core/atendia/runner/__init__.py`
- Create: `core/tests/__init__.py`
- Create: `core/tests/conftest.py` (vacío por ahora)

**Step 1: Crear estructura**

```bash
mkdir -p core/atendia/{db,contracts,state_machine,tools,runner}
mkdir -p core/tests
touch core/atendia/__init__.py
touch core/atendia/{db,contracts,state_machine,tools,runner}/__init__.py
touch core/tests/__init__.py core/tests/conftest.py
```

**Step 2: Crear `core/atendia/config.py`**

```python
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ATENDIA_V2_",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2"
    )
    redis_url: str = Field(default="redis://localhost:6379/1")
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Step 3: Smoke test**

```bash
cd core
uv run python -c "from atendia.config import get_settings; print(get_settings().database_url)"
```

Expected: `postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2`

**Step 4: Commit**

```bash
git add core/atendia core/tests
git commit -m "feat(core): add package layout and Settings"
```

---

## Task 4: Docker Compose para Postgres v2 + Redis v2

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

**Step 1: Crear `docker-compose.yml`** en la raíz del repo

```yaml
services:
  postgres-v2:
    image: postgres:15-alpine
    container_name: atendia_postgres_v2
    restart: unless-stopped
    environment:
      POSTGRES_USER: atendia
      POSTGRES_PASSWORD: atendia
      POSTGRES_DB: atendia_v2
    ports:
      - "5433:5432"
    volumes:
      - atendia_v2_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U atendia -d atendia_v2"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis-v2:
    image: redis:7-alpine
    container_name: atendia_redis_v2
    restart: unless-stopped
    ports:
      - "6380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  atendia_v2_pg_data:
```

**Nota:** puertos no estándar (5433, 6380) para no chocar con v1.

**Step 2: Crear `.env.example`** en la raíz

```
ATENDIA_V2_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2
ATENDIA_V2_REDIS_URL=redis://localhost:6380/0
ATENDIA_V2_LOG_LEVEL=INFO
```

**Step 3: Levantar servicios**

```bash
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
```

Expected: ambos contenedores `healthy`.

**Step 4: Verificar conexión**

```bash
docker exec -it atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT version();"
docker exec -it atendia_redis_v2 redis-cli ping
```

Expected: versión de Postgres impresa; `PONG`.

**Step 5: Crear `core/.env`** copiando del example y ajustando puertos

```bash
cp .env.example core/.env
# Editar core/.env: cambiar 5432→5433 y 6379→6380 si no están ya
```

**Step 6: Re-test config con DB real**

```bash
cd core
uv run python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from atendia.config import get_settings

async def ping():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        result = await conn.execute(__import__('sqlalchemy').text('SELECT 1'))
        print('DB:', result.scalar())
    await engine.dispose()

asyncio.run(ping())
"
```

Expected: `DB: 1`

**Step 7: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore(v2): add docker-compose for separate postgres + redis"
```

---

## Task 5: Configurar Alembic para `atendia_v2`

**Files:**
- Create: `core/alembic.ini`
- Create: `core/atendia/db/migrations/env.py`
- Create: `core/atendia/db/migrations/script.py.mako`
- Create: `core/atendia/db/migrations/versions/.gitkeep`
- Create: `core/atendia/db/base.py`

**Step 1: Inicializar Alembic**

```bash
cd core
uv run alembic init -t async atendia/db/migrations
```

**Step 2: Editar `core/alembic.ini`**

Cambiar línea de `sqlalchemy.url`:

```ini
sqlalchemy.url =
```

(Vacía — la leemos desde Settings en `env.py`.)

Cambiar `script_location`:

```ini
script_location = atendia/db/migrations
```

**Step 3: Crear `core/atendia/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for AtendIA v2 ORM models."""
```

**Step 4: Editar `core/atendia/db/migrations/env.py`**

Reemplazar contenido por:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from atendia.config import get_settings
from atendia.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 5: Smoke test de Alembic**

```bash
cd core
uv run alembic current
```

Expected: salida vacía o "(no current revision)" — pero sin error.

**Step 6: Commit**

```bash
git add core/alembic.ini core/atendia/db/
git commit -m "feat(core): configure Alembic with async support"
```

---

## Task 6: CI baseline — GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Crear workflow**

```yaml
name: v2-core CI

on:
  push:
    branches: [main]
    paths:
      - "core/**"
      - "contracts/**"
      - ".github/workflows/ci.yml"
  pull_request:
    paths:
      - "core/**"
      - "contracts/**"
      - ".github/workflows/ci.yml"

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER: atendia
          POSTGRES_PASSWORD: atendia
          POSTGRES_DB: atendia_v2_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U atendia"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Set up Python
        run: uv python install 3.12
      - name: Install deps
        working-directory: core
        run: uv sync
      - name: Lint
        working-directory: core
        run: uv run ruff check . && uv run ruff format --check .
      - name: Run migrations
        working-directory: core
        env:
          ATENDIA_V2_DATABASE_URL: postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2_test
        run: uv run alembic upgrade head
      - name: Run tests
        working-directory: core
        env:
          ATENDIA_V2_DATABASE_URL: postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2_test
          ATENDIA_V2_REDIS_URL: redis://localhost:6379/0
        run: uv run pytest -v
```

**Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(v2): add CI workflow for core (lint + migrate + test)"
```

**Step 3: Push y verificar que el workflow corra (verde)**

```bash
git push origin feat/v2-nucleo-conversacional
```

Verificar en GitHub Actions: workflow `v2-core CI` corre y pasa (puede fallar si aún no hay tests, pero lint y migrations deben pasar). Si falla, **arreglar antes de continuar al Bloque B.**

---

# Bloque B — Contratos canónicos

> **Patrón general de los siguientes 6 tasks:** definimos el contrato como JSON Schema en `contracts/`, generamos modelo Pydantic en `core/atendia/contracts/`, escribimos test que valida que un payload válido parsea y un payload inválido falla.

## Task 7: Schema canónico — `Message`

**Files:**
- Create: `contracts/message.schema.json`
- Create: `core/atendia/contracts/message.py`
- Create: `core/tests/contracts/__init__.py`
- Create: `core/tests/contracts/test_message.py`

**Step 1: Escribir test failing**

`core/tests/contracts/test_message.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from atendia.contracts.message import Message, MessageDirection


def test_message_inbound_text_valid():
    msg = Message(
        id="01J3Z6V8N1Q4WZS5MXY9KQHF7C",
        conversation_id="01J3Z6V8N1Q4WZS5MXY9KQHF7D",
        tenant_id="dinamomotos",
        direction=MessageDirection.INBOUND,
        text="Hola, info de la 150Z",
        sent_at=datetime(2026, 4, 30, 14, 0, tzinfo=timezone.utc),
    )
    assert msg.direction == MessageDirection.INBOUND
    assert msg.text == "Hola, info de la 150Z"


def test_message_missing_required_field_raises():
    with pytest.raises(ValidationError):
        Message(  # type: ignore[call-arg]
            id="x",
            conversation_id="y",
            tenant_id="z",
            direction=MessageDirection.INBOUND,
        )


def test_message_invalid_direction_raises():
    with pytest.raises(ValidationError):
        Message(
            id="x",
            conversation_id="y",
            tenant_id="z",
            direction="sideways",  # type: ignore[arg-type]
            text="hi",
            sent_at=datetime.now(timezone.utc),
        )
```

**Step 2: Correr test, debe fallar**

```bash
cd core && uv run pytest tests/contracts/test_message.py -v
```

Expected: `ImportError: cannot import name 'Message' from 'atendia.contracts.message'`

**Step 3: Crear `contracts/message.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://atendia.io/contracts/message.schema.json",
  "title": "Message",
  "description": "A message exchanged in a conversation, inbound or outbound.",
  "type": "object",
  "required": ["id", "conversation_id", "tenant_id", "direction", "text", "sent_at"],
  "properties": {
    "id": { "type": "string" },
    "conversation_id": { "type": "string" },
    "tenant_id": { "type": "string" },
    "direction": { "type": "string", "enum": ["inbound", "outbound", "system"] },
    "text": { "type": "string" },
    "sent_at": { "type": "string", "format": "date-time" },
    "channel_message_id": { "type": ["string", "null"] },
    "delivery_status": {
      "type": ["string", "null"],
      "enum": [null, "queued", "sent", "delivered", "read", "failed"]
    },
    "metadata": { "type": "object" }
  }
}
```

**Step 4: Implementar `core/atendia/contracts/message.py`**

```python
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class Message(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    conversation_id: str
    tenant_id: str
    direction: MessageDirection
    text: str
    sent_at: datetime
    channel_message_id: str | None = None
    delivery_status: DeliveryStatus | None = None
    metadata: dict = Field(default_factory=dict)
```

**Step 5: Correr test, debe pasar**

```bash
cd core && uv run pytest tests/contracts/test_message.py -v
```

Expected: 3 passed.

**Step 6: Commit**

```bash
git add contracts/message.schema.json core/atendia/contracts/message.py core/tests/contracts/
git commit -m "feat(contracts): add Message schema and Pydantic model"
```

---

## Task 8: Schema canónico — `Event`

Mismo patrón que Task 7. Eventos representan cambios atómicos del sistema (mensaje recibido, estado cambió, tool llamada, etc.).

**Files:**
- Create: `contracts/event.schema.json`
- Create: `core/atendia/contracts/event.py`
- Create: `core/tests/contracts/test_event.py`

**Step 1: Test failing**

`core/tests/contracts/test_event.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from atendia.contracts.event import Event, EventType


def test_event_message_received_valid():
    evt = Event(
        id="01J3Z6V8N1Q4WZS5MXY9KQHF8A",
        conversation_id="01J3Z6V8N1Q4WZS5MXY9KQHF8B",
        tenant_id="dinamomotos",
        type=EventType.MESSAGE_RECEIVED,
        payload={"message_id": "01J3Z6V8N1Q4WZS5MXY9KQHF8C"},
        occurred_at=datetime.now(timezone.utc),
    )
    assert evt.type == EventType.MESSAGE_RECEIVED


def test_event_invalid_type_raises():
    with pytest.raises(ValidationError):
        Event(
            id="x",
            conversation_id="y",
            tenant_id="z",
            type="banana",  # type: ignore[arg-type]
            payload={},
            occurred_at=datetime.now(timezone.utc),
        )
```

**Step 2: Correr, debe fallar (ImportError).**

**Step 3: Crear `contracts/event.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://atendia.io/contracts/event.schema.json",
  "title": "Event",
  "type": "object",
  "required": ["id", "conversation_id", "tenant_id", "type", "payload", "occurred_at"],
  "properties": {
    "id": { "type": "string" },
    "conversation_id": { "type": "string" },
    "tenant_id": { "type": "string" },
    "type": {
      "type": "string",
      "enum": [
        "message_received",
        "message_sent",
        "stage_entered",
        "stage_exited",
        "field_extracted",
        "tool_called",
        "human_handoff_requested",
        "followup_scheduled",
        "error_occurred"
      ]
    },
    "payload": { "type": "object" },
    "occurred_at": { "type": "string", "format": "date-time" },
    "trace_id": { "type": ["string", "null"] }
  }
}
```

**Step 4: Implementar `core/atendia/contracts/event.py`**

```python
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    STAGE_ENTERED = "stage_entered"
    STAGE_EXITED = "stage_exited"
    FIELD_EXTRACTED = "field_extracted"
    TOOL_CALLED = "tool_called"
    HUMAN_HANDOFF_REQUESTED = "human_handoff_requested"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    ERROR_OCCURRED = "error_occurred"


class Event(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    conversation_id: str
    tenant_id: str
    type: EventType
    payload: dict
    occurred_at: datetime
    trace_id: str | None = None
```

**Step 5: Correr test, debe pasar.**

**Step 6: Commit**

```bash
git add contracts/event.schema.json core/atendia/contracts/event.py core/tests/contracts/test_event.py
git commit -m "feat(contracts): add Event schema and Pydantic model"
```

---

## Task 9: Schema canónico — `ConversationState`

Mismo patrón. El estado vivo de la conversación: stage actual, datos extraídos, confirmación pendiente, contadores.

**Files:**
- Create: `contracts/conversation_state.schema.json`
- Create: `core/atendia/contracts/conversation_state.py`
- Create: `core/tests/contracts/test_conversation_state.py`

**Step 1: Test failing**

`core/tests/contracts/test_conversation_state.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from atendia.contracts.conversation_state import ConversationState, ExtractedField


def test_conversation_state_minimal_valid():
    s = ConversationState(
        conversation_id="01J3Z6V8N1Q4WZS5MXY9KQHF7D",
        tenant_id="dinamomotos",
        current_stage="qualify",
        extracted_data={
            "nombre": ExtractedField(value="Juan", confidence=0.95, source_turn=2),
        },
        last_intent="ask_info",
        stage_entered_at=datetime.now(timezone.utc),
        followups_sent_count=0,
        total_cost_usd=Decimal("0.0000"),
    )
    assert s.current_stage == "qualify"
    assert s.extracted_data["nombre"].value == "Juan"


def test_extracted_field_low_confidence():
    f = ExtractedField(value="quizá CDMX", confidence=0.4, source_turn=3)
    assert f.confidence < 0.7
```

**Step 2: Correr, debe fallar.**

**Step 3: Crear `contracts/conversation_state.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://atendia.io/contracts/conversation_state.schema.json",
  "title": "ConversationState",
  "type": "object",
  "required": [
    "conversation_id", "tenant_id", "current_stage",
    "extracted_data", "stage_entered_at",
    "followups_sent_count", "total_cost_usd"
  ],
  "properties": {
    "conversation_id": { "type": "string" },
    "tenant_id": { "type": "string" },
    "current_stage": { "type": "string" },
    "extracted_data": {
      "type": "object",
      "additionalProperties": { "$ref": "#/$defs/ExtractedField" }
    },
    "pending_confirmation": { "type": ["string", "null"] },
    "last_intent": { "type": ["string", "null"] },
    "stage_entered_at": { "type": "string", "format": "date-time" },
    "followups_sent_count": { "type": "integer", "minimum": 0 },
    "total_cost_usd": { "type": "string" }
  },
  "$defs": {
    "ExtractedField": {
      "type": "object",
      "required": ["value", "confidence", "source_turn"],
      "properties": {
        "value": {},
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
        "source_turn": { "type": "integer", "minimum": 0 }
      }
    }
  }
}
```

**Step 4: Implementar `core/atendia/contracts/conversation_state.py`**

```python
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class ExtractedField(BaseModel):
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source_turn: int = Field(ge=0)


class ConversationState(BaseModel):
    conversation_id: str
    tenant_id: str
    current_stage: str
    extracted_data: dict[str, ExtractedField] = Field(default_factory=dict)
    pending_confirmation: str | None = None
    last_intent: str | None = None
    stage_entered_at: datetime
    followups_sent_count: int = Field(default=0, ge=0)
    total_cost_usd: Decimal = Field(default=Decimal("0.0000"))
```

**Step 5: Test passes.**

**Step 6: Commit**

```bash
git add contracts/conversation_state.schema.json core/atendia/contracts/conversation_state.py core/tests/contracts/test_conversation_state.py
git commit -m "feat(contracts): add ConversationState + ExtractedField"
```

---

## Task 10: Schema canónico — `PipelineDefinition`

Define la estructura JSONB que cada tenant carga en `tenant_pipelines.definition_jsonb`. Es el contrato más crítico — toda la lógica del state machine lee esto.

**Files:**
- Create: `contracts/pipeline_definition.schema.json`
- Create: `core/atendia/contracts/pipeline_definition.py`
- Create: `core/tests/contracts/test_pipeline_definition.py`

**Step 1: Test failing**

`core/tests/contracts/test_pipeline_definition.py`:

```python
import pytest
from pydantic import ValidationError

from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
    Transition,
)


def test_pipeline_minimal_valid():
    p = PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(
                id="greeting",
                actions_allowed=["greet"],
                transitions=[Transition(to="qualify", when="intent in [ask_info, ask_price]")],
            ),
            StageDefinition(
                id="qualify",
                required_fields=["interes_producto", "ciudad"],
                actions_allowed=["ask_field", "lookup_faq"],
                transitions=[],
            ),
        ],
        tone={"register": "informal_mexicano", "use_emojis": "sparingly"},
        fallback="escalate_to_human",
    )
    assert p.stages[0].id == "greeting"
    assert p.stages[1].required_fields == ["interes_producto", "ciudad"]


def test_pipeline_duplicate_stage_id_raises():
    with pytest.raises(ValidationError):
        PipelineDefinition(
            version=1,
            stages=[
                StageDefinition(id="qualify", actions_allowed=[], transitions=[]),
                StageDefinition(id="qualify", actions_allowed=[], transitions=[]),
            ],
            tone={},
            fallback="escalate_to_human",
        )


def test_transition_to_unknown_stage_raises():
    with pytest.raises(ValidationError):
        PipelineDefinition(
            version=1,
            stages=[
                StageDefinition(
                    id="greeting",
                    actions_allowed=[],
                    transitions=[Transition(to="nonexistent", when="true")],
                ),
            ],
            tone={},
            fallback="escalate_to_human",
        )
```

**Step 2: Correr, debe fallar.**

**Step 3: Crear `contracts/pipeline_definition.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://atendia.io/contracts/pipeline_definition.schema.json",
  "title": "PipelineDefinition",
  "type": "object",
  "required": ["version", "stages", "tone", "fallback"],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "stages": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/StageDefinition" }
    },
    "tone": { "type": "object" },
    "fallback": { "type": "string" }
  },
  "$defs": {
    "StageDefinition": {
      "type": "object",
      "required": ["id", "actions_allowed", "transitions"],
      "properties": {
        "id": { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
        "required_fields": { "type": "array", "items": { "type": "string" } },
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

**Step 4: Implementar `core/atendia/contracts/pipeline_definition.py`**

```python
from pydantic import BaseModel, Field, model_validator


class Transition(BaseModel):
    to: str
    when: str


class StageDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    required_fields: list[str] = Field(default_factory=list)
    actions_allowed: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    timeout_hours: int | None = None
    timeout_action: str | None = None


class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    stages: list[StageDefinition] = Field(min_length=1)
    tone: dict
    fallback: str

    @model_validator(mode="after")
    def _validate_stage_ids_unique(self) -> "PipelineDefinition":
        ids = [s.id for s in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("stage ids must be unique")
        return self

    @model_validator(mode="after")
    def _validate_transitions_target_existing_stages(self) -> "PipelineDefinition":
        ids = {s.id for s in self.stages}
        for stage in self.stages:
            for t in stage.transitions:
                if t.to not in ids:
                    raise ValueError(f"transition target '{t.to}' is not a known stage")
        return self
```

**Step 5: Test passes.**

**Step 6: Commit**

```bash
git add contracts/pipeline_definition.schema.json core/atendia/contracts/pipeline_definition.py core/tests/contracts/test_pipeline_definition.py
git commit -m "feat(contracts): add PipelineDefinition with structural validation"
```

---

## Task 11: Schema canónico — `NLUResult` (placeholder, sin LLM aún)

Aunque la Fase 1 no llama al LLM, el state machine consume objetos `NLUResult`. Los fixtures los van a producir manualmente.

**Files:**
- Create: `contracts/nlu_result.schema.json`
- Create: `core/atendia/contracts/nlu_result.py`
- Create: `core/tests/contracts/test_nlu_result.py`

**Step 1: Test failing**

`core/tests/contracts/test_nlu_result.py`:

```python
import pytest
from pydantic import ValidationError

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment


def test_nlu_result_high_confidence_no_ambiguity():
    r = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={"interes_producto": ExtractedField(value="150Z", confidence=0.9, source_turn=2)},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.92,
        ambiguities=[],
    )
    assert r.intent == Intent.ASK_PRICE
    assert r.confidence > 0.7


def test_nlu_result_confidence_out_of_range_raises():
    with pytest.raises(ValidationError):
        NLUResult(
            intent=Intent.GREETING,
            entities={},
            sentiment=Sentiment.NEUTRAL,
            confidence=1.5,
            ambiguities=[],
        )
```

**Step 2: Correr, debe fallar.**

**Step 3: Crear `contracts/nlu_result.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://atendia.io/contracts/nlu_result.schema.json",
  "title": "NLUResult",
  "type": "object",
  "required": ["intent", "entities", "sentiment", "confidence", "ambiguities"],
  "properties": {
    "intent": {
      "type": "string",
      "enum": ["greeting", "ask_info", "ask_price", "buy", "schedule", "complain", "off_topic", "unclear"]
    },
    "entities": { "type": "object" },
    "sentiment": { "type": "string", "enum": ["positive", "neutral", "negative"] },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "ambiguities": { "type": "array", "items": { "type": "string" } }
  }
}
```

**Step 4: Implementar `core/atendia/contracts/nlu_result.py`**

```python
from enum import Enum

from pydantic import BaseModel, Field

from atendia.contracts.conversation_state import ExtractedField


class Intent(str, Enum):
    GREETING = "greeting"
    ASK_INFO = "ask_info"
    ASK_PRICE = "ask_price"
    BUY = "buy"
    SCHEDULE = "schedule"
    COMPLAIN = "complain"
    OFF_TOPIC = "off_topic"
    UNCLEAR = "unclear"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class NLUResult(BaseModel):
    intent: Intent
    entities: dict[str, ExtractedField] = Field(default_factory=dict)
    sentiment: Sentiment
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguities: list[str] = Field(default_factory=list)
```

**Step 5: Test passes.**

**Step 6: Commit**

```bash
git add contracts/nlu_result.schema.json core/atendia/contracts/nlu_result.py core/tests/contracts/test_nlu_result.py
git commit -m "feat(contracts): add NLUResult contract"
```

---

## Task 12: Validar JSON Schemas vs modelos Pydantic

Aseguramos que los modelos Pydantic generan un schema equivalente al JSON Schema canónico (no idéntico — Pydantic produce su variante — pero los campos requeridos y enums deben coincidir).

**Files:**
- Create: `core/tests/contracts/test_schema_consistency.py`

**Step 1: Test**

```python
import json
from pathlib import Path

from atendia.contracts.event import Event
from atendia.contracts.message import Message
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def _required_fields(schema: dict) -> set[str]:
    return set(schema.get("required", []))


def _enum_values(schema: dict, prop: str) -> set[str] | None:
    p = schema.get("properties", {}).get(prop, {})
    if "enum" in p:
        return set(p["enum"])
    return None


def test_message_required_match():
    canonical = json.loads((CONTRACTS_DIR / "message.schema.json").read_text())
    pydantic = Message.model_json_schema()
    assert _required_fields(canonical) <= _required_fields(pydantic)


def test_message_direction_enum_match():
    canonical = json.loads((CONTRACTS_DIR / "message.schema.json").read_text())
    canonical_enum = _enum_values(canonical, "direction")
    pydantic_schema = Message.model_json_schema()
    pydantic_enum = set(pydantic_schema["$defs"]["MessageDirection"]["enum"])
    assert canonical_enum == pydantic_enum


def test_event_type_enum_match():
    canonical = json.loads((CONTRACTS_DIR / "event.schema.json").read_text())
    canonical_enum = _enum_values(canonical, "type")
    pydantic_schema = Event.model_json_schema()
    pydantic_enum = set(pydantic_schema["$defs"]["EventType"]["enum"])
    assert canonical_enum == pydantic_enum


def test_pipeline_definition_required():
    canonical = json.loads((CONTRACTS_DIR / "pipeline_definition.schema.json").read_text())
    pydantic = PipelineDefinition.model_json_schema()
    assert _required_fields(canonical) <= _required_fields(pydantic)


def test_nlu_intent_enum_match():
    canonical = json.loads((CONTRACTS_DIR / "nlu_result.schema.json").read_text())
    canonical_enum = _enum_values(canonical, "intent")
    pydantic_schema = NLUResult.model_json_schema()
    pydantic_enum = set(pydantic_schema["$defs"]["Intent"]["enum"])
    assert canonical_enum == pydantic_enum
```

**Step 2: Correr todos los tests del bloque B**

```bash
cd core && uv run pytest tests/contracts/ -v
```

Expected: todos los tests del bloque pasan.

**Step 3: Commit**

```bash
git add core/tests/contracts/test_schema_consistency.py
git commit -m "test(contracts): assert pydantic↔json-schema field/enum consistency"
```

---

# Bloque C — Schema Postgres + migraciones

> **Patrón general:** cada migración crea una o varias tablas; cada migración tiene `upgrade()` y `downgrade()` simétricos; cada migración tiene un test que la corre, valida estructura, y la revierte.

## Task 13: Migration 001 — `tenants` y `tenant_users`

**Files:**
- Create: `core/atendia/db/migrations/versions/001_tenants.py`
- Create: `core/atendia/db/models/tenant.py`
- Create: `core/atendia/db/models/__init__.py`
- Create: `core/tests/db/__init__.py`
- Create: `core/tests/db/test_migration_001.py`

**Step 1: Crear modelo ORM `core/atendia/db/models/tenant.py`**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atendia.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(String(40), default="standard")
    status: Mapped[str] = mapped_column(String(20), default="active")
    meta_business_id: Mapped[str | None] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    users: Mapped[list["TenantUser"]] = relationship(back_populates="tenant")


class TenantUser(Base):
    __tablename__ = "tenant_users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="operator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
```

**Step 2: `core/atendia/db/models/__init__.py`**

```python
from atendia.db.models.tenant import Tenant, TenantUser

__all__ = ["Tenant", "TenantUser"]
```

**Step 3: Generar migración con autogenerate**

```bash
cd core
uv run alembic revision --autogenerate -m "001_tenants"
```

Expected: archivo creado en `core/atendia/db/migrations/versions/<hash>_001_tenants.py`. Renombrarlo a `001_tenants.py`.

**Step 4: Inspeccionar la migración generada** y asegurar que `upgrade()` crea ambas tablas con índices apropiados, y que `downgrade()` las dropea.

**Step 5: Test de migración `core/tests/db/test_migration_001.py`**

```python
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_tenants_table_exists_after_upgrade():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            assert "tenants" in tables
            assert "tenant_users" in tables
            cols = {c["name"] for c in insp.get_columns("tenants")}
            assert {"id", "name", "plan", "status", "meta_business_id", "config", "created_at"} <= cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenants_can_insert_and_query():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tenants (name) VALUES ('test_tenant_001')")
        )
        result = await conn.execute(
            text("SELECT name FROM tenants WHERE name = 'test_tenant_001'")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "test_tenant_001"
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_tenant_001'"))
    await engine.dispose()
```

**Step 6: Aplicar migración**

```bash
cd core && uv run alembic upgrade head
```

**Step 7: Correr tests, deben pasar**

```bash
cd core && uv run pytest tests/db/test_migration_001.py -v
```

**Step 8: Probar reversión**

```bash
cd core && uv run alembic downgrade base
cd core && uv run alembic upgrade head
```

No debe haber errores. Esto valida que `downgrade()` funciona.

**Step 9: Commit**

```bash
git add core/atendia/db/models/ core/atendia/db/migrations/versions/001_tenants.py core/tests/db/
git commit -m "feat(db): migration 001 - tenants + tenant_users"
```

---

## Task 14: Migration 002 — `customers`

Mismo patrón que Task 13. Cliente final del tenant.

**Modelo ORM `core/atendia/db/models/customer.py`:**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", name="uq_customers_tenant_phone"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    phone_e164: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

**Steps idénticos a Task 13:**
1. Agregar import en `models/__init__.py`.
2. `alembic revision --autogenerate -m "002_customers"`.
3. Renombrar a `002_customers.py`.
4. Test de migración (tabla existe, índice por tenant_id, unique constraint funciona).
5. `alembic upgrade head`, correr tests.
6. Probar `downgrade base` → `upgrade head`.
7. Commit: `feat(db): migration 002 - customers`.

---

## Task 15: Migration 003 — `conversations` + `conversation_state`

**Modelos ORM `core/atendia/db/models/conversation.py`:**

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atendia.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="whatsapp_meta")
    status: Mapped[str] = mapped_column(String(20), default="active")
    current_stage: Mapped[str] = mapped_column(String(60), default="greeting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    state: Mapped["ConversationStateRow"] = relationship(back_populates="conversation", uselist=False)


class ConversationStateRow(Base):
    __tablename__ = "conversation_state"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    extracted_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    pending_confirmation: Mapped[str | None] = mapped_column(String(160))
    last_intent: Mapped[str | None] = mapped_column(String(40))
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    followups_sent_count: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="state")
```

**Steps:**
1. Agregar a `models/__init__.py`.
2. Generar migración 003.
3. Test: ambas tablas existen, FK funciona, insertar conversación crea relación.
4. `upgrade` / `downgrade` / `upgrade` exitoso.
5. Commit: `feat(db): migration 003 - conversations + conversation_state`.

---

## Task 16: Migration 004 — `messages`

**Modelo ORM:**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    channel_message_id: Mapped[str | None] = mapped_column(String(120), index=True)
    delivery_status: Mapped[str | None] = mapped_column(String(20))
    metadata: Mapped[dict] = mapped_column("metadata_json", JSONB, default=dict)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Steps:**
1. Agregar a `models/__init__.py`.
2. Generar migración 004.
3. Test: tabla con índices en `conversation_id`, `tenant_id`, `sent_at`. CHECK constraint en `direction in ('inbound', 'outbound', 'system')` (agregar manualmente al `upgrade` si no autogenera).
4. Roundtrip migration ok.
5. Commit: `feat(db): migration 004 - messages`.

---

## Task 17: Migration 005 — `events`

**Modelo ORM:**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(60), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Steps idénticos al patrón.** Commit: `feat(db): migration 005 - events`.

---

## Task 18: Migration 006 — `turn_traces` + `tool_calls`

**Modelo:**

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atendia.db.base import Base


class TurnTrace(Base):
    __tablename__ = "turn_traces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    inbound_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id"))
    inbound_text: Mapped[str | None] = mapped_column(Text)

    nlu_input: Mapped[dict | None] = mapped_column(JSONB)
    nlu_output: Mapped[dict | None] = mapped_column(JSONB)
    nlu_model: Mapped[str | None] = mapped_column(String(60))
    nlu_tokens_in: Mapped[int | None] = mapped_column(Integer)
    nlu_tokens_out: Mapped[int | None] = mapped_column(Integer)
    nlu_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    nlu_latency_ms: Mapped[int | None] = mapped_column(Integer)

    state_before: Mapped[dict | None] = mapped_column(JSONB)
    state_after: Mapped[dict | None] = mapped_column(JSONB)
    stage_transition: Mapped[str | None] = mapped_column(String(120))

    composer_input: Mapped[dict | None] = mapped_column(JSONB)
    composer_output: Mapped[dict | None] = mapped_column(JSONB)
    composer_model: Mapped[str | None] = mapped_column(String(60))
    composer_tokens_in: Mapped[int | None] = mapped_column(Integer)
    composer_tokens_out: Mapped[int | None] = mapped_column(Integer)
    composer_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    composer_latency_ms: Mapped[int | None] = mapped_column(Integer)

    outbound_messages: Mapped[list | None] = mapped_column(JSONB)

    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    total_latency_ms: Mapped[int | None] = mapped_column(Integer)

    errors: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tool_calls: Mapped[list["ToolCallRow"]] = relationship(back_populates="turn_trace")


class ToolCallRow(Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    turn_trace_id: Mapped[UUID] = mapped_column(ForeignKey("turn_traces.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    input_payload: Mapped[dict] = mapped_column("input", JSONB, nullable=False)
    output_payload: Mapped[dict | None] = mapped_column("output", JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turn_trace: Mapped[TurnTrace] = relationship(back_populates="tool_calls")
```

**Commit:** `feat(db): migration 006 - turn_traces + tool_calls`

---

## Task 19: Migration 007 — `tenant_pipelines` + `tenant_catalogs` + `tenant_faqs`

**Modelos:**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class TenantPipeline(Base):
    __tablename__ = "tenant_pipelines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_tenant_pipelines_tenant_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantCatalogItem(Base):
    __tablename__ = "tenant_catalogs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_tenant_catalogs_tenant_sku"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantFAQ(Base):
    __tablename__ = "tenant_faqs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(String(2000), nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

(Embeddings llegan en una fase posterior — Fase 3 IA. Aquí no.)

**Commit:** `feat(db): migration 007 - tenant_pipelines + catalogs + faqs`

---

## Task 20: Migration 008 — `tenant_templates_meta` + `tenant_tools_config` + `tenant_branding`

**Modelos:**

```python
class TenantTemplateMeta(Base):
    __tablename__ = "tenant_templates_meta"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_name", "language",
                         name="uq_tenant_templates_meta"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    template_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # marketing/utility/auth
    language: Mapped[str] = mapped_column(String(10), default="es_MX")
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    cost_estimate_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    last_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantToolConfig(Base):
    __tablename__ = "tenant_tools_config"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tool_name", name="uq_tenant_tools_config"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class TenantBranding(Base):
    __tablename__ = "tenant_branding"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    bot_name: Mapped[str] = mapped_column(String(80), default="Asistente")
    voice: Mapped[dict] = mapped_column(JSONB, default=dict)
    default_messages: Mapped[dict] = mapped_column(JSONB, default=dict)
```

(Importar `Text` y `Decimal` cuando agregues a archivo real.)

**Commit:** `feat(db): migration 008 - templates_meta + tools_config + branding`

---

## Task 21: Migration 009 — `followups_scheduled` + `human_handoffs`

**Modelos:**

```python
class FollowupScheduled(Base):
    __tablename__ = "followups_scheduled"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    template_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_templates_meta.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HumanHandoff(Base):
    __tablename__ = "human_handoffs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    assigned_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenant_users.id"))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

**Commit:** `feat(db): migration 009 - followups_scheduled + human_handoffs`

---

## Task 22: Test integral de migraciones — round-trip total

**Files:**
- Create: `core/tests/db/test_migrations_roundtrip.py`

**Step 1: Test**

```python
import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _alembic_cfg() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


@pytest.mark.asyncio
async def test_full_roundtrip_drops_and_recreates_all_tables():
    expected_tables = {
        "tenants", "tenant_users", "customers",
        "conversations", "conversation_state",
        "messages", "events",
        "turn_traces", "tool_calls",
        "tenant_pipelines", "tenant_catalogs", "tenant_faqs",
        "tenant_templates_meta", "tenant_tools_config", "tenant_branding",
        "followups_scheduled", "human_handoffs",
        "alembic_version",
    }

    cfg = _alembic_cfg()

    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _names(sync_conn):
            return set(inspect(sync_conn).get_table_names())

        names = await conn.run_sync(_names)

    await engine.dispose()
    missing = expected_tables - names
    assert not missing, f"missing tables after upgrade: {missing}"
```

**Step 2: Correr**

```bash
cd core && uv run pytest tests/db/test_migrations_roundtrip.py -v
```

Expected: PASS.

**Step 3: Commit**

```bash
git add core/tests/db/test_migrations_roundtrip.py
git commit -m "test(db): roundtrip migration test asserts all tables created"
```

---

# Bloque D — State machine engine (sin LLM)

## Task 23: Pipeline parser — JSONB → `PipelineDefinition`

Carga un pipeline desde DB y lo convierte en el modelo Pydantic ya validado.

**Files:**
- Create: `core/atendia/state_machine/__init__.py` (ya existe vacío)
- Create: `core/atendia/state_machine/pipeline_loader.py`
- Create: `core/tests/state_machine/__init__.py`
- Create: `core/tests/state_machine/test_pipeline_loader.py`
- Create: `core/tests/state_machine/conftest.py` (fixtures async + DB)

**Step 1: `core/tests/state_machine/conftest.py`**

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
        await session.rollback()
    await engine.dispose()
```

**Step 2: Test failing `core/tests/state_machine/test_pipeline_loader.py`**

```python
import pytest
from sqlalchemy import text

from atendia.state_machine.pipeline_loader import PipelineNotFoundError, load_active_pipeline


@pytest.mark.asyncio
async def test_load_active_pipeline_returns_validated_definition(db_session):
    await db_session.execute(text("INSERT INTO tenants (name) VALUES ('test_loader_tenant') RETURNING id"))
    res = await db_session.execute(text("SELECT id FROM tenants WHERE name = 'test_loader_tenant'"))
    tenant_id = res.scalar()

    definition = {
        "version": 1,
        "stages": [
            {"id": "greeting", "actions_allowed": ["greet"], "transitions": [{"to": "qualify", "when": "true"}]},
            {"id": "qualify", "required_fields": ["nombre"], "actions_allowed": ["ask_field"], "transitions": []},
        ],
        "tone": {"register": "informal_mexicano"},
        "fallback": "escalate_to_human",
    }
    await db_session.execute(
        text("""
            INSERT INTO tenant_pipelines (tenant_id, version, definition, active)
            VALUES (:tid, 1, :def, true)
        """),
        {"tid": tenant_id, "def": __import__("json").dumps(definition)},
    )
    await db_session.commit()

    p = await load_active_pipeline(db_session, tenant_id)
    assert len(p.stages) == 2
    assert p.stages[0].id == "greeting"

    # cleanup
    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_load_active_pipeline_raises_when_none_active(db_session):
    res = await db_session.execute(text("INSERT INTO tenants (name) VALUES ('test_no_pipeline') RETURNING id"))
    tenant_id = res.scalar()
    await db_session.commit()

    with pytest.raises(PipelineNotFoundError):
        await load_active_pipeline(db_session, tenant_id)

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db_session.commit()
```

**Step 3: Correr, debe fallar (ImportError).**

**Step 4: Implementar `core/atendia/state_machine/pipeline_loader.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.models import TenantPipeline


class PipelineNotFoundError(Exception):
    """Raised when no active pipeline exists for a tenant."""


async def load_active_pipeline(session: AsyncSession, tenant_id: UUID) -> PipelineDefinition:
    stmt = (
        select(TenantPipeline)
        .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
        .order_by(TenantPipeline.version.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise PipelineNotFoundError(f"no active pipeline for tenant {tenant_id}")
    return PipelineDefinition.model_validate(row.definition)
```

**Step 5: Correr tests, deben pasar.**

**Step 6: Commit**

```bash
git add core/atendia/state_machine/pipeline_loader.py core/tests/state_machine/
git commit -m "feat(state-machine): pipeline loader from DB with validation"
```

---

## Task 24: Transition condition evaluator

Evalúa expresiones de transición: `intent == ask_price`, `confidence > 0.7`, `all_required_fields_present`, `intent in [info, price, buy]`, `sentiment == negative AND turn_count > 3`.

**Files:**
- Create: `core/atendia/state_machine/conditions.py`
- Create: `core/tests/state_machine/test_conditions.py`

**Step 1: Test failing**

```python
import pytest

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.state_machine.conditions import EvaluationContext, evaluate


@pytest.fixture
def ctx():
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={
            "interes_producto": ExtractedField(value="150Z", confidence=0.9, source_turn=2),
            "ciudad": ExtractedField(value="CDMX", confidence=0.95, source_turn=2),
        },
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    return EvaluationContext(
        nlu=nlu,
        extracted_data={k: v.value for k, v in nlu.entities.items()},
        required_fields=["interes_producto", "ciudad"],
        turn_count=3,
    )


def test_eval_intent_equals(ctx):
    assert evaluate("intent == ask_price", ctx) is True
    assert evaluate("intent == buy", ctx) is False


def test_eval_intent_in_list(ctx):
    assert evaluate("intent in [ask_info, ask_price, buy]", ctx) is True
    assert evaluate("intent in [greeting]", ctx) is False


def test_eval_all_required_fields_present(ctx):
    assert evaluate("all_required_fields_present", ctx) is True


def test_eval_sentiment_and_turn(ctx):
    assert evaluate("sentiment == neutral AND turn_count > 1", ctx) is True
    assert evaluate("sentiment == negative AND turn_count > 1", ctx) is False


def test_eval_confidence(ctx):
    assert evaluate("confidence > 0.7", ctx) is True
    assert evaluate("confidence < 0.5", ctx) is False


def test_eval_invalid_syntax_raises():
    from atendia.state_machine.conditions import ConditionSyntaxError
    nlu = NLUResult(
        intent=Intent.GREETING, entities={}, sentiment=Sentiment.NEUTRAL,
        confidence=0.9, ambiguities=[],
    )
    c = EvaluationContext(nlu=nlu, extracted_data={}, required_fields=[], turn_count=0)
    with pytest.raises(ConditionSyntaxError):
        evaluate("intent ==== buy", c)


def test_eval_true_literal(ctx):
    assert evaluate("true", ctx) is True
    assert evaluate("false", ctx) is False
```

**Step 2: Correr, debe fallar.**

**Step 3: Implementar `core/atendia/state_machine/conditions.py`**

DSL minimalista. Soporta:
- Literales: `true`, `false`
- Comparaciones: `intent == X`, `intent != X`, `confidence > 0.7`, `turn_count >= 3`
- `intent in [a, b, c]`
- Predicados especiales: `all_required_fields_present`
- Combinadores: `AND`, `OR` (sin paréntesis anidados — keep it simple)

```python
import re
from dataclasses import dataclass

from atendia.contracts.nlu_result import NLUResult


class ConditionSyntaxError(Exception):
    """Raised when a condition expression cannot be parsed."""


@dataclass
class EvaluationContext:
    nlu: NLUResult
    extracted_data: dict
    required_fields: list[str]
    turn_count: int


_TOKEN_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)
_TOKEN_OR = re.compile(r"\s+OR\s+", re.IGNORECASE)


def _eval_atom(expr: str, ctx: EvaluationContext) -> bool:
    e = expr.strip()
    if e == "true":
        return True
    if e == "false":
        return False
    if e == "all_required_fields_present":
        return all(f in ctx.extracted_data for f in ctx.required_fields)

    # intent in [a, b, c]
    m = re.match(r"^intent\s+in\s+\[([^\]]+)\]$", e)
    if m:
        values = [v.strip() for v in m.group(1).split(",")]
        return ctx.nlu.intent.value in values

    # X op Y where X in {intent, sentiment, confidence, turn_count}
    m = re.match(r"^(intent|sentiment|confidence|turn_count)\s*(==|!=|>=|<=|>|<)\s*(.+)$", e)
    if not m:
        raise ConditionSyntaxError(f"cannot parse condition: {expr!r}")
    var, op, raw_val = m.group(1), m.group(2), m.group(3).strip()

    if var == "intent":
        left = ctx.nlu.intent.value
        right = raw_val
    elif var == "sentiment":
        left = ctx.nlu.sentiment.value
        right = raw_val
    elif var == "confidence":
        try:
            left = ctx.nlu.confidence
            right = float(raw_val)
        except ValueError as ve:
            raise ConditionSyntaxError(str(ve)) from ve
    elif var == "turn_count":
        try:
            left = ctx.turn_count
            right = int(raw_val)
        except ValueError as ve:
            raise ConditionSyntaxError(str(ve)) from ve
    else:
        raise ConditionSyntaxError(f"unknown variable {var!r}")

    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    raise ConditionSyntaxError(f"unknown operator {op!r}")


def evaluate(expression: str, ctx: EvaluationContext) -> bool:
    expression = expression.strip()
    if not expression:
        raise ConditionSyntaxError("empty expression")

    or_parts = _TOKEN_OR.split(expression)
    for or_part in or_parts:
        and_parts = _TOKEN_AND.split(or_part)
        if all(_eval_atom(p, ctx) for p in and_parts):
            return True
    return False
```

**Step 4: Tests pasan.**

**Step 5: Commit**

```bash
git add core/atendia/state_machine/conditions.py core/tests/state_machine/test_conditions.py
git commit -m "feat(state-machine): condition DSL evaluator (intent, sentiment, confidence, in, AND/OR)"
```

---

## Task 25: Action permission checker

Dado un stage actual y una intent del NLU, decide qué acción ejecutar (de las `actions_allowed` del stage).

**Files:**
- Create: `core/atendia/state_machine/action_resolver.py`
- Create: `core/tests/state_machine/test_action_resolver.py`

**Step 1: Test**

```python
import pytest

from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import StageDefinition
from atendia.state_machine.action_resolver import (
    NoActionAvailableError,
    resolve_action,
)


def test_resolve_ask_price_when_quote_allowed():
    stage = StageDefinition(
        id="quote",
        actions_allowed=["quote", "explain_payment_options", "lookup_faq"],
        transitions=[],
    )
    assert resolve_action(stage, Intent.ASK_PRICE) == "quote"


def test_resolve_falls_back_to_lookup_faq_when_off_topic():
    stage = StageDefinition(
        id="qualify",
        actions_allowed=["ask_field", "lookup_faq"],
        transitions=[],
    )
    assert resolve_action(stage, Intent.OFF_TOPIC) == "lookup_faq"


def test_resolve_unclear_returns_ask_clarification_action():
    stage = StageDefinition(
        id="qualify",
        actions_allowed=["ask_field", "lookup_faq", "ask_clarification"],
        transitions=[],
    )
    assert resolve_action(stage, Intent.UNCLEAR) == "ask_clarification"


def test_resolve_no_match_raises():
    stage = StageDefinition(id="quote", actions_allowed=["quote"], transitions=[])
    with pytest.raises(NoActionAvailableError):
        resolve_action(stage, Intent.OFF_TOPIC)
```

**Step 2: Correr, fallar.**

**Step 3: Implementar `core/atendia/state_machine/action_resolver.py`**

```python
from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import StageDefinition


class NoActionAvailableError(Exception):
    """No action in `actions_allowed` matches the intent and there is no fallback action."""


_INTENT_TO_PREFERRED_ACTIONS: dict[Intent, list[str]] = {
    Intent.GREETING: ["greet", "ask_field"],
    Intent.ASK_INFO: ["ask_field", "lookup_faq", "search_catalog"],
    Intent.ASK_PRICE: ["quote", "search_catalog", "ask_field"],
    Intent.BUY: ["close", "quote", "book_appointment"],
    Intent.SCHEDULE: ["book_appointment", "ask_field"],
    Intent.COMPLAIN: ["escalate_to_human", "lookup_faq"],
    Intent.OFF_TOPIC: ["lookup_faq", "ask_field"],
    Intent.UNCLEAR: ["ask_clarification", "lookup_faq"],
}


def resolve_action(stage: StageDefinition, intent: Intent) -> str:
    preferred = _INTENT_TO_PREFERRED_ACTIONS.get(intent, [])
    allowed = set(stage.actions_allowed)
    for candidate in preferred:
        if candidate in allowed:
            return candidate
    raise NoActionAvailableError(
        f"no action in {sorted(allowed)} matches intent {intent.value}"
    )
```

**Step 4: Tests pasan.**

**Step 5: Commit**

```bash
git add core/atendia/state_machine/action_resolver.py core/tests/state_machine/test_action_resolver.py
git commit -m "feat(state-machine): action resolver maps intent → allowed action"
```

---

## Task 26: Stage transitioner

Dado el estado actual y NLU, decide a qué stage transicionar (o quedarse).

**Files:**
- Create: `core/atendia/state_machine/transitioner.py`
- Create: `core/tests/state_machine/test_transitioner.py`

**Step 1: Test**

```python
import pytest

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
    Transition,
)
from atendia.state_machine.transitioner import next_stage


@pytest.fixture
def pipeline():
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(
                id="greeting",
                actions_allowed=["greet"],
                transitions=[Transition(to="qualify", when="intent in [ask_info, ask_price]")],
            ),
            StageDefinition(
                id="qualify",
                required_fields=["interes_producto", "ciudad"],
                actions_allowed=["ask_field"],
                transitions=[
                    Transition(to="quote", when="all_required_fields_present AND intent == ask_price"),
                    Transition(to="escalate", when="sentiment == negative AND turn_count > 3"),
                ],
            ),
            StageDefinition(id="quote", actions_allowed=["quote"], transitions=[]),
            StageDefinition(id="escalate", actions_allowed=[], transitions=[]),
        ],
        tone={},
        fallback="escalate_to_human",
    )


def test_no_transition_when_no_condition_met(pipeline):
    nlu = NLUResult(intent=Intent.GREETING, entities={}, sentiment=Sentiment.NEUTRAL,
                    confidence=0.9, ambiguities=[])
    assert next_stage(pipeline, "greeting", nlu, extracted_data={}, turn_count=0) == "greeting"


def test_transition_greeting_to_qualify(pipeline):
    nlu = NLUResult(intent=Intent.ASK_INFO, entities={}, sentiment=Sentiment.NEUTRAL,
                    confidence=0.9, ambiguities=[])
    assert next_stage(pipeline, "greeting", nlu, extracted_data={}, turn_count=1) == "qualify"


def test_transition_qualify_to_quote_when_fields_complete(pipeline):
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={}, sentiment=Sentiment.NEUTRAL,
                    confidence=0.9, ambiguities=[])
    extracted = {"interes_producto": "150Z", "ciudad": "CDMX"}
    assert next_stage(pipeline, "qualify", nlu, extracted_data=extracted, turn_count=2) == "quote"


def test_no_transition_qualify_when_fields_incomplete(pipeline):
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={}, sentiment=Sentiment.NEUTRAL,
                    confidence=0.9, ambiguities=[])
    assert next_stage(pipeline, "qualify", nlu, extracted_data={"ciudad": "CDMX"}, turn_count=2) == "qualify"


def test_transition_to_escalate_on_negative_sentiment(pipeline):
    nlu = NLUResult(intent=Intent.COMPLAIN, entities={}, sentiment=Sentiment.NEGATIVE,
                    confidence=0.8, ambiguities=[])
    assert next_stage(pipeline, "qualify", nlu, extracted_data={}, turn_count=4) == "escalate"
```

**Step 2: Correr, fallar.**

**Step 3: Implementar `core/atendia/state_machine/transitioner.py`**

```python
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.state_machine.conditions import EvaluationContext, evaluate


class UnknownStageError(Exception):
    """Raised when a stage id is not in the pipeline."""


def next_stage(
    pipeline: PipelineDefinition,
    current_stage_id: str,
    nlu: NLUResult,
    extracted_data: dict,
    turn_count: int,
) -> str:
    stage = next((s for s in pipeline.stages if s.id == current_stage_id), None)
    if stage is None:
        raise UnknownStageError(current_stage_id)

    ctx = EvaluationContext(
        nlu=nlu,
        extracted_data=extracted_data,
        required_fields=stage.required_fields,
        turn_count=turn_count,
    )
    for t in stage.transitions:
        if evaluate(t.when, ctx):
            return t.to
    return current_stage_id
```

**Step 4: Tests pasan.**

**Step 5: Commit**

```bash
git add core/atendia/state_machine/transitioner.py core/tests/state_machine/test_transitioner.py
git commit -m "feat(state-machine): stage transitioner evaluates pipeline conditions"
```

---

## Task 27: Ambiguity guard

Antes de transicionar o ejecutar acción, si el NLU dice ambiguo o low-confidence, fuerza `ask_clarification`.

**Files:**
- Create: `core/atendia/state_machine/ambiguity.py`
- Create: `core/tests/state_machine/test_ambiguity.py`

**Step 1: Test**

```python
from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.state_machine.ambiguity import is_ambiguous, AMBIGUITY_CONFIDENCE_THRESHOLD


def test_high_confidence_no_ambiguities_is_not_ambiguous():
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={},
                    sentiment=Sentiment.NEUTRAL, confidence=0.92, ambiguities=[])
    assert is_ambiguous(nlu) is False


def test_low_confidence_is_ambiguous():
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={},
                    sentiment=Sentiment.NEUTRAL,
                    confidence=AMBIGUITY_CONFIDENCE_THRESHOLD - 0.05,
                    ambiguities=[])
    assert is_ambiguous(nlu) is True


def test_explicit_ambiguity_is_ambiguous():
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={},
                    sentiment=Sentiment.NEUTRAL, confidence=0.95,
                    ambiguities=["could be 150Z or 250Z"])
    assert is_ambiguous(nlu) is True


def test_low_field_confidence_is_ambiguous():
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={"modelo": ExtractedField(value="?", confidence=0.4, source_turn=1)},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.95,
        ambiguities=[],
    )
    assert is_ambiguous(nlu) is True
```

**Step 2: Implementar `core/atendia/state_machine/ambiguity.py`**

```python
from atendia.contracts.nlu_result import NLUResult

AMBIGUITY_CONFIDENCE_THRESHOLD = 0.7


def is_ambiguous(nlu: NLUResult) -> bool:
    if nlu.confidence < AMBIGUITY_CONFIDENCE_THRESHOLD:
        return True
    if nlu.ambiguities:
        return True
    for field in nlu.entities.values():
        if field.confidence < AMBIGUITY_CONFIDENCE_THRESHOLD:
            return True
    return False
```

**Step 3: Tests pasan.**

**Step 4: Commit**

```bash
git add core/atendia/state_machine/ambiguity.py core/tests/state_machine/test_ambiguity.py
git commit -m "feat(state-machine): ambiguity guard (confidence threshold + explicit list)"
```

---

## Task 28: Orchestrator (composición de pieces)

Junta `pipeline_loader`, `ambiguity`, `action_resolver`, `transitioner` en una sola función `process_turn(state, nlu) -> OrchestratorDecision`.

**Files:**
- Create: `core/atendia/state_machine/orchestrator.py`
- Create: `core/tests/state_machine/test_orchestrator.py`

**Step 1: Test**

```python
from datetime import datetime, timezone

import pytest

from atendia.contracts.conversation_state import ConversationState, ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
    Transition,
)
from atendia.state_machine.orchestrator import OrchestratorDecision, process_turn


@pytest.fixture
def pipeline():
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(
                id="qualify",
                required_fields=["interes_producto", "ciudad"],
                actions_allowed=["ask_field", "lookup_faq", "ask_clarification"],
                transitions=[
                    Transition(to="quote", when="all_required_fields_present AND intent == ask_price"),
                ],
            ),
            StageDefinition(
                id="quote",
                actions_allowed=["quote", "ask_clarification"],
                transitions=[],
            ),
        ],
        tone={},
        fallback="escalate_to_human",
    )


@pytest.fixture
def state_qualify():
    return ConversationState(
        conversation_id="c1",
        tenant_id="t1",
        current_stage="qualify",
        extracted_data={},
        stage_entered_at=datetime.now(timezone.utc),
    )


def test_ambiguous_nlu_forces_ask_clarification(pipeline, state_qualify):
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={}, sentiment=Sentiment.NEUTRAL,
                    confidence=0.5, ambiguities=[])
    decision = process_turn(pipeline, state_qualify, nlu, turn_count=2)
    assert decision.action == "ask_clarification"
    assert decision.next_stage == "qualify"


def test_normal_flow_picks_action_and_transitions(pipeline):
    state = ConversationState(
        conversation_id="c2",
        tenant_id="t1",
        current_stage="qualify",
        extracted_data={
            "interes_producto": ExtractedField(value="150Z", confidence=0.95, source_turn=1),
            "ciudad": ExtractedField(value="CDMX", confidence=0.95, source_turn=1),
        },
        stage_entered_at=datetime.now(timezone.utc),
    )
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={}, sentiment=Sentiment.NEUTRAL,
                    confidence=0.9, ambiguities=[])
    decision = process_turn(pipeline, state, nlu, turn_count=2)
    assert decision.next_stage == "quote"
    # action_resolver should pick from the NEXT stage's allowed actions
    assert decision.action == "quote"
```

**Step 2: Implementar `core/atendia/state_machine/orchestrator.py`**

```python
from dataclasses import dataclass

from atendia.contracts.conversation_state import ConversationState
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.state_machine.action_resolver import resolve_action
from atendia.state_machine.ambiguity import is_ambiguous
from atendia.state_machine.transitioner import next_stage


@dataclass
class OrchestratorDecision:
    next_stage: str
    action: str
    reason: str


def _stage_by_id(pipeline: PipelineDefinition, sid: str):
    return next(s for s in pipeline.stages if s.id == sid)


def process_turn(
    pipeline: PipelineDefinition,
    state: ConversationState,
    nlu: NLUResult,
    turn_count: int,
) -> OrchestratorDecision:
    if is_ambiguous(nlu):
        current_stage = _stage_by_id(pipeline, state.current_stage)
        action = (
            "ask_clarification"
            if "ask_clarification" in current_stage.actions_allowed
            else current_stage.actions_allowed[0] if current_stage.actions_allowed
            else pipeline.fallback
        )
        return OrchestratorDecision(
            next_stage=state.current_stage,
            action=action,
            reason="ambiguous_nlu",
        )

    flat_extracted = {k: v.value for k, v in state.extracted_data.items()}
    target_stage_id = next_stage(
        pipeline, state.current_stage, nlu, flat_extracted, turn_count
    )

    target_stage = _stage_by_id(pipeline, target_stage_id)
    action = resolve_action(target_stage, nlu.intent)

    transition_reason = (
        f"transition:{state.current_stage}->{target_stage_id}"
        if target_stage_id != state.current_stage
        else "stay_in_stage"
    )
    return OrchestratorDecision(
        next_stage=target_stage_id,
        action=action,
        reason=transition_reason,
    )
```

**Step 3: Tests pasan.**

**Step 4: Commit**

```bash
git add core/atendia/state_machine/orchestrator.py core/tests/state_machine/test_orchestrator.py
git commit -m "feat(state-machine): orchestrator composes ambiguity guard + transitioner + action resolver"
```

---

## Task 29: Event emitter

Persiste eventos en la tabla `events` durante un turno.

**Files:**
- Create: `core/atendia/state_machine/event_emitter.py`
- Create: `core/tests/state_machine/test_event_emitter.py`

**Step 1: Test**

```python
import pytest
from sqlalchemy import select, text

from atendia.contracts.event import Event, EventType
from atendia.db.models.tenant import Tenant
from atendia.state_machine.event_emitter import EventEmitter


@pytest.mark.asyncio
async def test_emit_persists_event(db_session):
    res = await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_emitter') RETURNING id")
    )
    tenant_id = res.scalar()
    res2 = await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:tid, '+5215555555555') RETURNING id"),
        {"tid": tenant_id},
    )
    customer_id = res2.scalar()
    res3 = await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:tid, :cid) RETURNING id"),
        {"tid": tenant_id, "cid": customer_id},
    )
    conversation_id = res3.scalar()
    await db_session.commit()

    emitter = EventEmitter(db_session)
    await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.STAGE_ENTERED,
        payload={"stage": "qualify"},
    )
    await db_session.commit()

    res4 = await db_session.execute(
        text("SELECT type, payload FROM events WHERE conversation_id = :cid"),
        {"cid": conversation_id},
    )
    rows = res4.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "stage_entered"
    assert rows[0][1] == {"stage": "qualify"}

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db_session.commit()
```

**Step 2: Implementar `core/atendia/state_machine/event_emitter.py`**

```python
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.event import EventType
from atendia.db.models import EventRow


class EventEmitter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def emit(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        event_type: EventType,
        payload: dict,
        trace_id: str | None = None,
    ) -> EventRow:
        row = EventRow(
            id=uuid4(),
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            type=event_type.value,
            payload=payload,
            occurred_at=datetime.now(timezone.utc),
            trace_id=trace_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row
```

**Step 3: Tests pasan.**

**Step 4: Commit**

```bash
git add core/atendia/state_machine/event_emitter.py core/tests/state_machine/test_event_emitter.py
git commit -m "feat(state-machine): event emitter persists events to DB"
```

---

# Bloque E — Tools tipadas con stubs

> **Patrón general:** cada tool define `Input` y `Output` Pydantic + función async que recibe la sesión DB. Para Fase 1, las tools retornan datos canned y se loggean en `tool_calls`. La implementación real vive en Fase 3.

## Task 30: Tool registry + base interface

**Files:**
- Create: `core/atendia/tools/base.py`
- Create: `core/atendia/tools/registry.py`
- Create: `core/tests/tools/__init__.py`
- Create: `core/tests/tools/test_registry.py`

**Step 1: Test**

```python
import pytest

from atendia.tools.base import Tool, ToolNotFoundError
from atendia.tools.registry import register_tool, get_tool, _registry


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


def test_register_and_get_tool():
    class FakeTool(Tool):
        name = "fake"
        async def run(self, session, **kwargs):
            return {"ok": True}

    register_tool(FakeTool())
    t = get_tool("fake")
    assert t.name == "fake"


def test_get_unknown_tool_raises():
    with pytest.raises(ToolNotFoundError):
        get_tool("nonexistent")
```

**Step 2: Implementar `core/atendia/tools/base.py`**

```python
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class ToolNotFoundError(Exception):
    """Raised when a tool name is not in the registry."""


class Tool(ABC):
    name: str

    @abstractmethod
    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        ...
```

**Step 3: Implementar `core/atendia/tools/registry.py`**

```python
from atendia.tools.base import Tool, ToolNotFoundError

_registry: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    _registry[tool.name] = tool


def get_tool(name: str) -> Tool:
    try:
        return _registry[name]
    except KeyError as ke:
        raise ToolNotFoundError(name) from ke


def list_tools() -> list[str]:
    return sorted(_registry.keys())
```

**Step 4: Tests pasan.**

**Step 5: Commit**

```bash
git add core/atendia/tools/base.py core/atendia/tools/registry.py core/tests/tools/
git commit -m "feat(tools): registry + base Tool interface"
```

---

## Task 31: Tool stubs — `search_catalog` + `quote`

**Files:**
- Create: `core/atendia/tools/search_catalog.py`
- Create: `core/atendia/tools/quote.py`
- Create: `core/tests/tools/test_search_catalog.py`
- Create: `core/tests/tools/test_quote.py`

**Implementaciones (stubs):**

`core/atendia/tools/search_catalog.py`:

```python
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Tool


class SearchCatalogInput(BaseModel):
    tenant_id: UUID
    query: str
    limit: int = 5


class CatalogResult(BaseModel):
    sku: str
    name: str
    attrs: dict


class SearchCatalogTool(Tool):
    name = "search_catalog"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = SearchCatalogInput.model_validate(kwargs)
        stmt = (
            select(TenantCatalogItem)
            .where(
                TenantCatalogItem.tenant_id == params.tenant_id,
                TenantCatalogItem.active.is_(True),
            )
            .where(TenantCatalogItem.name.ilike(f"%{params.query}%"))
            .limit(params.limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {
            "results": [
                CatalogResult(sku=r.sku, name=r.name, attrs=r.attrs).model_dump()
                for r in rows
            ]
        }
```

`core/atendia/tools/quote.py` (stub canned):

```python
from typing import Any
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Tool


class QuoteInput(BaseModel):
    tenant_id: UUID
    sku: str
    options: dict = {}


class QuoteTool(Tool):
    name = "quote"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = QuoteInput.model_validate(kwargs)
        stmt = select(TenantCatalogItem).where(
            TenantCatalogItem.tenant_id == params.tenant_id,
            TenantCatalogItem.sku == params.sku,
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if item is None:
            return {"error": "sku_not_found", "sku": params.sku}
        # Stub pricing logic — real lives in Fase 3
        base_price = Decimal(str(item.attrs.get("price_mxn", "0")))
        return {
            "sku": item.sku,
            "name": item.name,
            "price_mxn": str(base_price),
            "options_applied": params.options,
        }
```

**Tests:** crear catalog item de prueba, llamar tool, verificar output esperado.

**Commit:** `feat(tools): search_catalog + quote stubs`

---

## Task 32: Tool stubs — `lookup_faq` + `book_appointment`

**Implementaciones similares.** `lookup_faq` busca por ILIKE en `tenant_faqs.question`. `book_appointment` retorna canned `{"booking_id": ..., "confirmed_at": ...}` sin tocar calendario real.

**Commit:** `feat(tools): lookup_faq + book_appointment stubs`

---

## Task 33: Tool stubs — `escalate_to_human` + `schedule_followup`

`escalate_to_human` inserta row en `human_handoffs`. `schedule_followup` inserta row en `followups_scheduled`.

**Commit:** `feat(tools): escalate_to_human + schedule_followup stubs`

---

## Task 34: Tool runner con persistencia en `tool_calls`

Wrapper que invoca cualquier tool del registry y persiste el `tool_call` en DB con timing.

**Files:**
- Create: `core/atendia/tools/runner.py`
- Create: `core/tests/tools/test_runner.py`

**Implementación:**

```python
import time
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import ToolCallRow
from atendia.tools.registry import get_tool


async def run_tool(
    session: AsyncSession,
    *,
    turn_trace_id: UUID,
    tool_name: str,
    inputs: dict,
) -> dict:
    tool = get_tool(tool_name)
    started = time.perf_counter()
    error = None
    output = None
    try:
        output = await tool.run(session, **inputs)
        return output
    except Exception as e:
        error = str(e)
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        session.add(ToolCallRow(
            id=uuid4(),
            turn_trace_id=turn_trace_id,
            tool_name=tool_name,
            input_payload=inputs,
            output_payload=output,
            latency_ms=latency_ms,
            error=error,
        ))
        await session.flush()
```

**Test:** ejecutar un tool stub vía runner, verificar que `tool_calls` tiene un row con `latency_ms > 0` y `output_payload` no nulo.

**Commit:** `feat(tools): runner persists tool_calls with latency`

---

## Task 35: Registrar todas las tools en startup

**Files:**
- Modify: `core/atendia/tools/__init__.py`

```python
from atendia.tools.book_appointment import BookAppointmentTool
from atendia.tools.escalate import EscalateToHumanTool
from atendia.tools.followup import ScheduleFollowupTool
from atendia.tools.lookup_faq import LookupFAQTool
from atendia.tools.quote import QuoteTool
from atendia.tools.registry import register_tool
from atendia.tools.search_catalog import SearchCatalogTool


def register_all_tools() -> None:
    for tool_cls in [
        SearchCatalogTool,
        QuoteTool,
        LookupFAQTool,
        BookAppointmentTool,
        EscalateToHumanTool,
        ScheduleFollowupTool,
    ]:
        register_tool(tool_cls())
```

**Test:** llamar `register_all_tools()`, verificar que `list_tools()` retorna las 6.

**Commit:** `feat(tools): register all tools at startup`

---

# Bloque F — Conversation runner

## Task 36: Canned NLU adapter

Adaptador que en lugar de llamar a un LLM lee `NLUResult` desde un fixture YAML/JSON. Para Fase 1 esto es suficiente.

**Files:**
- Create: `core/atendia/runner/nlu_canned.py`
- Create: `core/tests/runner/__init__.py`
- Create: `core/tests/runner/test_nlu_canned.py`

**Implementación:**

```python
from pathlib import Path

import yaml

from atendia.contracts.nlu_result import NLUResult


class CannedNLU:
    """Reads a list of NLUResult from a YAML file and returns them in order."""

    def __init__(self, fixture_path: Path) -> None:
        data = yaml.safe_load(fixture_path.read_text())
        self._queue = [NLUResult.model_validate(item) for item in data["nlu_results"]]
        self._idx = 0

    def next(self) -> NLUResult:
        if self._idx >= len(self._queue):
            raise IndexError("no more canned NLU results")
        result = self._queue[self._idx]
        self._idx += 1
        return result
```

**Step 1: Agregar `pyyaml` a dependencies**

```bash
cd core && uv add pyyaml
```

**Step 2: Crear fixture de prueba `core/tests/runner/fixtures/nlu_simple.yaml`**

```yaml
nlu_results:
  - intent: greeting
    entities: {}
    sentiment: neutral
    confidence: 0.95
    ambiguities: []
  - intent: ask_price
    entities:
      interes_producto: { value: "150Z", confidence: 0.9, source_turn: 1 }
    sentiment: neutral
    confidence: 0.9
    ambiguities: []
```

**Step 3: Test que carga fixture, llama `.next()` dos veces, valida intent.**

**Step 4: Commit**

```bash
git add core/atendia/runner/nlu_canned.py core/tests/runner/
git commit -m "feat(runner): canned NLU adapter for fixture-driven tests"
```

---

## Task 37: ConversationRunner — pipeline completo sin LLM

Orquesta: lee mensaje → consulta NLU canned → llama orchestrator → ejecuta tool → escribe state → emite eventos → escribe turn_trace. **Sin composer aún** (composer llega en Fase 3).

**Files:**
- Create: `core/atendia/runner/conversation_runner.py`
- Create: `core/tests/runner/test_conversation_runner.py`

**Implementación:**

```python
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.conversation_state import ConversationState, ExtractedField
from atendia.contracts.event import EventType
from atendia.contracts.message import Message, MessageDirection
from atendia.db.models import (
    Conversation,
    ConversationStateRow,
    MessageRow,
    TurnTrace,
)
from atendia.runner.nlu_canned import CannedNLU
from atendia.state_machine.event_emitter import EventEmitter
from atendia.state_machine.orchestrator import process_turn
from atendia.state_machine.pipeline_loader import load_active_pipeline


class ConversationRunner:
    def __init__(self, session: AsyncSession, nlu_provider: CannedNLU) -> None:
        self._session = session
        self._nlu = nlu_provider
        self._emitter = EventEmitter(session)

    async def run_turn(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        inbound: Message,
        turn_number: int,
    ) -> TurnTrace:
        started = time.perf_counter()
        pipeline = await load_active_pipeline(self._session, tenant_id)
        state_row = await self._load_state(conversation_id)
        state = self._row_to_state(state_row, tenant_id, conversation_id)
        nlu = self._nlu.next()

        decision = process_turn(pipeline, state, nlu, turn_number)

        # Update extracted_data from NLU entities (overwrite same key)
        for k, v in nlu.entities.items():
            state.extracted_data[k] = v

        previous_stage = state.current_stage
        state.current_stage = decision.next_stage
        state.last_intent = nlu.intent.value
        if previous_stage != decision.next_stage:
            state.stage_entered_at = datetime.now(timezone.utc)
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.STAGE_EXITED,
                payload={"from": previous_stage},
            )
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.STAGE_ENTERED,
                payload={"to": decision.next_stage},
            )

        await self._persist_state(state_row, state)

        latency_ms = int((time.perf_counter() - started) * 1000)
        trace = TurnTrace(
            id=uuid4(),
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            turn_number=turn_number,
            inbound_message_id=UUID(inbound.id) if _looks_like_uuid(inbound.id) else None,
            inbound_text=inbound.text,
            nlu_input={"text": inbound.text},
            nlu_output=nlu.model_dump(mode="json"),
            state_before=_state_to_jsonable(self._row_to_state(state_row, tenant_id, conversation_id, snapshot_before=True)),
            state_after=_state_to_jsonable(state),
            stage_transition=(
                f"{previous_stage}->{decision.next_stage}"
                if previous_stage != decision.next_stage
                else None
            ),
            outbound_messages=None,
            total_latency_ms=latency_ms,
        )
        self._session.add(trace)
        await self._session.flush()
        return trace

    # ... (helper methods _load_state, _row_to_state, _persist_state, etc.)
```

**Notas para el implementador:**
- `_looks_like_uuid` y `_state_to_jsonable` son helpers triviales — implementar in-line.
- En Fase 1 el `outbound_messages` siempre es `None` (composer llega en Fase 3).
- El "snapshot before" se obtiene capturando `state_row.attrs` antes de mutar; ajustar como convenga.

**Test:** preparar pipeline + state + canned NLU para 2-3 turnos, ejecutar `run_turn` en loop, verificar:
- Stage transitiona como esperado.
- Eventos correctos emitidos.
- Turn traces creados con `state_before/state_after` correctos.

**Commit:** `feat(runner): ConversationRunner orchestrates turn end-to-end (no LLM)`

---

## Task 38: API mínima FastAPI para invocar runner

Endpoint para disparar un turno desde HTTP. Útil para humans-in-the-loop debugging.

**Files:**
- Create: `core/atendia/main.py`
- Create: `core/atendia/api/__init__.py`
- Create: `core/atendia/api/runner_routes.py`
- Create: `core/tests/api/__init__.py`
- Create: `core/tests/api/test_runner_routes.py`

**Implementación de `core/atendia/main.py`:**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from atendia.api.runner_routes import router as runner_router
from atendia.tools import register_all_tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    register_all_tools()
    yield


app = FastAPI(title="atendia-core", version="0.1.0", lifespan=lifespan)
app.include_router(runner_router, prefix="/api/v1")
```

`core/atendia/api/runner_routes.py`:

```python
from datetime import datetime, timezone
from uuid import UUID, uuid4
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.message import Message, MessageDirection
from atendia.db.session import get_db_session
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU

router = APIRouter()


class RunTurnRequest(BaseModel):
    conversation_id: UUID
    tenant_id: UUID
    text: str
    turn_number: int
    fixture_path: str


class RunTurnResponse(BaseModel):
    turn_trace_id: UUID
    next_stage: str


@router.post("/runner/turn", response_model=RunTurnResponse)
async def run_turn(req: RunTurnRequest, session: AsyncSession = Depends(get_db_session)):
    fp = Path(req.fixture_path)
    if not fp.exists():
        raise HTTPException(404, f"fixture not found: {fp}")
    runner = ConversationRunner(session, CannedNLU(fp))
    inbound = Message(
        id=str(uuid4()),
        conversation_id=str(req.conversation_id),
        tenant_id=str(req.tenant_id),
        direction=MessageDirection.INBOUND,
        text=req.text,
        sent_at=datetime.now(timezone.utc),
    )
    trace = await runner.run_turn(
        conversation_id=req.conversation_id,
        tenant_id=req.tenant_id,
        inbound=inbound,
        turn_number=req.turn_number,
    )
    await session.commit()
    return RunTurnResponse(turn_trace_id=trace.id, next_stage=trace.state_after["current_stage"])
```

(También agregar `core/atendia/db/session.py` con `get_db_session` dependency.)

**Test con `httpx.AsyncClient`** que llama el endpoint contra app de FastAPI in-process.

**Commit:** `feat(api): runner endpoint with FastAPI`

---

## Task 39: Smoke test E2E manual

Script que se puede correr a mano para validar que todo el flujo Bloque B → F funciona.

**Files:**
- Create: `core/scripts/smoke_test_phase1.py`

**Implementación:** crea tenant + customer + conversation + pipeline, levanta `ConversationRunner`, alimenta canned NLU para 5 turnos, imprime estado final y eventos.

```bash
cd core && uv run python scripts/smoke_test_phase1.py
```

Expected: termina con `OK — phase 1 smoke test passed`.

**Commit:** `chore(scripts): smoke test for phase 1 happy path`

---

# Bloque G — Fixtures + verificación E2E

## Task 40: Fixture — happy path (greeting → qualify → quote → close)

**Files:**
- Create: `core/tests/fixtures/conversations/01_happy_path.yaml`

**Estructura del fixture (formato unificado):**

```yaml
name: happy_path
description: Cliente saluda, pregunta info, da datos, pide precio, compra.
tenant:
  name: dinamomotos_test
pipeline:
  version: 1
  stages:
    - id: greeting
      actions_allowed: [greet, ask_field]
      transitions:
        - to: qualify
          when: "intent in [ask_info, ask_price]"
    - id: qualify
      required_fields: [interes_producto, ciudad]
      actions_allowed: [ask_field, lookup_faq, ask_clarification]
      transitions:
        - to: quote
          when: "all_required_fields_present AND intent == ask_price"
    - id: quote
      actions_allowed: [quote, ask_clarification]
      transitions:
        - to: close
          when: "intent == buy"
    - id: close
      actions_allowed: [close]
      transitions: []
  tone: { register: informal_mexicano }
  fallback: escalate_to_human
catalog:
  - { sku: M150Z, name: "Italika 150Z", attrs: { price_mxn: 28500 } }
turns:
  - inbound: "hola"
    nlu:
      intent: greeting
      entities: {}
      sentiment: neutral
      confidence: 0.95
      ambiguities: []
    expected:
      next_stage: greeting
      action: greet
  - inbound: "info de la 150Z, soy de CDMX"
    nlu:
      intent: ask_info
      entities:
        interes_producto: { value: "150Z", confidence: 0.95, source_turn: 1 }
        ciudad: { value: "CDMX", confidence: 0.95, source_turn: 1 }
      sentiment: neutral
      confidence: 0.95
      ambiguities: []
    expected:
      next_stage: qualify
      action: ask_field   # or lookup_faq depending on resolver
  - inbound: "cuánto cuesta?"
    nlu:
      intent: ask_price
      entities: {}
      sentiment: neutral
      confidence: 0.95
      ambiguities: []
    expected:
      next_stage: quote
      action: quote
  - inbound: "la quiero"
    nlu:
      intent: buy
      entities: {}
      sentiment: positive
      confidence: 0.95
      ambiguities: []
    expected:
      next_stage: close
      action: close
```

**Step 1: Crear fixture.**

**Step 2: Commit**

```bash
git add core/tests/fixtures/conversations/01_happy_path.yaml
git commit -m "test(fixtures): happy_path conversation fixture"
```

---

## Task 41: Fixtures restantes

Crear los siguientes 4 fixtures (mismo formato, distinto contenido):

- `02_ambiguity.yaml` — turno con `confidence: 0.4` → action esperada = `ask_clarification`, stage no transiciona.
- `03_negative_sentiment.yaml` — sentiment negative en stage qualify por más de 3 turnos → transición a `escalate`.
- `04_required_fields_incomplete.yaml` — cliente pide precio sin haber dado ciudad → stage queda en `qualify`, action = `ask_field`.
- `05_off_topic.yaml` — cliente pregunta off-topic → action = `lookup_faq`.

**Commits:** uno por fixture: `test(fixtures): add 02_ambiguity`, etc.

---

## Task 42: E2E fixture runner

Test que carga cada fixture, lo ejecuta contra el runner, y valida los `expected` de cada turno.

**Files:**
- Create: `core/tests/e2e/__init__.py`
- Create: `core/tests/e2e/test_fixture_runner.py`

**Implementación esquemática:**

```python
import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import text

from atendia.contracts.message import Message, MessageDirection
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "conversations"


@pytest.mark.parametrize("fixture_path", sorted(FIXTURES_DIR.glob("*.yaml")))
@pytest.mark.asyncio
async def test_fixture_runs_to_expected_states(fixture_path, db_session):
    spec = yaml.safe_load(fixture_path.read_text())

    # Setup tenant + pipeline + catalog
    res = await db_session.execute(
        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
        {"n": spec["tenant"]["name"]},
    )
    tenant_id = res.scalar()
    await db_session.execute(
        text("INSERT INTO tenant_pipelines (tenant_id, version, definition, active) VALUES (:t, :v, :d, true)"),
        {"t": tenant_id, "v": spec["pipeline"]["version"], "d": json.dumps(spec["pipeline"])},
    )
    for item in spec.get("catalog", []):
        await db_session.execute(
            text("INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) VALUES (:t, :s, :n, :a)"),
            {"t": tenant_id, "s": item["sku"], "n": item["name"], "a": json.dumps(item["attrs"])},
        )
    res2 = await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555555000') RETURNING id"),
        {"t": tenant_id},
    )
    customer_id = res2.scalar()
    res3 = await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id, current_stage) VALUES (:t, :c, :s) RETURNING id"),
        {"t": tenant_id, "c": customer_id, "s": spec["pipeline"]["stages"][0]["id"]},
    )
    conversation_id = res3.scalar()
    await db_session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conversation_id},
    )
    await db_session.commit()

    # Build inline NLU fixture file from spec turns
    inline_nlu = {"nlu_results": [t["nlu"] for t in spec["turns"]]}
    inline_path = fixture_path.with_suffix(".inline.yaml")
    inline_path.write_text(yaml.safe_dump(inline_nlu))

    runner = ConversationRunner(db_session, CannedNLU(inline_path))

    for i, turn in enumerate(spec["turns"]):
        msg = Message(
            id=str(uuid4()),
            conversation_id=str(conversation_id),
            tenant_id=str(tenant_id),
            direction=MessageDirection.INBOUND,
            text=turn["inbound"],
            sent_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        trace = await runner.run_turn(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            inbound=msg,
            turn_number=i,
        )
        await db_session.commit()
        expected = turn["expected"]
        assert trace.state_after["current_stage"] == expected["next_stage"], (
            f"turn {i} stage mismatch in {fixture_path.name}"
        )

    inline_path.unlink()
    await db_session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    await db_session.commit()
```

**Commit:** `test(e2e): fixture runner asserts expected stages per turn`

---

## Task 43: Cobertura ≥ 85%

**Files:**
- Modify: `core/pyproject.toml` (agregar `[tool.coverage.run]`)

**Step 1:** correr suite con cobertura

```bash
cd core && uv run pytest --cov=atendia --cov-report=term-missing
```

Expected: cobertura agregada ≥ 85%. Si no, agregar tests para módulos < 85%.

**Step 2:** Hacer falla la build si cobertura cae bajo 85%:

en `core/pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 85
```

**Step 3: Commit**

```bash
git add core/pyproject.toml
git commit -m "test: enforce coverage >= 85%"
```

---

## Task 44: Documentar el núcleo en README

**Files:**
- Create: `core/README.md`

Sin ser épico — referencia rápida para quien entre. Cubrir:
- Setup (uv sync, docker compose up)
- Arquitectura interna (mismas secciones del design doc, resumidas)
- Cómo correr tests
- Cómo agregar una nueva tool
- Cómo agregar un nuevo stage al pipeline

**Commit:** `docs(core): README with setup, architecture, contribution`

---

# Verificación final de Fase 1

Antes de declarar Fase 1 completa, ejecutar:

```bash
cd core
uv run alembic downgrade base   # revierte todo
uv run alembic upgrade head     # vuelve a aplicar
uv run ruff check .             # lint pasa
uv run ruff format --check .    # format pasa
uv run pytest -v                # todos los tests pasan
uv run pytest --cov=atendia --cov-report=term-missing   # cobertura ≥ 85%
uv run python scripts/smoke_test_phase1.py              # smoke OK
```

**Criterios de salida de Fase 1:**

- [ ] 17 tablas creadas, todas las migraciones reversibles.
- [ ] 6 contratos canónicos (`Message`, `Event`, `ConversationState`, `PipelineDefinition`, `NLUResult`) con tests pydantic↔json-schema.
- [ ] State machine ejecuta condiciones, transiciones, ambigüedad correctamente.
- [ ] 6 tools tipadas con stubs registrados y verificables.
- [ ] `ConversationRunner` ejecuta turn end-to-end persistiendo state, events, turn_traces.
- [ ] 5 fixtures de conversación pasan E2E.
- [ ] Cobertura ≥ 85%.
- [ ] CI verde en GitHub Actions.

Si todos los criterios pasan, **Fase 1 está completa** y se puede comenzar a planear Fase 2 (transporte WhatsApp).

---

# Próximo paso de planeación

Cuando Fase 1 esté completa, generar el plan de Fase 2 (Transporte WhatsApp Cloud API + webhooks + cola + realtime) con la skill `superpowers:writing-plans`.

Documento de Fase 2 esperado: `docs/plans/YYYY-MM-DD-atendia-v2-fase2-transporte-whatsapp.md`.

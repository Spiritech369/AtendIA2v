# AtendIA v2 — Fase 3c.1: Datos reales (catálogo + FAQs + planes con embeddings) — Plan de Implementación

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Reemplazar las tools `quote`/`lookup_faq`/`search_catalog` que devuelven `ToolNoDataResult` (Phase 3b stubs) por queries reales contra `tenant_catalogs` y `tenant_faqs` poblados con embeddings (`text-embedding-3-large`, 3072 dims). El bot deja de redirigir y empieza a dar precios reales y FAQ relevantes.

**Architecture:** Postgres + pgvector para almacenar embeddings; ingestion script idempotente que lee 3 JSONs en `docs/`, genera embeddings batch via OpenAI, persiste con `INSERT ON CONFLICT DO UPDATE`. Búsqueda híbrida en catálogo (alias-keyword first, semantic fallback) y semántica pura en FAQs (cosine similarity con HNSW index). Composer prompts actualizados para usar `action_payload` con datos reales.

**Tech Stack:** Python 3.12 · Postgres 15 + pgvector ≥0.5 · OpenAI Embeddings API (`text-embedding-3-large`) · SQLAlchemy 2.0 + `pgvector.sqlalchemy.Vector` · respx (test mocks).

**Diseño aprobado:** [`docs/plans/2026-05-05-fase-3c1-datos-reales-design.md`](./2026-05-05-fase-3c1-datos-reales-design.md).

**Pre-requisitos del entorno:**
- Working tree limpio en branch dedicado: `feat/phase-3c1-datos-reales`.
- Docker Desktop corriendo.
- `cd core && uv run pytest -q` pasa con 326 tests + 4 skips.
- Phase 3b mergeada (commit `091bf5a`+).
- Los 3 archivos en `docs/`: `CATALOGO_MODELOS.json`, `FAQ_CREDITO.json`, `REQUISITOS_PLANES.json`.
- `ATENDIA_V2_OPENAI_API_KEY` en `core/.env`.

**Convenciones:**
- TDD: cada feature arranca con un test que falla.
- Commits chicos por bloque lógico.
- Sin `--no-verify`, sin saltarse hooks.

---

## Mapa de tareas

| Bloque | Tareas | Foco |
|---|---|---|
| **A.** Setup Docker + deps | T1–T3 | pgvector image + Python client + extension migration |
| **B.** Schema migrations | T4–T5 | embedding columns + indexes + tool_cost column |
| **C.** Models + Pydantic | T6–T8 | SQLAlchemy + Quote/FAQMatch/CatalogResult |
| **D.** Embedding helper | T9 | wrapper de OpenAI Embeddings + cost tracking |
| **E.** Tools refactor | T10–T12 | quote/lookup_faq/search_catalog con datos reales |
| **F.** Ingestion script | T13–T15 | flatten + embeddings + upsert + smoke run |
| **G.** Composer prompts | T16–T17 | ACTION_GUIDANCE updates + snapshot |
| **H.** Runner integration | T18–T19 | dispatch real + cost tracking |
| **I.** Tests adicionales | T20–T23 | unit + integration + E2E |
| **J.** Live + cierre | T24–T26 | live smoke + gates + README/memory |

**Total: 26 tareas. Estimado: 5–6 días (1 dev).**

---

# Bloque A — Setup Docker + dependencias

## Task 1: Cambiar imagen Docker a pgvector

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml` (CI service image)

**Step 1: Editar docker-compose.yml**

Cambiar la línea de la imagen y pinear a una versión específica para mantener
`<=>` (cosine) determinístico entre máquinas:

```yaml
  postgres-v2:
-   image: postgres:15-alpine
+   # Pinned to a specific pgvector release to keep `<=>` cosine semantics
+   # deterministic across machines. Bumping requires re-running ingestion.
+   image: pgvector/pgvector:0.8.2-pg15
```

Nota sobre el volume: si el contenedor que ya corre fue creado bajo otro
project name de Compose (p. ej. `v2-nucleo-conversacional`), `compose up`
crearía un volume nuevo vacío. Usar `external: true` para enlazar el volume
existente con sus datos:

```yaml
volumes:
  atendia_v2_pg_data:
+   external: true
+   name: v2-nucleo-conversacional_atendia_v2_pg_data
```

(Si el dev arranca de cero y no tiene volume previo, omitir el bloque
`external` y dejar que Compose lo cree.)

**Step 2: Actualizar la imagen del servicio postgres en CI**

Editar `.github/workflows/ci.yml` (sección `services.postgres.image`):

```yaml
-   image: postgres:15-alpine
+   image: pgvector/pgvector:0.8.2-pg15
```

Sin esto, el `alembic upgrade head` de CI fallará en T3 al ejecutar
`CREATE EXTENSION vector` contra la imagen base sin pgvector.

**Step 3: Recrear contenedor preservando datos**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2" && docker compose pull postgres-v2 && docker compose up -d
```

Expected: Postgres rearranca con la nueva imagen, mismo volume `atendia_v2_pg_data`, mismos datos.

**Step 4: Verificar que la extensión está disponible**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT * FROM pg_available_extensions WHERE name = 'vector';"
```

Expected: una fila con `name=vector`, `default_version=0.5+` (en la práctica `0.8.2`).

**Step 5: Verificar que los datos previos siguen ahí**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT version_num FROM alembic_version;"
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT id, name FROM tenants;"
```

Expected: `alembic_version` apunta al head correcto (`4329f44c0243` o el que esté actualmente). Si `tenants` está vacío, no es regresión de T1 — confirmar con el dev si era el estado previo. (En esta branch lo era; el seed se vuelve a correr más adelante.)

**Step 6: Commit**

```bash
git add docker-compose.yml .github/workflows/ci.yml
git commit -m "chore(docker): switch Postgres image to pgvector/pgvector:0.8.2-pg15"
```

---

## Task 2: Agregar dependencias Python (`pgvector`)

**Files:**
- Modify: `core/pyproject.toml`
- Modify: `core/uv.lock` (auto-regenerado)

**Step 1: Agregar `pgvector>=0.2.5` a `core/pyproject.toml`**

En la lista `[project] dependencies`, agregar después de `"openai>=1.50.0",`:

```toml
    "pgvector>=0.2.5",
```

**Step 2: Sync**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv sync
```

Expected: `pgvector` instalado.

**Step 3: Smoke import**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run python -c "from pgvector.sqlalchemy import Vector; print('pgvector ready')"
```

Expected: `pgvector ready`.

**Step 4: Commit**

```bash
git add core/pyproject.toml core/uv.lock
git commit -m "chore(core): add pgvector dependency for embedding columns"
```

---

## Task 3: Migración Alembic 012 — `CREATE EXTENSION vector`

**Files:**
- Create: `core/atendia/db/migrations/versions/012_pgvector_extension.py`

**Step 1: Generar revisión**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic revision -m "create pgvector extension"
```

Renombrar el archivo generado a `012_pgvector_extension.py`.

**Step 2: Editar el archivo**

```python
"""012_pgvector_extension

Revision ID: <auto-generated>
Revises: 9a35558e5d5f
"""
from alembic import op


revision = "<auto-generated-hex>"
down_revision = "9a35558e5d5f"  # last Phase 3a head
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Don't drop — other vector columns may depend on it.
    pass
```

(Use the actual auto-generated hex from `alembic revision`. The chain in this project uses random hex revisions.)

**Step 3: Apply**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic upgrade head
```

Expected: migration applied without error.

**Step 4: Verify the extension is enabled**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Expected: a row showing `vector` extension with a version number.

**Step 5: Commit**

```bash
git add core/atendia/db/migrations/versions/012_pgvector_extension.py
git commit -m "feat(db): create pgvector extension"
```

---

# Bloque B — Schema migrations

## Task 4: Migración 013 — embedding columns + indexes

**Files:**
- Create: `core/atendia/db/migrations/versions/013_catalog_faqs_embeddings.py`

**Step 1: Generate revision**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic revision -m "catalog faqs embeddings"
```

Rename to `013_catalog_faqs_embeddings.py`.

**Step 2: Edit**

```python
"""013_catalog_faqs_embeddings

Revision ID: <auto>
Revises: <012's hex>
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "<auto-generated>"
down_revision = "<012-revision-hex>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tenant_catalogs
    op.add_column("tenant_catalogs",
        sa.Column("embedding", Vector(3072), nullable=True))
    op.add_column("tenant_catalogs",
        sa.Column("category", sa.String(60), nullable=True))
    op.create_index(
        "ix_tenant_catalogs_category",
        "tenant_catalogs",
        ["tenant_id", "category"],
    )
    op.create_index(
        "ix_tenant_catalogs_embedding",
        "tenant_catalogs",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # tenant_faqs
    op.add_column("tenant_faqs",
        sa.Column("embedding", Vector(3072), nullable=True))
    op.create_index(
        "ix_tenant_faqs_embedding",
        "tenant_faqs",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_unique_constraint(
        "uq_tenant_faqs_tenant_question",
        "tenant_faqs",
        ["tenant_id", "question"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tenant_faqs_tenant_question", "tenant_faqs", type_="unique")
    op.drop_index("ix_tenant_faqs_embedding", table_name="tenant_faqs")
    op.drop_column("tenant_faqs", "embedding")
    op.drop_index("ix_tenant_catalogs_embedding", table_name="tenant_catalogs")
    op.drop_index("ix_tenant_catalogs_category", table_name="tenant_catalogs")
    op.drop_column("tenant_catalogs", "category")
    op.drop_column("tenant_catalogs", "embedding")
```

**Step 3: Apply**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic upgrade head
```

**Step 4: Verify**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "\d tenant_catalogs"
```

Expected: columns include `embedding vector(3072)` and `category varchar(60)`.

**Step 5: Verify reversibility**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: both succeed without error.

**Step 6: Commit**

```bash
git add core/atendia/db/migrations/versions/013_catalog_faqs_embeddings.py
git commit -m "feat(db): add embedding + category columns with HNSW indexes"
```

---

## Task 5: Migración 014 — `tool_cost_usd` en `turn_traces`

**Files:**
- Create: `core/atendia/db/migrations/versions/014_turn_traces_tool_cost.py`

**Step 1: Generate revision**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic revision -m "turn_traces tool_cost"
```

Rename to `014_turn_traces_tool_cost.py`.

**Step 2: Edit**

```python
"""014_turn_traces_tool_cost

Revision ID: <auto>
Revises: <013's hex>
"""
from alembic import op
import sqlalchemy as sa


revision = "<auto>"
down_revision = "<013-revision-hex>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("turn_traces",
        sa.Column("tool_cost_usd", sa.Numeric(10, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("turn_traces", "tool_cost_usd")
```

**Step 3: Apply + verify reversibility**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

**Step 4: Commit**

```bash
git add core/atendia/db/migrations/versions/014_turn_traces_tool_cost.py
git commit -m "feat(db): add tool_cost_usd to turn_traces for embedding cost tracking"
```

---

# Bloque C — Models + Pydantic types

## Task 6: Update `TenantCatalogItem` model

**Files:**
- Modify: `core/atendia/db/models/tenant_config.py`

**Step 1: Add imports + columns**

At top of `tenant_config.py`, add:

```python
from pgvector.sqlalchemy import Vector
```

In `class TenantCatalogItem(Base)`, add fields:

```python
class TenantCatalogItem(Base):
    __tablename__ = "tenant_catalogs"
    # ... existing columns: id, tenant_id, sku, name, attrs, active, created_at ...
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
```

**Step 2: Smoke test**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run python -c "from atendia.db.models import TenantCatalogItem; print(TenantCatalogItem.__table__.c.embedding.type, TenantCatalogItem.__table__.c.category.type)"
```

Expected: `VECTOR(3072) VARCHAR(60)`.

**Step 3: Run existing tests to confirm no regression**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/contracts -v
```

**Step 4: Commit**

```bash
git add core/atendia/db/models/tenant_config.py
git commit -m "feat(db): add embedding + category fields to TenantCatalogItem"
```

---

## Task 7: Update `TenantFAQ` model

**Files:**
- Modify: `core/atendia/db/models/tenant_config.py`

**Step 1: Add embedding column**

```python
class TenantFAQ(Base):
    __tablename__ = "tenant_faqs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "question", name="uq_tenant_faqs_tenant_question"),
    )
    # ... existing columns ...
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
```

**Step 2: Verify**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run python -c "from atendia.db.models import TenantFAQ; print(TenantFAQ.__table__.c.embedding.type)"
```

Expected: `VECTOR(3072)`.

**Step 3: Commit**

```bash
git add core/atendia/db/models/tenant_config.py
git commit -m "feat(db): add embedding field to TenantFAQ"
```

---

## Task 8: Add `Quote`, `FAQMatch`, `CatalogResult` Pydantic models

**Files:**
- Modify: `core/atendia/tools/base.py`
- Test: `core/tests/tools/test_tool_base_models.py` (NEW)

**Step 1: Test**

Create `core/tests/tools/test_tool_base_models.py`:

```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from atendia.tools.base import CatalogResult, FAQMatch, Quote


def test_quote_status_is_literal_ok():
    q = Quote(
        sku="adventure-150-cc", name="Adventure 150 CC", category="Motoneta",
        price_lista_mxn=Decimal("31395"), price_contado_mxn=Decimal("29900"),
        planes_credito={"plan_10": {"enganche": 3140}}, ficha_tecnica={"motor_cc": 150},
    )
    assert q.status == "ok"


def test_faq_match_score_validation():
    m = FAQMatch(pregunta="¿X?", respuesta="Y", score=0.85)
    assert m.score == 0.85


def test_catalog_result_minimal():
    r = CatalogResult(
        sku="x", name="X", category="Motoneta",
        price_contado_mxn=Decimal("29900"), score=1.0,
    )
    assert r.sku == "x"
```

**Step 2: Verify failure**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_tool_base_models.py -v
```

Expected: ImportError (`Quote`, `FAQMatch`, `CatalogResult` don't exist).

**Step 3: Implement in `core/atendia/tools/base.py`**

Append to existing file (which has `Tool`, `ToolNotFoundError`, `ToolNoDataResult`):

```python
from decimal import Decimal


class Quote(BaseModel):
    """Real-data result from quote() tool."""
    status: Literal["ok"] = "ok"
    sku: str
    name: str
    category: str
    price_lista_mxn: Decimal
    price_contado_mxn: Decimal
    planes_credito: dict
    ficha_tecnica: dict


class FAQMatch(BaseModel):
    """Single FAQ match with similarity score."""
    pregunta: str
    respuesta: str
    score: float


class CatalogResult(BaseModel):
    """Single catalog match — lighter than Quote (for browsing)."""
    sku: str
    name: str
    category: str
    price_contado_mxn: Decimal
    score: float
```

**Step 4: Run tests**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_tool_base_models.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add core/atendia/tools/base.py core/tests/tools/test_tool_base_models.py
git commit -m "feat(tools): add Quote, FAQMatch, CatalogResult Pydantic models"
```

---

# Bloque D — Embedding helper

## Task 9: `embeddings.py` wrapper + tests

**Files:**
- Create: `core/atendia/tools/embeddings.py`
- Create: `core/tests/tools/test_embeddings.py`

**Step 1: Tests**

Create `core/tests/tools/test_embeddings.py`:

```python
"""Tests for the OpenAI embeddings wrapper (mock-based)."""
from decimal import Decimal

import pytest
import respx
from httpx import Response
from openai import AsyncOpenAI

from atendia.tools.embeddings import (
    EMBEDDING_PRICE_PER_1M,
    generate_embedding,
    generate_embeddings_batch,
)


def _ok_embeddings_response(num: int, dim: int = 3072, total_tokens: int = 100):
    return Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1] * dim}
                for i in range(num)
            ],
            "model": "text-embedding-3-large",
            "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
        },
    )


@respx.mock
async def test_generate_embedding_single():
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=_ok_embeddings_response(num=1, total_tokens=10),
    )
    client = AsyncOpenAI(api_key="sk-test")
    emb, tokens, cost = await generate_embedding(client=client, text="hola")
    assert len(emb) == 3072
    assert tokens == 10
    assert cost == Decimal("0.000001")  # 10 * 0.13 / 1M


@respx.mock
async def test_generate_embeddings_batch():
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=_ok_embeddings_response(num=50, total_tokens=5000),
    )
    client = AsyncOpenAI(api_key="sk-test")
    embs, tokens, cost = await generate_embeddings_batch(
        client=client, texts=[f"texto {i}" for i in range(50)],
    )
    assert len(embs) == 50
    assert tokens == 5000
    assert cost == Decimal("0.000650")


async def test_generate_embeddings_batch_empty():
    client = AsyncOpenAI(api_key="sk-test")
    embs, tokens, cost = await generate_embeddings_batch(client=client, texts=[])
    assert embs == []
    assert tokens == 0
    assert cost == Decimal("0")


def test_cost_formula_constant():
    assert EMBEDDING_PRICE_PER_1M == Decimal("0.130")
```

**Step 2: Verify failure**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_embeddings.py -v
```

Expected: ImportError.

**Step 3: Implement `core/atendia/tools/embeddings.py`**

```python
"""OpenAI text-embedding wrapper with cost tracking.

Used both for ingestion (one-time) and for runtime queries (per-turn).
"""
from decimal import Decimal

from openai import AsyncOpenAI


# Pricing for text-embedding-3-large at 2026-05: $0.13 per 1M tokens.
EMBEDDING_PRICE_PER_1M = Decimal("0.130")


def _compute_cost(tokens: int) -> Decimal:
    return (Decimal(tokens) * EMBEDDING_PRICE_PER_1M / Decimal("1000000")).quantize(
        Decimal("0.000001")
    )


async def generate_embedding(
    *,
    client: AsyncOpenAI,
    text: str,
    model: str = "text-embedding-3-large",
) -> tuple[list[float], int, Decimal]:
    """Single-text embedding. Returns (embedding, tokens, cost_usd)."""
    resp = await client.embeddings.create(model=model, input=text)
    return resp.data[0].embedding, resp.usage.total_tokens, _compute_cost(resp.usage.total_tokens)


async def generate_embeddings_batch(
    *,
    client: AsyncOpenAI,
    texts: list[str],
    model: str = "text-embedding-3-large",
) -> tuple[list[list[float]], int, Decimal]:
    """Batch embedding (single API call). Returns (embeddings, total_tokens, total_cost)."""
    if not texts:
        return [], 0, Decimal("0")
    resp = await client.embeddings.create(model=model, input=texts)
    return (
        [item.embedding for item in resp.data],
        resp.usage.total_tokens,
        _compute_cost(resp.usage.total_tokens),
    )
```

**Step 4: Tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_embeddings.py -v
```

Expected: 4 PASS.

**Step 5: Commit**

```bash
git add core/atendia/tools/embeddings.py core/tests/tools/test_embeddings.py
git commit -m "feat(tools): add OpenAI embeddings wrapper with cost tracking"
```

---

# Bloque E — Tools refactor

## Task 10: `quote()` real

**Files:**
- Modify: `core/atendia/tools/quote.py`
- Create: `core/tests/tools/test_quote_real.py`

**Step 1: Test**

Create `core/tests/tools/test_quote_real.py`:

```python
"""Tests for quote() against real DB. Requires Postgres v2 running.

Uses the existing _seed_tenant fixture from conftest (or create one if missing).
"""
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.tools.base import Quote, ToolNoDataResult
from atendia.tools.quote import quote


pytestmark = pytest.mark.asyncio


async def test_quote_returns_quote_for_existing_sku(db_session, seeded_tenant):
    """Seed 1 catalog item, quote(sku=...) returns Quote with real prices."""
    tid = seeded_tenant
    sku = "adventure-150-cc"
    await db_session.execute(text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), true)
    """), {
        "t": tid, "s": sku, "n": "Adventure 150 CC", "c": "Motoneta",
        "a": json.dumps({
            "alias": ["adventure", "elite"],
            "ficha_tecnica": {"motor_cc": 150},
            "precio_lista": "31395",
            "precio_contado": "29900",
            "planes_credito": {"plan_10": {"enganche": 3140}},
        }),
    })
    await db_session.commit()

    result = await quote(session=db_session, tenant_id=tid, sku=sku)
    assert isinstance(result, Quote)
    assert result.sku == sku
    assert result.price_contado_mxn == Decimal("29900")
    assert result.planes_credito["plan_10"]["enganche"] == 3140


async def test_quote_returns_no_data_for_missing_sku(db_session, seeded_tenant):
    result = await quote(session=db_session, tenant_id=seeded_tenant, sku="lambretta-200")
    assert isinstance(result, ToolNoDataResult)
    assert "lambretta-200" in result.hint


async def test_quote_ignores_inactive_items(db_session, seeded_tenant):
    tid = seeded_tenant
    sku = "discontinued-100"
    await db_session.execute(text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), false)
    """), {"t": tid, "s": sku, "n": "Discontinued", "c": "Motoneta", "a": "{}"})
    await db_session.commit()

    result = await quote(session=db_session, tenant_id=tid, sku=sku)
    assert isinstance(result, ToolNoDataResult)
```

(Assumes `db_session` and `seeded_tenant` fixtures exist in `tests/conftest.py` from prior phases. If not, create them in `tests/tools/conftest.py`.)

**Step 2: Verify failure**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_quote_real.py -v
```

Expected: import error or test failures (current `quote` doesn't accept these args / doesn't return Quote).

**Step 3: Replace `core/atendia/tools/quote.py`**

```python
"""Real-data quote tool. Returns Quote with prices from tenant_catalogs."""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import Quote, ToolNoDataResult


async def quote(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    sku: str,
) -> Quote | ToolNoDataResult:
    """Look up a catalog item by sku and return its real pricing data."""
    stmt = select(TenantCatalogItem).where(
        TenantCatalogItem.tenant_id == tenant_id,
        TenantCatalogItem.sku == sku,
        TenantCatalogItem.active.is_(True),
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        return ToolNoDataResult(hint=f"sku '{sku}' not found in catalog")
    attrs = item.attrs or {}
    return Quote(
        sku=item.sku,
        name=item.name,
        category=item.category or "",
        price_lista_mxn=Decimal(str(attrs.get("precio_lista", "0"))),
        price_contado_mxn=Decimal(str(attrs.get("precio_contado", "0"))),
        planes_credito=attrs.get("planes_credito", {}),
        ficha_tecnica=attrs.get("ficha_tecnica", {}),
    )
```

**Step 4: Tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_quote_real.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add core/atendia/tools/quote.py core/tests/tools/test_quote_real.py
git commit -m "feat(tools): quote() returns real Quote from tenant_catalogs"
```

---

## Task 11: `lookup_faq()` real con búsqueda semántica

**Files:**
- Modify: `core/atendia/tools/lookup_faq.py`
- Create: `core/tests/tools/test_lookup_faq_real.py`

**Step 1: Test**

Create `core/tests/tools/test_lookup_faq_real.py`:

```python
import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.tools.base import FAQMatch, ToolNoDataResult
from atendia.tools.lookup_faq import lookup_faq


pytestmark = pytest.mark.asyncio


def _emb(seed: int, dim: int = 3072) -> list[float]:
    """Deterministic embedding: a unit vector with a 1.0 at position seed."""
    v = [0.0] * dim
    v[seed] = 1.0
    return v


async def test_lookup_faq_returns_top_k_matches(db_session, seeded_tenant):
    """Seed 5 FAQs with orthogonal embeddings; query close to first → top_k=3 returned in order."""
    tid = seeded_tenant
    for i in range(5):
        await db_session.execute(text("""
            INSERT INTO tenant_faqs (tenant_id, question, answer, embedding)
            VALUES (:t, :q, :a, :e)
        """), {"t": tid, "q": f"pregunta {i}", "a": f"respuesta {i}", "e": str(_emb(i))})
    await db_session.commit()

    result = await lookup_faq(session=db_session, tenant_id=tid, embedding=_emb(0), top_k=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    # First match should be question 0 (perfect cosine similarity).
    assert result[0].pregunta == "pregunta 0"
    assert result[0].score >= 0.99  # near 1.0


async def test_lookup_faq_filters_below_threshold(db_session, seeded_tenant):
    """If best match has score < threshold, return ToolNoDataResult."""
    tid = seeded_tenant
    await db_session.execute(text("""
        INSERT INTO tenant_faqs (tenant_id, question, answer, embedding)
        VALUES (:t, :q, :a, :e)
    """), {"t": tid, "q": "preg", "a": "resp", "e": str(_emb(100))})
    await db_session.commit()

    # Query embedding orthogonal to the one we inserted (cosine ~0).
    result = await lookup_faq(
        session=db_session, tenant_id=tid,
        embedding=_emb(0), top_k=3, score_threshold=0.5,
    )
    assert isinstance(result, ToolNoDataResult)


async def test_lookup_faq_skips_null_embeddings(db_session, seeded_tenant):
    """FAQ with embedding=None should not appear in results."""
    tid = seeded_tenant
    await db_session.execute(text("""
        INSERT INTO tenant_faqs (tenant_id, question, answer, embedding)
        VALUES (:t, :q1, :a1, NULL), (:t, :q2, :a2, :e)
    """), {"t": tid, "q1": "no embedding", "a1": "x", "q2": "with embedding", "a2": "y", "e": str(_emb(0))})
    await db_session.commit()

    result = await lookup_faq(session=db_session, tenant_id=tid, embedding=_emb(0))
    assert isinstance(result, list)
    assert all(m.pregunta != "no embedding" for m in result)
```

**Step 2: Replace `core/atendia/tools/lookup_faq.py`**

```python
"""Semantic FAQ lookup using cosine similarity via pgvector."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantFAQ
from atendia.tools.base import FAQMatch, ToolNoDataResult


async def lookup_faq(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    embedding: list[float],
    top_k: int = 3,
    score_threshold: float = 0.5,
) -> list[FAQMatch] | ToolNoDataResult:
    stmt = (
        select(
            TenantFAQ,
            (1 - TenantFAQ.embedding.cosine_distance(embedding)).label("score"),
        )
        .where(
            TenantFAQ.tenant_id == tenant_id,
            TenantFAQ.embedding.is_not(None),
        )
        .order_by(TenantFAQ.embedding.cosine_distance(embedding))
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    matches = [
        FAQMatch(pregunta=faq.question, respuesta=faq.answer, score=float(score))
        for faq, score in rows
        if score >= score_threshold
    ]
    if not matches:
        return ToolNoDataResult(hint="no FAQ above similarity threshold")
    return matches
```

**Step 3: Tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_lookup_faq_real.py -v
```

Expected: 3 PASS.

**Step 4: Commit**

```bash
git add core/atendia/tools/lookup_faq.py core/tests/tools/test_lookup_faq_real.py
git commit -m "feat(tools): lookup_faq() uses semantic similarity via pgvector"
```

---

## Task 12: `search_catalog()` híbrido

**Files:**
- Modify: `core/atendia/tools/search_catalog.py`
- Create: `core/tests/tools/test_search_catalog_real.py`

**Step 1: Test**

Create `core/tests/tools/test_search_catalog_real.py`:

```python
import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.tools.base import CatalogResult, ToolNoDataResult
from atendia.tools.search_catalog import search_catalog


pytestmark = pytest.mark.asyncio


def _emb(seed: int, dim: int = 3072) -> list[float]:
    v = [0.0] * dim
    v[seed] = 1.0
    return v


async def _insert(session, tid, sku, name, category, alias, embedding):
    attrs = {"alias": alias, "precio_contado": "29900"}
    await session.execute(text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, embedding, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), :e, true)
    """), {"t": tid, "s": sku, "n": name, "c": category, "a": json.dumps(attrs), "e": str(embedding)})


async def test_alias_keyword_match(db_session, seeded_tenant):
    """Query 'adventure' → matches via alias, score=1.0."""
    tid = seeded_tenant
    await _insert(db_session, tid, "adventure-150", "Adventure 150", "Motoneta",
                  ["adventure", "elite"], _emb(0))
    await db_session.commit()
    result = await search_catalog(
        session=db_session, tenant_id=tid, query="adventure", embedding=None,
    )
    assert isinstance(result, list)
    assert result[0].sku == "adventure-150"
    assert result[0].score == 1.0


async def test_falls_back_to_no_data_when_no_alias_and_no_embedding(db_session, seeded_tenant):
    tid = seeded_tenant
    await _insert(db_session, tid, "x-1", "X", "Motoneta", ["other"], _emb(0))
    await db_session.commit()
    result = await search_catalog(
        session=db_session, tenant_id=tid, query="nonexistent", embedding=None,
    )
    assert isinstance(result, ToolNoDataResult)


async def test_semantic_fallback(db_session, seeded_tenant):
    """No alias match, but embedding provided → semantic search returns top match."""
    tid = seeded_tenant
    await _insert(db_session, tid, "x-1", "X", "Motoneta", ["other"], _emb(0))
    await db_session.commit()
    result = await search_catalog(
        session=db_session, tenant_id=tid, query="something else",
        embedding=_emb(0),
    )
    assert isinstance(result, list)
    assert result[0].sku == "x-1"


async def test_respects_limit(db_session, seeded_tenant):
    tid = seeded_tenant
    for i in range(10):
        await _insert(db_session, tid, f"sku-{i}", f"Name {i}", "Motoneta",
                      [f"alias{i}"], _emb(i))
    await db_session.commit()
    result = await search_catalog(
        session=db_session, tenant_id=tid, query="alias3", embedding=None, limit=3,
    )
    assert isinstance(result, list)
    assert len(result) <= 3


async def test_filters_inactive(db_session, seeded_tenant):
    tid = seeded_tenant
    await db_session.execute(text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), false)
    """), {"t": tid, "s": "old-1", "n": "Old", "c": "Motoneta",
           "a": json.dumps({"alias": ["old"]})})
    await db_session.commit()
    result = await search_catalog(
        session=db_session, tenant_id=tid, query="old", embedding=None,
    )
    assert isinstance(result, ToolNoDataResult)
```

**Step 2: Replace `core/atendia/tools/search_catalog.py`**

```python
"""Hybrid catalog search: alias-keyword first, semantic fallback."""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import CatalogResult, ToolNoDataResult


def _to_result(item: TenantCatalogItem, score: float) -> CatalogResult:
    return CatalogResult(
        sku=item.sku,
        name=item.name,
        category=item.category or "",
        price_contado_mxn=Decimal(str((item.attrs or {}).get("precio_contado", "0"))),
        score=score,
    )


async def search_catalog(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    query: str,
    embedding: list[float] | None = None,
    limit: int = 5,
) -> list[CatalogResult] | ToolNoDataResult:
    # Path 1: alias-keyword match (JSONB ?| operator)
    keyword_stmt = (
        select(TenantCatalogItem)
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.active.is_(True),
            text("attrs->'alias' ?| ARRAY[:q]").bindparams(q=query.lower()),
        )
        .limit(limit)
    )
    keyword_hits = (await session.execute(keyword_stmt)).scalars().all()
    if keyword_hits:
        return [_to_result(item, score=1.0) for item in keyword_hits]

    # Path 2: semantic similarity (only if embedding provided)
    if embedding is None:
        return ToolNoDataResult(hint=f"no alias match for '{query}', semantic not invoked")

    semantic_stmt = (
        select(
            TenantCatalogItem,
            (1 - TenantCatalogItem.embedding.cosine_distance(embedding)).label("score"),
        )
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.active.is_(True),
            TenantCatalogItem.embedding.is_not(None),
        )
        .order_by(TenantCatalogItem.embedding.cosine_distance(embedding))
        .limit(limit)
    )
    rows = (await session.execute(semantic_stmt)).all()
    if not rows:
        return ToolNoDataResult(hint=f"no semantic match for '{query}'")
    return [_to_result(item, score=float(score)) for item, score in rows]
```

**Step 3: Tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools/test_search_catalog_real.py -v
```

Expected: 5 PASS.

**Step 4: Update existing `test_search_catalog.py` / `test_quote.py` / `test_lookup_faq.py`**

These tests likely reference the OLD class-based interface (`SearchCatalogTool.run(...)`). After this refactor, the function signatures changed. Update them to:
- Use the new function signatures (`search_catalog(...)`, `quote(...)`, `lookup_faq(...)`).
- Delete tests that asserted on the old `dict` return shape.
- Keep tests that exercise behavior we still preserve.

If the existing tests are too coupled to the old API, **delete them** and rely on the new `*_real.py` test files for coverage. The class-based `Tool` ABC + registry pattern can stay for tools that haven't been refactored (escalate, followup, book_appointment).

Run the broader tools suite:

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools -v
```

Fix anything that breaks.

**Step 5: Commit**

```bash
git add core/atendia/tools core/tests/tools
git commit -m "feat(tools): search_catalog hybrid alias+semantic; obsolete tests removed"
```

---

# Bloque F — Ingestion script

## Task 13: Ingestion helpers (pure functions, no IO)

**Files:**
- Create: `core/atendia/scripts/ingest_dinamo_data.py` (helpers only — `_main` in T14)
- Create: `core/tests/scripts/test_ingest_dinamo_data.py`

**Step 1: Tests**

Create `core/tests/scripts/test_ingest_dinamo_data.py`:

```python
from atendia.scripts.ingest_dinamo_data import (
    _embedding_text_for_catalog_item,
    _flatten_catalog,
    _slugify,
)


def test_slugify():
    assert _slugify("Adventure Elite 150 CC") == "adventure-elite-150-cc"
    assert _slugify("Heavy Cab-R 200 CC") == "heavy-cab-r-200-cc"
    assert _slugify("MotoCross / Doble Propósito") == "motocross-doble-propósito"


def test_flatten_catalog():
    sample = {
        "catalogo": [
            {"categoria": "Motoneta", "modelos": [
                {"modelo": "X 100 CC", "alias": ["x"], "ficha_tecnica": {"motor_cc": 100},
                 "precios": {"lista": 20000, "contado": 19000},
                 "planes_credito": {"plan_10": {"enganche": 2000}}},
            ]},
            {"categoria": "Chopper", "modelos": [
                {"modelo": "Y 200 CC", "alias": ["y"], "ficha_tecnica": {"motor_cc": 200},
                 "precios": {"lista": 30000, "contado": 28000}, "planes_credito": {}},
            ]},
        ]
    }
    items = _flatten_catalog(sample)
    assert len(items) == 2
    assert items[0]["sku"] == "x-100-cc"
    assert items[0]["name"] == "X 100 CC"
    assert items[0]["category"] == "Motoneta"
    assert items[0]["attrs"]["precio_contado"] == "19000"
    assert items[0]["attrs"]["alias"] == ["x"]
    assert items[1]["sku"] == "y-200-cc"
    assert items[1]["category"] == "Chopper"


def test_embedding_text_for_catalog_item():
    item = {
        "name": "Adventure 150 CC", "category": "Motoneta",
        "attrs": {
            "alias": ["adventure", "elite"],
            "ficha_tecnica": {"motor_cc": 150, "potencia_hp": 9, "transmision": "Automática"},
            "precio_contado": "29900",
        },
    }
    text = _embedding_text_for_catalog_item(item)
    assert "Categoría: Motoneta" in text
    assert "Adventure 150 CC" in text
    assert "150 CC" in text
    assert "29900" in text
```

**Step 2: Verify failure**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/scripts/test_ingest_dinamo_data.py -v
```

Expected: ImportError.

**Step 3: Implement helpers in `core/atendia/scripts/ingest_dinamo_data.py`**

```python
"""Ingest Dinamo's catalog + FAQs + plans into DB with embeddings.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.ingest_dinamo_data \\
        --tenant-id <uuid> --docs-dir ../docs [--dry-run]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID


def _slugify(s: str) -> str:
    """'Adventure Elite 150 CC' → 'adventure-elite-150-cc'.
    Slashes become hyphens. Multi-spaces collapse."""
    return "-".join(s.lower().replace("/", "-").split())


def _flatten_catalog(catalog_json: dict) -> list[dict[str, Any]]:
    """Tree of categories → flat list of items with `category` field."""
    items = []
    for cat_block in catalog_json.get("catalogo", []):
        category = cat_block.get("categoria", "")
        for modelo in cat_block.get("modelos", []):
            sku = _slugify(modelo["modelo"])
            items.append({
                "sku": sku,
                "name": modelo["modelo"],
                "category": category,
                "attrs": {
                    "alias": modelo.get("alias", []),
                    "ficha_tecnica": modelo.get("ficha_tecnica", {}),
                    "precio_lista": str(modelo.get("precios", {}).get("lista", "0")),
                    "precio_contado": str(modelo.get("precios", {}).get("contado", "0")),
                    "planes_credito": modelo.get("planes_credito", {}),
                },
            })
    return items


def _embedding_text_for_catalog_item(item: dict[str, Any]) -> str:
    """Concatenate fields into the text we embed.
    What gets embedded determines what queries match.
    """
    f = item["attrs"].get("ficha_tecnica", {})
    return (
        f"Categoría: {item['category']}. "
        f"Modelo: {item['name']}. "
        f"Alias: {', '.join(item['attrs'].get('alias', []))}. "
        f"Motor: {f.get('motor_cc', '?')} CC. "
        f"Potencia: {f.get('potencia_hp', '?')} HP. "
        f"Transmisión: {f.get('transmision', '?')}. "
        f"Precio contado: ${item['attrs'].get('precio_contado', '?')}."
    )
```

**Step 4: Tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/scripts/test_ingest_dinamo_data.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add core/atendia/scripts/ingest_dinamo_data.py core/tests/scripts/test_ingest_dinamo_data.py
git commit -m "feat(scripts): ingestion helpers (flatten, slugify, embedding text)"
```

---

## Task 14: Ingestion `_main` async logic

**Files:**
- Modify: `core/atendia/scripts/ingest_dinamo_data.py`
- Modify: `core/tests/scripts/test_ingest_dinamo_data.py`

**Step 1: Add idempotency test**

Append to `test_ingest_dinamo_data.py`:

```python
import pytest
from sqlalchemy import text


pytestmark_db = pytest.mark.asyncio


async def test_ingest_idempotent_inserts_only_once(db_session, seeded_tenant, monkeypatch, respx_mock):
    """Run ingestion twice on same tenant; row counts stay the same."""
    from pathlib import Path
    import respx
    from httpx import Response

    # Mock OpenAI embeddings endpoint to always return dim-3072 vectors
    respx_mock.post("https://api.openai.com/v1/embeddings").mock(
        return_value=Response(200, json={
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * 3072}],
            "model": "text-embedding-3-large",
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        })
    )

    # Use a tiny test docs directory (or skip and use real docs/ if available).
    # ... setup fixtures docs/ ...
    # First run
    # ... call _main(tenant_id=seeded_tenant, docs_dir=..., dry_run=False)
    # Get row count
    # Second run
    # ... same call
    # Assert row count unchanged
```

(This test is complex; you can mark it skip-if-no-docs or simply test the ingestion in T15 manually.)

**Step 2: Implement `_main` in `core/atendia/scripts/ingest_dinamo_data.py`**

Append to the existing file:

```python
async def _main(tenant_id: UUID, docs_dir: Path, dry_run: bool) -> int:
    from openai import AsyncOpenAI
    from sqlalchemy import text
    from atendia.config import get_settings
    from atendia.db.session import _get_factory
    from atendia.tools.embeddings import generate_embeddings_batch

    settings = get_settings()
    if not settings.openai_api_key:
        print("ATENDIA_V2_OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    catalog_json = json.loads((docs_dir / "CATALOGO_MODELOS.json").read_text(encoding="utf-8"))
    faq_json = json.loads((docs_dir / "FAQ_CREDITO.json").read_text(encoding="utf-8"))
    plans_json = json.loads((docs_dir / "REQUISITOS_PLANES.json").read_text(encoding="utf-8"))

    catalog_items = _flatten_catalog(catalog_json)
    faqs = faq_json.get("faq", [])
    planes = plans_json.get("planes", [])

    print(f"Ingesting for tenant {tenant_id}:")
    print(f"  Catálogo: {len(catalog_items)} items")
    print(f"  FAQs: {len(faqs)}")
    print(f"  Planes: {len(planes)}")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    catalog_texts = [_embedding_text_for_catalog_item(it) for it in catalog_items]
    faq_texts = [f["pregunta"] + " " + f["respuesta"] for f in faqs]

    print("Generating embeddings...")
    cat_embs, cat_tokens, cat_cost = await generate_embeddings_batch(client=client, texts=catalog_texts)
    faq_embs, faq_tokens, faq_cost = await generate_embeddings_batch(client=client, texts=faq_texts)
    total_cost = cat_cost + faq_cost
    print(f"  Tokens: {cat_tokens + faq_tokens}, cost: ${total_cost}")

    if dry_run:
        print("[dry run] not writing")
        return 0

    factory = _get_factory()
    async with factory() as session:
        for item, emb in zip(catalog_items, cat_embs, strict=True):
            await session.execute(text("""
                INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, embedding, active)
                VALUES (:t, :sku, :n, :cat, CAST(:a AS jsonb), :e, true)
                ON CONFLICT (tenant_id, sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    attrs = EXCLUDED.attrs,
                    embedding = EXCLUDED.embedding,
                    active = true
            """), {
                "t": tenant_id, "sku": item["sku"], "n": item["name"],
                "cat": item["category"], "a": json.dumps(item["attrs"]),
                "e": str(emb),
            })

        for faq, emb in zip(faqs, faq_embs, strict=True):
            await session.execute(text("""
                INSERT INTO tenant_faqs (tenant_id, question, answer, tags, embedding)
                VALUES (:t, :q, :a, CAST(:tags AS jsonb), :e)
                ON CONFLICT (tenant_id, question) DO UPDATE SET
                    answer = EXCLUDED.answer,
                    tags = EXCLUDED.tags,
                    embedding = EXCLUDED.embedding
            """), {
                "t": tenant_id, "q": faq["pregunta"], "a": faq["respuesta"],
                "tags": json.dumps(faq.get("documentos", [])),
                "e": str(emb),
            })

        await session.execute(text("""
            UPDATE tenant_branding
            SET default_messages = jsonb_set(
                COALESCE(default_messages, '{}'::jsonb), '{planes}', CAST(:p AS jsonb)
            )
            WHERE tenant_id = :t
        """), {"t": tenant_id, "p": json.dumps(planes)})

        await session.commit()
    print(f"Done. Total cost: ${total_cost}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--docs-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.tenant_id, args.docs_dir, args.dry_run)))
```

**Step 3: Pre-requisite — UNIQUE constraint on `tenant_catalogs(tenant_id, sku)`**

Check if it already exists (probably from Phase 1 migration 007):

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "\d tenant_catalogs"
```

If `uq_tenant_catalogs_tenant_sku` is not there, the `ON CONFLICT` clause will fail. Add it to migration 013 or create a small migration 015 to add it.

**Step 4: Commit**

```bash
git add core/atendia/scripts/ingest_dinamo_data.py core/tests/scripts/test_ingest_dinamo_data.py
git commit -m "feat(scripts): ingest_dinamo_data _main with idempotent upserts"
```

---

## Task 15: Run ingestion against local DB

**Files:** none new — verification step.

**Step 1: Dry-run first to check costs**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && PYTHONPATH=. uv run python -m atendia.scripts.ingest_dinamo_data --tenant-id eb272fdc-0795-41ef-869c-801f3a2d4ffb --docs-dir ../docs --dry-run
```

(Use the actual Dinamo UUID from your local DB — `eb272fdc-...` was seeded earlier.)

Expected output:
```
Ingesting for tenant eb272fdc-...:
  Catálogo: ~30 items
  FAQs: ~12
  Planes: ~7
Generating embeddings...
  Tokens: ~5000, cost: $0.000650
[dry run] not writing
```

**Step 2: Real run**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && PYTHONPATH=. uv run python -m atendia.scripts.ingest_dinamo_data --tenant-id eb272fdc-0795-41ef-869c-801f3a2d4ffb --docs-dir ../docs
```

Expected: same output but ending with `Done. Total cost: $0.000650`.

**Step 3: Verify rows**

```bash
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT COUNT(*) FROM tenant_catalogs WHERE tenant_id = 'eb272fdc-0795-41ef-869c-801f3a2d4ffb' AND embedding IS NOT NULL;"
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT COUNT(*) FROM tenant_faqs WHERE tenant_id = 'eb272fdc-0795-41ef-869c-801f3a2d4ffb' AND embedding IS NOT NULL;"
docker exec atendia_postgres_v2 psql -U atendia -d atendia_v2 -c "SELECT default_messages->'planes' FROM tenant_branding WHERE tenant_id = 'eb272fdc-0795-41ef-869c-801f3a2d4ffb';"
```

Expected: catalog count ≈ 30, FAQ count ≈ 12, planes JSONB array with 7 entries.

**Step 4: Test idempotency**

Run the ingestion command from Step 2 again. Re-verify counts haven't changed.

**Step 5: Commit (no code changes — this is a manual verification task)**

Skip. The verification doesn't produce any artifact to commit.

---

# Bloque G — Composer prompts

## Task 16: ACTION_GUIDANCE updates for quote/lookup_faq/search_catalog

**Files:**
- Modify: `core/atendia/runner/composer_prompts.py`
- Modify: `core/tests/runner/test_composer_prompts.py`

**Step 1: Tests**

Append to `test_composer_prompts.py`:

```python
def test_action_guidance_quote_handles_status_ok():
    """For ok payload, prompt instructs to give real price + popular plan."""
    assert "status='ok'" in ACTION_GUIDANCE["quote"] or "status=\"ok\"" in ACTION_GUIDANCE["quote"]
    assert "price_contado_mxn" in ACTION_GUIDANCE["quote"]
    assert "plan_10" in ACTION_GUIDANCE["quote"] or "plan más popular" in ACTION_GUIDANCE["quote"].lower()


def test_action_guidance_quote_says_no_inventes_other_price():
    """Anti-hallucination clause kept."""
    assert "NO INVENTES" in ACTION_GUIDANCE["quote"].upper() or "no inventes" in ACTION_GUIDANCE["quote"].lower()


def test_action_guidance_lookup_faq_handles_matches_field():
    assert "matches" in ACTION_GUIDANCE["lookup_faq"]


def test_action_guidance_search_catalog_present():
    """search_catalog wasn't in ACTION_GUIDANCE in Phase 3b — added in 3c.1."""
    assert "search_catalog" in ACTION_GUIDANCE
    assert "results" in ACTION_GUIDANCE["search_catalog"]
```

**Step 2: Verify failure**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_composer_prompts.py -v -k "quote_handles or quote_says_no_inventes or lookup_faq_handles or search_catalog_present"
```

Expected: failures because the strings aren't in the prompts yet.

**Step 3: Update `composer_prompts.py`**

Replace `ACTION_GUIDANCE["quote"]` with:

```python
    "quote": (
        "Acción: COTIZAR. El sistema te pasa los datos REALES en action_payload:\n"
        "  - status='ok': hay precio. Campos: name, category, price_lista_mxn, "
        "    price_contado_mxn, planes_credito (dict de planes 10/15/20/30%), "
        "    ficha_tecnica (motor_cc, potencia_hp, etc.).\n"
        "  - status='no_data': el modelo no se encontró. Pregunta al cliente "
        "    cuál modelo le interesa (sin inventar uno).\n"
        "Si status='ok':\n"
        "- DA el precio de contado en MXN, formateado con coma de miles "
        "  (ej: $32,900). NO INVENTES otro precio.\n"
        "- Menciona el plan más popular (plan_10 o plan_15) con enganche "
        "  y pago quincenal (formateados con $).\n"
        "- Pregunta si quiere financiamiento o contado.\n"
        "- Máximo 2 mensajes (cap del max_messages). Sé natural."
    ),
```

Replace `ACTION_GUIDANCE["lookup_faq"]` with:

```python
    "lookup_faq": (
        "Acción: RESPONDER FAQ. El sistema te pasa los matches encontrados "
        "en action_payload.matches (lista de {pregunta, respuesta, score}).\n"
        "- Si action_payload.matches NO está vacía: usa la PRIMERA match para "
        "  responder. Adapta la respuesta al tono (informal mexicano), pero "
        "  NO inventes datos extra. Si la respuesta tiene una lista, "
        "  enuméralala con bullets cortos.\n"
        "- Si action_payload.status='no_data': el cliente preguntó algo "
        "  que NO está en la base. Redirige diciendo que lo consultas. "
        "  NO inventes una respuesta. DEBES decir literalmente algo como:\n"
        "    'Déjame revisar y te confirmo en un momento.'"
    ),
```

Add new entry `ACTION_GUIDANCE["search_catalog"]`:

```python
    "search_catalog": (
        "Acción: PRESENTAR OPCIONES DE CATÁLOGO. action_payload.results es una "
        "lista de hasta 5 motos {sku, name, category, price_contado_mxn, score}.\n"
        "- Si results tiene 1 item: presenta esa moto y sugiere ver el precio detallado.\n"
        "- Si results tiene 2-5 items: lista 3 máximo con nombre + precio "
        "  (en bullets), pregunta cuál le interesa.\n"
        "- NO INVENTES motos que no estén en results. NO mezcles datos entre items.\n"
        "- Si results vacío o status='no_data': pregunta más detalles del modelo o categoría."
    ),
```

**Step 4: Tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_composer_prompts.py -v
```

Expected: all PASS.

**Step 5: Commit**

```bash
git add core/atendia/runner/composer_prompts.py core/tests/runner/test_composer_prompts.py
git commit -m "feat(composer): ACTION_GUIDANCE updated for real quote/lookup_faq/search_catalog data"
```

---

## Task 17: Snapshot test for quote prompt with real data

**Files:**
- Create: `core/tests/fixtures/composer/quote_dinamo_with_data_system.txt`
- Modify: `core/tests/runner/test_composer_prompts.py`

**Step 1: Generate the fixture**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && PYTHONIOENCODING=utf-8 uv run python -c "
from pathlib import Path
from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput

m = build_composer_prompt(ComposerInput(
    action='quote',
    action_payload={
        'status': 'ok',
        'sku': 'adventure-150-cc',
        'name': 'Adventure 150 CC',
        'category': 'Motoneta',
        'price_lista_mxn': '31395',
        'price_contado_mxn': '29900',
        'planes_credito': {'plan_10': {'enganche': 3140, 'pago_quincenal': 1247, 'quincenas': 72}},
        'ficha_tecnica': {'motor_cc': 150},
    },
    current_stage='quote',
    extracted_data={'interes_producto': 'Adventure', 'ciudad': 'CDMX'},
    tone=Tone(
        register='informal_mexicano',
        use_emojis='sparingly',
        max_words_per_message=40,
        bot_name='Dinamo',
        forbidden_phrases=['estimado cliente', 'le saluda atentamente'],
        signature_phrases=['¡qué onda!', 'te paso'],
    ),
))
Path('tests/fixtures/composer/quote_dinamo_with_data_system.txt').write_text(
    m[0]['content'], encoding='utf-8', newline='',
)
print('fixture written')
"
```

**Step 2: Add snapshot test**

Append to `test_composer_prompts.py`:

```python
def test_composer_quote_with_data_snapshot():
    """Byte-equality guard for the quote prompt with real action_payload."""
    expected = (_FIXTURES / "quote_dinamo_with_data_system.txt").read_text(encoding="utf-8")
    msgs = build_composer_prompt(ComposerInput(
        action="quote",
        action_payload={
            "status": "ok",
            "sku": "adventure-150-cc",
            "name": "Adventure 150 CC",
            "category": "Motoneta",
            "price_lista_mxn": "31395",
            "price_contado_mxn": "29900",
            "planes_credito": {"plan_10": {"enganche": 3140, "pago_quincenal": 1247, "quincenas": 72}},
            "ficha_tecnica": {"motor_cc": 150},
        },
        current_stage="quote",
        extracted_data={"interes_producto": "Adventure", "ciudad": "CDMX"},
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
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_composer_prompts.py::test_composer_quote_with_data_snapshot -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add core/tests/fixtures/composer/quote_dinamo_with_data_system.txt core/tests/runner/test_composer_prompts.py
git commit -m "test(composer): snapshot for quote+real-data system prompt"
```

---

# Bloque H — Runner integration

## Task 18: Runner dispatches real tools

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- Modify: `core/tests/runner/test_conversation_runner.py`

**Step 1: Tests**

Append to `test_conversation_runner.py`:

```python
async def test_runner_dispatches_quote_with_real_data(...):
    """Seed catalog with Adventure; runner.run_turn with intent=ask_price + entity Adventure
    populates composer_input.action_payload with status='ok' and price_contado_mxn=29900."""
    # ... fixture setup ...
    # Run turn
    # Read trace.composer_input
    # Assert payload['status'] == 'ok'
    # Assert payload['price_contado_mxn'] == '29900'

async def test_runner_quote_falls_back_for_unknown_model(...):
    """NLU extracts 'Lambretta' (not in catalog) → composer_input.action_payload.status == 'no_data'."""

async def test_runner_lookup_faq_uses_embedding(...):
    """NLU intent=ask_info → embedding generated → action_payload.matches populated."""
```

(These tests require a fake composer that records the input, plus respx mock for embedding API.)

**Step 2: Implement the runner refactor**

In `conversation_runner.py`, replace the existing tool dispatch block:

```python
# (around the existing "if decision.action == 'quote':" block)

action_payload: dict = {}
tool_cost_usd = Decimal("0")  # accumulator for embedding API calls this turn

if decision.action == "quote":
    interes_producto = (
        state_obj.extracted_data.get("interes_producto").value
        if state_obj.extracted_data.get("interes_producto")
        else None
    )
    if interes_producto:
        # Step 1: resolve SKU via alias-keyword (no embedding cost)
        from atendia.tools.search_catalog import search_catalog
        catalog_hits = await search_catalog(
            session=self._session, tenant_id=tenant_id,
            query=str(interes_producto), embedding=None, limit=1,
        )
        if isinstance(catalog_hits, list) and catalog_hits:
            from atendia.tools.quote import quote
            quote_result = await quote(
                session=self._session, tenant_id=tenant_id, sku=catalog_hits[0].sku,
            )
            action_payload = quote_result.model_dump(mode="json")
        else:
            from atendia.tools.base import ToolNoDataResult
            action_payload = ToolNoDataResult(
                hint=f"no catalog match for '{interes_producto}'"
            ).model_dump(mode="json")
    else:
        from atendia.tools.base import ToolNoDataResult
        action_payload = ToolNoDataResult(
            hint="no interes_producto extracted yet"
        ).model_dump(mode="json")

elif decision.action == "lookup_faq":
    settings = get_settings()
    from openai import AsyncOpenAI
    from atendia.tools.embeddings import generate_embedding
    from atendia.tools.lookup_faq import lookup_faq
    if settings.openai_api_key:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        embedding, _, emb_cost = await generate_embedding(
            client=client, text=inbound.text,
        )
        tool_cost_usd += emb_cost
        faq_result = await lookup_faq(
            session=self._session, tenant_id=tenant_id,
            embedding=embedding, top_k=3,
        )
        if isinstance(faq_result, list):
            action_payload = {"matches": [m.model_dump(mode="json") for m in faq_result]}
        else:
            action_payload = faq_result.model_dump(mode="json")
    else:
        from atendia.tools.base import ToolNoDataResult
        action_payload = ToolNoDataResult(hint="no api key").model_dump(mode="json")

elif decision.action == "search_catalog":
    from atendia.tools.search_catalog import search_catalog
    interes_producto = (
        state_obj.extracted_data.get("interes_producto").value
        if state_obj.extracted_data.get("interes_producto")
        else inbound.text
    )
    catalog_hits = await search_catalog(
        session=self._session, tenant_id=tenant_id,
        query=str(interes_producto), embedding=None,
    )
    if isinstance(catalog_hits, list) and catalog_hits:
        action_payload = {"results": [r.model_dump(mode="json") for r in catalog_hits]}
    else:
        # Fall back to semantic
        settings = get_settings()
        if settings.openai_api_key:
            from openai import AsyncOpenAI
            from atendia.tools.embeddings import generate_embedding
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            embedding, _, emb_cost = await generate_embedding(
                client=client, text=str(interes_producto),
            )
            tool_cost_usd += emb_cost
            semantic_hits = await search_catalog(
                session=self._session, tenant_id=tenant_id,
                query=str(interes_producto), embedding=embedding,
            )
            if isinstance(semantic_hits, list):
                action_payload = {"results": [r.model_dump(mode="json") for r in semantic_hits]}
            else:
                action_payload = semantic_hits.model_dump(mode="json")
        else:
            from atendia.tools.base import ToolNoDataResult
            action_payload = ToolNoDataResult(hint="no api key").model_dump(mode="json")

# (Other actions: ask_field, close — unchanged from Phase 3b)
```

**Step 3: Verify tests pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_conversation_runner.py -v
```

**Step 4: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "feat(runner): dispatch real tools (quote/lookup_faq/search_catalog) with embedding"
```

---

## Task 19: Persist `tool_cost_usd` to `turn_traces`

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py`
- Modify: `core/tests/runner/test_conversation_runner.py`

**Step 1: Test**

Append:

```python
async def test_runner_persists_tool_cost_when_embedding_used(...):
    """When lookup_faq is invoked, tool_cost_usd is populated in turn_traces."""
    # ... setup with respx mock for embeddings ...
    # Run turn with action=lookup_faq
    # Query trace.tool_cost_usd
    # Assert > 0
```

**Step 2: Implement persistence**

In the runner, after the tool dispatch block, add `tool_cost_usd` to the `TurnTrace(...)` constructor:

```python
trace = TurnTrace(
    # ... existing fields ...
    tool_cost_usd=tool_cost_usd if tool_cost_usd > 0 else None,
)
```

Also accumulate into `conversation_state.total_cost_usd`:

```python
if tool_cost_usd > 0:
    await self._session.execute(
        text("UPDATE conversation_state SET total_cost_usd = total_cost_usd + :c "
             "WHERE conversation_id = :cid"),
        {"c": tool_cost_usd, "cid": conversation_id},
    )
```

**Step 3: Test pass**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/runner/test_conversation_runner.py -v
```

**Step 4: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner.py
git commit -m "feat(runner): persist tool_cost_usd to turn_traces and accumulate in total"
```

---

# Bloque I — Tests adicionales

## Task 20: Update obsolete `test_quote.py` / `test_lookup_faq.py` / `test_search_catalog.py`

**Files:**
- Modify: `core/tests/tools/test_quote.py`
- Modify: `core/tests/tools/test_lookup_faq.py`
- Modify: `core/tests/tools/test_search_catalog.py`

**Step 1: Identify what's obsolete**

These existing test files were written for the OLD class-based interface (`QuoteTool.run(...)`). After T10–T12 the interface changed to plain async functions (`quote(...)`).

**Step 2: Decision per test**

For each test in the 3 files:
- If the test exercises behavior covered by `*_real.py` (T10–T12): **DELETE**.
- If the test exercises edge cases not covered (e.g., specific input validation): adapt to new signature.

**Step 3: Run**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/tools -v
```

Expected: all PASS.

**Step 4: Commit**

```bash
git add core/tests/tools
git commit -m "test(tools): clean obsolete tests covered by *_real.py"
```

---

## Task 21: E2E integration test with real catalog

**Files:**
- Create: `core/tests/integration/test_inbound_with_real_catalog.py`

**Step 1: Write the test**

```python
"""E2E: webhook → runner → real Dinamo catalog → outbound message has real price."""
import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from atendia.config import get_settings
from atendia.main import app


@respx.mock
def test_inbound_to_quote_with_real_catalog(
    monkeypatch, setup_dinamo_with_catalog,
):
    """Send 'cuanto cuesta el Adventure?' via webhook. The bot should
    respond with a message containing the real Adventure price ($29,900)."""
    monkeypatch.setenv("ATENDIA_V2_NLU_PROVIDER", "openai")
    monkeypatch.setenv("ATENDIA_V2_COMPOSER_PROVIDER", "openai")
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()

    # Mock NLU + Composer + Embeddings calls.
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[
            # NLU response: ask_price + Adventure
            _ok_nlu_response(intent="ask_price", entities={
                "interes_producto": {"value": "Adventure", "confidence": 0.9, "source_turn": 0},
            }),
            # Composer response: includes real price
            _ok_composer_response(messages=["¡Qué onda! El Adventure 150 CC cuesta $29,900 de contado."]),
        ],
    )

    tid = setup_dinamo_with_catalog
    body = json.dumps(_payload("wamid.test_3c1", "cuanto cuesta el Adventure?")).encode("utf-8")
    sig = _sign(body)

    with TestClient(app) as client:
        resp = client.post(f"/webhooks/meta/{tid}", content=body,
                           headers={"x-hub-signature-256": sig})
    assert resp.status_code == 200

    # Verify outbound message contains "29,900"
    # (query the messages or arq queue / inspect a fixture)
```

(Use existing test helpers `_ok_nlu_response`, `_ok_composer_response`, `_payload`, `_sign` from `test_inbound_to_runner.py`.)

**Step 2: Implement `setup_dinamo_with_catalog` fixture** (in `conftest.py`)

```python
@pytest.fixture
def setup_dinamo_with_catalog(setup_tenant_with_pipeline):
    """Set up tenant + pipeline + 1 catalog item (Adventure 150 CC)."""
    tid = setup_tenant_with_pipeline
    # Insert catalog item with embedding=NULL (we don't need it for alias match)
    # Insert 1 row in tenant_catalogs with sku=adventure-150-cc, name=Adventure 150 CC,
    # alias=["adventure"], precio_contado=29900
    return tid
```

**Step 3: Run**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest tests/integration/test_inbound_with_real_catalog.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add core/tests/integration/test_inbound_with_real_catalog.py
git commit -m "test(integration): E2E webhook → real catalog → outbound with price"
```

---

# Bloque J — Live + cierre

## Task 22: Live test for "no inventa precios" with real catalog

**Files:**
- Create: `core/tests/runner/test_phase3c_live.py`

**Step 1: Write the test**

```python
"""Live OpenAI test with real Dinamo catalog. Cost ~$0.002.

Most important: ensure gpt-4o uses the REAL price from action_payload
and does NOT invent a different one.
"""
import os
import re

import pytest

# (Implementation: build a ComposerInput with action='quote' + real Adventure data,
# call OpenAIComposer.compose(), assert the response contains "29,900" or "31,395"
# and does NOT contain any other 4-6 digit number resembling a price.)
```

(This is similar to the existing `test_composer_live.py` but uses a real catalog payload.)

**Step 2: Run with flag**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && RUN_LIVE_LLM_TESTS=1 uv run pytest tests/runner/test_phase3c_live.py -v
```

Expected: PASS.

**Step 3: Commit**

```bash
git add core/tests/runner/test_phase3c_live.py
git commit -m "test(phase3c): live test verifies gpt-4o uses real price, no invention"
```

---

## Task 23: Coverage gate + lint + mypy

**Step 1: Coverage**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest --cov=atendia --cov-fail-under=85 --cov-report=term-missing
```

Expected: PASS gate ≥85%.

**Step 2: Lint**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run ruff check . 2>&1 | tail -20
```

Fix any new violations introduced by Phase 3c.1.

**Step 3: mypy**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run mypy atendia 2>&1 | tail -30
```

Address Phase 3c.1 errors. Pre-existing out of scope.

**Step 4: Commit (if changes)**

```bash
git add ...
git commit -m "chore: bring Phase 3c.1 to coverage/lint/mypy gates"
```

---

## Task 24: README + memory updates

**Files:**
- Modify: `README.md`
- Modify: `core/README.md`
- Update: `~/.claude/projects/.../memory/project_overview.md`

**Step 1: README.md status**

Update the Phase 3c entry:

```markdown
- ⏳ **Phase 3c** — Migración real de Dinamo + integraciones avanzadas
  - ✅ **3c.1** — Datos reales (catálogo + FAQs + planes con embeddings via pgvector)
  - ⏳ **3c.2** — Router LLM + flow v1 (PLAN/SALES/DOC/etc. modes)
  - ⏳ **3c.3** — Multimedia (imágenes + Vision API + validación de docs)
```

**Step 2: core/README.md**

Add to env section:
- pgvector image requirement (`docker-compose.yml`)

Add to "Activación" section:
- `uv run python -m atendia.scripts.ingest_dinamo_data --tenant-id <UUID> --docs-dir ../docs`

**Step 3: Memory update**

Update `project_overview.md`:

```markdown
- ✅ Phase 3c.1: Datos reales — completed YYYY-MM-DD; commit history on branch `feat/phase-3c1-datos-reales`. <N> tests, <%> coverage.
```

**Step 4: Commit**

```bash
git add README.md core/README.md
git commit -m "docs: mark Phase 3c.1 (real data) as complete"
```

---

## Task 25: Smoke real end-to-end

**Files:** none — manual verification.

**Step 1: Setup**

Ensure:
- Docker up
- API key in `.env`
- `composer_provider=openai`, `nlu_provider=openai` in `.env`
- Dinamo catálogo + FAQs ya ingestados (T15)

**Step 2: Send real WhatsApp message**

Via ngrok + Meta sandbox, or via curl simulating webhook, send: "cuanto cuesta el Adventure?"

Expected response: includes "$29,900" or "$31,395" (real Adventure prices).

**Step 3: Verify cost**

```sql
SELECT AVG(nlu_cost_usd), AVG(composer_cost_usd), AVG(tool_cost_usd), AVG(total_cost_usd)
FROM turn_traces
WHERE tenant_id = '<dinamo>' AND created_at > NOW() - INTERVAL '1 hour';
```

Expected: total_cost_usd ≈ $0.0015–0.0025 per turn.

**Step 4: No commit (manual verification).**

---

## Task 26: Final verification + tag

**Step 1: Run full suite**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest --cov=atendia --cov-fail-under=85 -q
```

Expected: PASS.

**Step 2: Tag (optional)**

```bash
git tag phase-3c1-datos-reales
```

**Step 3: Commit final summary**

If anything else needs commit (changelog, etc.), do it.

---

## Verificación final del éxito de la fase

| # | Criterio | Comando |
|---|---|---|
| 1 | Suite completa pasa | `pytest -q` |
| 2 | Coverage ≥ 85% | `pytest --cov-fail-under=85` |
| 3 | Live test "no inventa" pasa | `RUN_LIVE_LLM_TESTS=1 pytest tests/runner/test_phase3c_live.py` |
| 4 | Ingestion idempotente | run twice, row counts unchanged |
| 5 | lookup_faq semantic OK | "¿cuánto pongo de inicial?" matches FAQ enganche |
| 6 | search_catalog hybrid OK | "Adventure" → alias; "moto urbana" → semantic |
| 7 | quote real | bot responds with "$29,900" or "$31,395" for Adventure |
| 8 | Costo medido ≈ $0.002 + embedding | `SELECT AVG(tool_cost_usd) FROM turn_traces` |

Cumplido todo, **Phase 3c.1 queda lista**. Próximo paso: brainstorm de Phase 3c.2 (router LLM + flow v1).

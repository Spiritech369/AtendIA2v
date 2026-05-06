# AtendIA v2 — Fase 3c.1: Datos reales (catálogo + FAQs + planes con embeddings) — Diseño

> **Estado:** diseño aprobado, pendiente de plan de implementación.
> **Fecha:** 2026-05-05
> **Autor:** brainstorm conjunto (Frank + Claude)
> **Reemplaza:** las tools `quote/lookup_faq/search_catalog` que devuelven `ToolNoDataResult` (Phase 3b stubs) por queries reales contra `tenant_catalogs`/`tenant_faqs` poblados con embeddings.

---

## 1. Contexto y objetivo

Phase 3a sustituyó `KeywordNLU` por `OpenAINLU` (gpt-4o-mini con structured outputs). Phase 3b sustituyó `_PHASE2_TEXTS` por `OpenAIComposer` (gpt-4o con tono per-tenant). Pero las tools (`quote`, `lookup_faq`, `search_catalog`) siguen devolviendo `ToolNoDataResult`, así que el bot "redirige" en vez de responder con datos reales.

**Objetivo Phase 3c.1**: poblar la DB con el catálogo real de Dinamo (30 motos), las 12 FAQs de crédito y los 7 planes con requisitos. Reemplazar las tools stubs por queries SQL reales con búsqueda híbrida (alias-keyword + semántica via pgvector). El bot deja de redirigir y empieza a dar precios y respuestas reales.

**Phase 3c se parte en 3 sub-fases que se mergean por separado**:

- **3c.1 (este diseño)** — datos reales, ~1 semana.
- **3c.2** — router LLM + flow v1 (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT modes), ~1-2 semanas.
- **3c.3** — multimedia (recepción de imágenes + Vision API + validación de documentos), ~1-2 semanas.

---

## 2. Decisiones tomadas en el brainstorm

| # | Decisión | Elección | Alternativas descartadas |
|---|---|---|---|
| 1 | Alcance Phase 3c.1 | **Solo datos reales** (no router, no multimedia) | Todo el flow v1 en una fase; solo PLAN MODE |
| 2 | Embeddings model | **`text-embedding-3-large`** (3072 dims) | text-embedding-3-small; multilingual-e5 |
| 3 | Vector storage | **pgvector** (extensión Postgres) | array nativo; servicio externo (Pinecone) |
| 4 | Imagen Docker | **`pgvector/pgvector:pg15`** (cambio en docker-compose) | postgres:15-alpine + array workaround |
| 5 | Ingestion strategy | **Script ahead-of-time, idempotente, leyendo los 3 JSONs en `docs/`** | Lazy on first query; background job con arq |
| 6 | Categoría en catálogo | **Columna nueva `category VARCHAR(60)`** | en `attrs JSONB` |
| 7 | Planes de crédito | **`tenant_branding.default_messages.planes` JSONB** | tabla nueva `tenant_credit_plans` |
| 8 | quote() return shape | **`Quote` Pydantic con precios + planes + ficha técnica + categoría** | dict crudo |
| 9 | search_catalog semantics | **Híbrido — alias-keyword primero, semántica si falla** | solo semantic; solo keyword |
| 10 | lookup_faq semantics | **Solo semántica con `score_threshold=0.5`** | híbrido; sin threshold |
| 11 | Embedding generation runtime | **Lazy — solo cuando aplica (siempre lookup_faq, fallback search_catalog)** | always; precomputed cache |
| 12 | Cost tracking embeddings | **Nueva columna `tool_cost_usd` en `turn_traces`** | sumar en `nlu_cost_usd` (semánticamente incorrecto); sin tracking |
| 13 | Idempotency keys ingestion | **`(tenant_id, sku)` en catálogo, `(tenant_id, question)` en FAQs** | timestamp; UUID nuevo cada vez |
| 14 | HNSW index params | **`m=16, ef_construction=64`** (defaults pgvector) | IVFFlat; valores agresivos |
| 15 | Distance metric | **Cosine** (`vector_cosine_ops`) | L2; inner product |

---

## 3. Arquitectura

```
┌─────────────────────────┐
│  Webhook + Runner       │  (existente, Phase 3a/3b)
└────┬────────────────────┘
     │ action=quote / lookup_faq / search_catalog
     ▼
┌─────────────────────────┐
│  Tool dispatch (NEW)    │
│  - search_catalog(q)    │  ← alias-keyword + (opcional) embedding
│  - quote(sku)           │  ← lee precio real de tenant_catalogs
│  - lookup_faq(emb)      │  ← top-3 por similitud coseno
└────┬────────────────────┘
     │ result (Quote / FAQMatch / CatalogResult / ToolNoDataResult)
     ▼
┌─────────────────────────┐
│  Composer (gpt-4o)      │  ← prompts actualizados, recibe datos reales
└─────────────────────────┘
```

### 3.1 Archivos nuevos

- `core/atendia/db/migrations/versions/012_pgvector_extension.py` — `CREATE EXTENSION IF NOT EXISTS vector`
- `core/atendia/db/migrations/versions/013_catalog_faqs_embeddings.py` — agrega columnas `embedding vector(3072)` + `category` + índices HNSW + UNIQUE constraint en `tenant_faqs(tenant_id, question)`
- `core/atendia/db/migrations/versions/014_tool_cost.py` — agrega `tool_cost_usd numeric(10, 6)` a `turn_traces`
- `core/atendia/tools/embeddings.py` — wrapper de OpenAI Embeddings + cost tracking
- `core/atendia/scripts/ingest_dinamo_data.py` — ingestion idempotente
- `core/tests/tools/test_embeddings.py`, `test_quote_real.py`, `test_lookup_faq_real.py`, `test_search_catalog_real.py`
- `core/tests/scripts/test_ingest_dinamo_data.py`
- `core/tests/integration/test_inbound_with_real_catalog.py`
- `core/tests/runner/test_phase3c_live.py` (gated por `RUN_LIVE_LLM_TESTS=1`)
- `core/tests/fixtures/composer/quote_dinamo_with_data_system.txt` (snapshot del prompt actualizado)

### 3.2 Archivos modificados

- `docker-compose.yml` — `postgres:15-alpine` → `pgvector/pgvector:pg15`
- `core/atendia/db/models/tenant_config.py` — `TenantCatalogItem` agrega `embedding` + `category`; `TenantFAQ` agrega `embedding`
- `core/atendia/tools/base.py` — agrega `Quote`, `FAQMatch`, `CatalogResult` Pydantic models
- `core/atendia/tools/quote.py` — devuelve `Quote | ToolNoDataResult`
- `core/atendia/tools/lookup_faq.py` — semantic search via cosine similarity
- `core/atendia/tools/search_catalog.py` — híbrido alias-keyword + semantic
- `core/atendia/runner/conversation_runner.py` — dispatch real de tools, embeddings on-demand, cost tracking
- `core/atendia/runner/composer_prompts.py` — `ACTION_GUIDANCE["quote"]`, `["lookup_faq"]`, `["search_catalog"]` reescritas para datos reales
- `core/pyproject.toml` — agrega `pgvector>=0.2.5`

### 3.3 Lo que no se toca

- NLU (Phase 3a queda intacta).
- State machine / orchestrator.
- Webhook signing, dedup, status callbacks.
- Realtime WS / Pub/Sub.
- Templates de Meta (Phase 3d).
- Router de modos del v1 (Phase 3c.2).
- Multimedia (Phase 3c.3).

---

## 4. Schema y migraciones

### 4.1 Migración 012 — pgvector extension

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

def downgrade() -> None:
    pass  # don't drop — other tables may depend on it
```

### 4.2 Migración 013 — embeddings + categoría

```python
from pgvector.sqlalchemy import Vector

def upgrade() -> None:
    # tenant_catalogs
    op.add_column('tenant_catalogs',
        sa.Column('embedding', Vector(3072), nullable=True))
    op.add_column('tenant_catalogs',
        sa.Column('category', sa.String(60), nullable=True))
    op.create_index('ix_tenant_catalogs_category',
        'tenant_catalogs', ['tenant_id', 'category'])
    op.create_index(
        'ix_tenant_catalogs_embedding', 'tenant_catalogs', ['embedding'],
        postgresql_using='hnsw',
        postgresql_with={'m': 16, 'ef_construction': 64},
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )

    # tenant_faqs
    op.add_column('tenant_faqs',
        sa.Column('embedding', Vector(3072), nullable=True))
    op.create_index(
        'ix_tenant_faqs_embedding', 'tenant_faqs', ['embedding'],
        postgresql_using='hnsw',
        postgresql_with={'m': 16, 'ef_construction': 64},
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )
    op.create_unique_constraint(
        'uq_tenant_faqs_tenant_question', 'tenant_faqs',
        ['tenant_id', 'question'],
    )
```

### 4.3 Migración 014 — tool_cost en turn_traces

```python
def upgrade() -> None:
    op.add_column('turn_traces',
        sa.Column('tool_cost_usd', sa.Numeric(10, 6), nullable=True))
```

Reversibles las tres.

---

## 5. Tool refactor

### 5.1 Pydantic models nuevos

```python
class Quote(BaseModel):
    status: Literal["ok"] = "ok"
    sku: str
    name: str
    category: str
    price_lista_mxn: Decimal
    price_contado_mxn: Decimal
    planes_credito: dict
    ficha_tecnica: dict


class FAQMatch(BaseModel):
    pregunta: str
    respuesta: str
    score: float


class CatalogResult(BaseModel):
    sku: str
    name: str
    category: str
    price_contado_mxn: Decimal
    score: float
```

### 5.2 quote()

```python
async def quote(*, session, tenant_id, sku) -> Quote | ToolNoDataResult:
    # SELECT FROM tenant_catalogs WHERE tenant_id=:t AND sku=:s AND active=true
    # Return Quote or ToolNoDataResult
```

### 5.3 search_catalog() — híbrido

```python
async def search_catalog(*, session, tenant_id, query, embedding=None, limit=5):
    # Path 1: alias-keyword (JSONB ?| operator). If matches found, score=1.0, return.
    # Path 2: if no alias match AND embedding provided, semantic via cosine_distance.
    # Path 3: no embedding provided AND no alias match → ToolNoDataResult.
```

### 5.4 lookup_faq() — semántica pura

```python
async def lookup_faq(*, session, tenant_id, embedding, top_k=3, score_threshold=0.5):
    # SELECT *, (1 - embedding <=> :q) AS score FROM tenant_faqs
    # ORDER BY embedding <=> :q LIMIT :top_k
    # Filter score >= threshold; ToolNoDataResult if empty after filter.
```

---

## 6. Ingestion script

`core/atendia/scripts/ingest_dinamo_data.py`:

- Lee 3 JSONs (`docs/CATALOGO_MODELOS.json`, `FAQ_CREDITO.json`, `REQUISITOS_PLANES.json`).
- Aplana catálogo: 8 categorías × ~30 modelos → 30 items con `category` + `attrs` (alias, ficha_tecnica, precios, planes_credito).
- Genera embeddings en batch (1 request por catálogo, 1 por FAQs):
  - Texto embedded para catálogo: `"Categoría: X. Modelo: Y. Alias: Z. Motor: NCC. Potencia: NHP. Transmisión: T. Precio contado: $N."`
  - Texto embedded para FAQs: `pregunta + " " + respuesta`.
- Persiste con `INSERT ... ON CONFLICT DO UPDATE` (idempotente).
- Planes → `tenant_branding.default_messages.planes` JSONB.
- Costo: ~50 items × ~100 tokens = 5000 tokens × $0.13/1M = **$0.00065** una vez.
- Flag `--dry-run` que imprime el resumen sin escribir.

---

## 7. Runner integration

`conversation_runner.py` cambia el bloque que construía `action_payload`:

- **`quote`**: dos pasos. Resolver SKU vía `search_catalog(query=interes_producto, embedding=None)` (alias-only, sin embedding API call). Si match, llamar `quote(sku=...)`. Si no, `ToolNoDataResult`.
- **`lookup_faq`**: generar embedding del `inbound.text`, llamar `lookup_faq(embedding=...)`. Persistir cost en `turn_traces.tool_cost_usd`.
- **`search_catalog`**: alias-keyword primero, embedding fallback solo si no hay match.
- **`ask_field`**, **`close`**: sin cambio respecto a Phase 3b.

---

## 8. Composer prompts actualizados

`ACTION_GUIDANCE["quote"]`, `["lookup_faq"]`, `["search_catalog"]` se reescriben:

- `quote`: si `action_payload.status="ok"`, dar precio formateado, mencionar plan popular (10/15%), max 2 mensajes. Si `status="no_data"`, redirigir.
- `lookup_faq`: si `action_payload.matches` no vacío, usar PRIMER match adaptando al tono. Si vacío/`no_data`, redirigir.
- `search_catalog`: si 1 match → presenta + sugiere precio. Si 2-5 → bullets cortos + pregunta cuál. Si 0 → `ToolNoDataResult`.

Snapshot test del prompt para `quote` con datos reales (`quote_dinamo_with_data_system.txt`) congela el contrato.

---

## 9. Tests

Resumen del cuadro:

| Archivo | Tests |
|---|---|
| `test_embeddings.py` | 4: single, batch, empty, cost formula |
| `test_quote_real.py` | 3: hit, miss, inactive |
| `test_lookup_faq_real.py` | 4: top_k, threshold, order, null embedding |
| `test_search_catalog_real.py` | 5: alias hit, semantic fallback, no match, limit, inactive |
| `test_ingest_dinamo_data.py` | 4: flatten, embed text, idempotent, dry-run |
| `test_conversation_runner.py` extensión | 3: quote real data, faq semantic, fallback |
| `test_inbound_with_real_catalog.py` | 1: E2E webhook → real price |
| `test_phase3c_live.py` | 1: live "no inventa precio" |

Cobertura ≥85% (gate actual).

---

## 10. Rollout

1. Mergear código.
2. `docker compose down && docker compose up -d` (nueva imagen pgvector).
3. `uv run alembic upgrade head` (migrations 012–014).
4. `uv run python -m atendia.scripts.ingest_dinamo_data --tenant-id <UUID> --dry-run`
5. Si OK → ejecutar sin `--dry-run`.
6. Smoke manual con WhatsApp real.
7. Rollback instantáneo: `UPDATE tenant_catalogs SET active = false WHERE tenant_id = :t` — tools devuelven `ToolNoDataResult` y bot vuelve al modo redirect (Phase 3b behavior).

---

## 11. Criterios de aceptación

| # | Criterio | Verificación |
|---|---|---|
| 1 | Suite completa pasa | `pytest -q` |
| 2 | Coverage ≥ 85% | `pytest --cov-fail-under=85` |
| 3 | Live test pasa, no inventa precios | `RUN_LIVE_LLM_TESTS=1 pytest tests/runner/test_phase3c_live.py` |
| 4 | Ingestion idempotente | dos runs, row counts iguales |
| 5 | lookup_faq semántico funciona | "¿cuánto pongo de inicial?" matchea FAQ enganche |
| 6 | search_catalog híbrido funciona | "Adventure" → alias; "una motoneta urbana" → semantic |
| 7 | quote real | bot responde "$29,900" o "$31,395" para Adventure |
| 8 | Costo agregado ≈ $0.002 + embedding | `SELECT AVG(tool_cost_usd) FROM turn_traces` |

---

## 12. Fuera de alcance (YAGNI)

- Router LLM modes — Phase 3c.2.
- Multimedia + Vision API — Phase 3c.3.
- Embedding cache en Redis — al volumen actual no aporta.
- Re-ingestion automática on tenant config change — futuro job arq.
- Multi-language embeddings — todo en español por ahora.

---

## 13. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| pgvector image incompatible con volume | El volume `atendia_v2_pg_data` es Postgres 15 vanilla. La imagen `pgvector/pgvector:pg15` es Postgres 15 + extensión instalada. Compatible. Verificable corriendo `docker compose down && up -d` y `\dx` en psql. |
| HNSW index slow build (>30s) en seed | 30 motos + 12 FAQs es trivial — < 1 segundo. Si en el futuro escala a 10k+, `m`/`ef_construction` se afinan. |
| LLM inventa un precio pese a tener datos | El prompt dice "NO INVENTES otro precio" + el live test corre antes de cada release con regex `\$?\d{4,6}` para cazar cifras inventadas. |
| Alias-keyword match falsos positivos | Aliases son cortos y específicos por modelo (`["adventure", "elite", "adventure150"]`). Match exacto via JSONB `?|` no produce false positives. |
| FAQ embeddings devuelven respuesta off-topic | `score_threshold=0.5` filtra matches débiles. Si la mejor match es <0.5, el bot redirige en vez de responder con FAQ irrelevante. |
| Ingestion API call costs runaway | El script reporta cost antes de escribir. El `--dry-run` muestra cuánto va a costar. Para Dinamo: $0.00065 una sola vez. |

---

## 14. Próximo paso

Generar plan de implementación detallado vía `superpowers:writing-plans`. Plan se commiteará como `docs/plans/05-fase-3c1-datos-reales.md`.

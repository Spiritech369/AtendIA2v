# atendia core

The conversational core of AtendIA — Python package implementing the data-driven state machine, WhatsApp Cloud API transport, realtime layer, RAG pipeline, and operator REST API.

> ⓘ Para un mapa de "qué hace cada módulo y dónde vive el código" mira [`../docs/PROJECT_MAP.md`](../docs/PROJECT_MAP.md).

## Setup

Prereqs: Docker + [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. Desde el repo root, levanta Postgres + Redis.
docker compose up -d

# 2. Desde core/, instala deps y aplica migraciones.
cd core
uv sync
uv run alembic upgrade head

# 3. Smoke test del full happy path contra la DB live.
uv run python scripts/smoke_test_phase1.py

# 4. (Opcional) Corre la API local.
uv run uvicorn atendia.main:app --reload --port 8001
```

### Environment variables (loaded from `core/.env`)

| Variable | Default |
|---|---|
| `ATENDIA_V2_DATABASE_URL` | `postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2` |
| `ATENDIA_V2_REDIS_URL` | `redis://localhost:6380/0` |
| `ATENDIA_V2_LOG_LEVEL` | `INFO` |
| `ATENDIA_V2_OPENAI_API_KEY` | _(empty — set para activar real NLU/Composer/KB)_ |
| `ATENDIA_V2_NLU_PROVIDER` | `keyword` (set `openai` para `gpt-4o-mini`) |
| `ATENDIA_V2_NLU_MODEL` | `gpt-4o-mini` |
| `ATENDIA_V2_NLU_TIMEOUT_S` | `8.0` |
| `ATENDIA_V2_COMPOSER_PROVIDER` | `canned` (set `openai` para `gpt-4o`) |
| `ATENDIA_V2_COMPOSER_MODEL` | `gpt-4o` |
| `ATENDIA_V2_COMPOSER_MAX_MESSAGES` | `2` |
| `ATENDIA_V2_KB_PROVIDER` | `openai` (auto-fallback a `mock` si no hay API key) |
| `ATENDIA_V2_AUTH_SESSION_SECRET` | (override en prod) |
| `ATENDIA_V2_AUTH_SESSION_TTL_S` | `28800` (8h) |
| `ATENDIA_V2_AUTH_COOKIE_SECURE` | `false` (true detrás de TLS) |

Postgres en puerto **5433**, Redis en **6380**. Ambos manejados por `docker-compose.yml` en el repo root. La imagen Postgres es **`pgvector/pgvector:0.8.2-pg15`** — extensiones `vector` + `halfvec` precompiladas.

### Seed scripts

```bash
# Dinamo data + brand_facts (Phase 3c.1)
cd core
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m atendia.scripts.ingest_dinamo_data \
    --tenant-id <UUID> --docs-dir ../docs [--dry-run]

PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m atendia.scripts.seed_brand_facts \
    --tenant-name dinamomotos

# KB module defaults (B2)
uv run python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>
```

## Tests

```bash
cd core

# Suite completa (~800 tests).
uv run pytest

# Sólo el área que estás cambiando:
uv run pytest tests/state_machine/
uv run pytest tests/api/test_kb_test_query.py
uv run pytest -k "happy_path"

# Coverage (gate: ≥85%).
uv run pytest --cov=atendia

# Lint + type-check.
uv run ruff check .
uv run mypy atendia
```

Tests con DB (anything bajo `tests/db/`, `tests/runner/`, `tests/api/`, `tests/e2e/`) requieren Postgres + Redis corriendo y `alembic upgrade head` aplicado.

Live OpenAI tests gated por `RUN_LIVE_LLM_TESTS=1` (default off).

## Workers

```bash
# Outbound queue + cron jobs (followups, etc.).
cd core
uv run arq atendia.queue.worker.WorkerSettings
```

`WorkerSettings` registra `send_outbound` (queue), `index_document` (queue), `force_summary` (queue), `poll_followups` (cron cada minuto), `poll_workflow_triggers` (cron). El worker lee `ATENDIA_V2_META_ACCESS_TOKEN` y `ATENDIA_V2_META_APP_SECRET` del env. Per-tenant `phone_number_id` vive en `tenants.config.meta.phone_number_id` (JSONB).

## Smoke tests

```bash
cd core
# Phase 1: state machine sin LLM end-to-end
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/smoke_test_phase1.py

# Phase 2: full transport chain (webhook → runner → outbox → worker → mocked Meta)
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/smoke_test_phase2.py
```

**Windows:** `PYTHONIOENCODING=utf-8` evita errores de encoding al imprimir emoji / arrows. `PYTHONPATH=.` es necesario porque el package no está instalado.

## Architecture (resumen)

```
core/atendia/
  api/              FastAPI routes (per feature) + _kb/ subrouters
  channels/         Meta Cloud API adapter + DTOs + HMAC
  config.py         pydantic-settings (ATENDIA_V2_*)
  contracts/        Pydantic v2 contracts (Message, Event, NLUResult, ...)
  db/
    base.py session.py
    models/         ORM (28+ tablas)
    migrations/     Alembic async, 36+ revisions
  queue/            arq workers + outbox + circuit breaker
  realtime/         Pub/Sub publisher + WebSocket + JWT
  runner/           ConversationRunner + NLU adapters + Composer + flow_router
  scripts/          ingest_dinamo_data, seed_brand_facts, seed_knowledge_defaults
  state_machine/    Pipeline loader, conditions, orchestrator
  storage/          Storage backend abstraction
  tools/            7 tools + tools/rag/ (provider, retriever, prompt_builder,
                    answer_synthesizer, conflict_detector, risky_phrase_detector)
  webhooks/         POST /webhooks/meta/:tenant_id
  main.py           FastAPI app
```

Per-feature breakdown completo: ver [`../docs/PROJECT_MAP.md`](../docs/PROJECT_MAP.md).

Stack: Python 3.12, `uv`, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, Pydantic v2, `arq`, Redis, Postgres + pgvector + halfvec(3072) HNSW, pytest-asyncio, ruff, mypy.

## How-to

### Add a new tool

1. Crear clase en `core/atendia/tools/<name>.py` que herede de `Tool` (`atendia/tools/base.py`). Definir `name: str` y `async def run(self, session: AsyncSession, **kwargs) -> dict`.
2. Registrarlo en `core/atendia/tools/__init__.py` añadiéndolo a `register_all_tools()`.
3. Test unitario en `core/tests/tools/`.

El runner (`atendia/tools/runner.py`) lo recoge automáticamente del registry y persiste un `tool_calls` row con `latency_ms`. Sin glue extra.

### Add a new pipeline stage

Un pipeline vive como un único JSONB blob en `tenant_pipelines.definition`, keyed por `(tenant_id, version)` con `active = true` para la fila en uso. **No hay migración involucrada.**

```sql
INSERT INTO tenant_pipelines (tenant_id, version, definition, active) VALUES (
  '<tenant-uuid>', 1,
  '{
    "version": 1,
    "stages": [
      {"id": "greeting", "actions_allowed": ["greet", "ask_field"],
       "transitions": [{"to": "qualify", "when": "intent in [ask_info, ask_price]"}]},
      {"id": "qualify", "required_fields": ["interes_producto", "ciudad"],
       "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
       "transitions": [{"to": "quote",
                        "when": "all_required_fields_present AND intent == ask_price"}]},
      {"id": "quote", "actions_allowed": ["quote", "ask_clarification"],
       "transitions": [{"to": "close", "when": "intent == buy"}]},
      {"id": "close", "actions_allowed": ["close"], "transitions": []}
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human"
  }'::jsonb, true
);
```

DSL completo: [`atendia/state_machine/conditions.py`](atendia/state_machine/conditions.py).
Validador estructural: [`atendia/contracts/pipeline_definition.py`](atendia/contracts/pipeline_definition.py).

### Connect to WebSocket from a client

Endpoint: `/ws/conversations/{conversation_id}?token=<JWT>`. JWT firmado por `atendia.realtime.auth.issue_token(...)`.

```js
const token = await fetch("/api/v1/auth/ws-token").then(r => r.text());
const ws = new WebSocket(`ws://localhost:8000/ws/conversations/${conversationId}?token=${token}`);
ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  console.log(event.type, event.data);
};
```

CLI con `wscat`:

```bash
TOKEN=$(uv run python -c "from atendia.realtime.auth import issue_token; print(issue_token(tenant_id='YOUR_TENANT_UUID', ttl_seconds=3600))")
wscat -c "ws://localhost:8000/ws/conversations/YOUR_CONV_UUID?token=$TOKEN"
```

## Status (2026-05-10)

Phases 1, 2, 3a, 3b, 3c.1, 3c.2, 3d.1 — ✅ shipped.
Phase 3d.2 (WhatsApp Templates >24h) + 3d.3 (outbound multimedia) — ⏳ pendientes.
Phase 4 / V1 parity sprint (frontend operator workspace) — ✅ scaffolded; per-module parity verification still pending.
Knowledge Base module B2 — ⚠️ **partial** (backend Phase 1+2 + 3 endpoints + seed/runbook; frontend rebuild + ~44 endpoints + 5 workers diferidos). Ver [`../docs/runbooks/knowledge-base.md`](../docs/runbooks/knowledge-base.md).

Status detallado por módulo en [`../docs/PROJECT_MAP.md`](../docs/PROJECT_MAP.md) y [`../docs/plans/2026-05-08-v1-parity-modular-plan.md`](../docs/plans/2026-05-08-v1-parity-modular-plan.md).

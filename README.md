# AtendIA v2

WhatsApp sales assistant — multi-tenant, data-driven, with a deterministic state machine for sales flow and LLM only where it must.

## Status

- ✅ **Phase 1** — State machine sin LLM end-to-end (17 tablas, 6 tools, fixtures E2E)
- ✅ **Phase 2** — WhatsApp Cloud API transport (webhook, outbound queue, realtime WebSocket)
- ✅ **Phase 3a** — NLU real (`gpt-4o-mini`) con structured outputs, retry, cost tracking
- ✅ **Phase 3b** — Composer real (`gpt-4o`) con `list[str]`, tono per-tenant, 24h handoff, fallback canned
- ⏳ **Phase 3c** — Migración real Dinamo + integraciones avanzadas
  - ✅ **3c.1** — Datos reales: catálogo + FAQs + planes con embeddings (pgvector + halfvec(3072))
  - ⏳ **3c.2** — Router LLM + flow v1 (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT modes)
  - ⏳ **3c.3** — Multimedia (imágenes + Vision API + validación de documentos)
- ⏳ **Phase 4** — Frontend debug panel + tenant config UI
- ⏳ **Phase 5+** — Onboarding flow, multi-channel, integrations

**266 tests passing · 91% coverage · gate ≥ 85%** (Phase 3c.1 scope: contracts + state_machine + runner + tools + webhooks + integration + scripts; legacy Tool wrappers + ingestion CLI excluded from coverage)

## Architecture (one-paragraph version)

A FastAPI service (`core/atendia`) receives WhatsApp webhooks from Meta Cloud API, validates HMAC + dedupes, and runs each turn through a state-machine orchestrator parameterized by per-tenant pipeline JSONB. The orchestrator decides the next stage and action, dispatches an outbound message via an `arq` Redis queue, and the worker calls Meta to send. Both inbound and outbound publish events on Redis Pub/Sub; a WebSocket endpoint (`/ws/conversations/:id?token=<JWT>`) forwards them to the frontend in realtime. State and history live in Postgres (17 tables); every turn writes a `turn_traces` row for full observability.

Full design: [`docs/design/atendia-v2-architecture.md`](docs/design/atendia-v2-architecture.md).

## Stack

Python 3.12 · `uv` · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · Pydantic v2 · `arq` · Redis · Postgres · pytest-asyncio · ruff · mypy

## Quick start

```bash
# Bring up Postgres + Redis
docker compose up -d

# Install deps and run migrations
cd core
uv sync
uv run alembic upgrade head

# Smoke test the full stack
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/smoke_test_phase2.py
```

Full setup, run, and test instructions: [`core/README.md`](core/README.md).

## Repo layout

```
.
├── core/                       Python package (atendia.*)
│   ├── atendia/
│   │   ├── api/                FastAPI routes
│   │   ├── channels/           Meta Cloud API adapter + DTOs + HMAC
│   │   ├── contracts/          Canonical Pydantic contracts
│   │   ├── db/                 Models + Alembic migrations
│   │   ├── queue/              arq worker, enqueue, circuit breaker
│   │   ├── realtime/           Pub/Sub publisher + WebSocket + JWT
│   │   ├── runner/             ConversationRunner + NLU adapters
│   │   ├── state_machine/      Pipeline loader, conditions, orchestrator
│   │   ├── tools/              Registry + 6 typed tool stubs
│   │   ├── webhooks/           POST /webhooks/meta/:tenant_id
│   │   └── main.py             FastAPI app
│   ├── scripts/                smoke_test_phase1.py + smoke_test_phase2.py
│   └── tests/                  196 tests, mirrors atendia/ layout
├── contracts/                  JSON Schemas (source of truth for codegen)
├── docs/
│   ├── design/                 Architecture doc
│   └── plans/                  Implementation plans (Phase 1, Phase 2)
├── .github/workflows/ci.yml    GitHub Actions: lint + migrate + tests
├── docker-compose.yml          Postgres 15 + Redis 7
└── .env.example                Environment variables template
```

## Configuration

Per-environment values live in `core/.env` (gitignored). Copy `.env.example` to `core/.env` and adjust:

```bash
cp .env.example core/.env
```

Phase 2 needs Meta Cloud API credentials (`ATENDIA_V2_META_APP_SECRET`, `ATENDIA_V2_META_ACCESS_TOKEN`) for production. Tests use mocks via `respx` and don't need real credentials.

## License

Private. Not yet open-sourced.

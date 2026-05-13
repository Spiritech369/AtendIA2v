# AtendIA v2

WhatsApp sales assistant — multi-tenant, data-driven, with a deterministic state machine for sales flow and LLM only where it must.

## Status (2026-05-10)

| Área | Estado |
|---|---|
| Phase 1 — State machine sin LLM end-to-end (17 tablas, 6 tools, fixtures E2E) | ✅ shipped |
| Phase 2 — WhatsApp Cloud API transport (webhook + outbound queue + realtime WS) | ✅ shipped |
| Phase 3a — NLU real (`gpt-4o-mini`) con structured outputs + cost tracking | ✅ shipped |
| Phase 3b — Composer real (`gpt-4o`) con `list[str]` + tono per-tenant + 24h handoff | ✅ shipped |
| Phase 3c.1 — Datos reales: catálogo + FAQs + planes con embeddings (pgvector + halfvec(3072)) | ✅ shipped |
| Phase 3c.2 — Router determinístico + 6 modos (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT) + Vision API | ✅ shipped |
| Phase 3d.1 — In-window follow-ups (3h+12h cron) con cancelación atómica | ✅ shipped |
| Phase 3d.2 — WhatsApp Templates (>24h re-engagement) | ⏳ pendiente |
| Phase 3d.3 — Outbound multimedia + blob storage | ⏳ pendiente |
| Phase 4 / V1 parity sprint — operator workspace (Conversations / Customers / Pipeline / Handoffs / Appointments / Workflows / Agents / Notifications / Audit / Inbox settings) | ✅ scaffolded — no parity-verified vs v1 todavía |
| Knowledge Base module (B2 scope) | ⚠️ **partial** — backend Phase 1+2 + 3 endpoints + seed/runbook; frontend rebuild + ~44 endpoints + 5 workers diferidos |

## Empezar aquí

| Necesitas… | Lee… |
|---|---|
| Saber qué hace cada categoría del programa y dónde vive el código | [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md) |
| Setup local + arquitectura técnica | [core/README.md](core/README.md) |
| Diseño general del sistema | [docs/design/atendia-v2-architecture.md](docs/design/atendia-v2-architecture.md) |
| Roadmap v1 → v2 con status por módulo | [docs/plans/2026-05-08-v1-parity-modular-plan.md](docs/plans/2026-05-08-v1-parity-modular-plan.md) |
| Working contract (reglas de honestidad post-trust-break) | [docs/handoffs/v1-v2-conversations-gap.md](docs/handoffs/v1-v2-conversations-gap.md) |
| Runbooks operativos | [docs/runbooks/](docs/runbooks/) |
| Diseño + plan del módulo KB (parcial) | [docs/plans/2026-05-10-knowledge-base-module-design.md](docs/plans/2026-05-10-knowledge-base-module-design.md) · [implementation](docs/plans/2026-05-10-knowledge-base-module-implementation.md) |

## Architecture (one-paragraph version)

A FastAPI service (`core/atendia`) receives WhatsApp webhooks from Meta Cloud API, validates HMAC + dedupes, and runs each turn through a state-machine orchestrator parameterized by per-tenant pipeline JSONB. The orchestrator decides the next stage and action, dispatches an outbound message via an `arq` Redis queue (with a staged `outbound_outbox` table for atomic same-transaction enqueue), and the worker calls Meta to send. Both inbound and outbound publish events on Redis Pub/Sub; a WebSocket endpoint (`/ws/conversations/:id?token=<JWT>`) forwards them to the frontend in realtime. State and history live in Postgres (28+ tables); every turn writes a `turn_traces` row for full observability. The frontend is a Vite/React 19/TanStack Router/Tailwind v4/shadcn SPA served by the same FastAPI via `StaticFiles` for single-Docker deploy.

Full design: [`docs/design/atendia-v2-architecture.md`](docs/design/atendia-v2-architecture.md).

## Stack

**Backend:** Python 3.12 · `uv` · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · Pydantic v2 · `arq` · Redis · Postgres + pgvector + halfvec(3072) HNSW · pytest-asyncio · ruff · mypy

**Frontend:** React 19 · TanStack Query/Router · Tailwind v4 · shadcn/ui v2 (vendored) · Vitest · MSW · sonner

**LLM:** OpenAI `gpt-4o-mini` (NLU) · `gpt-4o` (Composer) · `text-embedding-3-large` (3072 dims, halfvec storage) · `gpt-4o` Vision API

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

### Workflows Operations Center

The Workflows module now ships as an operational command center at `/workflows`.
It auto-seeds realistic demo workflows for an empty tenant, then persists CRUD,
safe pause, node edits, draft/publish, validation, simulation, dependency,
variable, execution replay and retry flows through the FastAPI API.

Useful local checks:

```bash
cd core && uv run alembic upgrade head
cd core && uv run pytest tests/api/test_workflows_routes.py tests/workflows -q
cd frontend && pnpm build
```

Demo login after `scripts/start-demo.ps1`:
`admin@demo.com / admin123`.

### Handoff Command Center

The Handoffs module now ships as a real-time AI-to-human escalation command
center at `/handoffs`. The backend exposes the command-center API under
`/api/v1/handoffs/command-center`, analytics under `/api/v1/analytics/handoffs/*`,
and tenant-wide live invalidation through `/ws/tenants/:tenant_id`.

The local snapshot auto-enriches existing `human_handoffs` rows and appends
deterministic demo cases when the tenant has sparse data, so a fresh local
workspace opens with an operational queue, SLA/priority scoring, smart
assignment, AI explanations, suggested replies, feedback, timelines, and risk
radar data.

Useful local checks:

```bash
cd core && uv run ruff check atendia/api/_handoffs/command_center.py atendia/realtime/ws_routes.py
cd frontend && npm run typecheck
cd frontend && npm run build
```

## Repo layout

```
.
├── core/                       Python package (atendia.*) — backend
│   ├── atendia/
│   │   ├── api/                FastAPI routes (per feature) + _kb/ subrouters
│   │   ├── channels/           Meta Cloud API adapter + DTOs + HMAC
│   │   ├── contracts/          Canonical Pydantic contracts
│   │   ├── db/                 Models + Alembic migrations (36+)
│   │   ├── queue/              arq workers, enqueue, outbox, circuit breaker
│   │   ├── realtime/           Pub/Sub publisher + WebSocket + JWT
│   │   ├── runner/             ConversationRunner + NLU + Composer + flow router
│   │   ├── scripts/            CLI: ingest_dinamo_data, seed_brand_facts, seed_knowledge_defaults
│   │   ├── state_machine/      Pipeline loader, conditions, orchestrator
│   │   ├── storage/            Storage backend abstraction (local tier)
│   │   ├── tools/              Tool registry + 7 tools + tools/rag/ (KB pipeline)
│   │   ├── webhooks/           POST /webhooks/meta/:tenant_id
│   │   └── main.py             FastAPI app
│   ├── scripts/                smoke_test_phase{1,2}.py + e2e_meta_workflow.py
│   └── tests/                  ~800 tests
├── frontend/                   React 19 SPA (servido por FastAPI vía StaticFiles)
│   └── src/
│       ├── features/           one folder per feature (api.ts + components/ + hooks/)
│       ├── routes/             TanStack Router routes ((auth)/* protegidas)
│       ├── components/ui/      shadcn vendored
│       └── lib/                axios client, realtime helpers
├── contracts/                  JSON Schemas (source of truth para codegen)
├── docs/
│   ├── PROJECT_MAP.md          Mapa categoría → propósito → archivos
│   ├── design/                 Architecture doc
│   ├── plans/                  Design + implementation plans (vivos)
│   ├── runbooks/               Guías operativas (KB / Conversations / Clients / Pipeline / Workflows)
│   └── handoffs/               Working contract + sign-offs históricos
├── .github/workflows/ci.yml    GitHub Actions: lint + migrate + tests
├── docker-compose.yml          Postgres 15 (+pgvector) + Redis 7
└── .env.example                Environment variables template
```

## Configuration

Per-environment values live in `core/.env` (gitignored). Copy `.env.example` to `core/.env` y ajusta:

```bash
cp .env.example core/.env
```

Vars críticas en producción:
- `ATENDIA_V2_META_APP_SECRET`, `ATENDIA_V2_META_ACCESS_TOKEN` — credenciales Meta Cloud API.
- `ATENDIA_V2_OPENAI_API_KEY` — NLU + Composer + Embeddings + Vision + KB. (Empty → MockProvider auto-fallback en KB.)
- `ATENDIA_V2_KB_PROVIDER` — `openai` (default) o `mock`.
- `ATENDIA_V2_NLU_PROVIDER` — `keyword` (default) o `openai`.
- `ATENDIA_V2_COMPOSER_PROVIDER` — `canned` (default) o `openai`.
- `ATENDIA_V2_AUTH_SESSION_SECRET` — JWT signing key (override en prod).

Per-tenant config (no requiere migration):
- `tenants.config.meta.{phone_number_id, verify_token}`
- `tenant_pipelines.definition` — JSONB con stages, transitions, flow_mode_rules, docs_per_plan
- `tenant_branding.{voice, default_messages.brand_facts}` — tono + brand_facts inyectados en prompts
- `kb_agent_permissions / kb_safe_answer_settings / kb_source_priority_rules` — runtime config del KB

Seed Dinamo brand_facts:

```bash
cd core && PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m atendia.scripts.seed_brand_facts \
    --tenant-name dinamomotos
```

Seed KB defaults (B2):

```bash
cd core && uv run python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>
```

## License

Private. Not yet open-sourced.

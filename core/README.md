# atendia core

The conversational core of AtendIA — Python package implementing the data-driven state machine, WhatsApp Cloud API transport, and realtime layer.

## Overview

`core/` is a self-contained Python package (`atendia`) that runs a conversation
turn end-to-end **without an LLM**: a deterministic, data-driven state machine
reads a JSONB pipeline definition per tenant, evaluates conditions against an
NLU result, resolves the next action, executes any tools attached to that
action, and persists a full `turn_traces` row plus structured `events`.

Phase 1 delivers:

- Tenant-configurable pipelines stored as JSONB in `tenant_pipelines`.
- A `ConversationRunner` that drives one turn (NLU is canned in tests via YAML
  fixtures; the real LLM-backed NLU lands in Phase 2).
- 6 tool stubs registered behind a common `Tool` ABC.
- Full observability: every turn writes a `turn_traces` record and emits
  domain events into `events`.
- A FastAPI surface (`POST /api/v1/runner/turn`, `GET /health`) and a smoke
  script that exercises the full happy path against a real Postgres.

## Setup

Prereqs: Docker + [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. From the repo root, bring up Postgres + Redis.
docker compose up -d

# 2. From core/, install deps and run migrations.
cd core
uv sync
uv run alembic upgrade head

# 3. Smoke test the full happy path against the live DB.
uv run python scripts/smoke_test_phase1.py

# 4. (Optional) Run the API locally.
uv run uvicorn atendia.main:app --reload --port 8001
```

Environment variables (loaded from `core/.env`):

| Variable                          | Default                                                                  |
|-----------------------------------|--------------------------------------------------------------------------|
| `ATENDIA_V2_DATABASE_URL`         | `postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2`         |
| `ATENDIA_V2_REDIS_URL`            | `redis://localhost:6380/0`                                               |
| `ATENDIA_V2_LOG_LEVEL`            | `INFO`                                                                   |
| `ATENDIA_V2_OPENAI_API_KEY`       | _(empty — set to enable real NLU)_                                       |
| `ATENDIA_V2_NLU_PROVIDER`         | `keyword` (set to `openai` to use `gpt-4o-mini`)                         |
| `ATENDIA_V2_NLU_MODEL`            | `gpt-4o-mini`                                                            |
| `ATENDIA_V2_NLU_TIMEOUT_S`        | `8.0`                                                                    |
| `ATENDIA_V2_NLU_RETRY_DELAYS_MS`  | `[500, 2000]`                                                            |

Postgres lives on port **5433**, Redis on **6380**. Both managed by `docker-compose.yml` at the repo root. (The non-default ports are a holdover from when v2 lived alongside v1; you can change them in `docker-compose.yml` and `core/.env` if you want.)

### NLU rollout sequence (Phase 3a)

1. Deploy with `ATENDIA_V2_NLU_PROVIDER=keyword` (default). Behavior matches Phase 2.
2. Provision the OpenAI key in env (`ATENDIA_V2_OPENAI_API_KEY=sk-...`).
3. Flip `ATENDIA_V2_NLU_PROVIDER=openai` to enable the real classifier. The runner switches over without restart-only-code-changes.
4. Watch `turn_traces.nlu_cost_usd` and `nlu_latency_ms` for cost/quality monitoring.

## Running the outbound worker

The webhook handler enqueues outbound messages on Redis. A separate `arq` worker process picks them up and calls Meta:

```bash
cd core
uv run arq atendia.queue.worker.WorkerSettings
```

The worker reads `ATENDIA_V2_META_ACCESS_TOKEN` and `ATENDIA_V2_META_APP_SECRET` from env. Per-tenant `phone_number_id` lives in `tenants.config.meta.phone_number_id` (JSONB).

In dev you can also drain the queue manually for one job and call `send_outbound` directly — see `tests/integration/test_e2e_echo_bot.py` for the pattern.

## Connecting to WebSocket from a client

The realtime endpoint is `/ws/conversations/{conversation_id}?token=<JWT>`. The JWT is issued by `atendia.realtime.auth.issue_token(tenant_id=..., ttl_seconds=...)` and signed with the Meta app secret (Phase 2 reuses it; Phase 3 will use a dedicated `WS_AUTH_SECRET`).

JavaScript example (browser):

```js
const token = await fetch("/api/v1/auth/ws-token").then(r => r.text());  // your auth endpoint
const ws = new WebSocket(`ws://localhost:8000/ws/conversations/${conversationId}?token=${token}`);
ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  console.log(event.type, event.data);  // "message_received" / "message_sent"
};
```

CLI testing with `wscat`:

```bash
TOKEN=$(uv run python -c "from atendia.realtime.auth import issue_token; print(issue_token(tenant_id='YOUR_TENANT_UUID', ttl_seconds=3600))")
wscat -c "ws://localhost:8000/ws/conversations/YOUR_CONV_UUID?token=$TOKEN"
```

## Smoke tests

Two end-to-end smoke scripts you can run manually against your local DB + Redis:

```bash
cd core
# Phase 1: state machine sin LLM end-to-end
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/smoke_test_phase1.py

# Phase 2: full transport chain (webhook → runner → queue → worker → mocked Meta)
PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/smoke_test_phase2.py
```

**Windows note:** `PYTHONIOENCODING=utf-8` avoids Unicode encoding errors when printing emoji / arrows. `PYTHONPATH=.` is needed because the package isn't installed (no build-system entry in `pyproject.toml`); pytest doesn't need it because pytest auto-adds the rootdir.

Both scripts print a turn-by-turn summary and exit `0` with `OK — phase N smoke test passed`.

## Architecture

```
core/
  atendia/
    api/              FastAPI router (POST /api/v1/runner/turn, GET /health)
    config.py         pydantic-settings: ATENDIA_V2_* env vars
    contracts/        Pydantic v2 contracts (Message, Event, NLUResult,
                      ConversationState, PipelineDefinition)
    db/
      base.py         declarative Base
      session.py      async SQLAlchemy engine + session factory
      models/         ORM models (tenant, customer, conversation, message,
                      event, turn_trace, lifecycle, tenant_config)
      migrations/     Alembic (async). 9 revisions, 17 tables total.
    runner/
      conversation_runner.py  Orchestrates one turn end-to-end
      nlu_canned.py           YAML-fixture-backed NLU for tests
      nlu_keywords.py         Keyword-matching NLU (Phase 2 default)
      nlu_openai.py           gpt-4o-mini structured-output NLU (Phase 3a)
      nlu_prompts.py          System/user prompt builder for the LLM
      nlu/pricing.py          Per-token cost computation
    state_machine/
      pipeline_loader.py  Loads + validates active tenant pipeline
      conditions.py       Tiny DSL: intent, sentiment, confidence, in, AND/OR
      ambiguity.py        Confidence threshold + explicit ambiguity guard
      transitioner.py     Picks next stage from the pipeline
      action_resolver.py  Maps intent -> first allowed action in the stage
      event_emitter.py    Persists Event rows
      orchestrator.py     Composes the above into one call
    tools/
      base.py             Tool ABC + ToolNotFoundError
      registry.py         In-memory registry (name -> Tool)
      runner.py           Executes a tool and persists a tool_calls row
      __init__.py         register_all_tools()
      search_catalog.py, quote.py, lookup_faq.py,
      book_appointment.py, escalate.py, followup.py
    main.py             FastAPI app entry point
  scripts/
    smoke_test_phase1.py  End-to-end smoke against the live v2 DB
  tests/                  pytest-asyncio suite (139 tests in Phase 3a scope, 85.52% coverage)
    fixtures/conversations/  5 YAML conversation scenarios
```

The 17 tables, by migration:

1. `tenants`, `tenant_users`
2. `customers`
3. `conversations`, `conversation_state`
4. `messages`
5. `events`
6. `turn_traces`, `tool_calls`
7. `tenant_catalogs`, `tenant_faqs`, `tenant_pipelines`
8. `tenant_branding`, `tenant_templates_meta`, `tenant_tools_config`
9. `followups_scheduled`, `human_handoffs`

Stack: Python 3.12, `uv`, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic,
Pydantic v2, pytest-asyncio, ruff, mypy.

## How to run tests

```bash
cd core

# Full suite (196 tests).
uv run pytest

# With coverage report. Hard floor is 85% (enforced via pyproject.toml).
uv run pytest --cov=atendia

# A single module or test.
uv run pytest tests/state_machine/test_orchestrator.py
uv run pytest -k "happy_path"

# Lint and type-check.
uv run ruff check .
uv run mypy atendia
```

DB-touching tests (anything under `tests/db/`, `tests/runner/`, `tests/api/`,
`tests/e2e/`) require the v2 Postgres to be running and migrations applied.

## How to add a new tool

1. Create a class in `core/atendia/tools/<name>.py` that subclasses `Tool`
   from `atendia/tools/base.py`. Set `name: str` and implement
   `async def run(self, session: AsyncSession, **kwargs) -> dict`.
2. Register it in `core/atendia/tools/__init__.py` by adding the class to the
   list inside `register_all_tools()`.
3. Add a unit test under `core/tests/tools/`.

The runner (`atendia/tools/runner.py`) will pick it up via the registry,
execute it, and persist a `tool_calls` row with `latency_ms` automatically.
No glue code beyond steps 1 and 2.

## How to add a new stage to a tenant pipeline

A pipeline lives as a single JSONB blob in `tenant_pipelines.definition`,
keyed by `tenant_id` + `version`, with `active = true` for the row in use.
There is no schema migration involved.

Minimal example: insert a 4-stage pipeline for a tenant.

```sql
INSERT INTO tenant_pipelines (tenant_id, version, definition, active) VALUES (
  '<tenant-uuid>',
  1,
  '{
    "version": 1,
    "stages": [
      {"id": "greeting",
       "actions_allowed": ["greet", "ask_field"],
       "transitions": [{"to": "qualify", "when": "intent in [ask_info, ask_price]"}]},
      {"id": "qualify",
       "required_fields": ["interes_producto", "ciudad"],
       "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
       "transitions": [{"to": "quote",
                        "when": "all_required_fields_present AND intent == ask_price"}]},
      {"id": "quote",
       "actions_allowed": ["quote", "ask_clarification"],
       "transitions": [{"to": "close", "when": "intent == buy"}]},
      {"id": "close", "actions_allowed": ["close"], "transitions": []}
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human"
  }'::jsonb,
  true
);
```

The condition DSL supports `intent`, `sentiment`, `confidence`,
`all_required_fields_present`, `in [...]`, `==`, and `AND` / `OR`. See
`atendia/state_machine/conditions.py` for the full grammar and
`atendia/contracts/pipeline_definition.py` for the structural validator that
runs at load time.

## Phase 1 status

**Done:**

- 9 Alembic migrations, 17 tables, async-first.
- Pydantic contracts with json-schema consistency tests.
- Pipeline loader + condition DSL + transitioner + action resolver +
  ambiguity guard, all wired through an orchestrator.
- 6 registered tools (`search_catalog`, `quote`, `lookup_faq`,
  `book_appointment`, `escalate_to_human`, `schedule_followup`) — currently
  stubs that return deterministic payloads and persist `tool_calls` rows.
- `ConversationRunner` end-to-end with a canned-NLU adapter for fixtures.
- FastAPI runner endpoint + healthcheck.
- 5 conversation fixtures exercised by an e2e test runner.
- Smoke test script against the live DB.
- 196 tests passing (90 from Fase 1 + 106 from Fase 2), 95.32% aggregate coverage. Gate: ≥ 85%.

**Deliberately NOT done in Phase 1:**

- No real LLM. NLU is canned per fixture (`runner/nlu_canned.py`); the
  Anthropic-backed NLU adapter lands in Phase 2.
- No WhatsApp transport. The gateway and Meta adapter are still v1; v2
  ingestion is Phase 3.
- No outbound message composer. Tools return structured data; turning that
  into a customer-facing reply is Phase 2.
- Tool implementations are stubs. Real catalog search, real quote logic,
  real FAQ retrieval and real calendar booking land alongside the LLM
  composer.

## Phase 2 status — WhatsApp Cloud API transport

Done:
- Webhook GET (subscription challenge) verified per-tenant via `verify_token` in `tenants.config.meta`.
- Webhook POST validates HMAC-SHA256, dedupes via Redis (24h TTL), persists inbound, emits `message_received` event, publishes to Pub/Sub, and runs `ConversationRunner` with keyword-based NLU.
- Outbound queue (`arq`) with idempotency-by-key, exponential backoff retry on transient failures, and per-tenant circuit breaker (10 failures / 60s opens for 30s).
- Worker (`atendia.queue.worker.send_outbound`) calls Meta Cloud API, persists outbound message, publishes `message_sent` event.
- WebSocket endpoint `/ws/conversations/:conversation_id?token=<JWT>` forwards Pub/Sub events scoped to the JWT's tenant.
- Outbound dispatcher maps orchestrator decisions to Phase 2 canned text per action (Phase 3 will replace this with the LLM Composer).

Not in Phase 2 (deliberate):
- LLM-based NLU (`gpt-4o-mini`) — Phase 3.
- LLM Composer (`gpt-4o`) — Phase 3.
- Real Meta Business onboarding flow — Phase 5.
- Encryption at rest for tenant credentials — Phase 6.

## Next phases

- Architecture doc: [`../docs/design/atendia-v2-architecture.md`](../docs/design/atendia-v2-architecture.md)
- Phase 1 plan (state machine): [`../docs/plans/01-nucleo-conversacional.md`](../docs/plans/01-nucleo-conversacional.md)
- Phase 2 plan (WhatsApp transport): [`../docs/plans/02-transporte-whatsapp.md`](../docs/plans/02-transporte-whatsapp.md)

**Phase 3a (done)** — NLU real (`gpt-4o-mini`) with structured outputs, retry on transient
errors, and per-turn cost/latency tracking persisted in `turn_traces`. Toggled by
`ATENDIA_V2_NLU_PROVIDER` (`keyword` → `openai`). Live OpenAI smoke test gated by
`RUN_LIVE_LLM_TESTS=1`.

**Phase 3b** — Composer real (`gpt-4o`) replaces the canned action-text dispatcher.

**Phase 3c** — Migración de pipeline / catálogo / FAQs de Dinamo a DB con embeddings.

The state machine, transport, queue, and realtime layer stay unchanged across 3a–3c — only
the LLM-touched components swap in.

**Phase 4** — frontend debug panel + tenant config UI consuming the realtime WebSocket.

**Phase 5+** — onboarding flow, multi-channel adapters (Instagram DM, web), Google
Calendar / Sheets integrations, A/B testing of prompts.

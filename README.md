# AtendIA v2

AtendIA v2 is a multi-tenant WhatsApp sales assistant and operator workspace.
The product is designed to keep business behavior configurable per tenant:
pipeline stages, customer fields, document requirements, agent prompts,
catalog evidence, quote rules, channel credentials and follow-up behavior live
in tenant configuration instead of being hardcoded for one vertical.

## Current Status

Last manual update: 2026-05-18.

| Area | Status |
|---|---|
| Multi-tenant FastAPI backend, auth, Postgres, Redis and workers | Active |
| WhatsApp channels through Meta Cloud API and Baileys bridge | Active |
| Conversation runner with NLU, flow router, tools, composer and turn traces | Active |
| Configurable PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT modes | Active |
| Knowledge Base for documents, catalog, FAQ and RAG evidence | Active |
| Pipeline editor, document catalog, docs-per-plan and Vision mapping | Active |
| Customer data panel with editable tenant-defined fields and DOCS_* statuses | Active |
| Deterministic docs_complete_for_plan pipeline rule | Active |
| Deterministic quote rendering from retrieved catalog evidence | Active |
| Operator workspace: conversations, customers, pipeline, agents, KB, workflows, traces | Active |

## Start Here

| Need | Read |
|---|---|
| New laptop setup and clean tenant configuration | [docs/runbooks/laptop-new-tenant-setup.md](docs/runbooks/laptop-new-tenant-setup.md) |
| High-level repository map | [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md) |
| Detailed technical map | [docs/PROJECT_MAP_DETAILED.md](docs/PROJECT_MAP_DETAILED.md) |
| Backend setup details | [core/README.md](core/README.md) |
| Knowledge Base operations | [docs/runbooks/knowledge-base.md](docs/runbooks/knowledge-base.md) |
| Conversations operations | [docs/runbooks/conversations.md](docs/runbooks/conversations.md) |
| Pipeline operations | [docs/runbooks/pipeline-kanban.md](docs/runbooks/pipeline-kanban.md) |

## Architecture

The backend is a FastAPI service in `core/atendia`. It receives inbound
WhatsApp messages, stores them in Postgres, runs the conversation through the
runner, updates customer fields and pipeline state, creates turn traces, and
enqueues outbound messages through Redis/arq workers. The runner is deliberately
split into configurable steps: extraction, flow routing, tool/evidence lookup,
composer mode prompts and deterministic guards for sensitive surfaces such as
quotes and document completion.

The frontend is a React/TanStack Router workspace in `frontend/src`. Operators
use it to manage conversations, customer data, documents, pipelines, agents,
Knowledge Base, workflows and debug traces. Tenant admins configure behavior
from the UI where possible; advanced setup can also be seeded through scripts or
SQL/API calls.

## Core Concepts

### Tenant Configuration

The tenant owns the behavior:

- `tenant_pipelines.definition`: stages, rules, document catalog, docs-per-plan,
  Vision mapping and `docs_plan_field`.
- `customer_field_definitions`: fields visible in Datos de cliente and available
  to AI extraction.
- `tenant_branding` and agent mode prompts: voice, tone and workflow behavior.
- Knowledge Base documents: catalog, requirements, FAQ and policy evidence.
- `tenants.config`: channel credentials, QoS, integrations and runtime toggles.

### Documents

Documents use canonical keys such as `DOCS_INE_FRENTE`,
`DOCS_INE_ATRAS` and `DOCS_DOMICILIO`.

The expected canonical runtime shape is:

```json
{
  "DOCS_INE_FRENTE": {
    "status": "ok",
    "source": "vision"
  }
}
```

The pipeline rule `docs_complete_for_plan` checks the document list configured
for the customer's current plan/type. This keeps the document requirements
editable per tenant and avoids hardcoding a single financing vertical.

### Quotes

Quotes must not be free text from the LLM. The runner builds structured quote
data from retrieved catalog evidence and renders the final quote deterministically
when model, plan and price evidence are available. The composer can still answer
natural language around the quote, but price, down payment, payment amount and
term must come from evidence/catalog.

## Quick Start

Prerequisites:

- Docker Desktop
- Python 3.12
- Node.js 20+
- `uv`
- Git

```powershell
# 1. Clone or update the repo
git clone https://github.com/Spiritech369/AtendIA2v.git
cd AtendIA2v

# 2. Start infrastructure
docker compose up -d

# 3. Backend
cd core
uv sync
uv run alembic upgrade head

# 4. Frontend
cd ..\frontend
npm install
npm run typecheck
```

For a clean tenant setup, follow:
[docs/runbooks/laptop-new-tenant-setup.md](docs/runbooks/laptop-new-tenant-setup.md).

## Useful Local Checks

```powershell
# Backend focused tests
cd core
uv run pytest tests/state_machine/test_pipeline_evaluator.py tests/runner/test_structured_quotes.py

# Frontend typecheck
cd ..\frontend
npm run typecheck
```

## Repository Layout

```text
.
|-- core/                       FastAPI backend and workers
|   |-- atendia/
|   |   |-- api/                HTTP routes
|   |   |-- db/                 SQLAlchemy models and Alembic migrations
|   |   |-- runner/             NLU, flow router, tools, composer, traces
|   |   |-- state_machine/      Pipeline loading and rule evaluation
|   |   |-- tools/              Catalog, requirements, quote, RAG, Vision
|   |   |-- queue/              arq workers and outbound jobs
|   |   |-- realtime/           Redis pub/sub and WebSockets
|   |   `-- webhooks/           Meta inbound webhooks
|   `-- tests/                  Backend tests
|-- frontend/                   React operator workspace
|   `-- src/features/           Conversations, customers, pipeline, agents, KB, etc.
|-- docs/                       Maps, runbooks and plans
|-- tools/                      E2E probes and sandbox utilities
|-- contracts/                  JSON schemas
`-- docker-compose.yml          Postgres + Redis local infra
```

## Environment

Copy the example env file and fill production/local secrets:

```powershell
Copy-Item .env.example core\.env
```

Important variables:

- `ATENDIA_V2_OPENAI_API_KEY`
- `ATENDIA_V2_NLU_PROVIDER`
- `ATENDIA_V2_COMPOSER_PROVIDER`
- `ATENDIA_V2_KB_PROVIDER`
- `ATENDIA_V2_META_APP_SECRET`
- `ATENDIA_V2_META_ACCESS_TOKEN`
- `ATENDIA_V2_AUTH_SESSION_SECRET`

Provider defaults can run in safer/mock modes locally, but a real tenant with
catalog, requirements, Vision and quote flows needs the OpenAI key configured.

## License

Private repository.

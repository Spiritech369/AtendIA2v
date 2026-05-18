# AtendIA v2 Project Map

Last manual update: 2026-05-18.

This is the short navigation map. Use
`docs/PROJECT_MAP_DETAILED.md` for implementation-level detail and
`docs/runbooks/laptop-new-tenant-setup.md` when configuring a fresh tenant.

## Source Of Truth

| Need | Read |
|---|---|
| Clean laptop and new tenant setup | `docs/runbooks/laptop-new-tenant-setup.md` |
| Detailed repository map | `docs/PROJECT_MAP_DETAILED.md` |
| Backend setup and commands | `core/README.md` |
| Knowledge Base operations | `docs/runbooks/knowledge-base.md` |
| Conversation operations | `docs/runbooks/conversations.md` |
| Pipeline operations | `docs/runbooks/pipeline-kanban.md` |
| Historical plans | `docs/_archive/README.md` |

## Runtime Areas

| Area | Purpose | Main paths |
|---|---|---|
| Backend API | FastAPI app, auth and feature routes | `core/atendia/api/`, `core/atendia/main.py` |
| Webhooks | Meta inbound/status handling | `core/atendia/webhooks/` |
| Channels | Meta and Baileys transport adapters | `core/atendia/channels/`, `core/baileys-bridge/` |
| Runner | NLU, flow routing, tools, composer, traces | `core/atendia/runner/`, `core/atendia/tools/` |
| State machine | Pipeline definitions, rules and auto-stage moves | `core/atendia/state_machine/` |
| Documents | DOCS_* statuses, Vision mapping and docs-per-plan | `core/atendia/runner/vision_to_attrs.py`, `core/atendia/state_machine/pipeline_evaluator.py`, `frontend/src/features/expediente/` |
| Quotes | Deterministic quote extraction/rendering from catalog evidence | `core/atendia/runner/conversation_runner.py`, `core/tests/runner/test_structured_quotes.py` |
| Knowledge Base | Documents, catalog, FAQ, RAG and command center | `core/atendia/api/knowledge_routes.py`, `core/atendia/api/_kb/`, `core/atendia/tools/rag/` |
| Queue | arq workers, outbound, followups, indexing | `core/atendia/queue/` |
| Realtime | Redis pub/sub and WebSocket routes | `core/atendia/realtime/` |
| Database | Models and migrations | `core/atendia/db/` |
| Frontend | Operator workspace | `frontend/src/` |
| Contracts | JSON schemas and generated TS types | `contracts/`, `frontend/src/types/generated/` |

## Frontend Routes

| Route | Feature folder |
|---|---|
| `/conversations` | `frontend/src/features/conversations/` |
| `/customers` | `frontend/src/features/customers/` |
| `/pipeline` | `frontend/src/features/pipeline/` |
| `/expediente` | `frontend/src/features/expediente/` |
| `/agents` | `frontend/src/features/agents/` |
| `/knowledge` | `frontend/src/features/knowledge/` |
| `/workflows` | `frontend/src/features/workflows/` |
| `/turn-traces` | `frontend/src/features/turn-traces/` |
| `/config` | `frontend/src/features/config/` |

## Configurable Tenant Surfaces

| Surface | What it controls |
|---|---|
| `tenant_pipelines.definition.stages` | Pipeline stages, labels and auto-enter rules |
| `tenant_pipelines.definition.documents_catalog` | Canonical document keys and labels |
| `tenant_pipelines.definition.docs_per_plan` | Required document list per plan/type |
| `tenant_pipelines.definition.docs_plan_field` | Customer field used to pick docs-per-plan |
| `tenant_pipelines.definition.vision_doc_mapping` | Vision category to DOCS_* status mapping |
| `customer_field_definitions` | Fields shown in Datos de cliente and extracted by AI |
| Agent mode prompts | PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT behavior |
| Knowledge Base documents | Catalog, requirements, FAQ and policies used as evidence |
| `tenants.config.qos` | Max messages per turn and response SLO |

## Tooling Folders

| Folder | Use |
|---|---|
| `scripts/` | Repo-level local startup scripts |
| `tools/e2e/` | One-off validation probes and E2E scripts |
| `tools/sandbox/` | Runner sandbox utilities |
| `core/scripts/` | Backend operational scripts |

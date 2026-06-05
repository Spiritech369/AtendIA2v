# Frontend Config Surface Audit - 2026-06-02

Tenant: Dinamo Motos NL  
tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`  
agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`

## Route Matrix

| Route | Purpose | Backend API | Data source | Status | Problems | Required for live? | Decision |
|---|---|---|---|---|---|---|---|
| `/knowledge` | Operar fuentes y pruebas RAG | `/api/v1/knowledge/items`, `/knowledge/test`, `/knowledge/simulate` | Knowledge OS v2 + legacy KB fallback | ACTIVE | Default tab could hide non-FAQ sources; endpoint did not expose Knowledge OS v2 sources | yes | FIX_NOW |
| `/expediente` | Editar matriz documentos por caso | `/api/v1/tenants/pipeline`, `/api/v1/customer-fields` | Tenant pipeline definition | ACTIVE | Depends on pipeline having `docs_plan_field`/`document_requirements`; needs DB verification | yes | KEEP_ACTIVE |
| `/pipeline` | Lifecycle stages and editor | `/api/v1/pipeline`, `/api/v1/tenants/pipeline` | Tenant pipeline definition + lifecycle | ACTIVE | Composer mode label can look authoritative; should be legacy/guidance wording for v2 | yes | KEEP_ACTIVE |
| `/workflows` | Workflow editor/simulation | `/api/v1/workflows`, `/api/v1/executions` | Workflows table | BROKEN | Nodes without `config.intent` could crash editor | conditional | FIX_NOW |
| `/customer-fields` | Contact Memory field config | `/api/v1/customer-fields` | Customer field definitions | ACTIVE | Needs tenant DB verification for duplicates | yes | KEEP_ACTIVE |
| `/catalog` | Official quote catalog surface | `/api/v1/knowledge/catalog` | Legacy `tenant_catalogs`, now commercial `catalog_items` too | BROKEN | UI showed 0 when official commercial catalog existed outside legacy endpoint | yes | FIX_NOW |
| `/agents` | Agent Studio/ops/readiness | `/api/v1/agents` | Agent rows + ops config + Knowledge OS | ACTIVE | Several widgets need REAL_DATA vs MOCK labeling audit | yes | NEEDS_HUMAN_REVIEW |
| `/composer` | Stage/composer guidance | `/api/v1/tenants/pipeline` | `mode_prompts` in pipeline | LEGACY | Can be mistaken for final-copy authority | no | KEEP_LEGACY_COLLAPSED |
| `/conversations` ContactPanel | Contact field presentation | `/api/v1/conversations/*` | Contact Memory values + presentation grouping | ACTIVE | Needs screenshot review after DB online | yes | KEEP_ACTIVE |
| `/turn-traces` / why-this-answer | Runtime traceability | `/api/v1/turn-traces` | TurnTrace / AgentRuntime v2 traces | ACTIVE | No code change in this pass | yes | KEEP_ACTIVE |

## Fixes Applied

- `/knowledge/items` now includes native Knowledge OS v2 `knowledge_sources`, with item/chunk counts, factual vs non-factual collection labels, and retrieval/agent disabled flags in the title.
- `/knowledge` now opens on a `Fuentes` tab so default filters do not hide `catalogo_dinamo`, `requisitos_dinamo`, or `faq_dinamo`.
- `/knowledge/catalog` now exposes active commercial catalog rows from `catalogs/catalog_items/catalog_item_plans` in the same response shape the current `/catalog` page already consumes.
- `/workflows` now normalizes workflow definitions server-side and handles missing node `config` client-side. Missing detect-intent labels fall back to `Sin intent`.

## Safety

No WhatsApp enablement, no send/manual-send/auto-send, no real outbox writes, no real action execution, and no workflow event execution were introduced.


# Moto-Crédito E2E Validation — FINDINGS

> Evidence log for `docs/plans/2026-05-15-moto-credito-e2e-validation.md`.
> Contract (ESTADO-Y-GAPS §11): evidence before claims; declare scope cuts;
> report bugs with repro; no green emojis unsold.

**Run metadata**
- Date: 2026-05-15
- Branch: `claude/moto-credito-e2e-validation` (main checkout)
- Isolated tenant: `dele.zored@hotmail.com` → `tenant_id = 867a1047-6aea-4b21-85d8-898aef0051cb` ("Zored QA Workspace" — verified empty in prior recon: 0 agents/catalog/faqs/conversations → ideal isolated target)
- **Validation API budget: $1.53. Cumulative spent (this plan): $0.00 after Task 0** (Task 0 makes no LLM calls).
- Transparency note: ~$0.04 was spent earlier this session on the *separate* sandbox-smoke exploration (not part of this plan's budget).

---

## Task 0 — Stack + API contracts + findings scaffold — ✅ PASS

**Stack health (Bash curl + docker ps):**
- backend `http://localhost:8001/openapi.json` → HTTP `200`
- frontend `http://localhost:5173` → HTTP `200`
- Docker (all Up ~25 min): `atendia_backend` (0.0.0.0:8001), `atendia_frontend` (0.0.0.0:5173), `atendia_postgres_v2` healthy (0.0.0.0:5433), `atendia_redis_v2` healthy (0.0.0.0:6380), `atendia_worker`, `atendia_workflow_worker`, `atendia_baileys_bridge` healthy.

**Auth (POST /api/v1/auth/login, isolated tenant):**
- HTTP `200`; response `{csrf_token, user:{id:53662e2b-…, tenant_id:867a1047-6aea-4b21-85d8-898aef0051cb, role:superadmin, email:dele.zored@hotmail.com}}`. CSRF + session cookie path confirmed.

**API contracts captured (openapi.json, source of truth — do NOT guess payloads):**
- `POST /api/v1/agents` — required `['name']`; fields incl. `system_prompt` (str|null), `flow_mode_rules` (obj|null), `knowledge_config` (object), `is_default` (bool), `tone`, `no_emoji` (bool), `language`, `goal`, `active_intents` (array), `extraction_config` (object), `ops_config` (object).
- `PATCH /api/v1/agents/{agent_id}/config` — all optional (used to set `knowledge_config` later).
- `POST /api/v1/agents/{agent_id}/preview-response` — `{message:str, conversationContext:obj, draftConfig:obj}` (product's own "test agent" path).
- `POST /api/v1/agents/{agent_id}/publish`, `GET /api/v1/agents/{agent_id}` — present.
- `PUT /api/v1/tenants/pipeline` — required `['definition']` (object); `GET` counterpart present.
- KB is under **`/api/v1/knowledge/...`** (NOT `/kb`): `POST /api/v1/knowledge/catalog` required `['sku','name']` (+`attrs` obj, `category`, `tags` array, `active`). FAQ/documents/search sub-schemas to be pinned in Task 3 by reading `knowledge_routes.py`.
- `POST /api/v1/workflows` — required `['name','trigger_type']` (+`trigger_config` obj, `definition` obj, `active`). Node/publish sub-schemas pinned in Task 6.

**Open items deferred to their tasks (by design):** exact pipeline `definition` JSON shape (Task 4), KB FAQ/document ingest shapes (Task 3), workflow node/publish shapes (Task 6) — each task reads the route file for the precise contract.

**Status: PASS.** Stack reachable, isolated tenant authenticates, core contracts pinned.

---

## Task 1 — Flow order (msg→process→send) — pending
## Task 2 — Prompt master via /agents + browser — pending
## Task 3 — KB ingestion + retrieval + scoping — pending
## Task 4 — Pipeline text+document moves — pending
## Task 5 — Conversaciones committed + browser — pending
## Task 6 — Workflow create+trigger+execute — pending
## Task 7 — Scorecard + Respond.io + recommendation — pending

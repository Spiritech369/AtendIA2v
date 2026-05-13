# Knowledge Base module — runbook

| Field | Value |
|---|---|
| Module status | **Phase 1 + B2 backend REAL · Command Center mock surface live with stable contracts · 9-tab frontend live · 4 workers pending** |
| Last updated | 2026-05-12 |
| Backend code | `core/atendia/api/knowledge_routes.py` (819 lines) + `core/atendia/api/_kb/` sub-routers |
| Frontend code | `frontend/src/features/knowledge/` — `KnowledgeBasePage.tsx` (2,261 lines, 9 tabs) + `api.ts` (326 lines) |
| Design doc | [docs/plans/2026-05-10-knowledge-base-module-design.md](../plans/2026-05-10-knowledge-base-module-design.md) |
| Demo/mock convention | [§3](#3-demomock-isolation-convention) — `tenant.is_demo` flag (migration 041) + `_demo: true` on API responses + `DemoBadge` / `NYIButton` in UI |

> **Honest status.** The 9-tab Command Center frontend ships against a typed mock surface in `_kb/command_center.py`. The mocks are **stable contracts**: the FE can develop and ship UX while individual GETs flip from fixture to real one by one. Foundations (FAQ/Catalog/Document CRUD, RAG `/test-query`, unified `/search`, collections) are real and persist to Postgres. The four worker jobs that turn the Command Center "real" (conflict detection, daily health snapshot, content expiry, regression suite, CSV importer) are still TODO. See [§4 Roadmap](#4-roadmap-flipping-mock--real) for the priority order.

---

## 1. Endpoint inventory

Status legend: **REAL** = backed by DB / real provider · **MOCK** = typed fixture, stable contract · **MOCK-DEMO** = mock + gated by `demo_tenant()` dependency (501 on non-demo tenants) · **NYI** = no backend; UI stub.

### 1.1 Foundations — REAL

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET / POST / PATCH / DELETE | `/knowledge/faqs[/:id]` | user (mut = admin) | TenantFAQ CRUD; create/patch re-embeds via `_maybe_embed` |
| GET / POST / PATCH / DELETE | `/knowledge/catalog[/:id]` | user (mut = admin) | TenantCatalogItem CRUD; re-embeds on text change |
| GET | `/knowledge/documents` | user | KnowledgeDocument list |
| POST | `/knowledge/documents/upload` | admin | Stores file, enqueues `index_document` worker, returns 202 |
| GET | `/knowledge/documents/{id}` | user | Single doc |
| GET | `/knowledge/documents/{id}/download` | user | Streams from storage |
| POST | `/knowledge/documents/{id}/retry` | admin | Re-enqueues failed indexing |
| DELETE | `/knowledge/documents/{id}` | admin | Removes file + DB rows |
| POST | `/knowledge/test` | user | Quick RAG smoke — retrieval + simple LLM answer with fallback |
| POST | `/knowledge/reindex` | admin | Re-enqueues every doc; 5-min per-tenant cooldown + arq job dedupe |
| GET | `/knowledge/search` | user | Unified search across FAQ/Catalog/Doc, agent-scoped via `kb_agent_permissions` |
| POST | `/knowledge/test-query` | user (admin for `include_drafts`) | Full structured RAG pipeline (retriever → prompt → synthesizer); writes capture row to `kb_unanswered_questions` on low confidence |
| GET / POST / PATCH / DELETE | `/knowledge/collections[/:id]` | user (mut = admin) | `kb_collections` CRUD; 9 seeded defaults via `seed_knowledge_defaults` |

### 1.2 Command Center surface — MOCK with stable contracts

All in `core/atendia/api/_kb/command_center.py`. Frontend calls these from the 9-tab UI; each returns a typed fixture today.

| Method | Path | Status | What it needs to become REAL |
|---|---|---|---|
| GET | `/knowledge/health` | MOCK | `compute_health_snapshot_job` cron + `kb_health_snapshots` reads |
| GET | `/knowledge/health/history` | MOCK | Same daily job; 30/90-day window query |
| GET | `/knowledge/risks` | MOCK | Derived view over `kb_conflicts` + `kb_health_snapshots` once conflict worker exists |
| POST | `/knowledge/risks/{id}/resolve` | MOCK | Update `kb_conflicts.status` once `kb_conflicts` is populated |
| GET | `/knowledge/items` | MOCK | UNION query across FAQ/Catalog/Doc with shared metadata filters; **lowest effort to flip** |
| POST | `/knowledge/items/{id}/publish` | MOCK | Setter on `status` field of the source row |
| POST | `/knowledge/items/{id}/archive` | MOCK | Same — `status='archived'` |
| POST | `/knowledge/items/{id}/reindex` | MOCK | Look up source row and re-enqueue `index_document` (or re-embed for FAQ/Catalog) |
| GET | `/knowledge/unanswered-questions` | MOCK | List from `kb_unanswered_questions` (data already captured by `/test-query`) |
| POST | `/knowledge/unanswered-questions/{id}/create-faq` | MOCK | Insert TenantFAQ from `linked_faq_id` + flip status |
| POST | `/knowledge/unanswered-questions/{id}/ignore` | MOCK | `status='ignored'` |
| POST | `/knowledge/unanswered-questions/{id}/escalate` | MOCK | `status='escalated'` + raise notification |
| GET | `/knowledge/funnel-coverage` | MOCK | Derived analytics — keep MOCK in v1; backed by retrieval logs in v2 |
| GET | `/knowledge/dashboard-cards` | MOCK | Same — derived summary tiles, MOCK v1 |
| POST | `/knowledge/simulate` | **MOCK-DEMO** | Currently 501 on non-demo. Pragmatic fix: delegate to `/test-query` for non-demo and wrap response shape; see [§4](#4-roadmap-flipping-mock--real) |
| GET | `/knowledge/simulate/{id}` | MOCK | Persist simulations into `kb_test_runs` (rows already exist for the test runner) |
| POST | `/knowledge/simulate/{id}/mark-{correct,incomplete,incorrect}` | MOCK | Write `feedback` column on `kb_test_runs` |
| POST | `/knowledge/simulate/{id}/create-faq` | MOCK | Same path as unanswered-questions/create-faq |
| POST | `/knowledge/simulate/{id}/block-answer` | MOCK | Add to `kb_safe_answer_settings.risky_phrases` |
| GET | `/knowledge/chunks/{id}/impact` | MOCK | Compute from `KnowledgeChunk.retrieval_count` + `average_score` + scan `kb_conflicts` |
| POST | `/knowledge/chunks/{id}/disable` | MOCK | `chunk_status='disabled'` |
| POST | `/knowledge/chunks/{id}/split` | MOCK | **Defer — design §11 cut** ("chunk split/merge"). Keep MOCK indefinitely. |
| POST | `/knowledge/chunks/{id}/merge` | MOCK | **Defer — design §11 cut.** |
| POST | `/knowledge/chunks/{id}/prioritize` | MOCK | `marked_critical=true` + bump `priority` |
| POST | `/knowledge/chunks/{id}/reindex` | MOCK | Re-embed single chunk |
| GET | `/knowledge/conflicts` | MOCK | List from `kb_conflicts` after `detect_conflicts_job` populates it |
| POST | `/knowledge/conflicts/{id}/resolve` | MOCK | `status='resolved'` |
| GET | `/knowledge/audit-logs` | MOCK | Query `kb_versions` — **lowest effort to flip after `/items`** |

### 1.3 NYI in frontend (no backend mounted yet)

These are UI stubs in `KnowledgeBasePage.tsx` with no `onClick` handler. Replace with `<NYIButton />` for consistency with the rest of the app (per `docs/plans/2026-05-12-placeholder-elimination-*`).

| UI element | What it would require |
|---|---|
| Top bar "Import" file picker | `import_catalog_csv_job` worker + `/knowledge/catalog/import` endpoint |
| Top bar "Crear" dropdown shortcuts | Frontend-only: open the corresponding tab's create dialog |
| Top bar "Saved filters" dropdown | Frontend-only: persist filter combos in `localStorage` |
| Chunk Impact Drawer "Editar" button | Currently no editor UI; depends on whether chunk split/merge is built |

---

## 2. Workers

| Worker | File | Status | Trigger | Purpose |
|---|---|---|---|---|
| `index_document` | `core/atendia/queue/worker.py` | ✅ **REAL** | Enqueued by upload / retry / reindex / per-doc reindex | Parse → chunk → embed → write `KnowledgeChunk` rows. Idempotent via `_job_id`. |
| `detect_conflicts_job` | _not yet built_ | ❌ TODO | Cron (suggested hourly) | Run `conflict_detector.py` regexes across FAQ/Catalog/Doc, write `kb_conflicts` rows. Unblocks `/conflicts` + `/risks`. |
| `compute_health_snapshot_job` | _not yet built_ | ❌ TODO | Cron daily | Aggregate retrieval logs + chunk stats → `kb_health_snapshots` row. Unblocks `/health` + `/health/history`. |
| `expire_content_job` | _not yet built_ | ❌ TODO | Cron hourly | Auto-archive rows whose `expires_at < now()` across FAQ/Catalog/Doc. Lightweight. |
| `run_regression_suite_job` | _not yet built_ | ❌ TODO | On demand (POST `/tests/run-suite`, future endpoint) | Iterate `kb_test_cases`, replay through `/test-query`, write `kb_test_runs.diff_vs_expected`. Unblocks "Pruebas" tab. |
| `import_catalog_csv_job` | _not yet built_ | ❌ TODO | On demand (POST `/catalog/import`, future endpoint) | Stream CSV, validate schema, batch-insert with error_count tracking. Unblocks top-bar Import button. |

Queue infra: arq, Redis-backed, with a separate `workflows` queue (max_jobs=5) and the default queue (max_jobs=10) used by `index_document`. New KB workers go on the default queue.

---

## 3. Demo/mock isolation convention

Single source of truth: `tenant.is_demo` boolean (migration 041).

| Layer | Mechanism |
|---|---|
| Backend gating | FastAPI `demo_tenant()` dependency → returns `is_demo`. Demo-only endpoints raise `HTTP 501` if `is_demo=False`. |
| API response marker | Endpoints serving fixture data include `"_demo": true`. Real endpoints do not. |
| Frontend marker — simulated data | `<DemoBadge />` (violet chip) — "Datos de demostración — no reflejan operación real". |
| Frontend marker — unbuilt features | `<NYIButton />` (amber + lock) — replaces `toast.info("Feature en construcción")`. |
| Test fixtures | `MOCK_SEED="full_mock_v1"` tag on seeded rows; `seed_full_mock_data.py` runs at deploy time, **not** from route handlers. |

**In this module**: Only `POST /knowledge/simulate` is gated by `demo_tenant()` today (line 810 of `_kb/command_center.py`). The other Command Center GETs return fixtures unconditionally because the FE needs the contract to be visible to non-demo operators too. When a GET is flipped to REAL, drop the fixture; when it stays MOCK long-term, add `"_demo": true` and `demo_tenant()` gating so non-demo operators get a clear 501 instead of silent fake data.

---

## 4. Roadmap — flipping MOCK → REAL

Priority is "highest value per hour of work". Pick the next unblocked item; don't batch unless commits are tiny.

### Tier A — lowest effort, highest visibility (no new worker)

1. **`GET /knowledge/items` + per-item `publish/archive/reindex`** → UNION query across FAQ/Catalog/Doc with shared metadata filters. Mutations are setters on existing columns. ~1 session.
2. **`GET /knowledge/audit-logs`** → query `kb_versions` directly. ~½ session.
3. **`GET /knowledge/unanswered-questions` + create-faq/ignore/escalate** → query `kb_unanswered_questions` (data already captured by `/test-query`). The mutations are 3-line `UPDATE` calls. ~1 session.
4. **`POST /knowledge/simulate` for non-demo** → wrap `/test-query` response into `SimulationResponse` shape, persist into `kb_test_runs` with `feedback=NULL` initially. Simulation feedback mutations write to that same row. Removes the 501 wall for real operators. ~1 session.
5. **Chunk single-row mutations** (`disable`, `prioritize`, `reindex`) — three setters + one job enqueue. Skip `split`/`merge` per design §11. ~½ session.

### Tier B — one worker per item

6. **`detect_conflicts_job` + `GET /knowledge/conflicts`** → cron hourly, scan FAQ/Catalog/Doc text via `conflict_detector.py`, insert into `kb_conflicts`. The list endpoint becomes a straight query. Unblocks `/risks` partially. ~1 session.
7. **`compute_health_snapshot_job` + `GET /knowledge/health` + `/health/history`** → daily cron, aggregate retrieval logs into `kb_health_snapshots`. ~1 session.
8. **`expire_content_job`** → hourly cron, `UPDATE … SET status='archived' WHERE expires_at < now()`. Tiny. ~¼ session.
9. **`/knowledge/risks` real** → SQL view over `kb_conflicts` + `kb_health_snapshots`. Depends on 6 + 7. ~½ session.
10. **`run_regression_suite_job`** + future `POST /tests/run-suite` and `kb_test_cases` CRUD endpoints. Enables the "Pruebas" tab. ~2 sessions (worker + 8 endpoints).
11. **`import_catalog_csv_job`** + `POST /catalog/import` + `GET /catalog/import-status` + wire frontend Import button. ~1 session.

### Tier C — stays MOCK in v1

* `GET /knowledge/funnel-coverage` — derived from retrieval logs we don't aggregate yet; keep MOCK with `"_demo": true` until retrieval-log analytics ship.
* `GET /knowledge/dashboard-cards` — summary tiles, same rationale.
* `GET /knowledge/chunks/{id}/impact` — derivable but UI value is questionable until conflict detector lights it up; MOCK until conflicts are real.
* `POST /knowledge/chunks/{id}/split` / `/merge` — explicitly cut in design §11. Keep MOCK indefinitely; surface `<DemoBadge />` on the buttons if they remain visible.

---

## 5. Frontend coverage

`KnowledgeBasePage.tsx` (2,261 lines, 9 tabs) is wired to all 30+ endpoints listed in §1. Live status:

| Tab | Source types | Wiring | Notes |
|---|---|---|---|
| FAQs (156) | `faq` | ✅ Full CRUD + reindex | List → `/faqs`, mutations real |
| Catálogo (642) | `catalog_item` | ✅ Full CRUD + reindex | List → `/catalog`, Import button is stub (Tier B 11) |
| Documentos (412) | `document` | ✅ Upload + retry + delete + reindex | All real |
| Promociones (28) | filtered catalog | ✅ List | Same backend as Catálogo |
| Reglas de crédito (24) | filtered FAQ | ✅ List | Same backend as FAQs |
| Preguntas sin respuesta (118) | mock today | 🟡 List + 3 mutations | `<DemoBadge />` until Tier A 3 lands |
| Conflictos (32) | mock today | 🟡 List + resolve | `<DemoBadge />` until Tier B 6 lands |
| Pruebas (30) | mock today | 🟡 List + 3 actions | `<DemoBadge />` until Tier B 10 lands |
| Métricas (9) | mock today | 🟡 Tiles + health card | `<DemoBadge />` until Tier B 7 lands |

Side panels:
* **Health Cockpit** — `<DemoBadge />` until Tier B 7
* **Risk Radar** — `<DemoBadge />` until Tier B 9
* **WhatsApp Gaps** — `<DemoBadge />` until Tier A 3
* **Funnel Knowledge Coverage** — `<DemoBadge />` indefinitely (Tier C)
* **Bottom Action Cards** — `<DemoBadge />` indefinitely (Tier C)
* **RAG Simulation** — 🟡 `<DemoBadge />` until Tier A 4 (then drop badge on non-demo)
* **Chunk Impact Drawer** — `<DemoBadge />` while §11 cuts hold
* **Prompt Preview Drawer** — ✅ real (reads same builder output as `/test-query`)

Frontend NYI stubs (`<NYIButton />` candidates per [§1.3](#13-nyi-in-frontend-no-backend-mounted-yet)): Import button (Tier B 11), "Crear" dropdown shortcuts (FE-only wire), Saved filters (FE-only state), Chunk Impact "Editar" (design §11 cut).

---

## 6. Environment variables

| Var | Default | Purpose |
|---|---|---|
| `ATENDIA_V2_KB_PROVIDER` | `openai` | `openai` or `mock`. Mock forced when `OPENAI_API_KEY` is empty. |
| `ATENDIA_V2_OPENAI_API_KEY` | (empty) | Required for production `/test-query`. Empty in dev → `MockProvider` auto-fallback. |
| `ATENDIA_V2_REDIS_URL` | (existing) | Cooldowns, rate limits, arq worker queue. |
| `ATENDIA_V2_DATABASE_URL` | (existing) | Postgres + pgvector + halfvec. |
| `RUN_LIVE_LLM_TESTS` | unset | Set to `1` to opt-in to `@pytest.mark.live` tests against real OpenAI. |

---

## 7. Deploy steps

```powershell
# 1. Apply migrations through head (031-041 cover KB + demo flag)
cd core
uv run alembic upgrade head

# 2. Restart API (platform-specific)

# 3. Seed defaults per tenant (idempotent)
uv run python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>

# 4. (Demo tenants only) Seed full mock data
uv run python -m atendia.scripts.seed_full_mock_data <tenant_uuid>

# 5. Restart arq worker so it picks up index_document registrations
# (platform-specific — when new workers from §2 are built, redeploy the worker process)
```

> ⚠️ Cron workers (`compute_health_snapshot_job`, `expire_content_job`, `detect_conflicts_job`) are **not yet wired**. No new cron behavior is registered with this deploy. Adding any of them per [§4 Roadmap](#4-roadmap-flipping-mock--real) requires editing `core/atendia/queue/worker.py` `WorkerSettings.cron_jobs` and redeploying the worker process.

---

## 8. Rollback steps

```powershell
cd core
uv run alembic downgrade <previous-head>
```

| Migration | Rollback impact |
|---|---|
| 041 | Drops `tenants.is_demo` column. Demo gating disabled — `demo_tenant()` dependency must be removed or it errors. |
| 036 | Drops health snapshots + agent perms + priority + safe-answer settings. Retriever falls back to hardcoded defaults. |
| 035 | Drops test cases/runs. "Pruebas" tab data loss. |
| 034 | Drops conflicts + unanswered. Mock fixtures continue to render but capture stops working in `/test-query`. |
| 033 | Drops `kb_versions`. Audit history lost. |
| 032 | Strips shared metadata. Text columns preserved; `'indexed'`→`'ready'` migration is one-way. |
| 031 | Drops `kb_collections`. FAQs/Catalog/Docs lose `collection_id` (NULL). |

Forward-only after 24h on prod (per design §9).

---

## 9. Smoke checks

```powershell
$tid = "<tenant-uuid>"
cd core

# 1. Seed
uv run python -m atendia.scripts.seed_knowledge_defaults $tid

# 2. Login + capture cookie + CSRF (manual)

# 3. Foundations — REAL
curl http://localhost:8001/api/v1/knowledge/search?q=requisitos -H "Cookie: ..."
curl http://localhost:8001/api/v1/knowledge/collections -H "Cookie: ..."   # 9 defaults
curl -X POST http://localhost:8001/api/v1/knowledge/test-query \
  -H "Content-Type: application/json" -H "Cookie: ..." -H "X-CSRF-Token: ..." \
  -d '{"query":"¿Cuáles son los requisitos?","agent":"duda_general","minimum_score":0}'
# Expected: 200, structured RAG response with mode=mock (no OPENAI_API_KEY) or mode=llm

# 4. Command Center — MOCK (typed contracts)
curl http://localhost:8001/api/v1/knowledge/health -H "Cookie: ..."           # 200, fixture
curl http://localhost:8001/api/v1/knowledge/items?page=1 -H "Cookie: ..."     # 200, fixture
curl http://localhost:8001/api/v1/knowledge/conflicts -H "Cookie: ..."        # 200, fixture
curl http://localhost:8001/api/v1/knowledge/audit-logs -H "Cookie: ..."       # 200, fixture

# 5. Demo-gated — MOCK-DEMO
curl -X POST http://localhost:8001/api/v1/knowledge/simulate \
  -H "Content-Type: application/json" -H "Cookie: ..." -H "X-CSRF-Token: ..." \
  -d '{"message":"¿Aceptan INE de otro estado?","agent":"sales_agent","model":"mock-local"}'
# Expected on demo tenant: 200, SimulationResponse fixture.
# Expected on non-demo tenant: 501 — flip to REAL per Tier A 4.

# 6. Worker round-trip — REAL
# (upload a small PDF via UI or curl /documents/upload; watch arq logs for index_document)
```

---

## 10. Troubleshooting

* **`/test-query` returns `mode=sources_only`** — provider was `None`: no `OPENAI_API_KEY` AND `KB_PROVIDER=openai`. Either set the key or `KB_PROVIDER=mock` for templated mock answer.
* **`/search` returns no results** — check `kb_agent_permissions` for the agent. Retriever falls back to permissive when no row exists (all sources allowed, no collection restriction).
* **Frontend shows fixture data on real tenant** — expected for endpoints still in [§1.2](#12-command-center-surface--mock-with-stable-contracts). Track flip status in §4.
* **`POST /simulate` returns 501** — tenant is not demo (`tenant.is_demo=false`). Either flip to a demo tenant or implement Tier A 4 to remove the gate.
* **Worker not picking up uploads** — Redis down OR worker process not restarted after deploy. Check `arq:queue:default` length; restart worker. Document upload sets `status='error'` with `"index worker unavailable"` on enqueue failure (visible in document detail panel).
* **Frontend bun tests fail with `document is not defined`** — use `pnpm exec vitest run`, not `bun test`. Bun's native runner ignores `vitest.config.ts` and its jsdom environment.

---

## 11. Verification snapshot

| Surface | State on 2026-05-12 |
|---|---|
| Migrations through head | 031–041 applied; `tenants.is_demo` available |
| KB models | 10 model files under `core/atendia/db/models/kb_*.py` |
| RAG core | `provider.py` (mock + OpenAI), `retriever.py`, `prompt_builder.py`, `answer_synthesizer.py`, `conflict_detector.py`, `risky_phrase_detector.py` — all real |
| Endpoints REAL | 13 paths (FAQ/Catalog/Doc CRUD + reindex + RAG + collections) |
| Endpoints MOCK | 27 paths in `_kb/command_center.py` (1 demo-gated, 26 unconditional) |
| Workers REAL | `index_document` only |
| Workers TODO | 5 (see [§2](#2-workers)) |
| Frontend tabs | 9 wired; 4 surface `<DemoBadge />` until Tier A/B flips land |
| Backend test suite | (last full run prior to operations-center commit: 798 passed) |

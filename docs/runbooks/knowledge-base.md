# Knowledge Base module — runbook

| Field | Value |
|---|---|
| Module status | **Partial B2 implementation** — backend foundation only (Phases 1-2 + non-negotiable Phase 3 endpoints). Frontend rebuild and remaining endpoints deferred. |
| Branch | `feat/kb-module-b2` |
| Design doc | [docs/plans/2026-05-10-knowledge-base-module-design.md](../plans/2026-05-10-knowledge-base-module-design.md) |
| Plan | [docs/plans/2026-05-10-knowledge-base-module-implementation.md](../plans/2026-05-10-knowledge-base-module-implementation.md) |

> ⚠️ **Honest status:** this branch ships approximately **30% of the B2 design**. Migrations, models, RAG provider abstraction, retriever, prompt builder, answer synthesizer, seed script, and three endpoints (`/search`, `/test-query`, `/collections`). The frontend rebuild, the other ~44 endpoints, and the worker jobs all live in follow-up sessions. See "Explicit gap list" at the bottom.

---

## 1. What's in this module

### Database schema (Tasks 1-6 — all 6 migrations applied)

* `031_kb_collections` — tenant-scoped collections (slug, name, icon, color)
* `032_kb_extend_existing` — shared metadata block on `tenant_faqs`/`tenant_catalogs`/`knowledge_documents` (status, visibility, priority, expires_at, agent_permissions, collection_id, language, ...) plus catalog-specific (price_cents, stock_status, region, branch, payment_plans), document extras (progress_percentage, embedded_chunk_count, error_count), chunk extras (chunk_status, marked_critical, retrieval_count, average_score, ...). Migrates legacy `'indexed'` documents to `'ready'` and seeds `embedded_chunk_count := fragment_count`.
* `033_kb_versions` — audit timeline per (entity_type, entity_id), `diff_json` JSONB, indexed `version_number DESC`.
* `034_kb_conflicts_unanswered` — open queues for the operator review.
* `035_kb_test_cases_runs` — regression suite (test cases + run history with diff_vs_expected).
* `036_kb_health_perms_priority_safe` — health snapshots, agent permissions (UNIQUE(tenant_id, agent)), source priority rules, safe-answer settings (tenant-singleton).

### SQLAlchemy models (Task 7)

10 new model files under `core/atendia/db/models/kb_*.py` plus extensions to `knowledge_document.py` and `tenant_config.py`. Re-exported from `atendia.db.models`.

### RAG provider abstraction (Tasks 8-9)

* `atendia.tools.rag.provider.LLMProvider` Protocol + `PromptInput` / `AnswerOutput` Pydantic DTOs.
* `MockProvider` — deterministic SHA-256 → 3072-dim unit vector + templated answer; used by all tests and for `KB_PROVIDER=mock`.
* `OpenAIProvider` — wraps `atendia.tools.embeddings.generate_embedding` (preserves Phase 3c.1 cost tracking) and OpenAI chat completion.
* `get_provider()` — `lru_cache(1)` singleton; auto-falls back to mock when `OPENAI_API_KEY` is empty.

### RAG core (Tasks 11-15)

* `conflict_detector.py` — regex-only detection: `price_mismatch`, `enum_disagreement`, `text_overlap_with_negation` (Jaccard ≥ 0.4 + xor negation).
* `risky_phrase_detector.py` — 6 seeded Spanish-MX patterns; tenant override via `kb_safe_answer_settings.risky_phrases`.
* `retriever.py` — agent-scoped: load permissions/priority/safe-answer, embed query, vector-search 3 source types, filter by collection/status/expires_at/chunk_status, apply min_score, sort by (priority DESC, score DESC), top-K, run conflict detector.
* `prompt_builder.py` — base + per-agent block + safety block (last); chunks in `<fuente type=… id=… collection=… score=…>` envelopes.
* `answer_synthesizer.py` — confidence/action decision tree per design §6.

### Endpoints (Tasks 16/17/18/30 — partial Phase 3)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/knowledge/search` | user | unified search, grouped by source_type |
| POST | `/api/v1/knowledge/test-query` | user (admin for `include_drafts`) | full structured RAG response |
| GET / POST / PATCH / DELETE | `/api/v1/knowledge/collections[/:id]` | mixed (POST/PATCH/DELETE = admin) | kb_collections CRUD |

The remaining ~44 endpoints (chunks/conflicts/unanswered/tests/versions/health/analytics/settings, FAQ/Catalog publish/archive, document parse/chunk/embed/reindex/archive, catalog import) are not yet built. See the gap list below.

### Seed script (Task 10)

```powershell
cd core
uv run python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>
```

Idempotent. Inserts:
* 9 collections (requisitos / ubicacion / dudas_basicas / catalogo / credito / promociones / garantias / entrega / servicio).
* 4 agent permissions (recepcionista / sales_agent / duda_general / postventa) per design §6.
* 1 safe-answer-settings row with the 6 seeded risky-phrase patterns and the Spanish-MX fallback message.
* 3 source priority rules (faq=100, catalog=80, document=60, agent=NULL).

---

## 2. Environment variables (new)

| Var | Default | Purpose |
|---|---|---|
| `ATENDIA_V2_KB_PROVIDER` | `openai` | `openai` or `mock`. Mock is forced when `OPENAI_API_KEY` is empty. |
| `ATENDIA_V2_OPENAI_API_KEY` | (empty) | Required for production /test-query. Empty in dev → MockProvider auto-fallback. |
| `ATENDIA_V2_REDIS_URL` | (existing) | Cooldowns + rate limits. |
| `ATENDIA_V2_DATABASE_URL` | (existing) | Postgres + pgvector + halfvec. |

---

## 3. Deploy steps

```powershell
# 1. Apply migrations 031-036
cd core
uv run alembic upgrade head

# 2. Restart API
# (your platform's restart command)

# 3. Seed defaults per tenant
uv run python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>

# 4. Smoke check (see §5 below)
```

> ⚠️ Worker cron registrations (compute_health_snapshot daily, expire_content hourly) **are not yet wired** — the worker jobs themselves don't exist. No new cron behavior is registered with this deploy.

---

## 4. Rollback steps

```powershell
cd core
# Roll back any/all of the 6 KB migrations. Each downgrade is reverse-clean.
uv run alembic downgrade <previous-head>
```

| Migration | Rollback impact |
|---|---|
| 031 | Drops `kb_collections`. FAQ/Catalog/Doc lose `collection_id` (set NULL). |
| 032 | Strips shared metadata + catalog/document/chunk extras. **Text columns preserved.** Existing `'indexed'` documents are NOT auto-migrated back. |
| 033 | Drops `kb_versions` — version history lost. |
| 034 | Drops `kb_conflicts` + `kb_unanswered_questions`. |
| 035 | Drops `kb_test_cases` + `kb_test_runs`. |
| 036 | Drops health snapshots + agent perms + priority rules + safe-answer settings — runtime falls back to hardcoded defaults in the retriever's `load_*` helpers. |

Forward-only after 24h on prod (per design doc §9).

---

## 5. Manual smoke checklist (backend-only, the FE doesn't exist yet)

```powershell
# Pre-req: app running on :8001, dev tenant id known.
$tid = "<tenant-uuid>"

# 1. Seed
cd core
uv run python -m atendia.scripts.seed_knowledge_defaults $tid

# 2. Login as tenant_admin and capture cookie + CSRF token (manual in dev tools or:)
# (use existing /api/v1/auth/login flow)

# 3. Create a sandbox FAQ in the 'requisitos' collection (via existing POST /api/v1/knowledge/faqs).

# 4. /search
curl http://localhost:8001/api/v1/knowledge/search?q=requisitos -H "Cookie: ..." 

# 5. /test-query (mock provider — empty OPENAI_API_KEY)
curl -X POST http://localhost:8001/api/v1/knowledge/test-query \
  -H "Content-Type: application/json" -H "Cookie: ..." -H "X-CSRF-Token: ..." \
  -d '{"query":"¿Cuáles son los requisitos?","agent":"duda_general","minimum_score":0}'

# Expected: 200 with the structured shape — retrieved_chunks, prompt, answer, confidence,
# action, risks, citations, mode='mock'.

# 6. /collections
curl http://localhost:8001/api/v1/knowledge/collections -H "Cookie: ..."
# Expected: 200, 9 default collections (requisitos, ubicacion, ...).
```

**13-item full smoke list from the design doc cannot be executed yet** — items 4-13 require the frontend rebuild + the deferred endpoints.

---

## 6. Live OpenAI test guide

Existing tests run against MockProvider. To run live OpenAI tests:

```powershell
$env:RUN_LIVE_LLM_TESTS = "1"
$env:ATENDIA_V2_OPENAI_API_KEY = "sk-..."
$env:ATENDIA_V2_KB_PROVIDER = "openai"
cd core; uv run pytest -m live -v
```

(No `@pytest.mark.live` tests added in this session — pattern documented for future tests.)

---

## 7. Known issues / 🔴 Deferred features

### Phase 3 endpoints not yet built (44 of 47 deferred)

| Area | Endpoints | Status |
|---|---|---|
| FAQs `publish` / `archive` | 2 | not built |
| Catalog `publish` / `archive` / `import` + import status | 3 | not built |
| Documents `parse` / `chunk` / `embed` / `reindex` / `archive` (per-doc) | 5 | not built |
| Chunks (list / patch / exclude / include / re-embed) | 5 | not built |
| Conflicts (list / detect / patch / resolve) | 4 | not built |
| Unanswered (list / capture / create-faq / ignore / add-test) | 5 | not built |
| Tests (CRUD + run / run-suite + runs) | 8 | not built |
| Versions (list / restore) | 2 | not built |
| Health (snapshot get / per-collection / force-compute) | 3 | not built |
| Analytics (4 endpoints) | 4 | not built |
| Settings (3 sub-areas × 2 verbs) | 6 | not built |

### Worker jobs not yet built (5 of 5 deferred)

* `detect_conflicts_job.py`
* `compute_health_snapshot_job.py` (cron daily)
* `expire_content_job.py` (cron hourly)
* `run_regression_suite_job.py`
* `import_catalog_csv_job.py`

### Frontend not yet built (Phases 4-7 entirely deferred)

The current frontend `KnowledgeBasePage.tsx` (~412 lines, 4 tabs, basic CRUD) **still ships** and continues to work against the existing 16 endpoints from before this session. The 8-tab rebuild + PromptPreviewDrawer + ChunkEditorDrawer + BulkActionsBar + SearchBar + Cmd+K palette + StatsTilesRow + HealthScoreCard + SafeAnswerModeCard + ~35 components + dialogs are all deferred.

### Cuts that are explicitly Próximamente / 🔴 Deferred per design §11

These are still cuts even after the deferred work above lands:

| Feature | Where the stub lives |
|---|---|
| Knowledge Map (visual graph) | MetricsTab placeholder (when built) |
| Importer Inteligente auto-detect | manual file-type picker |
| Chunk split/merge | view + exclude + re-embed only |
| Synonyms tab | sidebar item not added |
| Plantillas tab | sidebar item not added |
| Multi-language toggle | language column stored, ES-MX assumed |
| Multi-step approval queue | `tenant_admin` is enough |
| Before/after comparator | timeline list + restore only |
| Per-collection Health Score | `per_collection_scores={}` |
| Risky-phrase LLM rewrites | regex flagging only (TODO marker in code) |
| Stats tiles "Editor de chunks" / "Analítica RAG" | omitted |
| Sidebar AppShell redesign | nav unchanged |
| Right-click context menu | not built |

### Cannot fit one session — operator's "100% finished" criteria

| Criterion | Why not | Mitigation |
|---|---|---|
| Real operator sign-off in writing | Requires operator action | this checklist is mechanical |
| Real OpenAI E2E certification | Depends on operator's account | live tests gated by `RUN_LIVE_LLM_TESTS=1` |
| Real Meta E2E | KB isn't a Meta surface | N/A |
| Adversarial-loopholes-fully-closed | Separate review session | known-issues list above |
| Side-by-side vs v1 visual diff | v1 has no Knowledge page | screenshots-vs-mockup TBD when FE lands |

---

## 8. Troubleshooting

* **`/test-query` returns `mode=sources_only`** — provider Was None, i.e. no `OPENAI_API_KEY` AND `KB_PROVIDER` is openai. Either set the key or switch `KB_PROVIDER=mock` to get a templated mock answer.
* **`/search` returns no results** — check the agent's `allowed_collection_slugs` and `allowed_source_types` in `kb_agent_permissions`. The retriever falls back to permissive when no `kb_agent_permissions` row exists for the agent (`load_agent_permissions` defaults all sources allowed, no collection restriction).
* **Migrations 030 + concurrent index** — if `pg_indexes` doesn't show `uq_messages_tenant_channel_message_id` after migration 030, manually re-run the SQL from the migration's `autocommit_block` (one-time DB-state thing; the migration itself is correct under roundtrip).

---

## 9. Verification snapshot at handoff (2026-05-10)

```
Backend tests: 798 passed, 0 failed, 16 skipped (excludes integration/e2e suites).
Migrations applied + roundtrip-clean: 031, 032, 033, 034, 035, 036.
New test files added this session:
  tests/db/test_migration_031.py through test_migration_036.py
  tests/db/test_kb_models.py
  tests/scripts/test_seed_knowledge_defaults.py
  tests/tools/test_rag_provider.py
  tests/tools/test_rag_conflict_detector.py
  tests/tools/test_rag_risky_phrase_detector.py
  tests/tools/test_rag_retriever.py
  tests/tools/test_rag_prompt_builder.py
  tests/tools/test_rag_answer_synthesizer.py
  tests/api/test_kb_test_query.py
```

# Moto-Crédito E2E Validation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate the real Dínamo moto-credit use case end-to-end across the 5 subsystems (Agente IA, KB, Pipelines, Conversaciones, Workflows) plus the msg→process→send flow order, by driving the product through the frontend's own REST endpoints + real-browser verification + the merged sandbox harness, producing a grounded scorecard (score/bugs/how-to-improve/vs Respond.io).

**Architecture:** Híbrido. Config goes in via the exact REST endpoints the SPA calls (so it's "frontend data entry", not raw SQL). Behavior is exercised with the merged `atendia.sandbox` harness (real LLM, zero side-effects, rolled back) and the product's own `POST /agents/{id}/preview-response`. The Conversaciones visual proof uses one controlled committed run in an isolated fresh tenant, then cleans up. All against the live stack served from the **main checkout**, branch `claude/moto-credito-e2e-validation`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / asyncpg (dev DB Postgres :5433), Vite+React SPA (:5173), backend (:8001), Redis (:6380), `uv`, OpenAI gpt-4o-mini + gpt-4o. Reuse `core/atendia/sandbox/harness.py` (`run_sandbox_conversation`, `estimate_cost`, `CostCapExceeded`).

**Working contract (ESTADO-Y-GAPS §11):** evidence before claims; declare any scope cut; report bugs with repro; no green emojis unsold; cumulative API cost reported, never exceed $1.53.

**Evidence convention:** every task appends a dated section to `docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md` (created in Task 0) with: what was run, raw evidence (HTTP status/body excerpt, screenshot path, turn_trace ids, stage_transition), PASS/PARTIAL/FAIL, bugs (`file:line` + repro), cumulative `$` spent.

---

### Task 0: Bring up the stack + capture exact API contracts + create FINDINGS doc

**Files:**
- Create: `docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md`
- Read only: backend `core/atendia/api/{auth_routes,agents_routes,tenants_routes,knowledge_routes,workflows_routes}.py`

**Step 1:** Verify stack health. Run:
`curl -s -o NUL -w "%{http_code}" http://localhost:8001/openapi.json` → expect `200`. If not 200, bring stack up: `powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1` (from main checkout) and re-check. Frontend: `curl -s -o NUL -w "%{http_code}" http://localhost:5173` → expect `200`; if not, `cd frontend && npm run dev` (background) and re-check.

**Step 2:** Dump the API surface for the endpoints this plan uses. Run:
`curl -s http://localhost:8001/openapi.json > C:/tmp/openapi.json` then extract the request schemas for `POST /api/v1/auth/login`, `POST /api/v1/agents`, `PATCH /api/v1/agents/{id}/config`, `POST /api/v1/agents/{id}/preview-response`, `GET/PUT /api/v1/tenants/pipeline`, KB ingest+search under `/api/v1/kb`, `POST /api/v1/workflows` + `/nodes` + `/publish`. Record the exact field names + required fields into FINDINGS (these are the source of truth for payloads in later tasks; do NOT guess).

**Step 3:** Confirm the isolated tenant. `POST /api/v1/auth/login` with `{"email":"dele.zored@hotmail.com","password":"dinamo123"}` → expect HTTP 200 + `csrf_token` + `user.tenant_id`. Record `tenant_id`. If 401, re-seed per memory `db_verification_env.md` (`scripts/seed_zored_user.py` against host 5433 / db `atendia_v2`) and retry.

**Step 4:** Create the FINDINGS doc with a header (date, tenant_id, branch, "$0.00 spent so far") and a section per Task 0-7.

**Step 5: Commit**
`git add docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "docs(e2e): findings scaffold + verified stack/API contracts (task 0)"`

**STOP if:** stack won't come up or login keeps failing — report, do not fake later phases.

---

### Task 1: Flow-order review (msg → process → send)

**Files:**
- Read only: `core/atendia/webhooks/meta_routes.py`, `core/atendia/runner/conversation_runner.py`, `core/atendia/runner/flow_router.py`, `core/atendia/runner/outbound_dispatcher.py`, `core/atendia/runner/followup_scheduler.py`
- Append: FINDINGS Task 1

**Step 1:** Trace the ordered pipeline with exact `file:line` for each stage: webhook receipt + signature + dedup → `_persist_inbound` → workflow enqueue → `run_turn` → state load + `bot_paused` short-circuit → cancel followups → load pipeline + agent → Vision/NLU (parallel) → AI extraction merge → `flow_router.pick_flow_mode` → composer → handoff check → outbound dispatch → turn_trace persist → followup schedule. Write the ordered list into FINDINGS.

**Step 2:** Sanity-check the order against one real harness run: write `core/scripts/e2e_flow_probe.py` reusing `run_sandbox_turn` with `_FakeNLUWithCost` + `_RecordingComposer` against a throwaway seeded conversation; print `trace.flow_mode`, `trace.nlu_output`, `trace.composer_output` presence, and assert composer ran after NLU (no exception). Run with `PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/e2e_flow_probe.py` from `core/`.

**Step 3:** Identify and record any logic-order bug or smell (e.g., extraction-before-route vs route-before-extraction mismatch, dual action/mode dispatch noted in §9 D5) with `file:line` + why it matters. Mark Task 1 PASS/PARTIAL.

**Step 4: Commit** `git add core/scripts/e2e_flow_probe.py docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "docs(e2e): msg→send flow order traced + probed (task 1)"`

---

### Task 2: Load Prompt master via Agente IA Manager (frontend API) + browser verify

**Files:**
- Create: `core/scripts/e2e_setup.py` (auth + agent create; extended in later tasks)
- Read only: `docs/Prompt master.txt`, `core/atendia/api/agents_routes.py` (AgentBody schema)
- Append: FINDINGS Task 2

**Step 1:** Write `e2e_setup.py`: a reusable async client that logs in (`POST /auth/login`, keeps session cookie + csrf header) against `http://localhost:8001`. Add `create_agent()` that `POST /api/v1/agents` with: `name="Francisco Esparza (Dínamo)"`, `is_default=true`, `system_prompt` = full contents of `docs/Prompt master.txt`, `tone`/`no_emoji=true`/`language="es"`, and `flow_mode_rules` mapping `#FLOW — ROUTER LOGIC` → deterministic rules (field_missing tipo_credito/plan_credito → PLAN; keyword moto/precio/contado + plan present → SALES; has_attachment → DOC; keywords mañana/ahorita/al rato/luego → OBSTACLE; gracias → RETENTION; always → SUPPORT). Use the EXACT field names captured in Task 0 Step 2.

**Step 2:** Run it: `PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/e2e_setup.py` from `core/`. Expected: HTTP 200/201, returns `agent_id`. Record `agent_id` + raw response in FINDINGS.

**Step 3:** API read-back: `GET /api/v1/agents/{agent_id}` → assert `system_prompt` round-tripped intact and `flow_mode_rules` persisted. Record.

**Step 4:** Browser verify (preview tools): `preview_start` the SPA, login, navigate to Agente IA Manager, `preview_snapshot` showing the agent listed + open it (system_prompt textarea populated, editable = "afinación desde FrontEnd"). `preview_screenshot` → save path in FINDINGS.

**Step 5:** Real behavior sanity: `POST /api/v1/agents/{agent_id}/preview-response` with a PLAN-mode opener ("hola, quiero una moto a crédito"). Assert non-empty Spanish reply consistent with PASO 0 micro-cotización. Record reply + `$` cost; update cumulative.

**Step 6: Commit** `git add core/scripts/e2e_setup.py docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "feat(e2e): Prompt master loaded via /agents + browser+preview verified (task 2)"`

**STOP if:** `POST /agents` rejects the payload after 2 schema-corrected attempts — record the schema mismatch as a bug and ask.

---

### Task 3: Knowledge Base ingestion (real JSON) + retrieval + agent scoping

**Files:**
- Modify: `core/scripts/e2e_setup.py` (add `ingest_kb()`)
- Read only: `core/atendia/api/knowledge_routes.py`, `docs/{CATALOGO_MODELOS,FAQ_CREDITO,REQUISITOS_PLANES}.json`
- Append: FINDINGS Task 3

**Step 1:** Inspect the 3 JSON shapes (`head` each) and the KB ingest endpoint contract from Task 0. Add `ingest_kb()` to `e2e_setup.py` that creates collections (`catalogo_dinamo`, `FAQ`, `requisitos`) and POSTs the records via the frontend KB endpoints (catalog items / FAQs / documents as appropriate to each file).

**Step 2:** Run it. Expected: HTTP 200 per batch + non-zero counts. Record counts.

**Step 3:** Retrieval check: `POST /api/v1/kb/search` (or `/kb/test`) for a query that must hit (e.g., a model name from `CATALOGO_MODELOS.json`, a question from `FAQ_CREDITO.json`). Assert ≥1 relevant result. Record query+hit. If embeddings async-pending, note it and use the ILIKE `/simulate` path; record which path answered.

**Step 4:** Scope the agent: `PATCH /api/v1/agents/{agent_id}/config` setting `knowledge_config.collection_ids` to the new collections. Read back, assert persisted.

**Step 5:** Browser verify: KB page shows the 3 collections with counts. `preview_screenshot`.

**Step 6: Commit** `git add core/scripts/e2e_setup.py docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "feat(e2e): KB ingested from real JSON + retrieval+scoping verified (task 3)"`

---

### Task 4: Pipeline (text-field move + document move) proven via harness

**Files:**
- Modify: `core/scripts/e2e_setup.py` (add `put_pipeline()`)
- Create: `core/scripts/e2e_pipeline_proof.py`
- Read only: `core/atendia/api/tenants_routes.py`, `core/atendia/runner/flow_router.py`, `core/atendia/contracts/pipeline_definition.py`
- Append: FINDINGS Task 4

**Step 1:** Add `put_pipeline()`: `PUT /api/v1/tenants/pipeline` with a definition mirroring the Prompt master — stages with `actions_allowed` + `flow_mode_rules`, including (a) a **text-field** transition (capture `tipo_credito`/`plan_credito` → PLAN→SALES) and (b) a **document** transition (`docs_complete_for_plan` on INE+comprobante → DOC stage → complete). Use exact pipeline schema from Task 0.

**Step 2:** Run `put_pipeline()`; `GET /tenants/pipeline` read-back asserts active version. Record.

**Step 3:** Write `e2e_pipeline_proof.py` using `run_sandbox_conversation` (real `OpenAINLU`+`OpenAIComposer`, `cost_cap_usd=Decimal("0.40")`) against a freshly seeded conversation in the isolated tenant: **script A (text-field)** drives the plan-assignment dialogue until `tipo_credito`/`plan_credito` are extracted; assert a `turn_trace.stage_transition` reflecting PLAN→SALES (or the configured move). **script B (document)** simulates INE+comprobante arrival (attachment-style turn) and asserts the document-driven `stage_transition`. Print per-turn `flow_mode`, `stage_transition`, cost; assert zero side-effects (before/after row counts).

**Step 4:** Run it (`PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/e2e_pipeline_proof.py`). Record both transitions (or honest PARTIAL/FAIL + bug repro). Update cumulative `$`.

**Step 5: Commit** `git add core/scripts/e2e_setup.py core/scripts/e2e_pipeline_proof.py docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "feat(e2e): pipeline text+document moves proven via harness (task 4)"`

**STOP if:** a stage move can't be produced after debugging — invoke superpowers:systematic-debugging, record root cause, mark FAIL, continue to next task (don't fake it).

---

### Task 5: Conversaciones — controlled committed run + browser verify + cleanup

**Files:**
- Create: `core/scripts/e2e_conv_commit.py`
- Append: FINDINGS Task 5

**Step 1:** Write `e2e_conv_commit.py`: seed a conversation in the isolated tenant, run the moto-credit script through the REAL runner **committing** (not the rollback harness) so it surfaces in the UI — reuse `ConversationRunner` directly with a committing session, real providers, `cost_cap` guard. Capture conversation_id.

**Step 2:** Run it. Record conversation_id, turn_trace ids, final stage, `$` cost. Update cumulative.

**Step 3:** Browser verify (preview tools): open Conversaciones, find the conversation, `preview_snapshot` + `preview_screenshot` of: message thread (inbound/outbound), current stage, DebugPanel (open it; Resumen + NLU + composer), and exercise one tuning action from the UI (e.g., human takeover/intervention or edit a contact field) to prove "se afina desde FrontEnd / aplica a todo lo que hay ahí".

**Step 4:** Cleanup: `DELETE FROM ...` only the rows created by this task's committed run (scoped to the seeded conversation/customer), keeping the agent/KB/pipeline/workflow config for later tasks. Verify deletion.

**Step 5: Commit** `git add core/scripts/e2e_conv_commit.py docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "feat(e2e): Conversaciones verified in real UI + cleaned up (task 5)"`

---

### Task 6: Workflows — create via API, trigger via real event, verify execution

**Files:**
- Modify: `core/scripts/e2e_setup.py` (add `create_workflow()`)
- Create: `core/scripts/e2e_workflow_proof.py`
- Read only: `core/atendia/api/workflows_routes.py`, `core/atendia/workflows/engine.py`
- Append: FINDINGS Task 6

**Step 1:** Add `create_workflow()`: `POST /api/v1/workflows` + `/nodes` + `/publish` for a workflow mirroring `#HANDOFF ESTRUCTURADO`: trigger `stage_entered` = "Papelería completa" → node `assign_agent` (Francisco) + node `message`/internal-note with the structured summary. Exact schema from Task 0.

**Step 2:** Run it; read back the published workflow. Record workflow_id + node ids.

**Step 3:** Write `e2e_workflow_proof.py`: drive a committed conversation (isolated tenant) into the "Papelería completa" stage so the `stage_entered` trigger fires the workflow; poll `workflow_executions` for a row with status + replay log for this conversation. Assert execution exists and replay shows the assign/message nodes.

**Step 4:** Run it. Record execution row + replay excerpt (or honest FAIL + repro). Cleanup the committed conversation rows. Update cumulative `$`.

**Step 5:** Browser verify: Workflows page shows the workflow + an execution in history. `preview_screenshot`.

**Step 6: Commit** `git add core/scripts/e2e_setup.py core/scripts/e2e_workflow_proof.py docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "feat(e2e): workflow created+triggered+executed verified (task 6)"`

---

### Task 7: Scorecard + Respond.io comparison + premium recommendation

**Files:**
- Read only: `docs/ESTADO-Y-GAPS.md` (§1 parity table, §8 differentiators), `docs/_archive/plans/2026-05-14-respond-io-style-maturity-audit.md`, all FINDINGS sections
- Append: FINDINGS Task 7 (the scorecard)

**Step 1:** Invoke superpowers:verification-before-completion. Re-read every FINDINGS section; confirm each claim has attached evidence (HTTP/screenshot/trace). Anything unproven → mark PARTIAL/FAIL, do not score on faith.

**Step 2:** For each of the 6 areas (Flujo msg→send, Agente IA, KB, Pipelines, Conversaciones, Workflows) write: **score 0-10** (with the evidence that justifies it), **bugs found** (`file:line` + repro), **cómo mejorar** (concrete, prioritized), **vs Respond.io** (mejor / igual / detrás — anchored to ESTADO-Y-GAPS §1/§8 + the maturity audit + live findings).

**Step 3:** Write the closing **premium-SaaS recommendation** (the single highest-leverage next move for product-market fit) + total `$` spent vs $1.53 budget + explicit list of any scope cut.

**Step 4: Commit** `git add docs/plans/2026-05-15-moto-credito-e2e-validation-FINDINGS.md && git commit -m "docs(e2e): scorecard + Respond.io comparison + recommendation (task 7)"`

**Step 5:** Invoke superpowers:finishing-a-development-branch (verify, present merge options, execute choice).

---

## Out of scope (explicit)

- General / multi-niche scenario (next session).
- Fixing discovered bugs (reported with repro; each fix is its own piece unless an agreed quick-win).
- Multi-channel, broadcasts, WhatsApp templates >24h (deferred by contract).
- Any run that would exceed the $1.53 cumulative API budget — stop and report instead.

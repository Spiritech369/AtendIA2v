# Moto-Crédito E2E Validation — FINDINGS

> Evidence log for `docs/plans/2026-05-15-moto-credito-e2e-validation.md`.
> Contract (ESTADO-Y-GAPS §11): evidence before claims; declare scope cuts;
> report bugs with repro; no green emojis unsold.

**Run metadata**
- Date: 2026-05-15
- Branch: `claude/moto-credito-e2e-validation` (main checkout)
- Isolated tenant: `dele.zored@hotmail.com` → `tenant_id = 867a1047-6aea-4b21-85d8-898aef0051cb` ("Zored QA Workspace" — verified empty in prior recon: 0 agents/catalog/faqs/conversations → ideal isolated target)
- **Validation API budget: $1.53. Cumulative spent (this plan): $0.00 after Task 0; $0.00 after Task 1 ($0 fake-provider probe); $0.00 after Task 2** (Task 2's single budgeted preview-response LLM call was never reached — blocked at the first HTTP `login()` call by a hung backend; zero LLM tokens consumed).
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

## Task 1 — Flow order (msg→process→send) — ✅ PASS

**Method:** read-only trace of the 5 pipeline files, then a $0 probe that runs
the REAL `ConversationRunner` once via the sandbox harness with fake providers
(zero side-effects — session rolled back) to empirically confirm ordering.

### Ordered `file:line` trace (verified against the code on this branch)

Webhook ingress — `core/atendia/webhooks/meta_routes.py`:
1. **Webhook receipt** — `POST /webhooks/meta/{tenant_id}` handler `receive_inbound` at `meta_routes.py:137-142`; raw body read `:143`.
2. **Signature verify** — `adapter.validate_signature(body, signature)` → 403 on fail, `meta_routes.py:153-154`. (Runs *before* JSON parse `:156-159`.)
3. **Tenant cfg load + phone-number-id ownership guard** — `load_meta_config` `:162`; `phone_ids != {cfg.phone_number_id}` → 403 `:168-173`.
4. **Parse webhook + resolve attachment URLs** — `parse_webhook` `:175`, `parse_status_callback` `:176`, `_resolve_attachment_urls` (Meta Graph media fetch, best-effort) `:181`.
5. **`_persist_inbound` per message** — loop `:196-202`; function `:229`. Inside it, in order: upsert customer `:231-240` → find/create conversation (soft-deleted excluded) `:244-266` → **dedup-aware inbound INSERT** `ON CONFLICT (tenant_id, channel_message_id) DO NOTHING` `:272-294` (returns `None` ⇒ duplicate ⇒ skipped `:293-294`) → bump `unread_count` `:297-300` → emit `MESSAGE_RECEIVED` event `:307-315` → **inline workflow `evaluate_event`** (flushes execution rows in-txn) `:323` → Pub/Sub `publish_event` `:330`.
6. **`ConversationRunner.run_turn` invoked synchronously inside the webhook txn** — built `:376`, called `:405-412` (wrapped in try/except → `ERROR_OCCURRED` event on failure `:414-424`, webhook never 500s). `arq_pool` + `to_phone_e164=m.from_phone_e164` are passed here `:410-411` (this is the real path that DOES stage outbound).
7. **`session.commit()`** `meta_routes.py:205`, then **`mark_processed` (redis dedup marker)** `:206-207`.
8. **Workflow enqueue to arq** — `enqueue_executions_to_workflows_queue` `:211-220` (AFTER commit, so the worker never sees an unpersisted execution id).

Note ordering smell **#1** (sequencing): step 5's dedup INSERT and step 6's runner all run *before* the single `session.commit()` at `:205`; redis `mark_processed` (`:207`) happens only after commit. The DB-level `ON CONFLICT` (`:279-281`) is the real idempotency guard; the redis marker is secondary. There is no signature/dedup *short-circuit before* DB work — dedup is enforced by the unique constraint mid-transaction, not up front.

Turn pipeline — `core/atendia/runner/conversation_runner.py` (`run_turn`):
9. **conversation_state load FIRST (single SELECT+JOIN)** `:208-217`; missing ⇒ `RuntimeError` `:218-219`.
10. **`bot_paused` short-circuit** `:240-255` — writes a minimal paused `TurnTrace` and returns *before* NLU/composer/cancel-followups. (Comment `:203-207` documents this was deliberately moved ahead of cancel-followups — Block D H1 fix.)
11. **Cancel pending follow-ups** `:261-264` → `followup_scheduler.cancel_pending_followups` (`followup_scheduler.py:85-110`). Only reached when not paused.
12. **Load pipeline + agent** — `load_active_pipeline` `:266`; `_load_agent` `:267`; customer id resolved once `:274-279`.
13. **pending-confirmation sí/no resolution** `:328-352` (`_maybe_apply_confirmation` `:141-171`) — applied *before* NLU/router.
14. **NLU (+ Vision in parallel only if image+URL+OpenAI)** `:354-409`. NLU task created `:360-366`; if a resolved image attachment and `openai_api_key`: `asyncio.gather(nlu_task, vision_task, return_exceptions=True)` `:384-388` (Vision failure is isolated, NLU failure re-raised `:389-390`); else NLU awaited alone `:408-409`. **Vision is parallel-with-NLU, not sequential.**
15. **Vision→attrs side-effects** `:420-435` (only if `vision_result`).
16. **NLU entities merged into `state_obj` BEFORE `process_turn`** `:462-464`; **AI field-extraction cascade** `apply_ai_extractions` + `FIELD_UPDATED` events `:471-512`.
17. **`process_turn` (FSM → `decision.action` + next stage)** `:514`. Then `auto_enter_rules` evaluation `:574-596`, stage-transition events `:599-647`, stage-entry handoff `:658-676`.
18. **Tone/brand_facts load + Composer-input prep** `:678-744`.
19. **`flow_router.pick_flow_mode`** `:765-772` (`flow_router.py:90-111`) → `flow_mode` `:773`; stage-pinned `behavior_mode` override `:788-800`.
20. **Tool dispatch keyed off `decision.action`** (quote/lookup_faq/search_catalog/ask_field/close) `:811-924`; requirements attach `:936-949`.
21. **24h-window check** `:951-960`.
22. **Handoff / Composer branch** `:962-1026`: if `auto_handoff_triggered` ⇒ skip composer `:972-975`; elif outside-24h & composed action ⇒ persist handoff, no compose `:976-1001`; **elif `decision.action in COMPOSED_ACTIONS` ⇒ `self._composer.compose(...)`** `:1002-1026`. Composer-raised pending-confirmation write-back `:1031-1040`; composer-fallback handoff `:1042-1068`.
23. **`turn_trace` persist** — `TurnTrace(...)` built `:1111-1164` (`flow_mode=flow_mode.value` `:1153`, `outbound_messages=composer_output.messages` `:1154`), `session.add` + `flush` `:1165-1166`.
24. **Outbound dispatch + follow-up scheduling** `:1169-1190` — ONLY when `composer_output is not None and arq_pool is not None and to_phone_e164 is not None`: `enqueue_messages` (`outbound_dispatcher.py:34-59` → stages into `outbound_outbox` via `stage_outbound` when a session is passed) `:1170-1179`, then `schedule_followups_after_outbound` (`followup_scheduler.py:37-82`) `:1185-1190`.
25. **Composer-suggested escalation** (send-then-pause) `:1205-1268`; `return trace` `:1270`.

Ordering smell **#2** (sequencing): `turn_trace` is persisted (`:1165-1166`) **before** the outbound is staged (`:1170`). In the harness/no-`to_phone_e164` path the outbound enqueue is skipped entirely, yet `trace.outbound_messages` is still set from `composer_output.messages` (`:1154`) — so the trace claims an outbound that the real path may or may not stage depending on `to_phone_e164`. Not a correctness bug for the production webhook path (which always passes `to_phone_e164`, `meta_routes.py:411`), but the trace's `outbound_messages` is "what the composer produced", not "what was enqueued".

### Probe — command + actual output

```
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/e2e_flow_probe.py
```
Actual stdout (exit 0):
```
DB: postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2
seeded tenant=f00472b4-cf65-4df5-9061-10df542fb4a4 conversation=1eb6d1e0-9681-4ebb-b087-2d979eaa59e8
---- PROBE EVIDENCE ----
trace.flow_mode          = 'SUPPORT'
nlu_output present       = True
composer_output present  = True
would_be_outbound        = ['hola, con gusto te ayudo']
cost_usd                 = 0.000050
composer messages        = ['hola, con gusto te ayudo']
------------------------
PASS: msg -> NLU -> flow_router -> Composer order confirmed empirically ($0, zero side-effects).
```
`script: core/scripts/e2e_flow_probe.py` — fake providers (`_FakeNLUWithCost`,
`_RecordingComposer`), no real LLM, $0. The harness rolls the session back
(verified zero-side-effects invariant lives in
`core/tests/sandbox/test_harness_no_side_effects.py`). The probe seeds + deletes
a throwaway tenant in a `finally`.

**TDD-spirit honesty:** I mispredicted two things and corrected them after the
first run (kept visible in the script docstring): (a) `flow_mode` is the
*upper-case* enum **value** `"SUPPORT"` (`flow_mode.py:18`, stored as
`flow_mode.value` at `conversation_runner.py:1153`), not lowercase; (b)
`would_be_outbound` is **non-empty** even without `to_phone_e164` because
`SandboxTurnResult.would_be_outbound` reads `trace.outbound_messages`, which is
set from `composer_output.messages` at `conversation_runner.py:1154`
unconditionally — `to_phone_e164` only gates the real `outbound_outbox` stage at
`:1169`. The pipeline *ordering* itself matched the prediction exactly: the turn
returned without exception with `nlu_output` AND `composer_output` populated,
which is only possible if the Composer ran strictly **after** NLU (NLU's intent
feeds `process_turn` → `decision.action`, which gates the Composer branch at
`:1002`).

### Bugs / smells

- **D5 — dual dispatch (CONFIRMED, architectural, pre-existing).** `ESTADO-Y-GAPS.md:444` flags "runner dispatch action-based, composer mode-based". Verified in code: `process_turn` returns `decision.action` (`conversation_runner.py:514`) which drives **tool dispatch** (`:811-924`) and **gates whether the Composer runs at all** (`if decision.action in COMPOSED_ACTIONS`, `:1002`; `COMPOSED_ACTIONS`/`SKIP_ACTIONS` in `outbound_dispatcher.py:16-31`). Independently, `flow_router.pick_flow_mode` (`flow_router.py:90-111`) produces a 6-value `FlowMode` (`flow_mode.py:10-18`) passed to the Composer as `ComposerInput.flow_mode` (`conversation_runner.py:1019`). So **two parallel taxonomies decide composer behavior**: the *action* (8-ish verbs) decides IF/which-tool, the *mode* (6 modes) decides the composer prompt template. They are derived from different inputs (FSM transitions vs. keyword/intent/field rules) and never reconciled — e.g. `decision.action == "ask_field"` can co-occur with `flow_mode == SUPPORT` or `PLAN` with no consistency check. *Why it matters:* a misconfigured pipeline can route to a composed action whose prompt-mode contradicts the intended flow (action says "quote", mode says "SUPPORT"), and there is no invariant or test asserting action↔mode coherence. This is logged as accepted permanent debt (option c) but is a real logic-order smell, not a closed item.
- **Smell #1 (no up-front dedup short-circuit)** — see step 8 note: signature is checked first (good), but dedup relies on a mid-transaction `ON CONFLICT DO NOTHING` (`meta_routes.py:279-294`) rather than an early redis check; the redis `mark_processed` happens *after* commit (`:207`). A Meta retry that arrives before commit is still correctly deduped by the unique constraint, but the runner work in `_persist_inbound` (event emit, `evaluate_event`) is only skipped because the inbound INSERT returns `None` first (`:293-294`) — correctness holds, but it's "dedup by constraint", not "dedup by guard clause".
- **Smell #2 (trace.outbound_messages ≠ enqueued)** — see step 24 note: `turn_trace` persists before outbound staging and records the composed text regardless of whether it was actually enqueued (`conversation_runner.py:1154` vs the `to_phone_e164`-gated enqueue at `:1169`). Audit/debug consumers reading `turn_traces.outbound_messages` see "composer output", not "delivered".

**Status: ✅ PASS** — full ordered trace verified against code with exact
`file:line`; $0 probe confirms msg→NLU→flow_router→Composer empirically and
exits 0. D5 dual-dispatch confirmed real (architectural debt, not introduced
here); two sequencing smells documented honestly. No runtime code modified.

---

## Task 2 — Prompt master via /agents + browser — ⚠️ BLOCKED (infra), code complete

**Goal:** load `docs/Prompt master.txt` (10802 chars, read as bytes→utf-8)
into the product as a real Agent via `POST /api/v1/agents`, read it back
byte-identical, persist operator-realistic `flow_mode_rules`, and do ONE
real-LLM `preview-response` sanity call.

### Deliverable (complete, verified static)

`core/scripts/e2e_setup.py` — reusable `Client` (httpx.Client; the core
venv has **no `requests`**, has `httpx` 0.28.1 — switched accordingly) that
logs in, keeps the session+csrf cookie jar, and injects `X-CSRF-Token` on
every unsafe verb. `create_agent()` POSTs the exact contract; `get_agent()`
+ `preview_response()` for steps 3–4. Runnable as `__main__`.

Static verification (no network) — all PASS:
- `ast.parse` + import + `Client()` construct OK.
- `load_prompt_master()` reads **10802 chars** from `docs/Prompt master.txt`
  (bytes→utf-8, no newline munging, for an exact round-trip compare).
- `AGENT_FLOW_MODE_RULES` = the exact 7-rule dict from the task spec
  (doc_attachment / obstacle_kw / retention_kw / plan_missing_tipo /
  plan_missing_plan / sales_plan_present / fallback_support→always).
- CSRF guard raises if `login()` not called before any POST/PATCH/PUT.

API contract pinned from source (not guessed):
`agents_routes.py:972` `POST ""` → `AgentCreate` (req `['name']`;
`max_sentences` `ge=1,le=5` so `2` valid; `flow_mode_rules: dict|None`;
accepts `system_prompt/language/no_emoji/tone/goal/is_default`).
`:1056` `GET /{id}` → `AgentItem`. `:1332` `POST /{id}/preview-response` →
`PreviewBody` (`message` 1–2000 chars; `conversationContext`/`draftConfig`
aliases). Router mounted `/api/v1/agents` (`main.py:151`).

### Steps 2–4 — NOT EXECUTED: shared backend is hung

Could not run end-to-end. The shared `atendia_backend` (container `running`,
restarts=0, up ~44 min, port `0.0.0.0:8001` mapped) **accepts TCP but never
returns an HTTP response** — every path (`/`, `/openapi.json`,
`/api/v1/health`) `ReadTimeout`s via httpx **and** `curl` (curl exit 28, 0
bytes), so it is not a client/sandbox artifact. `docker logs atendia_backend`
ends at:
```
WARNING:  WatchFiles detected changes in 'scripts/e2e_flow_probe.py'. Reloading...
INFO:     Shutting down
INFO:     Waiting for background tasks to complete. (CTRL+C to force quit)
```
**Root cause:** the dev backend runs uvicorn `--reload` (WatchFiles) and the
container mounts the **main repo `core/`** (per memory `docker_dev_stack_crashloop.md`).
A WatchFiles reload (triggered by churn in `core/scripts/` — Task 1's
`e2e_flow_probe.py`, and this branch is the main checkout so a new
`core/scripts/e2e_setup.py` also lands in the watched tree) hit a uvicorn
**graceful-shutdown that hung on a never-completing background task**, so the
reload never finishes and HTTP never resumes. Sibling `atendia_worker` is
healthy (arq `cron:dispatch_outbox` ticking) → Postgres :5433 / Redis :6380
are fine; only the backend HTTP app is dead. Recovery requires
`docker restart atendia_backend`, which was **explicitly denied** as
out-of-scope shared-infra modification (this task forbids runtime/infra
changes), and a 75 s recovery poll showed no self-recovery (hung shutdown
does not time out here). Not worked around.

- create HTTP status: **N/A — request never issued** (blocked at `login()`,
  the first call, which `ReadTimeout`d).
- system_prompt round-trip: **N/A — not executed.**
- flow_mode_rules persisted: **N/A — not executed.**
- preview-response reply: **N/A — Step 4 never reached.**

### Confirmed bug (pre-found, re-verified on this branch — recorded)

**`agent.flow_mode_rules` is stored + returned by the API but NEVER consumed
by the runner/router; flow routing is pipeline-sourced only.** Verified:
`conversation_runner.py:766` calls `pick_flow_mode(rules=pipeline.flow_mode_rules, …)`
— the *pipeline's* rules; the comment at `conversation_runner.py:749` says
"Tenants without rules in **pipeline.flow_mode_rules** get the default
`always -> SUPPORT` fallback". `grep flow_mode_rules core/atendia` shows the
only `agent.flow_mode_rules` touches are in `agents_routes.py`
(`:658`/`:1157` round-trip it; `:83/:120/:176` schema) and the ORM column
(`db/models/agent.py:44`) — **no runner/router read of
`agent.flow_mode_rules` anywhere**. So setting `flow_mode_rules` on the
agent (as `e2e_setup.py` does, operator-realistically) is **DEAD for
routing**; the real routing rules must live in the pipeline
(`PipelineDefinition.flow_mode_rules`, `contracts/pipeline_definition.py:296`)
— a later task. Operator-misleading: the Agente IA Manager UI/API accepts
and echoes back agent-level flow rules that have zero runtime effect.

### Cost

**$0.00 spent.** The single budgeted `preview-response` LLM call (Step 4)
was never reached — failure occurred at the very first HTTP call
(`login()`). No LLM tokens consumed. Cumulative unchanged.

### Status: ⚠️ PARTIAL / BLOCKED

Code deliverable complete and statically verified against the source-pinned
contract; the **confirmed agent.flow_mode_rules-dead bug is recorded with
fresh `file:line` evidence**. Live steps 2–4 (create / round-trip /
preview) are **unverified** — blocked by a hung shared backend whose only
fix (container restart) is out of scope for this task. Re-run
`e2e_setup.py` once the backend HTTP is restored to obtain the live
evidence; expected HTTP 201 + byte-identical round-trip.

## Task 3 — KB ingestion + retrieval + scoping — pending
## Task 4 — Pipeline text+document moves — pending
## Task 5 — Conversaciones committed + browser — pending
## Task 6 — Workflow create+trigger+execute — pending
## Task 7 — Scorecard + Respond.io + recommendation — pending

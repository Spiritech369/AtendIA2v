# Runbook — Conversations Enhanced

**Status (2026-05-08):** backend hardened in sessions 1–4, real OpenAI E2E
verified for `force_summary`, multiselect field-type regression closed,
`assigned_agent_name` wired into the list/detail responses. Frontend
browser screenshots vs v1 still pending operator sign-off.

This runbook is the deploy + operate guide for the Conversations area
(list, detail, sidebar/ContactPanel, force-summary). It does NOT cover
workflows or knowledge base — see their own runbooks.

---

## 1. Required environment variables

Set these in `core/.env` (loaded via `pydantic_settings`, prefix `ATENDIA_V2_`).
Never commit secrets.

| Variable | Purpose | Required for |
|---|---|---|
| `ATENDIA_V2_DATABASE_URL` | `postgresql+asyncpg://...` | All paths. |
| `ATENDIA_V2_REDIS_URL` | Redis URL (e.g. `redis://localhost:6380/1`) | arq enqueue + Pub/Sub realtime fan-out + KB rate limits. |
| `ATENDIA_V2_OPENAI_API_KEY` | OpenAI key | `force_summary` LLM mode. Without it the job persists a transcript-mode note clearly labeled `Transcripcion (sin LLM disponible)`. |
| `ATENDIA_V2_META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_API_VERSION`, `META_BASE_URL` | WhatsApp Cloud API | Inbound webhook signature + outbound send. |
| `ATENDIA_V2_AUTH_SESSION_SECRET` | HS256 JWT secret | Operator login (Phase 4). **Must override the dev fallback in production.** |
| `ATENDIA_V2_AUTH_COOKIE_SECURE` | `true` in prod | Required when serving over TLS. |

---

## 2. Worker processes you must run

Conversations Enhanced uses these arq worker classes. **Each is a separate
process** — they listen on different queues and have different concurrency
profiles.

| Process | Command | Queue | Jobs handled |
|---|---|---|---|
| Default worker | `uv run arq atendia.queue.worker.WorkerSettings` | `arq:queue` (default) | `send_outbound`, `index_document`, `force_summary` + `poll_followups` cron. |
| Workflows worker | `uv run arq atendia.queue.worker.WorkflowWorkerSettings` | `arq:queue:workflows` | `execute_workflow_step` + `poll_workflow_triggers` cron. |

**If you only run the default worker**, workflow executions enqueue to
Redis and never get consumed — operators see workflows that fire (audit
log shows the trigger) but the actions never execute. Add monitoring on
the `workflows` queue depth.

`force_summary` runs on the default worker. The arq job is enqueued from
`POST /api/v1/conversations/{id}/force-summary` with `_job_id =
"force_summary:{conversation_id}"` so duplicate clicks dedupe in Redis.
The job itself is also idempotent in the DB via the `high_water:` marker
inside the note body.

---

## 3. Cost model for `force_summary`

The job calls `gpt-4o-mini` with a hard cap of `max_tokens=400` and
`SUMMARY_TIMEOUT_SECONDS=20`. Input is the last 40 messages, capped at 16k
characters. With current OpenAI pricing this is **~$0.0001–0.0005 per
summary** depending on conversation length. No per-tenant rate limit
exists yet for force-summary specifically — operators can spam clicks but
arq's `_job_id` dedupe + the `high_water` idempotency marker mean only the
first job actually runs against the same message set.

If `OPENAI_API_KEY` is not set or the OpenAI call fails, the note is
persisted in transcript-mode with the header `"Transcripcion (sin LLM
disponible)"` so an operator viewing it can tell it isn't an AI summary.

---

## 4. Operator workflows the UI supports today

Sessions 1–4 closed these:

- **Inbox triage**: ConversationList has tabs (Todos / Míos / Sin asignar /
  Handoffs / Pausados), search persisted via `localStorage`, right-click
  context menu (assign, pause/resume bot, delete soft), per-row badges
  (current_stage, agent name, handoff, paused, tags).
- **Per-conversation sidebar**: ContactPanel has basic info edit, pipeline
  stage selector, document checklist (driven by `pipeline.docs_per_plan[
  extracted_data.plan_credito]`), custom fields (text/select/checkbox/
  number/date/multiselect — multiselect added in s4), notes (create/edit/
  delete/pin), force-summary button.
- **Multi-user unread**: per-user `conversation_reads` table keeps unread
  count separate per operator. Added in P0 hardening.
- **Audit trail**: workflow CRUD + KB CRUD + force-summary trigger all
  emit events to the `events` table, surfaced via
  `GET /api/v1/audit-log?type=admin.*`.

What is **NOT** in the UI today (operator must use API or accept the gap):

- Email field on the customer (schema doesn't have a `customers.email`
  column; v1 had it inline in the basic-info form). Adding it requires a
  migration.
- WhatsApp 24h-window banner per conversation (the bot still won't reply
  outside-24h until Phase 3d.2 templates exist; the workflow `message`
  action fails loudly with `OUTSIDE_24H_WINDOW` but there's no UI badge
  warning the operator on the chat itself).
- Origin / source attribution on the conversation row (v1 read from
  `customer_metadata.origin / origin_label / source / utm_source / referrer`;
  v2 doesn't store any of these).

---

## 5. Failure modes + recovery

### `force_summary` failed

- **Symptom**: `POST /force-summary` returned 202 but no note appears.
- **Diagnose**: check `events` table for `error_occurred` events, or look
  at the worker stdout. Most common cause is `OPENAI_API_KEY` unset — in
  that case the job actually *succeeds* with mode=transcript, so the note
  IS there, just labeled differently.
- **Fix**: re-enqueue by clicking "Resumen" again (idempotent against the
  same most-recent message; if a new inbound arrived since, a fresh
  summary is generated).

### Operator sees stale state after assigning a conversation

- **Symptom**: assignment saved (200 response) but list still shows old
  assignee.
- **Diagnose**: TanStack Query stale time. The list query invalidates on
  patch success, but there's no SSE event for assignment changes — the
  realtime fan-out covers `message_received`/`message_sent` only.
- **Fix**: refresh the page. **Open loophole** (P3): wire assignment
  changes into Pub/Sub.

### Worker "stuck" — outbound messages not sending

- Run `redis-cli LLEN arq:queue` (default queue) and `LLEN
  arq:queue:workflows` (workflow queue). If non-zero and growing, no
  consumer is attached to that queue.
- Verify both worker processes are running. Restart with the commands in
  section 2.

### Multi-user unread shows wrong count

- **Symptom**: operator A marks read, operator B's count doesn't drop.
- **By design**: unread is per-user. Each operator has independent state.
  Verify via `SELECT * FROM conversation_reads WHERE conversation_id = ?`
  — there should be one row per `(conversation_id, user_id)` that has
  ever opened the detail view.

---

## 6. Migrations relevant to Conversations

Run `uv run alembic upgrade head` to apply all. Key revisions:

| Rev | What it adds |
|---|---|
| 024 | Conversation scope-gap columns (tags, unread, assignment) |
| 025 | P0 hardening: `conversation_reads` + indexes |
| 026 | v1 parity roadmap base (agents, notifications, knowledge_documents, etc.) |
| 027 | Workflow safety (steps_completed, source_workflow_execution_id, error_code) |
| 028 | `workflows.version`, `events.conversation_id` nullable, `events.actor_user_id` |

`alembic downgrade -1` is supported on every revision in this list.

---

## 7. Loopholes still open in Conversations Enhanced

Documented for explicit acceptance or future closure. Each carries an
estimated effort.

| # | Loophole | Status (sesión 5) |
|---|---|---|
| C-1 | `customers.email` column missing | **CLOSED** — migration 029 adds the column, ContactPanel `BasicInfoSection` now shows + edits email. |
| C-2 | No outside-24h banner in the chat header | **CLOSED** — `ConversationDetail` reads `last_inbound_at` from the detail response and renders an amber banner when the inbound is older than 24h. |
| C-3 | Assignment changes not realtime | **CLOSED** — `patch_conversation` publishes a `conversation_updated` Pub/Sub event after commit; the existing WS subscriber forwards it to operator tabs. |
| C-4 | No origin attribution column | **DEFERRED — user-accepted (sesión 5)**. Cost: migration + ingestion changes. Reopen when marketing asks. |
| C-5 | `force_summary` has no per-tenant rate limit | **CLOSED** — Redis token bucket at 30/min/tenant via `_check_force_summary_rate_limit`; returns 429 once tripped. |
| C-6 | DebugPanel parity vs v1 not audited line-by-line | **DEFERRED — user-accepted (sesión 5)**. v2 is at 369 lines vs v1's 497 (~74%). Reopen when an operator complains about a missing field. |
| C-7 | No per-message debug click (v1 lets operator click any message → DebugPanel jumps to that turn's trace) | **PARTIALLY DONE** — v2 already wires `messageToTrace` + `onDebug` callback in `ConversationDetail.tsx`, so click-to-debug works for messages whose turn-trace ID is known. UX polish (highlighting current message, scroll-to-trace) is the remaining gap. **DEFERRED — user-accepted (sesión 5)**. |

---

## 8. Browser verification checklist (the operator's job)

Backend tests cannot prove the UI looks right. Open
`http://localhost:5173` (or your deploy URL), log in as a tenant_admin,
and verify each item by clicking. **Mark each ✓ or ✗ in the checklist
before declaring "done."**

- [ ] Conversation list shows status dot, name/phone, unread badge,
  current stage, agent name (if assigned), handoff badge, paused badge,
  up to 2 tags + overflow count.
- [ ] Right-click on a conversation row opens context menu with Assign /
  Pause / Resume / Delete.
- [ ] ContactPanel shows: edit name, phone (read-only), pipeline stage
  selector, document checklist (filled if `extracted_data.plan_credito`
  is set on a conversation_state row).
- [ ] Custom fields render correctly for each type: text, select,
  checkbox, number, date, **multiselect** (regression closed in s4 —
  must verify here).
- [ ] "Forzar resumen" button enqueues a job; after ~2-5 seconds (LLM
  call) a new internal note appears titled either "Resumen AI" (key set)
  or "Transcripcion (sin LLM disponible)".
- [ ] Notes can be created, edited, deleted, pinned/unpinned.
- [ ] Audit log (`/audit-log`) shows entries with `admin.*` types when an
  admin creates/patches/deletes a workflow or KB document.

When all boxes are checked, sign off in `docs/handoffs/sign-offs/conversations-enhanced.md`
with date + your initials.

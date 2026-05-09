# Adversarial Strategy Review — v2 Implementation State
**Date:** 2026-05-08
**Scope:** Full adversarial critique of the current plan and execution state. Produces a prioritized fix list.
**Status:** Awaiting user approval of Fix Priority List before implementation begins.

---

## Overall Scores

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Plan document quality | 7.5 / 10 | Strong gating model, honest self-review, clear module specs — but execution already violated the plan's own rules |
| Current execution state | 4.5 / 10 | 26 files live on disk but untracked; `force_summary` does not call an LLM; cron runs a full-table scan every 10s |
| Security posture | 6 / 10 | P0 RBAC and validation solid; agent assignment has no validated endpoint; KB quota unguarded |
| Reliability | 5 / 10 | Shared arq queue with no priority; workflow cursor has timestamp-collision edge case; `_persist_outbound` is non-deterministic for multi-conversation customers |

---

## Simulation Results

| Simulation | Outcome | Verdict |
|------------|---------|---------|
| Fresh git clone → `uv run fastapi dev` | 26+ route/model/job/storage/workflow files are untracked. App cannot boot from a clean clone or any CI pipeline. | ❌ FAIL |
| Operator clicks "Forzar resumen" | Returns a note titled "Resumen AI" containing raw concatenated message text. `force_summary` never calls gpt-4o-mini. | ❌ FAIL |
| Dashboard "Sin responder" metric, 2 operators | Uses `unread_count > 0` (global column). P0 added per-user `conversation_reads` but the dashboard ignores it. Metrics are wrong for multi-operator tenants. | ❌ FAIL |
| Tenant uploads 50 PDFs | 50 `index_document` arq jobs queued in the shared pool (`max_jobs=10`). Live `send_outbound` jobs wait behind batch jobs. WhatsApp sends stall. | ❌ FAIL |
| Operator assigns agent to conversation | Agent CRUD works. `PATCH /conversations/{id}` has no `assigned_agent_id` field → 422. Runner (C2) not shipped → even if the field were accepted, nothing changes in bot behavior. Two broken links in the path. | ❌ FAIL |
| `poll_workflow_triggers` at 10k events | `SELECT DISTINCT tenant_id FROM events` — full sequential scan on every 10-second tick. No index on this pattern. Response time grows linearly with event history. | ❌ FAIL (perf) |
| Workflow `message_received` → workflow sends message | Outbound message becomes an event. If the engine does not filter by direction, the workflow re-triggers on its own output. Loop until max-step guard fires. | ⚠️ RISK |
| Customer has 3 simultaneous conversations, workflow sends outbound | `_persist_outbound` picks conversation via `ORDER BY last_activity_at DESC LIMIT 1`. Tied timestamps → non-deterministic. Message attached to wrong conversation. | ⚠️ RISK |
| Rollback workflows migration | Migration 026 is a mega-migration: dropping it removes appointments, knowledge, agents, notifications, and workflows in one shot. Unrelated features share a rollback unit. | ⚠️ RISK |

---

## Hidden Assumptions Found (Round 3 — beyond the plan's own list)

| # | Assumption | Why it is unsafe | Severity |
|---|------------|-----------------|----------|
| 1 | "`force_summary` calls the LLM" | Job concatenates raw messages and labels the note "Resumen AI". No OpenAI call. | **CRITICAL** |
| 2 | "Untracked files are deployed code" | 26+ files exist only on local disk. Any CI pipeline that clones HEAD fails to import them. | **CRITICAL** |
| 3 | "`poll_workflow_triggers` is efficient" | Full sequential scan on the events table every 10 seconds. Gets worse as events accumulate. | **HIGH** |
| 4 | "Dashboard unread is per-user" | `unanswered_conversations` reads the global `unread_count` column. The per-user reads table from P0 is unused here. | **HIGH** |
| 5 | "Agent assignment has an end-to-end write path" | `PATCH /conversations/{id}` rejects `assigned_agent_id`. Runner ignores it (C2 unshipped). Two broken links. | **HIGH** |
| 6 | "`_persist_outbound` finds the right conversation" | `ORDER BY last_activity_at DESC LIMIT 1` is non-deterministic for tied timestamps. Workflow messages can attach to the wrong conversation. | **HIGH** |
| 7 | "Migration 026 is per-module" | All 7 future schemas live in one migration. Rollback couples unrelated features. | **MEDIUM** |
| 8 | "Embedding costs are bounded" | No per-tenant quota for KB indexing. 1,000 pages of PDFs → $5-50 in OpenAI embedding costs with no guard. | **MEDIUM** |
| 9 | "arq handles real-time and batch equally" | `max_jobs=10` shared: `send_outbound` (latency-sensitive) competes with `index_document` (CPU+network) and `poll_workflow_triggers` (every 10s). | **MEDIUM** |
| 10 | "Workflow triggers only fire on inbound events" | `message_received` fires on all message events. A workflow sending a message can re-trigger itself if the engine does not filter by direction or execution source. | **MEDIUM** |
| 11 | "CSV export is injection-safe" | The existing `exports_routes.py` predates the formula-injection fix. Cells starting with `=`, `+`, `-`, `@` are not yet escaped. | **MEDIUM** |
| 12 | "Operators understand agent assignment is in preview" | The agents UI will let operators assign agents. Runner C2 is unshipped. Bot behavior will not change. No UI warning exists. | **MEDIUM** |
| 13 | "Catalog search is deterministic" | `search_catalog limit=1` picks `[0]` non-deterministically when an alias matches multiple SKUs. Still unresolved since Phase 3c.1. | **LOW** |
| 14 | "Two sources of unread truth won't diverge" | `unread_count` (global column, bumped by webhook) and `conversation_reads` (per-user, via mark-read) are both maintained. They can drift. | **LOW** |

---

## Mandatory Fixes Before Next Feature

Ordered by severity. Each fix is scoped to be implementable in one session.

### Fix 1 — Commit all untracked files (blocker for CI/CD)

**What:** 26 files are on disk but not in git:
- `core/atendia/api/agents_routes.py` and 7 other route files
- `core/atendia/db/models/agent.py` and 4 other model files
- `core/atendia/queue/force_summary_job.py` and 2 other job files
- `core/atendia/storage/` (3 files)
- `core/atendia/workflows/` (2 files: `__init__.py`, `engine.py`)
- `core/atendia/db/migrations/versions/025_*.py` and `026_*.py`
- `core/tests/api/test_users_rbac.py`
- Frontend: `agents/`, `appointments/`, `dashboard/`, `knowledge/`, `notifications/` feature dirs, `ClientsPage.tsx`, `IntegrationsTab.tsx`

**Fix:** `git add` all of them in one commit with message "chore: track all in-progress module stubs". They are already imported; they must be in git.

**Acceptance:** `git status` shows no `??` files in `core/` or `frontend/src/features/`.

---

### Fix 2 — `force_summary` must call the LLM or be honestly renamed

**What:** `core/atendia/queue/force_summary_job.py:43` writes a note titled "Resumen AI" containing concatenated raw message text. No LLM call.

**Options:**

Option A (honest rename, 5 min): Change note title to `"Transcripción de conversación"`, remove AI branding. Rename arq function to `create_transcript_note`. Update the frontend button label to "Ver transcripción".

Option B (implement properly): Add an OpenAI call using the existing `gpt-4o-mini` client:
```python
from openai import AsyncOpenAI
client = AsyncOpenAI()
resp = await client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "Resume esta conversación de ventas en 3-5 puntos clave en español."},
        {"role": "user", "content": "\n".join(lines[-20:])},
    ],
    max_tokens=400,
)
summary = resp.choices[0].message.content
```

**Recommendation:** Implement Option B. The infrastructure already exists (AsyncOpenAI is imported elsewhere). Option A delays a feature users will expect.

**Acceptance:** POST `/api/v1/conversations/{id}/force-summary` → note body contains LLM-generated text, not raw message log.

---

### Fix 3 — `poll_workflow_triggers` cursor and scan

**Two bugs in `core/atendia/queue/workflow_jobs.py`:**

**Bug 3a — Full-table scan:**
```python
# CURRENT (scans all events):
tenants = (await session.execute(select(EventRow.tenant_id).distinct())).scalars().all()

# FIX (only tenants with active workflows):
from atendia.db.models.workflow import Workflow
active_tenants = (
    await session.execute(
        select(Workflow.tenant_id).where(Workflow.active == True).distinct()
    )
).scalars().all()
```

**Bug 3b — Timestamp cursor collision:**
```python
# CURRENT: uses created_at > last_created_at (microsecond ties silently skipped)
# FIX: add an index on (tenant_id, id) and filter by id:
stmt = (
    select(EventRow)
    .where(EventRow.tenant_id == tenant_id)
    .order_by(EventRow.id.asc())
    .limit(100)
)
if cursor and cursor.last_event_id:
    stmt = stmt.where(EventRow.id > cursor.last_event_id)
```

Add index to migration (or a new migration `027_event_cursor_index.py`):
```sql
CREATE INDEX idx_events_tenant_id ON events (tenant_id, id);
```

**Acceptance:** `poll_workflow_triggers` only queries tenants with at least one active workflow. Cursor advances by event UUID, not timestamp.

---

### Fix 4 — Add `assigned_agent_id` to PATCH /conversations/{id}

**What:** `core/atendia/api/conversations_routes.py` — the PATCH Pydantic model doesn't include `assigned_agent_id`. Add it with tenant-scoped validation:

```python
class ConversationPatch(BaseModel):
    current_stage: str | None = None
    assigned_user_id: UUID | None = None
    assigned_agent_id: UUID | None = None  # ADD THIS
    tags: list[str] | None = None

# In the PATCH handler, after validating assigned_user_id:
if body.assigned_agent_id is not None:
    agent = await session.get(Agent, body.assigned_agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="agent not found")
    conv.assigned_agent_id = body.assigned_agent_id
```

**Note:** Also add a UI warning in the agent assignment UI that "El agente se activará en el próximo mensaje." until C2 runner integration ships.

**Acceptance:** `PATCH /api/v1/conversations/{id}` with `{ "assigned_agent_id": "uuid" }` → 200 for valid agent, 404 for cross-tenant or missing agent.

---

### Fix 5 — Dashboard `unanswered_conversations` semantic

**What:** `core/atendia/api/dashboard_routes.py` computes `unanswered_conversations` as `conversations WHERE unread_count > 0`. This is the global counter, not per-user.

**Recommended fix (Option B — honest label, immediate):**
In `DashboardSummary`, rename the field to `conversations_with_unread` and add a UI label suffix "(global)". Document in a comment that this is tenant-wide, not per-operator.

**Ideal fix (Option A — correct semantics):**
```python
# Join against conversation_reads for the current user
from atendia.db.models.conversation import ConversationRead
unread_stmt = (
    select(func.count())
    .select_from(Conversation)
    .outerjoin(
        ConversationRead,
        (ConversationRead.conversation_id == Conversation.id) &
        (ConversationRead.user_id == current_user.user_id),
    )
    .where(
        Conversation.tenant_id == tenant_id,
        Conversation.deleted_at.is_(None),
        Conversation.last_message_at > func.coalesce(ConversationRead.last_read_at, sa.text("'1970-01-01'")),
    )
)
```

**Recommendation:** Option B immediately, Option A when P1 Conversations parity is verified.

**Acceptance:** Dashboard metric clearly communicates its scope. No silent wrong data for multi-operator tenants.

---

### Fix 6 — Separate arq concurrency for batch vs real-time

**What:** `core/atendia/queue/worker.py` runs all jobs with `max_jobs=10` shared. KB indexing bursts starve WhatsApp sends.

**Fix:** Add a semaphore guard in `index_document_job.py`:

```python
import asyncio
_INDEX_SEM = asyncio.Semaphore(3)  # max 3 concurrent KB indexing jobs

async def index_document(ctx, document_id):
    async with _INDEX_SEM:
        # ... existing implementation ...
```

This limits KB batch jobs to 3 concurrent, leaving headroom for `send_outbound`.

**Longer term:** Use separate arq queues (`queue_name` parameter) so `send_outbound` has a dedicated high-priority queue.

**Acceptance:** Uploading 10+ PDFs simultaneously does not delay a WhatsApp send by more than 2 seconds.

---

### Fix 7 — Verify workflow trigger direction filter

**What:** `core/atendia/workflows/engine.py` — verify that `evaluate_event` for `message_received` triggers filters by `direction='inbound'`. If not, a workflow that sends a message loops.

**Check:** In `engine.py`, find the `message_received` trigger handler and confirm:
```python
if event.event_type == "message_received":
    msg = event.payload.get("direction")
    if msg != "inbound":
        return  # do not trigger on bot-sent messages
```

If this check is missing, add it. Also add a test:
```python
# test_engine_triggers.py
async def test_message_received_only_fires_on_inbound(...):
    ...
```

**Acceptance:** A workflow with trigger `message_received` does not fire when the bot sends a message.

---

### Fix 8 — `_persist_outbound` conversation lookup

**What:** `core/atendia/queue/worker.py:_persist_outbound` uses `ORDER BY last_activity_at DESC LIMIT 1` which is non-deterministic for tied timestamps.

**Fix:** The `OutboundMessage` struct should carry the `conversation_id` when known (e.g., when the runner triggers the send). Pass it through:

```python
class OutboundMessage(BaseModel):
    ...
    conversation_id: str | None = None  # Add this field

async def _persist_outbound(session, msg, message_id, receipt):
    ...
    if msg.conversation_id:
        conv_id = UUID(msg.conversation_id)
    else:
        conv_id = (await session.execute(
            text("SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
                 "ORDER BY last_activity_at DESC LIMIT 1"),
            {"t": msg.tenant_id, "c": cust_id},
        )).scalar()
```

The fallback is retained for webhook-triggered sends where conversation context may be unknown.

**Acceptance:** Workflow-triggered outbound messages are always attached to the correct conversation.

---

## Secondary Fixes (next sprint, not blockers)

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| S1 | CSV export formula injection | `exports_routes.py` | Escape cells starting with `=`, `+`, `-`, `@` |
| S2 | Catalog disambiguation | `tools/catalog.py` | Return ranked list, not `[0]` when aliases match multiple SKUs |
| S3 | KB embedding cost quota | `knowledge_routes.py` | Add `max_documents_per_tenant` config limit, enforce before accepting upload |
| S4 | Agent UI "preview" warning | Frontend `AgentsPage.tsx` | Add banner: "El agente se activará cuando se complete la integración con el runner" |
| S5 | Pre-existing mypy errors | `state_machine/conditions.py:54,60`, `tools/__init__.py:19` | Fix 3 type errors |
| S6 | `unread_count` vs `conversation_reads` dual source | Both maintained | Add a DB trigger or application layer to keep them in sync, or deprecate `unread_count` |

---

## Decision Points for User

Before implementation starts, answer these:

**D1.** `force_summary`: Implement real LLM call (Option B, ~30 min), or honest rename (Option A, ~5 min)?

**D2.** Dashboard unread: Per-user join (Option A, correct), or global label (Option B, fast)?

**D3.** Fix 1 (commit all stubs): Do you want the stub route files committed as-is, or should we audit each one before committing (some may have partially implemented endpoints that need review)?

**D4.** Workflow trigger direction: Should we read the `engine.py` source now and verify, or treat Fix 7 as a dedicated test-writing session?

---

## What the Plan Gets Right — Do Not Undo

- P0 PATCH validation, per-user reads, RBAC, field encoding: correct and implemented.
- Module file convention: consistent, maintainable.
- Dependency graph: honest, accurately captures what blocks what.
- Acceptance gates (migration reversibility, RBAC tests per endpoint, browser screenshots): the right bar — apply them retroactively to the committed stubs.
- Workflow engine design (action idempotency via `workflow_action_runs`, execution locks, stop-on-first-error, cursor-based cron backup): architecturally correct.
- `StorageBackend` protocol for future S3 swap: good abstraction.

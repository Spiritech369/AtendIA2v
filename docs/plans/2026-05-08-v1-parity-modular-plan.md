# V1 → V2 Parity: Modular Implementation Plan

**Date:** 2026-05-08
**Status:** V1 parity roadmap modules **scaffolded** (code on disk and committed); each module is **not user-verified against v1** until it passes the acceptance gate (browser screenshots vs v1, real Meta worker end-to-end, operator sign-off). Workflows engine hardened in 2026-05-08 session 1 — see Implementation Status below.
**Scope:** Evidence-gated v1 parity roadmap. The 10 modules are an inventory, not permission to ship them in one batch.

---

## Table of Contents

0. [Adversarial Review Verdict](#adversarial-review-verdict)
1. [Architecture Overview](#architecture-overview)
2. [Infrastructure Prerequisites](#infrastructure-prerequisites)
3. [Phase A — Foundation](#phase-a--foundation-new-pages--quick-wins)
4. [Phase B — Enhance Core](#phase-b--enhance-core-upgrade-existing-pages)
5. [Phase C — Power Features](#phase-c--power-features-phased-internally)
6. [Dependency Graph](#dependency-graph)
7. [Migration Registry](#migration-registry)
8. [Nav Sidebar Changes](#nav-sidebar-changes)

---

## Adversarial Review Verdict

No. I am not 100% confident in the prior strategy. A factual 100% guarantee is not possible for a multi-module product migration, but the strategy can be made implementation-ready by making confidence conditional on concrete evidence gates. The old plan mixed three different things - v1 parity gaps, new product surface, and infrastructure ideas - and labeled the whole thing "Approved." That is the main loophole.

This section supersedes the original phase order below. The module specs remain useful as design inventory, but implementation must follow the gated order here.

### Implementation Status (2026-05-08)

P0 foundation hardening is implemented for:

- Conversation PATCH request typing, unknown-field rejection, stage validation, assignment validation, tag normalization/limits, and synchronized `stage_entered_at`.
- Per-user unread semantics through `conversation_reads`, with a migration, model, indexes, and mark-read/list/detail tests.
- Tenant-admin RBAC preservation and enforcement for unsafe tenant config, customer-field definition, and user-management endpoints.
- Canonical customer-field value encoding for `text`, `select`, `number`, `date`, `checkbox`, and `multiselect`.

**Module status — re-stated honestly per the trust-break contract.** Code for these modules is **scaffolded** (routes, models, migrations, components on disk and committed) but **not user-verified against v1**. Treat as draft until each module passes the acceptance gate below in its own session:

- File storage — **scaffolded + hardened in 2026-05-08 session 2**: tenant-scoped `read`/`delete` (key must begin with `tenant_id/`), magic-byte sniffer (PDF / zip / UTF-8 text — stdlib only, no new deps) on `save`, path-traversal rejection. 12 storage unit tests.
- Document parsing job — scaffolded; explicit 90s arq job timeout added so a malformed file can't sit at arq's 300s default; tenant-scoped `read` enforced when fetching bytes.
- arq job expansion, tenant timezone, lightweight notifications — scaffolded.
- Knowledge Base — **hardened in sessions 2 + 3**:
  - s2: authenticated download (attachment disposition, `X-Content-Type-Options: nosniff`), per-document retry, reindex cooldown (5 min/tenant), `/test` rate limit (10/min/tenant), DB-first delete order, magic-byte sniff on upload.
  - s3: `/test` now generates a real gpt-4o-mini answer when the OpenAI key is set, with prompt-injection guard (sources tagged `<fuente>`, system prompt explicitly tells the LLM to treat source contents as data not instructions). Mode flag in response: `llm` / `sources_only` / `empty` so the UI can label degradation honestly. Audit-event emission on upload/download/retry/delete.
  - **Still pending**: HNSW partial-index per tenant (cross-tenant query leakage at scale, documented), frontend KB UI, real OpenAI E2E with operator sign-off.
- **Conversations Enhanced** — backend has `force-summary` endpoint + `force_summary` arq job; in s3 the job was rewritten to actually call gpt-4o-mini (with transcript fallback when key missing). Frontend ContactPanel/DebugPanel scaffolded but not parity-verified vs v1. **Real LLM E2E pending operator credentials.**
- Appointments, Dashboard, Integrations tab, Clients enhanced table/import/export, Pipeline Kanban, Agents — scaffolded; pending browser parity verification.
- Agent runner integration for default/assigned agent tone/name/message limits and active-intent handoff signaling — scaffolded; pending end-to-end runner test on a real conversation.
- **Workflows engine — hardened in sessions 1 + 3 + 5.** Migration 027 + engine refactor in s1; migration 028 closures in s3; Meta E2E pipeline probe in s5:
  - s1: condition allowlist, definition validator (cycles/branches/references), `steps_completed` persisted, event source-tagging + self-loop guard, idempotency on every side-effect, outside-24h pre-flight on `message`, queue isolation via `WorkflowWorkerSettings`.
  - s3: `workflows.version` optimistic locking (409 on stale PATCH); audit-event emission on create/patch/delete/toggle/retry; **runner inline-trigger hook wired** in `webhooks/meta_routes.py` so MESSAGE_RECEIVED → `evaluate_event` → arq `workflows` queue happens inline (cron is now backstop only, not the only path).
  - s5: end-to-end pipeline probe (`core/scripts/e2e_meta_workflow.py`) verified against real `META_APP_SECRET`. Webhook → message_received event → workflow_execution → completed status all green. Final Meta API call blocked on **expired access token (error 190, sesion expired 2026-05-03)** — refresh token in `.env` and re-run; the same script will return exit 0. Runbook at `docs/runbooks/workflows-meta-e2e.md`.
  - **Still pending in their own sessions**: form editor, visual React Flow editor, runtime stale-reference detection (`active=true` workflow whose agent was deleted), mutual-loop detection between two workflows (only same-workflow self-loop blocked today).

What changed from the previous (oversold) status text: the original wording said "implemented and verified" with "remaining acceptance evidence" tucked at the end. That mirrors the Phase 4 trust-break and is no longer accurate. Verification under this plan now means **browser screenshots side-by-side with v1**, **real Meta worker end-to-end** for outbound paths, and **operator user sign-off in writing**. Backend tests, ruff, typecheck, and build are necessary but not sufficient.

### Hidden Assumptions Found

| Assumption | Why it is unsafe | Required fix |
|------------|------------------|--------------|
| "Roles are complete." | The code has `tenant_admin` references, but session auth treats roles as `operator` or `superadmin`; config-definition routes are currently operator-accessible. | Define the RBAC matrix before new admin/config pages. Either implement `tenant_admin` end-to-end or explicitly keep only `operator`/`superadmin` and gate admin actions to superadmin. |
| "Unread can be per conversation." | A global `unread_count` means one operator opening a conversation clears unread state for every operator. That conflicts with multi-user tenants and "Mios/Sin asignar" workflows. | Add `conversation_reads` per user or explicitly scope v1 parity to single-operator tenants. Prefer `conversation_reads(user_id, conversation_id, last_read_at, last_read_message_id)` and compute unread per current user. |
| "Just merged scope gaps are safe foundation." | `PATCH /conversations/:id` accepts raw JSON, does not validate stage against the active pipeline, does not validate `assigned_user_id` belongs to the tenant, and does not update `stage_entered_at`. | Add Pydantic request models, tenant-scoped assignment validation, tag limits, stage validation, and synchronized `stage_entered_at` updates before building Pipeline/Dashboard on top. |
| "Customer fields are complete." | Current values are `str | None`; v1-like checkbox, multiselect, number, and date fields need typed values or strict encoding. | Either add `value_json JSONB` or document and test canonical string encoding per field type. Do this before the ContactPanel rebuild. |
| "Turn traces / Debug is complete." | Backend data exists, but the v1 gap document says the UI is still JSON dumps, not v1 parity. | Reclassify as backend-complete/UI-incomplete. Require browser screenshot acceptance for DebugPanel before calling conversations parity done. |
| "Integrations needs a new status endpoint." | `/api/v1/channel/status` and `WhatsAppStatusBadge` already exist. Adding a second WhatsApp status API creates drift. | Module 10 should reuse `/api/v1/channel/status`; add only missing Meta detail fields if needed. |
| "Dashboard can parallelize SQL queries with one AsyncSession." | SQLAlchemy `AsyncSession` is not safe for concurrent use. | Use one aggregate statement, sequential queries, or independent sessions. Do not `asyncio.gather` on the same session. |
| "Local file storage is simple." | Uploads introduce path traversal, quota, PII leakage, prompt injection, parser crashes, and worker backpressure risk. | Add filename sanitization, tenant path enforcement, allowlisted MIME/extension checks, size limits, quotas, private storage, parser timeouts, and RAG prompt-injection handling before KB uploads. |
| "One arq worker can absorb all new jobs." | Embeddings, summaries, workflows, and outbound messages have different latency/cost/failure profiles. A KB indexing burst could starve WhatsApp sends. | Separate queues or at least separate job concurrency/timeouts/rate limits. Do not register job functions before their modules exist. |
| "Workflow idempotency on `(workflow_id, trigger_event_id)` is enough." | Workflow actions can emit new events and recursively trigger themselves; delayed jobs can duplicate; graph cycles can loop forever. | Add workflow definition validation, execution locks, max step count, action-level idempotency keys, loop guards, retry policy, and dead-letter visibility. |
| "CSV import/export covers the need safely." | CSV import can create formula-injection exports, duplicate phones, enormous transactions, and bad E.164 normalization. | Add max row count, phone normalization, transactional chunking, import preview/error report, and CSV export escaping for cells starting with `=`, `+`, `-`, or `@`. |
| "Full v1 parity can be measured by module completion." | The v1 gap doc defines operator workflows, not backend modules. New pages can ship while the core Conversations screen still feels worse than v1. | Parity is accepted only by side-by-side browser verification of the specific workflow, with scope cuts explicitly approved by the user. |

### Failure Simulations

| Simulation | Failure mode in old plan | Revised pass condition |
|------------|--------------------------|------------------------|
| Two operators open the same tenant. | Operator A opens a conversation and clears unread for Operator B. | Unread state is per user, or the release is explicitly labeled single-operator only. |
| Malicious or mistaken operator assigns another tenant's user UUID. | Cross-tenant assignment can leak user email through the join. | Assignment query verifies `tenant_users.tenant_id == current_tenant_id`; otherwise 404. |
| Operator moves a conversation to a deleted/renamed stage. | Pipeline board, stale timers, and router assumptions drift. | Stage changes validate against active pipeline and update `stage_entered_at` atomically. |
| Tenant uploads 200 PDFs. | Embedding jobs monopolize the worker and outbound WhatsApp delivery slows. | KB indexing has quotas, separate concurrency, and visible per-document error/progress states. |
| Workflow sends a message on `message_received`. | Its outbound/message events can retrigger the workflow repeatedly. | Workflow engine enforces trigger-source filters, max steps, action idempotency, and loop detection. |
| Dashboard is built before appointments migration. | "Graceful empty if table missing" hides schema drift and produces runtime conditionals. | Dashboard waits for its dependent migration or checks a feature flag generated from the migrated schema. |
| "Done" is declared after tests pass. | Tests miss the trust-breaking UI parity gap. | Done requires backend tests, frontend type/lint, and browser screenshots against the specific v1 workflow. |

### Revised Execution Order

1. **P0 - Stabilize existing Conversations foundation.** No new pages. Fix RBAC, conversation patch validation, per-user unread semantics, customer-field typing/encoding, stage transition timestamps, and route/API version consistency.
2. **P1 - Finish the most-used v1 workflows on Conversations.** ContactPanel, DebugPanel, ChatWindow media/debug actions, Inbox/list parity, and WhatsApp status. Each sub-scope is one session unless the user explicitly approves batching.
3. **P2 - Add only prerequisites needed by the next chosen module.** File storage is built only immediately before Knowledge Base. Notifications are built only before workflows/notify actions. Timezone is built before Dashboard/Appointments.
4. **P3 - Product expansion modules.** Appointments, Knowledge Base, Dashboard, Pipeline, Clients Enhanced, Agents, and Workflows proceed one at a time behind their gates.

### P0 Mandatory Fixes Before New Modules

- [x] Replace raw `PATCH /api/v1/conversations/{id}` body parsing with a Pydantic model and reject unknown fields.
- [x] Validate `current_stage` against the active tenant pipeline; update both `conversations.current_stage` and `conversation_state.stage_entered_at` in the same transaction.
- [x] Validate `assigned_user_id` against `tenant_users` for the current tenant; reject cross-tenant or unknown users with 404.
- [x] Constrain tags: list of unique trimmed strings, max 10 tags, max 40 chars each, lowercase-normalized unless the UI intentionally preserves case.
- [x] Decide unread semantics. Preferred: add per-user `conversation_reads`; acceptable only as a temporary MVP: document global `unread_count` as single-operator behavior in red before user approval.
- [x] Define RBAC for config/admin actions. At minimum, customer-field definitions, pipeline config, agents, workflows, and integrations must not be editable by every operator by accident.
- [x] Add indexes required by the new list/board queries: `(tenant_id, deleted_at, last_activity_at DESC)`, `(tenant_id, customer_id, deleted_at, last_activity_at DESC)`, and any per-user read index if `conversation_reads` is added.
- [x] Align endpoint docs to `/api/v1/...` because the frontend API client uses base URL `/api/v1`.
- [x] Run `alembic heads` and verify exactly one head before adding migration 025.

### Acceptance Gates

Each module is allowed to start only when:

- Its database migration has reversible tests and does not create multiple Alembic heads.
- Tenant scoping, CSRF, and role permissions are covered by tests for every unsafe endpoint.
- Background jobs are idempotent and have visible failed states.
- Frontend work passes typecheck/lint and has at least one browser verification screenshot for the primary workflow.
- Any scope reduction is written plainly in the plan and accepted by the user before implementation.

### Endpoint Notation

All operator API endpoints in this document must be implemented under `/api/v1/...` unless explicitly marked as a webhook or WebSocket route. Older tables that say `/api/...` are shorthand only.

---

## Architecture Overview

### What V2 Already Has

| System | Status |
|--------|--------|
| Auth + Users | Working |
| Roles / RBAC | P0 hardened: `tenant_admin` is preserved in auth and unsafe tenant/config/user actions are role-gated |
| Customers table + search | Basic (3 columns) |
| Conversations + Messages + ChatWindow | Substantial |
| WhatsApp Cloud API webhook + outbound | Working |
| Bot pause / Human handoff | Working |
| Customer notes (CRUD) | Complete |
| Customer field definitions + values (EAV) | Backend exists; typed value semantics have P0 canonical encoding/tests |
| Pipeline config editor (JSONB stages) | Working |
| TenantFAQ + TenantCatalog + embeddings | Backend only, no UI |
| Analytics (funnel, cost, volume) | Basic |
| Flow router (8 trigger types, 6 FlowModes) | Working |
| NLU with intent detection (8 intents) | Working |
| Composer with FlowMode-specific prompts | Working |
| arq worker (send_outbound + poll_followups) | Working |
| Turn traces / Debug | Backend exists; v1-parity UI incomplete |
| Audit log | Complete |
| Exports | Working |
| Conversation tags, unread, assign, soft-delete | P0 validation/security hardening implemented |
| Redis pub/sub for realtime events | Working (fire-and-forget) |
| Events table (durable append-only log) | Working |

### Module File Convention

Every module follows the same structure. Adding = create these files + register routes + add nav item. Removing = delete + unregister.

```
core/atendia/db/models/{module}.py              # SQLAlchemy model
core/atendia/db/migrations/versions/NNN_*.py    # Alembic migration
core/atendia/api/{module}_routes.py             # FastAPI endpoints
core/atendia/contracts/{module}.py              # Pydantic contracts (if needed)
frontend/src/features/{module}/api.ts           # Axios API client
frontend/src/features/{module}/components/*.tsx  # React components
frontend/src/routes/(auth)/{module}.tsx          # TanStack Router route
```

### Key Architectural Decisions (cross-cutting)

| Decision | Rationale |
|----------|-----------|
| Customer "stage" = `current_stage` of most recent active conversation | Stage lives on Conversation, not Customer. Avoids data duplication. Fallback: "Sin conversación" |
| Pipeline Kanban shows conversations grouped by stage, not customers | Matches data model. Each card shows customer info. |
| "Agent" = named configuration profile, NOT separate LLM instance | Maps to existing FlowMode + FlowRouter. Agent overrides prompt template variables. |
| Workflow triggers hook inline after runner + arq cron poll as backup | Redis pub/sub is fire-and-forget; DB events table is durable. Both paths for reliability. |
| Workflow definition = single JSONB blob (node graph) | Simple storage, flexible schema, easy versioning. |
| File storage = local disk MVP with StorageBackend protocol for S3 swap | No file infra exists today. Protocol allows production upgrade without code changes. |
| Google Sheets sync = OUT OF SCOPE | CSV import/export covers the need. Sheets = future integration. |
| `origin` column on conversations = DROPPED | `conversation.channel` already covers this. No migration needed. |
| Dashboard at `/dashboard`, conversations stays at `/` | No breaking URL changes. |
| Clients page = TABLE only (no kanban) | Pipeline page IS the kanban. Avoids redundancy + expensive effective_stage grouping. |
| Effective stage via lateral join | Single query, no N+1. `LEFT JOIN LATERAL (SELECT current_stage ... LIMIT 1)`. |
| Agent `active_intents` uses exact NLU enum values | NLU enum: GREETING, ASK_INFO, ASK_PRICE, BUY, SCHEDULE, COMPLAIN, OFF_TOPIC, UNCLEAR. Frontend shows Spanish labels. |
| Document checkboxes = static ExtractedFields booleans | Fields: docs_ine, docs_comprobante, docs_estados_de_cuenta, docs_nomina, etc. Looked up via `docs_per_plan[plan_credito]`. |
| Workflow conditions use dot notation for field namespace | `conversation.current_stage`, `extracted.docs_ine`, `customer.score`. Default namespace = `extracted`. |
| Workflow error handling = stop on first error | Execution fails, current_node_id saved, manual retry via API. No auto-retry. |

---

## Infrastructure Prerequisites

Build only the prerequisite needed by the next approved module. Do not block the P0 Conversations hardening work on Knowledge Base storage, workflow notifications, or Dashboard timezone work.

### P1: File Storage Layer

**Why:** Module 5 (Knowledge Base) needs file upload. Nothing exists today.

**Files to create:**
```
core/atendia/storage/__init__.py
core/atendia/storage/base.py       # StorageBackend Protocol
core/atendia/storage/local.py      # LocalStorageBackend implementation
```

**StorageBackend Protocol:**
```python
class StorageBackend(Protocol):
    async def save(self, tenant_id: str, filename: str, data: bytes) -> str:
        """Save file, return storage path/key."""
        ...

    async def read(self, path: str) -> bytes:
        """Read file by path/key."""
        ...

    async def delete(self, path: str) -> None:
        """Delete file by path/key."""
        ...
```

**LocalStorageBackend:**
- Saves to `{UPLOAD_DIR}/{tenant_id}/{uuid}.{ext}`
- `UPLOAD_DIR` from env var (default: `./uploads`)
- Returns relative path as the storage key
- Ignores the user-provided filename for the storage path except for a sanitized extension allowlist.
- Verifies every read/delete key resolves under `{UPLOAD_DIR}/{tenant_id}`; no `..`, absolute paths, or tenant-crossing keys.
- Enforces max file size, allowed MIME/extension pairs, and per-tenant quota before writing bytes.
- Stores files outside the served frontend/static tree. Downloads/previews must go through an authenticated tenant-scoped route.

**Config addition:** Add `upload_dir: str = "./uploads"` to `Settings`.

**Production upgrade path:** Create `S3StorageBackend` implementing same protocol. Swap via env var `STORAGE_BACKEND=local|s3`.

**Security tests required before Module 5:** path traversal rejection, cross-tenant key rejection, disallowed file type rejection, oversize rejection, and delete idempotency.

---

### P2: arq Worker Expansion

**Why:** Modules 3, 5, 9 need background job processing beyond send_outbound and poll_followups.

**New job functions to register, but only when their owning module lands:**

| Job | Module | Purpose |
|-----|--------|---------|
| `index_document` | 5 | Chunk file → embed → store in DB |
| `force_summary` | 3 | Generate AI conversation summary → save as customer note |
| `execute_workflow_step` | 9 | Continue workflow execution after delay |

**Changes to `core/atendia/queue/worker.py`:**
```python
functions = [send_outbound, index_document, force_summary, execute_workflow_step]
cron_jobs = [
    cron(poll_followups, second={0}, unique=True, run_at_startup=False),
    cron(poll_workflow_triggers, second={5, 15, 25, 35, 45, 55}, unique=True),  # Module 9
]
```

**Each job function follows the same pattern** as `send_outbound`: create engine + session from ctx, do work, commit, handle errors.

**Reliability rule:** do not import/register placeholder job functions before the module exists, or the worker can fail at boot. Heavy jobs (`index_document`) need separate queue/concurrency or strict rate limits so they cannot starve `send_outbound`.

---

### P3: Tenant Timezone

**Why:** Dashboard "today" queries, Appointments date display, and Pipeline stale alerts all need tenant-local time. No timezone field exists on tenants.

**Migration (part of 025 or standalone):**
```sql
ALTER TABLE tenants ADD COLUMN timezone VARCHAR(40) NOT NULL DEFAULT 'America/Mexico_City';
```

**Model change:** Add to `Tenant`:
```python
timezone: Mapped[str] = mapped_column(String(40), default="America/Mexico_City", server_default="'America/Mexico_City'")
```

**Usage:** Validate timezone names with Python `zoneinfo.ZoneInfo` before saving. "Today" queries should compute tenant-local `[start_utc, end_utc)` bounds and filter `scheduled_at >= start_utc AND scheduled_at < end_utc`; avoid `scheduled_at::date` because it can be timezone-wrong and index-hostile.

---

### P4: Notifications (lightweight)

**Why:** Workflow `notify_agent` action needs a delivery target. The Bell icon in AppShell is non-functional.

**Migration (part of first module that needs it, or standalone):**
```sql
CREATE TABLE notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES tenant_users(id) ON DELETE CASCADE,
    title       VARCHAR(200) NOT NULL,
    body        TEXT,
    read        BOOLEAN NOT NULL DEFAULT false,
    source_type VARCHAR(40),   -- 'workflow', 'system', 'handoff'
    source_id   UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notifications_user_unread ON notifications (user_id) WHERE read = false;
```

**API:** `core/atendia/api/notifications_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/notifications` | GET | List notifications for current user. Query: `unread_only`. |
| `/api/v1/notifications/{id}/read` | PATCH | Mark as read. |
| `/api/v1/notifications/read-all` | POST | Mark all as read. |

**Frontend:** Update Bell icon in `AppShell.tsx` → dropdown showing unread notifications with count badge. Small component, ~100 lines.

**RBAC rule:** notification reads are always scoped to `current_user.user_id`; workflow-created notifications must validate that the target user belongs to the same tenant.

**Model:** `core/atendia/db/models/notification.py`

**Job files:**
```
core/atendia/queue/index_document_job.py
core/atendia/queue/force_summary_job.py
core/atendia/queue/workflow_jobs.py
```

---

## Phase A — Foundation (New Pages + Quick Wins)

**Superseded execution note:** this is no longer Phase A for implementation. Per the adversarial review, P0 Conversations hardening and the v1 Conversations workflows come first. The modules below are retained as specs for when the user explicitly chooses product expansion.

### Module 4: Appointments

**Size:** M | **Type:** NEW full stack | **Dependencies:** Customers (exists)

#### 4.1 Database

**Migration `025_appointments.py`:**

```sql
CREATE TABLE appointments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id     UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    scheduled_at    TIMESTAMPTZ NOT NULL,
    service         VARCHAR(200) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    notes           TEXT,
    created_by_id   UUID REFERENCES tenant_users(id) ON DELETE SET NULL,
    created_by_type VARCHAR(10) NOT NULL DEFAULT 'user',  -- 'user' | 'bot'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_appointments_tenant_date ON appointments (tenant_id, scheduled_at);
CREATE INDEX idx_appointments_customer ON appointments (customer_id);
```

**Hardening:** add database or Pydantic validation for status values, timezone-aware `scheduled_at`, and same-tenant `customer_id`/`conversation_id` checks in the API. Prefer soft delete (`deleted_at`) if operators need recovery/audit; hard delete is acceptable only if the user confirms appointments are disposable.

**Model:** `core/atendia/db/models/appointment.py`

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| tenant_id | UUID | FK tenants |
| customer_id | UUID | FK customers |
| conversation_id | UUID | FK conversations, nullable (manual or bot-created) |
| scheduled_at | datetime(tz) | Single datetime, NOT separate date+time |
| service | String(200) | Free text |
| status | String(20) | Enum: scheduled, completed, cancelled, no_show |
| notes | Text | Optional |
| created_by_id | UUID | FK tenant_users, nullable |
| created_by_type | String(10) | 'user' or 'bot' |

#### 4.2 API

**File:** `core/atendia/api/appointments_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/appointments` | GET | List appointments. Query params: `date_from`, `date_to`, `customer_id`, `status`. Paginated. |
| `/api/v1/appointments` | POST | Create appointment. Body: customer_id, scheduled_at, service, notes. |
| `/api/v1/appointments/{id}` | PATCH | Update appointment with a typed Pydantic partial model; reject unknown fields. |
| `/api/v1/appointments/{id}` | DELETE | Soft delete unless the user explicitly accepts hard delete. |

**Response model `AppointmentItem`:** id, customer_id, customer_name, customer_phone, conversation_id, scheduled_at, service, status, notes, created_by_type, created_at.

#### 4.3 Frontend

**Route:** `frontend/src/routes/(auth)/appointments.tsx`

**Components:**
```
frontend/src/features/appointments/api.ts
frontend/src/features/appointments/components/AppointmentsPage.tsx
frontend/src/features/appointments/components/AppointmentTable.tsx
frontend/src/features/appointments/components/CreateAppointmentDialog.tsx
```

**AppointmentsPage:**
- Header: "Citas" + date range picker + "+ Nueva Cita" button
- AppointmentTable: columns = Fecha, Cliente, Servicio, Estado, Acciones
- Acciones: edit (opens dialog), complete, cancel, delete
- CreateAppointmentDialog: customer search/select, datetime picker, service input, notes textarea

#### 4.4 Runner Integration (optional subtask)

The NLU already detects `SCHEDULE` intent and extracts `cita_dia` (ISO date string). To enable bot-created appointments:

1. Add new action `"schedule_appointment"` to runner tool dispatch (`conversation_runner.py`)
2. When triggered: check for date, time, timezone, service, and customer identity. If any required field is missing, ask for it.
3. If present: ask for confirmation before INSERT unless the workflow explicitly marks the action as auto-confirmed.
4. Composer generates confirmation message using action_payload

This is additive — the CRUD page works independently. Bot integration can be deferred if needed.

#### 4.5 Tests

```
core/tests/api/test_appointments_crud.py     # 8-10 tests: create, list, filter by date, update status, delete
```

---

### Module 5: Knowledge Base UI

**Size:** L | **Type:** NEW frontend + backend enhancements | **Dependencies:** P1, P2

**Python deps to install first:** `uv add pymupdf python-docx openpyxl` (PDF, Word, Excel parsing)

#### 5.1 Database

**Migration `026_knowledge_documents.py`:**

```sql
CREATE TABLE knowledge_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    filename        VARCHAR(255) NOT NULL,
    storage_path    VARCHAR(500) NOT NULL,
    category        VARCHAR(60),
    status          VARCHAR(20) NOT NULL DEFAULT 'processing',  -- processing | indexed | error
    fragment_count  INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_knowledge_docs_tenant ON knowledge_documents (tenant_id);
```

**Migration `027_catalog_items_tags_uses.py`:**

```sql
ALTER TABLE tenant_catalogs ADD COLUMN tags JSONB NOT NULL DEFAULT '[]';
ALTER TABLE tenant_catalogs ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0;
```

**New model:** `core/atendia/db/models/knowledge_document.py`

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| tenant_id | UUID | FK tenants |
| filename | String(255) | Original filename |
| storage_path | String(500) | Path from StorageBackend |
| category | String(60) | User-assigned category tag |
| status | String(20) | processing → indexed or error |
| fragment_count | int | Updated by index_document job |
| error_message | Text | Populated on error |

**Chunk storage:** New `knowledge_chunks` table for document-sourced chunks:

```sql
CREATE TABLE knowledge_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    embedding       halfvec(3072),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_knowledge_chunks_doc ON knowledge_chunks (document_id);
CREATE INDEX idx_knowledge_chunks_embedding ON knowledge_chunks
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);
```

#### 5.2 API

**File:** `core/atendia/api/knowledge_routes.py`

**FAQs sub-routes:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/knowledge/faqs` | GET | List FAQs. Paginated. |
| `/api/v1/knowledge/faqs` | POST | Create FAQ (question, answer, tags). Auto-embeds. |
| `/api/v1/knowledge/faqs/{id}` | PATCH | Update FAQ. Re-embeds if question/answer changed. |
| `/api/v1/knowledge/faqs/{id}` | DELETE | Delete FAQ. |

**Catalog sub-routes:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/knowledge/catalog` | GET | List catalog items. Filter by category. |
| `/api/v1/knowledge/catalog` | POST | Create item (name, sku, category, attrs, tags). Auto-embeds. |
| `/api/v1/knowledge/catalog/{id}` | PATCH | Update item. Re-embeds if name/attrs changed. |
| `/api/v1/knowledge/catalog/{id}` | DELETE | Delete item. |

**Documents sub-routes:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/knowledge/documents` | GET | List documents with status + fragment_count. |
| `/api/v1/knowledge/documents/upload` | POST | Upload file (multipart). Saves via StorageBackend. Creates row status=processing. Enqueues arq `index_document`. Returns 202. |
| `/api/v1/knowledge/documents/{id}` | GET | Get single document details. |
| `/api/v1/knowledge/documents/{id}` | DELETE | Delete document + its chunks + file from storage. |

**Test sub-route:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/knowledge/test` | POST | Body: `{ "query": "string" }`. Runs vector similarity search across FAQs + catalog + document chunks. Returns: `{ answer: string, sources: [{ type, id, text, score }] }`. Uses gpt-4o-mini for answer generation. |

**`index_document` arq job:**
1. Read file from storage
2. Parse content (PDF via `pymupdf`, DOCX via `python-docx`, TXT/CSV direct read)
3. Split into chunks (~500 tokens each, 50 token overlap)
4. Embed each chunk via `text-embedding-3-large`
5. Batch insert into `knowledge_chunks`
6. Update `knowledge_documents` row: status=indexed, fragment_count=N
7. On error: status=error, error_message=str(e)

**Security/reliability constraints:**
- Parser runs with file size/page/row/time limits; parser failures never crash the worker.
- All vector searches include `tenant_id = current_tenant_id`.
- RAG answer prompt treats uploaded content as untrusted data and forbids following instructions found inside source documents.
- Reindex-all is an async job with per-tenant rate limits, not a blocking HTTP request.
- Document text shown in previews/source cards must be escaped and clipped.

#### 5.3 Frontend

**Route:** `frontend/src/routes/(auth)/knowledge.tsx`

**Components:**
```
frontend/src/features/knowledge/api.ts
frontend/src/features/knowledge/components/KnowledgeBasePage.tsx
frontend/src/features/knowledge/components/CatalogTab.tsx        # "Artículos"
frontend/src/features/knowledge/components/FAQsTab.tsx
frontend/src/features/knowledge/components/DocumentsTab.tsx
frontend/src/features/knowledge/components/TestTab.tsx            # "Probar"
frontend/src/features/knowledge/components/CreateFAQDialog.tsx
frontend/src/features/knowledge/components/CreateCatalogDialog.tsx
frontend/src/features/knowledge/components/FileUploadZone.tsx
```

**KnowledgeBasePage:** 4 tabs (Artículos, FAQs, Documentos, Probar) + "Reindexar" button (re-embeds all).

**DocumentsTab:**
- FileUploadZone: drag-and-drop area accepting PDF, Excel, Word, TXT (max 20MB)
- Document list: filename, category badge, fragment count, status badge (processing spinner / indexed green / error red), actions (Vista previa, Editar category, Delete)
- Status polling: useQuery with 3s refetchInterval while any document is `processing`
- Shows worker error messages in a clipped, non-technical way and allows retrying a failed index job.

**TestTab:**
- Chat-like interface: input field, send button
- Shows: AI answer + source cards (type, excerpt, relevance score)

#### 5.4 Tests

```
core/tests/api/test_knowledge_faqs.py        # CRUD + embedding
core/tests/api/test_knowledge_catalog.py     # CRUD + tags + embedding
core/tests/api/test_knowledge_documents.py   # Upload + status + delete
core/tests/api/test_knowledge_test.py        # RAG query endpoint
```

---

### Module 10: Integrations

**Size:** S | **Type:** NEW tab in config page | **Dependencies:** Existing WhatsApp infra

#### 10.1 Backend

**No new models or migrations.** WhatsApp status is already exposed by `core/atendia/api/channel_status_routes.py` at `/api/v1/channel/status` and rendered by `WhatsAppStatusBadge`. Do not create a duplicate status source.

**File:** only create `core/atendia/api/integrations_routes.py` if the config tab needs fields not returned by `/api/v1/channel/status` (for example phone number or business name).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/channel/status` | GET | Existing source of truth for connected/inactive/paused, circuit breaker, and last_webhook_at. |
| `/api/v1/integrations/whatsapp/details` | GET | Optional only if needed: phone_number, business_name, phone_number_id from tenant config. |

#### 10.2 Frontend

**No new route.** Add tab to existing `/config` page.

**Changes to:** `frontend/src/routes/(auth)/config.tsx` — add "Integraciones" tab.

**New components:**
```
frontend/src/features/config/components/IntegrationsTab.tsx
frontend/src/features/config/components/WhatsAppStatusCard.tsx
```

**WhatsAppStatusCard:**
- Connected/disconnected badge
- Phone number display
- Business name
- Last webhook timestamp
- "Desconectar" button (disabled for MVP — instructs user to manage via Meta Business)

**Future integration cards (placeholder):**
- Google Calendar: "Próximamente" with icon
- Google Sheets: "Próximamente" with icon

#### 10.3 Tests

```
core/tests/api/test_integrations_whatsapp.py  # 2-3 tests: status endpoint
```

If the optional details endpoint is skipped, tests should cover the existing channel status endpoint plus the Config tab rendering.

---

### Module 1: Dashboard

**Size:** M | **Type:** NEW page | **Dependencies:** Customers, Conversations, Appointments (Module 4), P3 (timezone)

**Frontend dep to install first:** `npm install recharts` (lightweight chart library)

#### 1.1 Backend

**No new models.** Pure aggregation queries.

**File:** `core/atendia/api/dashboard_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/dashboard/summary` | GET | Single aggregation endpoint returning all dashboard data. |

**Response model `DashboardSummary`:**

```python
class DashboardSummary(BaseModel):
    total_customers: int
    conversations_today: int
    active_conversations: int
    unanswered_conversations: int  # unread_count > 0
    todays_appointments: list[AppointmentItem]  # empty list if table doesn't exist
    recent_conversations: list[RecentConversation]  # last 10
    activity_chart: list[DayBucket]  # last 7 days: { date, inbound, outbound }
```

**Queries (all in a single endpoint):** use one aggregate SQL statement where practical, or run sequential queries on the same `AsyncSession`. If true parallelism is needed, use independent sessions; never call `asyncio.gather` with concurrent operations on one `AsyncSession`.
- `total_customers`: `SELECT count(*) FROM customers WHERE tenant_id = :t`
- `conversations_today`: `SELECT count(*) FROM conversations WHERE tenant_id = :t AND created_at >= :today AND deleted_at IS NULL`
- `active_conversations`: `SELECT count(*) FROM conversations WHERE tenant_id = :t AND status = 'active' AND deleted_at IS NULL`
- `unanswered_conversations`: `SELECT count(*) FROM conversations WHERE tenant_id = :t AND unread_count > 0 AND deleted_at IS NULL`
- `todays_appointments`: only after Module 4 migration is present, or behind an explicit feature flag. Compute tenant-local UTC bounds and use `scheduled_at >= :start_utc AND scheduled_at < :end_utc`; do not use `scheduled_at::date`.
- `recent_conversations`: `SELECT c.*, cust.name, cust.phone_e164 FROM conversations c JOIN customers cust ... ORDER BY c.last_activity_at DESC LIMIT 10`
- `activity_chart`: `SELECT date_trunc('day', sent_at) as day, count(*) FILTER (WHERE direction='inbound'), count(*) FILTER (WHERE direction='outbound') FROM messages WHERE tenant_id = :t AND sent_at >= :seven_days_ago GROUP BY 1 ORDER BY 1`

#### 1.2 Frontend

**Route:** `frontend/src/routes/(auth)/dashboard.tsx`

**Components:**
```
frontend/src/features/dashboard/api.ts
frontend/src/features/dashboard/components/DashboardPage.tsx
frontend/src/features/dashboard/components/MetricCards.tsx
frontend/src/features/dashboard/components/ActivityChart.tsx
frontend/src/features/dashboard/components/TodaysAppointments.tsx
frontend/src/features/dashboard/components/RecentConversations.tsx
```

**DashboardPage layout:**
```
┌─────────────────────────────────────────────┐
│  MetricCards (4 cards in a row)              │
│  [Total Clientes] [Conv. Hoy] [Activas] [Sin responder] │
├──────────────────────┬──────────────────────┤
│  ActivityChart        │  TodaysAppointments  │
│  (7-day bar chart)   │  (table)             │
├──────────────────────┴──────────────────────┤
│  RecentConversations (table, last 10)        │
└─────────────────────────────────────────────┘
```

**ActivityChart:** Use `recharts` BarChart (lightweight, already React-friendly). Two bars per day: inbound (green), outbound (blue).

**MetricCards:** shadcn Card with big number + label + optional trend indicator.

#### 1.3 Tests

```
core/tests/api/test_dashboard_summary.py  # 3-4 tests: empty state, with data, date filtering
```

---

## Phase B — Enhance Core (Upgrade Existing Pages)

### Module 2: Clients Enhanced

**Size:** M | **Type:** UPGRADE existing | **Dependencies:** Pipeline stages (exist)

#### 2.1 Database

**Migration `028_customers_score.py`:**

```sql
ALTER TABLE customers ADD COLUMN score INTEGER DEFAULT 0;
```

**Model change:** Add to `Customer`:
```python
score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
```

Score is manually-set (0-100). Auto-scoring is a future enhancement.

#### 2.2 API

**Enhance existing:** `core/atendia/api/customers_routes.py`

**Enhanced list endpoint `GET /api/v1/customers`:**
New query params: `stage`, `assigned_user_id`, `sort_by` (name, last_activity, score), `sort_dir` (asc, desc).

New response fields per customer:
- `effective_stage`: from lateral join (see below)
- `last_activity_at`: from lateral join
- `assigned_user_email`: from lateral join → assigned_user_id → tenant_users
- `score`: from customer record

**Lateral join for effective_stage (critical — avoids N+1):**
```sql
SELECT c.*, latest.current_stage AS effective_stage,
       latest.last_activity_at, latest.assigned_user_id
FROM customers c
LEFT JOIN LATERAL (
    SELECT current_stage, last_activity_at, assigned_user_id
    FROM conversations
    WHERE tenant_id = :t AND customer_id = c.id AND deleted_at IS NULL
    ORDER BY last_activity_at DESC
    LIMIT 1
) latest ON true
WHERE c.tenant_id = :t
```
Single query, no N+1 subqueries.

**Index required:** `conversations(tenant_id, customer_id, deleted_at, last_activity_at DESC)` or equivalent partial index before this ships to large tenants.

**New endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/customers/{id}/score` | PATCH | Set score. Body: `{ "score": 75 }`. Clamp 0-100. |
| `/api/v1/customers/import` | POST | CSV upload. Columns: name, phone. Upserts by normalized `phone_e164`. Returns `{ created: N, updated: N, errors: [...] }`. |
| `/api/v1/customers/export` | GET | CSV download. All customers with: name, phone, effective_stage, score, last_activity. Escape formula-leading cells. |

**CSV safeguards:** max rows per import, E.164 normalization, duplicate report, chunked transaction, and export escaping for values starting with `=`, `+`, `-`, or `@`.

#### 2.3 Frontend

**Rewrite:** `frontend/src/features/customers/components/CustomerSearch.tsx` → `ClientsPage.tsx`

**Components:**
```
frontend/src/features/customers/components/ClientsPage.tsx        # replaces CustomerSearch
frontend/src/features/customers/components/ClientsTable.tsx       # enriched table
frontend/src/features/customers/components/ImportExportBar.tsx    # import/export buttons
frontend/src/features/customers/components/StageFilter.tsx        # stage dropdown filter
```

**Note:** NO kanban view on Clients page. Pipeline page (Module 6) is the kanban.

**ClientsPage:**
- Header: "Clientes" + StageFilter + ImportExportBar
- Table: columns = Nombre, Teléfono, Etapa, Agente, Última actividad, Score
- Import: file input (CSV) -> POST /api/v1/customers/import -> show results toast
- Export: click -> GET /api/v1/customers/export -> browser download

#### 2.4 Tests

```
core/tests/api/test_customers_enhanced.py    # stage derivation, sort, filter, score patch
core/tests/api/test_customers_import.py      # CSV import with upsert, duplicates, errors
core/tests/api/test_customers_export.py      # CSV export content
```

---

### Module 3: Conversations Enhanced

**Size:** M | **Type:** UPGRADE existing | **Dependencies:** Customer fields (exist), Customer notes (exist), P2 (arq force_summary)

#### 3.1 Backend

**No new migrations for the sidebar read path.** If `force_summary` must distinguish AI summaries from manual notes, add a small `customer_notes.source VARCHAR(40) NOT NULL DEFAULT 'manual'` migration first; the current model has no source/type column.

**New endpoint:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/conversations/{id}/force-summary` | POST | Enqueues idempotent arq `force_summary` job. Returns 202 `{ "status": "processing" }`. |

**Enhanced detail response `GET /api/v1/conversations/{id}`:**
Add to response:
- `customer_fields`: list of `{ key, label, field_type, value }` — joined from CustomerFieldDefinition + CustomerFieldValue
- `customer_notes`: last 5 notes — from CustomerNote
- `required_docs`: list of `{ field_name, label, present: bool }` — pipeline's `docs_per_plan[extracted_data.plan_credito]` gives field names (e.g. `docs_ine`, `docs_comprobante`); `present` = `extracted_data[field_name]` (static booleans from `ExtractedFields`)
- `extracted_data`: the full `conversation_state.extracted_data` dict

**Customer field caveat:** field values are currently string-like. Before rendering checkboxes/multiselects/dates as editable controls, either add typed `value_json` storage or implement tested canonical string encoding/decoding per field type.

**`force_summary` arq job:**
1. Load conversation + last 20 messages
2. Call gpt-4o-mini with summary prompt
3. Create CustomerNote with source/type if the migration exists; otherwise create a clearly labeled note body without pretending a `source` column exists.
4. Emit event `CONVERSATION_UPDATED`

**Job safeguards:** make the job idempotent per conversation + message high-water mark so repeated clicks do not create duplicate summaries.

#### 3.2 Frontend

**Enhance:** `frontend/src/features/conversations/components/ContactPanel.tsx` → richer sidebar

**Components:**
```
frontend/src/features/conversations/components/ConversationSidebar.tsx   # replaces/enhances ContactPanel
frontend/src/features/conversations/components/CustomerInfoCard.tsx
frontend/src/features/conversations/components/PlanDropdown.tsx          # change stage inline
frontend/src/features/conversations/components/CustomFieldsCard.tsx      # checkboxes + values
frontend/src/features/conversations/components/InternalNotesCard.tsx     # notes list + "Forzar resumen"
frontend/src/features/conversations/components/DocumentStatusCard.tsx    # doc checklist
```

**ConversationSidebar layout:**
```
┌─────────────────────────┐
│ CustomerInfoCard         │
│ Name, Phone, Channel     │
├─────────────────────────┤
│ PlanDropdown             │
│ [Current Stage ▼]       │
├─────────────────────────┤
│ CustomFieldsCard         │
│ ☑ modelo_moto: Rayo     │
│ ☑ plan_credito: 36m     │
│ ☐ ingreso_mensual       │
├─────────────────────────┤
│ DocumentStatusCard       │
│ ☑ INE                   │
│ ☐ Comprobante domicilio │
│ ☑ Comprobante ingresos  │
├─────────────────────────┤
│ InternalNotesCard        │
│ [Forzar resumen]         │
│ Note 1...               │
│ Note 2...               │
└─────────────────────────┘
```

**PlanDropdown:** Uses hardened PATCH `/api/v1/conversations/{id}` to update `current_stage`. Stages from pipeline definition.

**Precondition:** the existing PATCH endpoint must first pass P0 hardening: typed request, stage validation, assignment validation, tag limits, and `stage_entered_at` synchronization.

**DocumentStatusCard:** Reads `docs_per_plan[current_plan]` from pipeline definition. Each doc shows checked/unchecked based on whether the key exists in `extracted_data`.

**InternalNotesCard:** Lists customer notes. "Forzar resumen" button calls POST `/api/v1/conversations/{id}/force-summary`, then refetches notes after the job completes or after a short polling interval.

#### 3.3 Tests

```
core/tests/api/test_conversations_force_summary.py   # 3 tests: enqueue, job execution, note creation
core/tests/api/test_conversations_detail_enhanced.py  # customer_fields, notes, required_docs in response
```

---

### Module 6: Pipeline Kanban

**Size:** M | **Type:** NEW page, existing data | **Dependencies:** TenantPipeline (exists), Conversations (exist)

#### 6.1 Backend

**No new models or migrations.**

**File:** `core/atendia/api/pipeline_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/pipeline/board` | GET | Returns conversations grouped by stage. Each group: `{ stage_id, stage_label, total_count, timeout_hours, conversations: [...first 50] }`. Conversations include: id, customer_name, customer_phone, last_message_text, last_activity_at, is_stale (bool). |
| `/api/v1/pipeline/board/{stage_id}` | GET | Paginated conversations for a single stage. Query: `cursor`, `limit` (default 50). For "Cargar mas" in large stages. |
| `/api/v1/pipeline/alerts` | GET | Returns conversations past their stage's `timeout_hours`. |

**`is_stale` logic:** prefer `conversation_state.stage_entered_at < now() - interval '{stage.timeout_hours} hours'` so a recent message does not hide a conversation that has sat too long in one stage. Fall back to `last_activity_at` only for legacy rows without `stage_entered_at`.

**Moving stage:** handled by hardened `PATCH /api/v1/conversations/{id}` with `{ "current_stage": "new_stage" }`.

#### 6.2 Frontend

**Route:** `frontend/src/routes/(auth)/pipeline.tsx`

**Components:**
```
frontend/src/features/pipeline/api.ts
frontend/src/features/pipeline/components/PipelineKanbanPage.tsx
frontend/src/features/pipeline/components/StageColumn.tsx
frontend/src/features/pipeline/components/ConversationCard.tsx
frontend/src/features/pipeline/components/AlertsBadge.tsx
```

**PipelineKanbanPage:**
- Header: "Pipeline de Ventas" + subtitle + AlertsBadge ("N alertas") + "Configurar" link → /config
- Info banner (collapsible, same style as v1): explains pipeline stages
- StageColumns: horizontal scroll, one per pipeline stage

**ConversationCard:**
- Customer name (bold)
- Phone (muted)
- Last message excerpt (truncated)
- Time ago
- Alert badge (bell icon, orange) if `is_stale`
- "MOVER A ETAPA" dropdown (stages from pipeline definition)
- Click card → navigates to `/conversations/{id}`

**No drag-and-drop.** Matches v1's dropdown-based approach.

#### 6.3 Tests

```
core/tests/api/test_pipeline_board.py    # grouped response, stale detection, stage filtering
core/tests/api/test_pipeline_alerts.py   # timeout-based alerts
```

---

## Phase C — Power Features (Phased Internally)

### Module 7+8: AI Agents & Configuration

**Size:** L | **Type:** NEW full stack | **Dependencies:** None (maps to existing FlowMode system)

**Key insight:** An "Agent" in v2 is a **named configuration profile** that maps to the existing FlowMode + FlowRouter system. The runner already has 6 FlowModes with distinct prompt blocks, intent-based routing, and configurable composer parameters. An agent overrides these per-conversation.

#### Sub-phase C1: Agent CRUD + Configuration UI

##### C1.1 Database

**Migration `029_agents.py`:**

```sql
CREATE TABLE agents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name              VARCHAR(120) NOT NULL,
    role              VARCHAR(40) NOT NULL DEFAULT 'custom',
    goal              TEXT,
    style             VARCHAR(200),
    tone              VARCHAR(40) DEFAULT 'amigable',
    language          VARCHAR(20) DEFAULT 'es',
    max_sentences     INTEGER DEFAULT 5,
    no_emoji          BOOLEAN NOT NULL DEFAULT false,
    return_to_flow    BOOLEAN NOT NULL DEFAULT true,
    is_default        BOOLEAN NOT NULL DEFAULT false,
    system_prompt     TEXT,
    active_intents    JSONB NOT NULL DEFAULT '[]',
    extraction_config JSONB NOT NULL DEFAULT '{}',
    auto_actions      JSONB NOT NULL DEFAULT '{}',
    knowledge_config  JSONB NOT NULL DEFAULT '{}',
    flow_mode_rules   JSONB,  -- NULL = use tenant defaults
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agents_tenant ON agents (tenant_id);
CREATE UNIQUE INDEX idx_agents_default ON agents (tenant_id) WHERE is_default = true;
```

**Add to conversations:**
```sql
ALTER TABLE conversations ADD COLUMN assigned_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL;
```

**Model:** `core/atendia/db/models/agent.py`

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| tenant_id | UUID | FK tenants |
| name | String(120) | "Dinamo Agent", "OCR-Documentos" |
| role | String(40) | sales, support, collections, documentation, reception, custom |
| goal | Text | "Ayudar al cliente a elegir modelo..." |
| style | String(200) | "asesor comercial mexicano" |
| tone | String(40) | Maps to composer register |
| language | String(20) | es, en |
| max_sentences | int | Maps to composer max_words |
| no_emoji | bool | Maps to composer use_emojis=false |
| return_to_flow | bool | When true, agent yields back to router after task |
| is_default | bool | Partial unique index — only one default per tenant |
| system_prompt | Text | Additional system prompt injected into composer |
| active_intents | JSONB | Exact NLU enum values: `["GREETING", "ASK_PRICE", "SCHEDULE", ...]`. Frontend maps to Spanish labels (ASK_PRICE → "Consulta precio"). Full list: GREETING, ASK_INFO, ASK_PRICE, BUY, SCHEDULE, COMPLAIN, OFF_TOPIC, UNCLEAR. |
| extraction_config | JSONB | Which fields this agent is allowed to extract |
| auto_actions | JSONB | Auto-actions config (stage transitions, field updates) |
| knowledge_config | JSONB | KB access config (which categories, max results) |
| flow_mode_rules | JSONB | Agent-specific FlowModeRules. NULL = use tenant default |

##### C1.2 API

**File:** `core/atendia/api/agents_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/agents` | GET | List agents for tenant. |
| `/api/v1/agents` | POST | Create agent. Validates role, active_intents. |
| `/api/v1/agents/{id}` | GET | Get agent with full config. |
| `/api/v1/agents/{id}` | PATCH | Update agent (partial). |
| `/api/v1/agents/{id}` | DELETE | Delete agent. Cannot delete default if it's the only one. |
| `/api/v1/agents/test` | POST | Test agent config without saving. Body: `{ "agent_config": {...}, "message": "hola" }`. Runs NLU + Composer in-memory with provided config. Returns: `{ response, flow_mode, intent }`. Used by "Probar ahora" tab. |

**RBAC:** agent create/update/delete and default-agent changes require the admin role chosen in P0. Operators may read agents only if needed for assignment UI.

##### C1.3 Frontend

**Route:** `frontend/src/routes/(auth)/agents.tsx`

**Components:**
```
frontend/src/features/agents/api.ts
frontend/src/features/agents/components/AgentsPage.tsx
frontend/src/features/agents/components/AgentList.tsx
frontend/src/features/agents/components/AgentConfigModal.tsx
frontend/src/features/agents/components/tabs/IdentityTab.tsx
frontend/src/features/agents/components/tabs/ExtractionTab.tsx
frontend/src/features/agents/components/tabs/AutoActionsTab.tsx
frontend/src/features/agents/components/tabs/KnowledgeTab.tsx
frontend/src/features/agents/components/tabs/MemoryTab.tsx
frontend/src/features/agents/components/tabs/TestTab.tsx
```

**AgentConfigModal (6 tabs):**

| Tab | Fields |
|-----|--------|
| Identidad | name, role (radio group), goal, style, tone (select), language (select), max_sentences, no_emoji, return_to_flow, is_default, system_prompt (textarea), active_intents (multi-select chips) |
| Datos que extrae | extraction_config editor — list of field names this agent can extract |
| Acciones automáticas | auto_actions editor — rules like "if X extracted, move to stage Y" |
| Conocimiento y seguimientos | knowledge_config — which KB categories, followup templates |
| Memoria IA | Context window settings, conversation history depth |
| Probar ahora | Test chat interface using this agent's config |

##### C1.4 Tests

```
core/tests/api/test_agents_crud.py          # 8 tests: CRUD, default constraint, role validation
```

#### Sub-phase C2: Runner Integration

**Changes to:** `core/atendia/runner/conversation_runner.py`

**Logic:**
1. At start of `run_turn()`, load assigned agent: `conversation.assigned_agent_id` → Agent row
2. If no agent assigned, load tenant's default agent (is_default=true)
3. If no default agent exists, use existing behavior (backward compatible)
4. Override composer input variables from agent config:
   - `bot_name` ← agent.name
   - `register` ← agent.tone
   - `use_emojis` ← not agent.no_emoji
   - `max_words` ← agent.max_sentences * ~20
5. If agent has `flow_mode_rules`, use those instead of tenant pipeline rules
6. If agent has `system_prompt`, append to composer system prompt
7. If agent has `active_intents` and NLU intent not in list → trigger handoff

**Changes to:** `core/atendia/runner/composer_prompts.py` — accept agent overrides in template rendering.

**Backward compatible:** If no agents exist for a tenant, everything works exactly as before.

##### C2 Tests

```
core/tests/runner/test_agent_integration.py  # agent overrides applied, fallback to defaults, intent filter
```

---

### Module 9: Workflows

**Size:** XL | **Type:** NEW full stack | **Dependencies:** Events system (exists), arq (P2), Agents (Module 7, optional)

#### Sub-phase C1: Workflow Engine + API

##### C1.1 Database

**Migration `030_workflows.py`:**

```sql
CREATE TABLE workflows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    trigger_type    VARCHAR(60) NOT NULL,
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    definition      JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}',
    active          BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_workflows_tenant_active ON workflows (tenant_id) WHERE active = true;

CREATE TABLE workflow_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    customer_id     UUID REFERENCES customers(id) ON DELETE SET NULL,
    trigger_event_id UUID,
    status          VARCHAR(20) NOT NULL DEFAULT 'running',  -- running | completed | failed | paused
    current_node_id VARCHAR(100),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    error           TEXT
);
CREATE INDEX idx_wf_exec_workflow ON workflow_executions (workflow_id);
CREATE UNIQUE INDEX idx_wf_exec_idempotent ON workflow_executions (workflow_id, trigger_event_id)
    WHERE trigger_event_id IS NOT NULL;
```

**Models:** `core/atendia/db/models/workflow.py`

**Workflow definition JSONB structure:**
```json
{
  "nodes": [
    {
      "id": "trigger_1",
      "type": "trigger",
      "config": { "event": "field_updated", "field": "galgo" }
    },
    {
      "id": "action_1",
      "type": "assign_agent",
      "config": { "agent_id": "uuid" }
    },
    {
      "id": "action_2",
      "type": "message",
      "config": { "text": "Tu trámite está completo..." }
    },
    {
      "id": "delay_1",
      "type": "delay",
      "config": { "seconds": 3600 }
    },
    {
      "id": "cond_1",
      "type": "condition",
      "config": { "field": "stage", "operator": "eq", "value": "papeleria_completa" }
    }
  ],
  "edges": [
    { "from": "trigger_1", "to": "action_1" },
    { "from": "action_1", "to": "action_2" },
    { "from": "action_2", "to": "delay_1" },
    { "from": "delay_1", "to": "cond_1" },
    { "from": "cond_1", "to": "action_3", "label": "true" },
    { "from": "cond_1", "to": "action_4", "label": "false" }
  ]
}
```

**Trigger types:**
- `message_received` — new inbound message
- `field_updated` — extracted field changed (config: field name)
- `stage_changed` — conversation stage changed (config: from, to)
- `conversation_created` — new conversation
- `appointment_created` — new appointment
- `bot_paused` — bot paused for human

**Action node types:**
- `message` — send a message (config: text or template_id)
- `move_stage` — change conversation stage (config: stage_id)
- `assign_agent` — assign agent to conversation (config: agent_id)
- `notify_agent` — send notification (config: user_id or role)
- `update_field` — update extracted_data field (config: field, value)
- `pause_bot` — set bot_paused=true
- `delay` — wait N seconds before next node (config: seconds)
- `condition` — evaluate condition, route to true/false edge (config: field with dot notation, operator, value). Field namespace: `conversation.current_stage`, `extracted.docs_ine`, `customer.score`. Default namespace = `extracted`.

##### C1.2 Workflow Engine

**File:** `core/atendia/workflows/engine.py`

**`evaluate_triggers(event)`:**
1. Load all active workflows for the tenant
2. For each workflow, check if trigger_type matches event type
3. If trigger_config matches (e.g., field name), start execution
4. Idempotency: unique constraint on (workflow_id, trigger_event_id)

**Trigger safeguards:** ignore events produced by the same workflow execution unless explicitly allowed, and persist an event cursor per tenant for the cron backup so missed events are replayed once.

**`execute_workflow(execution_id)`:**
1. Load execution + workflow definition
2. Start at first node after trigger (follow edges)
3. For each node:
   - `message` → enqueue arq `send_outbound`
   - `move_stage` → UPDATE conversation
   - `assign_agent` → UPDATE conversation
   - `update_field` → UPDATE conversation_state.extracted_data
   - `pause_bot` → UPDATE conversation_state.bot_paused
   - `delay` → save current_node_id, enqueue `execute_workflow_step` with _defer_by
   - `condition` → evaluate, follow true/false edge
4. On completion: status=completed, finished_at=now()
5. On error: **stop on first error**. status=failed, current_node_id=failed node, error=str(e). Manual retry via `POST /api/v1/workflows/{id}/executions/{exec_id}/retry` resumes from failed node. No auto-retry.

**Execution safeguards:** validate definitions before activation: known node types, existing stage/agent/user references, no unreachable nodes, no ambiguous condition branches, max delay, max total steps, and either acyclic graph or explicit loop limit. Every side-effecting node needs an action idempotency key so retries do not send duplicate messages or duplicate notifications.

**Hook point:** After `ConversationRunner.run_turn()` completes, call `evaluate_triggers(event)` for the emitted events. This is the inline trigger path.

**Cron backup:** `poll_workflow_triggers` reads events table since last cursor, evaluates triggers for any missed events.

##### C1.3 API

**File:** `core/atendia/api/workflows_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/workflows` | GET | List workflows for tenant. |
| `/api/v1/workflows` | POST | Create workflow (name, trigger_type, trigger_config, definition). |
| `/api/v1/workflows/{id}` | GET | Get workflow with full definition. |
| `/api/v1/workflows/{id}` | PATCH | Update workflow. |
| `/api/v1/workflows/{id}` | DELETE | Delete workflow + executions. |
| `/api/v1/workflows/{id}/toggle` | POST | Toggle active on/off after definition validation. |
| `/api/v1/workflows/{id}/executions` | GET | List executions for workflow (audit log). |
| `/api/v1/workflows/{id}/executions/{exec_id}/retry` | POST | Retry failed execution from the failed node. |

**RBAC:** workflow authoring/toggle/retry require the admin role chosen in P0. Operators may view execution history only if it is part of debugging permissions.

##### C1.4 Tests

```
core/tests/api/test_workflows_crud.py           # CRUD + toggle
core/tests/workflows/test_engine_triggers.py     # trigger matching, idempotency
core/tests/workflows/test_engine_execution.py    # action execution, delay handling, condition branching
```

#### Sub-phase C2: Form-Based Editor

**Components:**
```
frontend/src/features/workflows/api.ts
frontend/src/features/workflows/components/WorkflowsPage.tsx
frontend/src/features/workflows/components/WorkflowList.tsx
frontend/src/features/workflows/components/WorkflowFormEditor.tsx
frontend/src/features/workflows/components/TriggerConfig.tsx
frontend/src/features/workflows/components/ActionStepList.tsx
frontend/src/features/workflows/components/ActionStepConfig.tsx
```

**WorkflowFormEditor:** Sequential form-based editor.
1. Select trigger type + configure
2. Add action steps sequentially (+ button to add, drag to reorder)
3. Each step: select type (message, move_stage, assign_agent, etc.) + configure
4. Condition nodes show as if/else with two branches
5. Preview mode: shows the node graph (read-only rendering)
6. Save button → serializes to JSONB definition

This is functional without the full visual editor.

#### Sub-phase C3: Visual React Flow Editor

**Frontend dep to install:** `npm install @xyflow/react` (React Flow v12)

**Components:**
```
frontend/src/features/workflows/components/WorkflowVisualEditor.tsx
frontend/src/features/workflows/components/nodes/TriggerNode.tsx
frontend/src/features/workflows/components/nodes/ActionNode.tsx
frontend/src/features/workflows/components/nodes/ConditionNode.tsx
frontend/src/features/workflows/components/nodes/DelayNode.tsx
frontend/src/features/workflows/components/NodePalette.tsx
frontend/src/features/workflows/components/NodeConfigPanel.tsx
```

**WorkflowVisualEditor:**
- Left panel: NodePalette (draggable node types, grouped by INICIO/LOGICA/ACCIONES)
- Center: React Flow canvas with custom node components
- Right panel: NodeConfigPanel (shows config for selected node)
- Top: workflow name + "Guardar" button
- Serialization: React Flow nodes/edges → JSONB definition, bidirectional

**Dependencies:** `@xyflow/react` (React Flow v12).

---

## Dependency Graph

```
Prerequisites ──► P1 (File Storage) ──► Module 5 (KB)
              ──► P2 (arq expansion) ──► Module 5 (KB)
              │                      ──► Module 3 (Conv Enhanced)
              │                      ──► Module 9 (Workflows)
              ──► P3 (Tenant timezone) ──► Module 1 (Dashboard)
              │                        ──► Module 4 (Appointments)
              ──► P4 (Notifications) ──► Module 9 (Workflows notify_agent action)

Phase A:  Module 4 (Appointments) ──► Module 1 (Dashboard needs appointment data)
          Module 5 (KB) ───────────┘
          Module 10 (Integrations) ─┘

Phase B:  Module 2 (Clients, table only) ── independent
          Module 3 (Conv Enhanced) ───────── needs P2
          Module 6 (Pipeline Kanban) ─────── independent

Phase C:  Module 7+8 C1 (Agent CRUD) ──► C2 (Runner integration)
          Module 9 C1 (Engine, needs P4) ──► C2 (Form editor) ──► C3 (Visual editor)
          Module 9 optionally uses Module 7 (assign_agent action)
```

---

## Migration Registry

| Number | Module | Description |
|--------|--------|-------------|
| 025 | Prerequisites | Add `timezone` to `tenants`, create `notifications` table |
| 026 | Appointments | Create `appointments` table |
| 027 | Knowledge Base | Create `knowledge_documents` + `knowledge_chunks` tables |
| 028 | Knowledge Base | Add `tags`, `use_count` to `tenant_catalogs` |
| 029 | Clients | Add `score` to `customers` |
| 030 | Agents | Create `agents` table + add `assigned_agent_id` to conversations |
| 031 | Workflows | Create `workflows` + `workflow_executions` tables |

Before creating any new revision, run `alembic heads` and confirm exactly one head. Use Alembic-generated revision IDs; the numeric filenames are sequencing labels, not the actual source of truth.

---

## Nav Sidebar Changes

**Final sidebar order:**

```
Dashboard           /dashboard          (NEW - Phase A)
Conversaciones      /                   (existing, unchanged)
Pipeline            /pipeline           (NEW - Phase B)
Clientes            /customers          (existing, enhanced)
Citas               /appointments       (NEW - Phase A)
Agentes IA          /agents             (NEW - Phase C)
Flujos de Trabajo   /workflows          (NEW - Phase C)
Base de Conocimiento /knowledge         (NEW - Phase A)
Handoffs            /handoffs           (existing)
Analítica           /analytics          (existing)
Configuración       /config             (existing, +Integrations tab)
Debug de turnos     /turn-traces        (existing)
Usuarios            /users              (superadmin, existing)
Auditoría           /audit-log          (superadmin, existing)
Exportar            /exports            (existing)
```

---

## Implementation Notes

### For Each Module

Default execution is one narrowly scoped module or component per session. Use parallel subagents only if the user explicitly asks for parallel agent work. If parallel work is approved, split into disjoint ownership areas:
1. **Backend**: migration + model + API routes + tests
2. **Frontend**: route + components + API client
3. **Integration test**: browser verification

Never mark a broad module "done" because these three buckets exist. Mark only the verified user workflow done.

### Testing Strategy

- Backend: pytest with async fixtures, httpx test client
- Frontend: typecheck/lint plus browser verification via preview
- Each module has its own test file(s) in `core/tests/api/`
- Unsafe endpoints: CSRF, tenant scoping, and RBAC tests are mandatory.
- UI parity: browser screenshot or side-by-side verification against the v1 workflow is mandatory before calling the module complete.

### Estimated Sizes (for planning)

| Phase | Module | Backend Tasks | Frontend Tasks | Total Estimate |
|-------|--------|---------------|----------------|----------------|
| A | Appointments | 2 | 2 | S-M |
| A | Knowledge Base | 4 | 3 | L |
| A | Integrations | 1 | 1 | XS |
| A | Dashboard | 1 | 2 | S-M |
| B | Clients Enhanced | 2 | 2 | M |
| B | Conversations Enhanced | 2 | 2 | M |
| B | Pipeline Kanban | 1 | 2 | S-M |
| C | Agents C1 | 2 | 3 | M-L |
| C | Agents C2 | 1 | 0 | S |
| C | Workflows C1 | 3 | 0 | L |
| C | Workflows C2 | 0 | 3 | M |
| C | Workflows C3 | 0 | 3 | L |

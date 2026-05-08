# V1 → V2 Parity: Modular Implementation Plan

**Date:** 2026-05-08
**Status:** Approved
**Scope:** 10 modules covering full v1 feature parity + infrastructure prerequisites

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Infrastructure Prerequisites](#infrastructure-prerequisites)
3. [Phase A — Foundation](#phase-a--foundation-new-pages--quick-wins)
4. [Phase B — Enhance Core](#phase-b--enhance-core-upgrade-existing-pages)
5. [Phase C — Power Features](#phase-c--power-features-phased-internally)
6. [Dependency Graph](#dependency-graph)
7. [Migration Registry](#migration-registry)
8. [Nav Sidebar Changes](#nav-sidebar-changes)

---

## Architecture Overview

### What V2 Already Has

| System | Status |
|--------|--------|
| Auth + Users + Roles | Complete |
| Customers table + search | Basic (3 columns) |
| Conversations + Messages + ChatWindow | Substantial |
| WhatsApp Cloud API webhook + outbound | Working |
| Bot pause / Human handoff | Working |
| Customer notes (CRUD) | Complete |
| Customer field definitions + values (EAV) | Complete |
| Pipeline config editor (JSONB stages) | Working |
| TenantFAQ + TenantCatalog + embeddings | Backend only, no UI |
| Analytics (funnel, cost, volume) | Basic |
| Flow router (8 trigger types, 6 FlowModes) | Working |
| NLU with intent detection (8 intents) | Working |
| Composer with FlowMode-specific prompts | Working |
| arq worker (send_outbound + poll_followups) | Working |
| Turn traces / Debug | Complete |
| Audit log | Complete |
| Exports | Working |
| Conversation tags, unread, assign, soft-delete | Just merged |
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

---

## Infrastructure Prerequisites

Build these BEFORE any module. Both are small (1-2 days total).

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

**Config addition:** Add `upload_dir: str = "./uploads"` to `Settings`.

**Production upgrade path:** Create `S3StorageBackend` implementing same protocol. Swap via env var `STORAGE_BACKEND=local|s3`.

---

### P2: arq Worker Expansion

**Why:** Modules 3, 5, 9 need background job processing beyond send_outbound and poll_followups.

**New job functions to register:**

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

**Job files:**
```
core/atendia/queue/index_document_job.py
core/atendia/queue/force_summary_job.py
core/atendia/queue/workflow_jobs.py
```

---

## Phase A — Foundation (New Pages + Quick Wins)

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
| `/api/appointments` | GET | List appointments. Query params: `date_from`, `date_to`, `customer_id`, `status`. Paginated. |
| `/api/appointments` | POST | Create appointment. Body: customer_id, scheduled_at, service, notes. |
| `/api/appointments/{id}` | PATCH | Update appointment (partial update, same raw JSON pattern as conversations). |
| `/api/appointments/{id}` | DELETE | Hard delete (appointments are not soft-deleted). |

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

#### 4.4 Tests

```
core/tests/api/test_appointments_crud.py     # 8-10 tests: create, list, filter by date, update status, delete
```

---

### Module 5: Knowledge Base UI

**Size:** L | **Type:** NEW frontend + backend enhancements | **Dependencies:** P1, P2

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
| `/api/knowledge/faqs` | GET | List FAQs. Paginated. |
| `/api/knowledge/faqs` | POST | Create FAQ (question, answer, tags). Auto-embeds. |
| `/api/knowledge/faqs/{id}` | PATCH | Update FAQ. Re-embeds if question/answer changed. |
| `/api/knowledge/faqs/{id}` | DELETE | Delete FAQ. |

**Catalog sub-routes:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/knowledge/catalog` | GET | List catalog items. Filter by category. |
| `/api/knowledge/catalog` | POST | Create item (name, sku, category, attrs, tags). Auto-embeds. |
| `/api/knowledge/catalog/{id}` | PATCH | Update item. Re-embeds if name/attrs changed. |
| `/api/knowledge/catalog/{id}` | DELETE | Delete item. |

**Documents sub-routes:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/knowledge/documents` | GET | List documents with status + fragment_count. |
| `/api/knowledge/documents/upload` | POST | Upload file (multipart). Saves via StorageBackend. Creates row status=processing. Enqueues arq `index_document`. Returns 202. |
| `/api/knowledge/documents/{id}` | GET | Get single document details. |
| `/api/knowledge/documents/{id}` | DELETE | Delete document + its chunks + file from storage. |

**Test sub-route:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/knowledge/test` | POST | Body: `{ "query": "string" }`. Runs vector similarity search across FAQs + catalog + document chunks. Returns: `{ answer: string, sources: [{ type, id, text, score }] }`. Uses gpt-4o-mini for answer generation. |

**`index_document` arq job:**
1. Read file from storage
2. Parse content (PDF via `pymupdf`, DOCX via `python-docx`, TXT/CSV direct read)
3. Split into chunks (~500 tokens each, 50 token overlap)
4. Embed each chunk via `text-embedding-3-large`
5. Batch insert into `knowledge_chunks`
6. Update `knowledge_documents` row: status=indexed, fragment_count=N
7. On error: status=error, error_message=str(e)

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

**No new models or migrations.** WhatsApp status derived from existing tenant config + Redis.

**File:** `core/atendia/api/integrations_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/integrations/whatsapp/status` | GET | Returns: connected (bool), phone_number, business_name, last_webhook_at (from Redis timestamp), phone_number_id. Read from tenant config JSONB + Redis key. |

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

---

### Module 1: Dashboard

**Size:** M | **Type:** NEW page | **Dependencies:** Customers, Conversations, Appointments (Module 4)

#### 1.1 Backend

**No new models.** Pure aggregation queries.

**File:** `core/atendia/api/dashboard_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard/summary` | GET | Single aggregation endpoint returning all dashboard data. |

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

**Queries (all in single endpoint, parallel with asyncio.gather):**
- `total_customers`: `SELECT count(*) FROM customers WHERE tenant_id = :t`
- `conversations_today`: `SELECT count(*) FROM conversations WHERE tenant_id = :t AND created_at >= :today AND deleted_at IS NULL`
- `active_conversations`: `SELECT count(*) FROM conversations WHERE tenant_id = :t AND status = 'active' AND deleted_at IS NULL`
- `unanswered_conversations`: `SELECT count(*) FROM conversations WHERE tenant_id = :t AND unread_count > 0 AND deleted_at IS NULL`
- `todays_appointments`: `SELECT ... FROM appointments WHERE tenant_id = :t AND scheduled_at::date = :today ORDER BY scheduled_at` (graceful empty if table missing)
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

**Enhanced list endpoint `GET /api/customers`:**
New query params: `stage`, `assigned_user_id`, `sort_by` (name, last_activity, score), `sort_dir` (asc, desc).

New response fields per customer:
- `effective_stage`: derived from most recent active conversation's `current_stage`. SQL: `SELECT current_stage FROM conversations WHERE customer_id = :c AND deleted_at IS NULL ORDER BY last_activity_at DESC LIMIT 1`
- `last_activity_at`: derived from most recent conversation's `last_activity_at`
- `assigned_user_email`: from the most recent conversation's `assigned_user_id` join
- `score`: from customer record

**New endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/customers/{id}/score` | PATCH | Set score. Body: `{ "score": 75 }` |
| `/api/customers/import` | POST | CSV upload. Columns: name, phone. Upserts by phone_e164. Returns `{ created: N, updated: N, errors: [...] }` |
| `/api/customers/export` | GET | CSV download. All customers with: name, phone, effective_stage, score, last_activity. |

#### 2.3 Frontend

**Rewrite:** `frontend/src/features/customers/components/CustomerSearch.tsx` → `ClientsPage.tsx`

**Components:**
```
frontend/src/features/customers/components/ClientsPage.tsx        # replaces CustomerSearch
frontend/src/features/customers/components/ClientsTable.tsx       # enriched table
frontend/src/features/customers/components/ClientsKanban.tsx      # kanban view
frontend/src/features/customers/components/ViewToggle.tsx         # table/kanban switch
frontend/src/features/customers/components/ImportExportBar.tsx    # import/export buttons
frontend/src/features/customers/components/StageFilter.tsx        # stage dropdown filter
```

**ClientsPage:**
- Header: "Clientes" + ViewToggle (table | kanban) + StageFilter + ImportExportBar
- Table view: columns = Nombre, Teléfono, Etapa, Agente, Última actividad, Score
- Kanban view: columns from pipeline stages, customer cards grouped by effective_stage
- Import: file input (CSV) → POST /api/customers/import → show results toast
- Export: click → GET /api/customers/export → browser download

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

**No new migrations.** All data sources already exist.

**New endpoint:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/conversations/{id}/force-summary` | POST | Enqueues arq `force_summary` job. Returns 202 `{ "status": "processing" }`. |

**Enhanced detail response `GET /api/conversations/{id}`:**
Add to response:
- `customer_fields`: list of `{ key, label, field_type, value }` — joined from CustomerFieldDefinition + CustomerFieldValue
- `customer_notes`: last 5 notes — from CustomerNote
- `required_docs`: list of `{ name, present: bool }` — derived from pipeline's `docs_per_plan[current_plan]` cross-checked with `extracted_data` keys
- `extracted_data`: the full `conversation_state.extracted_data` dict

**`force_summary` arq job:**
1. Load conversation + last 20 messages
2. Call gpt-4o-mini with summary prompt
3. Create CustomerNote with `{ source: "ai_summary", text: summary }`
4. Emit event `CONVERSATION_UPDATED`

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

**PlanDropdown:** Uses existing PATCH `/api/conversations/{id}` to update `current_stage`. Stages from pipeline definition.

**DocumentStatusCard:** Reads `docs_per_plan[current_plan]` from pipeline definition. Each doc shows checked/unchecked based on whether the key exists in `extracted_data`.

**InternalNotesCard:** Lists customer notes. "Forzar resumen" button calls POST `/api/conversations/{id}/force-summary`, then refetches notes after 5s.

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
| `/api/pipeline/board` | GET | Returns conversations grouped by stage. Each group: `{ stage_id, stage_label, count, timeout_hours, conversations: [...] }`. Conversations include: id, customer_name, customer_phone, last_message_text, last_activity_at, is_stale (bool). Limited to 50 per stage. |
| `/api/pipeline/alerts` | GET | Returns conversations past their stage's `timeout_hours`. |

**`is_stale` logic:** `last_activity_at < now() - interval '{stage.timeout_hours} hours'`. Uses `StageDefinition.timeout_hours` from the active pipeline.

**Moving stage:** Already handled by existing `PATCH /api/conversations/{id}` with `{ "current_stage": "new_stage" }`.

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
| active_intents | JSONB | `["GREETING", "PRICE_QUERY", ...]` — permission filter |
| extraction_config | JSONB | Which fields this agent is allowed to extract |
| auto_actions | JSONB | Auto-actions config (stage transitions, field updates) |
| knowledge_config | JSONB | KB access config (which categories, max results) |
| flow_mode_rules | JSONB | Agent-specific FlowModeRules. NULL = use tenant default |

##### C1.2 API

**File:** `core/atendia/api/agents_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents` | GET | List agents for tenant. |
| `/api/agents` | POST | Create agent. Validates role, active_intents. |
| `/api/agents/{id}` | GET | Get agent with full config. |
| `/api/agents/{id}` | PATCH | Update agent (partial). |
| `/api/agents/{id}` | DELETE | Delete agent. Cannot delete default if it's the only one. |

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
- `condition` — evaluate condition, route to true/false edge (config: field, operator, value)

##### C1.2 Workflow Engine

**File:** `core/atendia/workflows/engine.py`

**`evaluate_triggers(event)`:**
1. Load all active workflows for the tenant
2. For each workflow, check if trigger_type matches event type
3. If trigger_config matches (e.g., field name), start execution
4. Idempotency: unique constraint on (workflow_id, trigger_event_id)

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
5. On error: status=failed, error=str(e)

**Hook point:** After `ConversationRunner.run_turn()` completes, call `evaluate_triggers(event)` for the emitted events. This is the inline trigger path.

**Cron backup:** `poll_workflow_triggers` reads events table since last cursor, evaluates triggers for any missed events.

##### C1.3 API

**File:** `core/atendia/api/workflows_routes.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workflows` | GET | List workflows for tenant. |
| `/api/workflows` | POST | Create workflow (name, trigger_type, trigger_config, definition). |
| `/api/workflows/{id}` | GET | Get workflow with full definition. |
| `/api/workflows/{id}` | PATCH | Update workflow. |
| `/api/workflows/{id}` | DELETE | Delete workflow + executions. |
| `/api/workflows/{id}/toggle` | POST | Toggle active on/off. |
| `/api/workflows/{id}/executions` | GET | List executions for workflow (audit log). |

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
                                     ──► Module 3 (Conv Enhanced)
                                     ──► Module 9 (Workflows)

Phase A:  Module 4 (Appointments) ──► Module 1 (Dashboard needs appointment data)
          Module 5 (KB) ───────────┘
          Module 10 (Integrations) ─┘

Phase B:  Module 2 (Clients) ─── independent
          Module 3 (Conv) ─────── needs P2
          Module 6 (Pipeline) ── independent

Phase C:  Module 7+8 C1 (Agent CRUD) ──► C2 (Runner integration)
          Module 9 C1 (Engine) ──► C2 (Form editor) ──► C3 (Visual editor)
          Module 9 optionally uses Module 7 (assign_agent action)
```

---

## Migration Registry

| Number | Module | Description |
|--------|--------|-------------|
| 025 | Appointments | Create `appointments` table |
| 026 | Knowledge Base | Create `knowledge_documents` + `knowledge_chunks` tables |
| 027 | Knowledge Base | Add `tags`, `use_count` to `tenant_catalogs` |
| 028 | Clients | Add `score` to `customers` |
| 029 | Agents | Create `agents` table + add `assigned_agent_id` to conversations |
| 030 | Workflows | Create `workflows` + `workflow_executions` tables |

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

### For Each Module (subagent pattern)

Each module should be implemented as 2-3 subagent tasks:
1. **Backend**: migration + model + API routes + tests
2. **Frontend**: route + components + API client
3. **Integration test**: browser verification

### Testing Strategy

- Backend: pytest with async fixtures, httpx test client
- Frontend: manual browser verification via preview
- Each module has its own test file(s) in `core/tests/api/`

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

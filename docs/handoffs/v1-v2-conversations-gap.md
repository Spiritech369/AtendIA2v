# Handoff: v1 → v2 Conversations page — gap analysis

> **Read this first if you are picking up after the Phase 4 trust break.**
> The previous session marked "Phase 4 done" but the frontend ships at
> roughly 20% of v1's quality. This doc is the verifiable gap so the next
> session can rebuild step-by-step instead of declaring victory.

## Working contract (renegotiated 2026-05-08)

| Rule | Why |
|---|---|
| **One component / one page per session.** Bigger scope → ask first. | Previous session shipped 60 tasks in one batch and oversold "complete" on every one. |
| **"Done" only when it looks ≥ v1.** Scope-reduced ⇒ say so in **bold red**, not in the footnote. | Multiple T-tasks landed at minimum-viable and were called done. |
| **The user picks what to cut.** Estimate cost (1h vs 1d), they decide. | Previous session decided unilaterally to skip Tremor, Storybook, browser notifications, full E2E, etc. |
| **No green emojis until verified in browser.** Summary = what changed + path + how to verify. | Self-celebratory tone hid that the deliverable was thin. |
| **No code-reviewer agent unless requested.** | Previous session ran review on Block A and C+D; rest got nothing. |
| **Branch per feature, show diff before merge.** | Previous session pushed straight to main. |

If the new session breaks one of these, the user calls it by number and the session pauses.

---

## Verifiable file sizes (do not trust, run `wc -l` yourself)

```
v1 (C:\Users\Sprt\Documents\Proyectos IA\1. Trabajando\2. Asistente de ventas)
  frontend/src/pages/Conversations/
    Conversations.jsx       1207 lines
    ContactPanel.jsx         446 lines
    DebugPanel.jsx           497 lines
    QuickReplies.jsx         148 lines
                  TOTAL:    2298 lines

v2 (C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2)
  frontend/src/features/conversations/components/
    ConversationDetail.tsx   140 lines
    ConversationList.tsx     155 lines
    InterventionComposer.tsx 109 lines
    MessageBubble.tsx         40 lines
                  TOTAL:     444 lines
```

**v2 ships at 19% of v1's volume.** Volume isn't quality, but in this
case the volume gap maps to a feature gap (see below).

---

## Component-by-component gap

### 1. Conversation list (left sidebar)

**v1** (`Conversations.jsx:105-289`):
- Search input persisted to `sessionStorage` (`conv_search`)
- Tab selector persisted to `sessionStorage` (`conv_tab`) — tabs separate "chats" / "calls" / etc.
- Mailbox sections persisted to `sessionStorage` (`conv_mailbox`):
  - **Main**: Todos / Míos / Sin asignar / Llamadas entrantes — each with live count
  - **AI agents**: dynamic list of which AI agents are active in conversations + count per agent
  - **Pipeline stages**: dynamic list of pipeline stages (`nuevo`, `interesado`, `contactado`, `cotizado`, `cerrado`) + count per stage
- Per-conversation row shows:
  - Customer name OR phone fallback (`getConversationLabel`)
  - Origin label (`getOriginLabel` from `customer_metadata.origin / origin_label / source / utm_source / referrer`)
  - Tags (parsed from comma-string or array)
  - Active AI agent name (if any)
  - WhatsApp connection lock indicator (icon if `locks[id]`)
  - Unread count badge (from `unread` map)
  - Status dot + label from `STATUS_LABELS` (`active`/`waiting_human`/`with_human`/`closed`)
- **Right-click context menu** (`ConversationContextMenu` at line 664) with actions: pipeline-stage assign, delete, archive, etc.

**v2** (`ConversationList.tsx`):
- shadcn Table with 5 columns (Cliente / Último mensaje / Etapa / Estado / Última actividad)
- Linear list, no mailbox concept
- No search
- No tabs
- No persistence (state lost on reload)
- No right-click menu
- No tag display
- No origin / source attribution
- No AI agent column
- No unread tracking
- No assignment lock indicator

**Gap severity:** 🔴 **MASSIVE.** v2 is a flat table; v1 is a triaged inbox.

---

### 2. Header / status badge above the conversation

**v1** (`Conversations.jsx:46-77` + integration in `ChatWindow`):
- `WhatsAppStatusBadge` polls `/whatsapp/status` and `/automation-config/status` every 10s
- Shows colored dot:
  - Green: connected
  - Amber + pulse: reconnecting/starting
  - Red: logged_out OR circuit breaker open
- Live label updates (`WhatsApp conectado` / `Reconectando…` / `WA pausado`)

**v2**:
- AppShell header shows static "Tenant: <uuid>" — no WhatsApp status, no circuit breaker, no live polling
- No "WA pausado" indicator anywhere

**Gap severity:** 🔴 **CRITICAL for production ops.** Without this, an operator has no idea if the bot is actually online.

---

### 3. Message rendering / chat window

**v1** (`Conversations.jsx:429-663` ChatWindow):
- Internal-notes-aware text cleanup (`cleanInternalNotes` strips `[AI_CONTEXT_SUMMARY]…[/AI_CONTEXT_SUMMARY]` blocks before display)
- `MediaContent` component renders inline images / audio / documents / video (line 291)
- `SKIPPED_CONTENT` array filters out raw `[imagen]` / `[audio]` / `[documento]` / `[video]` placeholders
- Per-message context (read state, delivery status, source — operator/bot/customer)
- **Click-on-message** opens `DebugPanel` showing full pipeline trace for that specific message
- Message-level actions: copy, edit, delete (where allowed)
- Long-running internal notes summary card (`InternalNotesCard:299`) with refresh-summary button calling `/customers/:id/refresh-summary`

**v2** (`MessageBubble.tsx` + `ConversationDetail.tsx`):
- 40-line `MessageBubble` — bubble shape, inbound/outbound/system styling, sent_at footer
- No media support (`text` field only)
- No click-to-debug
- No copy/edit/delete on individual messages
- No internal-notes summary card

**Gap severity:** 🔴 **HIGH.** Click-to-debug + media = daily operator workflows.

---

### 4. Composer (where operator types reply)

**v1** (`ChatWindow` send logic + `QuickReplies.jsx`):
- Textarea with autocomplete via `/` slash command (opens `QuickReplies` panel)
- Template browser (button "Plantillas") with:
  - Search by name / content / intent
  - Filter by detected intent (auto-passes current intent from message)
  - Variable interpolation (`{{nombre_cliente}}`, `{{telefono}}`, `{{precio}}`, `{{servicio}}`)
  - Track template usage to `/knowledge/templates/:id/track-use` (for A/B + analytics)
- Send button + Cmd/Ctrl+Enter shortcut
- Status feedback (sending, sent, failed)
- **Inline AI assistant** (the `Sparkles` icon import) — generate suggested reply

**v2** (`InterventionComposer.tsx`):
- Plain textarea
- "Tomar control" / "Devolver al bot" toggle
- Cmd/Ctrl+Enter sends
- No templates / no slash command / no variables / no AI suggest

**Gap severity:** 🟠 **HIGH.** Templates are a daily operator productivity multiplier.

---

### 5. Right-side info panel

**v1** (`ContactPanel.jsx`, full 446 lines):
- **Collapsible** (12px collapsed strip with icon + chevron)
- **Basic info card**: editable name + email + phone (read-only) + Save button calling `PUT /customers/:id`
- **Custom fields card**: dynamic schema from `/customer-fields/definitions`
  - Supports field types: `text`, `number`, `date`, `select`, `multiselect`, `checkbox`
  - `select`/`multiselect` parse options from `field_options` JSON
  - Per-customer values via `/customer-fields/:id/values` GET + PUT
  - Save button only saves what changed
- **Notes section** (`NotesSection:107`):
  - Full CRUD via `notesApi`: create / update / delete / pin
  - Pin highlights with amber border
  - Edit-in-place textarea
  - Author name + relative timestamp (`Hoy 14:32` if today, else full date)
  - "edited" marker when `updated_at !== created_at`
  - Ctrl+Enter shortcut to save
  - Confirmation dialog on delete

**v2** (right side of `ConversationDetail.tsx`):
- 50 lines max
- Shows `last_intent` (read-only)
- Shows `pending_confirmation` banner (read-only)
- Shows `extracted_data` as raw JSON in a `<pre>` block

**Gap severity:** 🔴 **MASSIVE.** v2 has no notes, no custom fields, no contact editing. The operator can't update a customer's name from the dashboard.

---

### 6. Debug panel

**v1** (`DebugPanel.jsx`, full 497 lines): per-message inspector showing
- **Mode** (current `mode`, change indicator with `← prev_mode`, `trigger_rule` text)
- **Intent** + confidence bar (rendered as % bar, 0-100)
- **Recorrido** (the most useful section — flow journey):
  - Cleaned message text
  - Agent name / role / tone
  - History message count
  - LLM provider used
  - Response origin (template / model / fallback)
  - Media kind + MIME + classification confidence
  - Fact pack (consolidated facts injected) shown as JSON
  - LLM raw response preview vs final response (catches post-processing differences)
  - **Per-step cards** with status (info/warning/error) + per-step data dump
- **Entities**: green pill = extracted+saved, yellow pill = extracted but NOT saved (catches schema drift)
- **Knowledge use**:
  - Source priority (ordered list)
  - Enabled / consulted / used sources (separate badges)
  - Hits per source (count)
  - Items used (specific KB article IDs)
  - Citas / evidence with snippet + similarity score + filename
- **Actions**: list of every state-changing action
- **Pipeline latency**: bars per stage (classify / entity_extract / mode_route / action_engine / llm) + total ms
- **LLM**: model name + tokens in/out + response template format/sentences/CTA
- **Rules evaluated**: pass/fail per rule
- **Errors**: list of errors + fallback indicator

**v2** (`features/turn-traces/components/TurnTraceInspector.tsx`):
- Modal Dialog with 5 tabs: NLU / Composer / Estado / Outbound / Raw
- Each tab is `<pre>{JSON.stringify(value, null, 2)}</pre>`
- No bars, no charts, no traces, no per-step UX
- Backend `/api/v1/turn-traces` returns the data but the UI is JSON dumps

**Gap severity:** 🔴 **CRITICAL for v2's main pain (coherence debugging).** Without this, the operator can't see *why* the bot said what it said. v2 has the data (`turn_traces` table); the UI is the missing piece.

---

### 7. Real-time / WebSocket

**v1**: `useWebSocket()` hook with multi-listener pattern (`addListener`). Handles inbound message arrival, status changes, lock changes (someone else is replying), AI-agent assignment changes, pipeline-stage changes.

**v2**: `useTenantStream` invalidates 4 query keys on every event (over-invalidates per Block C+D code review note). No specific message arrival event handling beyond invalidation.

**Gap severity:** 🟡 **MEDIUM.** v2 works but does refetch storms instead of patches.

---

## What v2 has that v1 doesn't (the wins to keep)

- TanStack Router type-safe paths
- TanStack Query infinite-query pattern (cleaner than v1's manual pagination)
- shadcn vendored components (faster iteration if we use them)
- TS strict everywhere (v1 is JS)
- Single-Docker deploy via FastAPI StaticFiles (v1 uses Caddy + nginx + 3 services)
- Multi-tenant from day 1 (v1 is hardcoded "Dinamo")
- Multi-tenant tenant-scoped queries verified by tests
- shadcn `Dialog` for modals (v1 uses inline panels)

These are **architecture wins from the rebuild.** Don't undo them when porting v1 features.

---

## Recommended next-session sequence

The user asked to start with **Conversations / ContactPanel / DebugPanel** since it's the most-used operator screen. The sequence below is granular enough that each step has clear acceptance criteria you can check in the browser.

### Step 1: Backend prep — endpoints v2 needs

(Estimated: 1 session, 2-3 commits)

Migrate / add to v2 backend:
1. `customer_notes` table (id, customer_id, tenant_id, author_user_id, content, pinned, created_at, updated_at)
2. `customer_field_definitions` table (id, tenant_id, key, label, field_type, field_options JSONB, ordering)
3. `customer_field_values` table (customer_id, field_definition_id, value, updated_at) — composite PK
4. Routes:
   - `GET/POST/PATCH/DELETE /api/v1/customers/:id/notes` (5 endpoints)
   - `PATCH /api/v1/customers/:id` (basic info edit)
   - `GET /api/v1/customer-fields/definitions` (tenant-scoped)
   - `POST/PATCH/DELETE /api/v1/customer-fields/definitions/:id` (admin)
   - `GET/PUT /api/v1/customers/:id/field-values`
5. Tests for each: tenant scoping, CSRF, RBAC

**Acceptance: 5 new test files green, smoke via curl works.**

### Step 2: ContactPanel v2 (right side panel rebuild)

(Estimated: 1 session, 1 commit)

Port `v1/ContactPanel.jsx` to `v2/features/conversations/components/ContactPanel.tsx`:
- Collapsible 12px ↔ 320px (same widths as v1)
- Basic info card with PUT
- Custom fields with dynamic schema fetch
- Notes section with full CRUD + pin + edit-in-place

**Acceptance: side-by-side screenshots vs v1 — pixels can differ, features must match. User verifies in browser.**

### Step 3: DebugPanel v2 (per-message inspector)

(Estimated: 1-2 sessions, 1-2 commits)

Replace `TurnTraceInspector` modal with `DebugPanel` side panel:
- Inline (not modal) — opens when operator clicks a bot message
- Sections: Mode, Intent (+ bar), Recorrido (flow steps), Entities, Knowledge, Actions, Pipeline (latency bars), LLM, Rules, Errors
- Backend may need extra fields in `turn_traces` (e.g. `flow_steps` JSONB, `fact_pack`, `kb_evidence`) — check what v2 records vs what v1 shows

**Acceptance: clicking any bot message in the chat opens panel with at least Mode + Intent + Pipeline bars + Errors. Other sections degrade gracefully when v2 doesn't have data yet.**

### Step 4: ChatWindow polish

(Estimated: 1 session, 1 commit)

Build `ChatWindow.tsx` to replace the inline chat in `ConversationDetail.tsx`:
- Click-message-to-debug
- `MediaContent` for images/audio/docs
- Internal-notes cleanup (`cleanInternalNotes` regex)
- Copy / delete on individual messages

**Acceptance: ConversationDetail.tsx is now a thin orchestrator; ChatWindow + ContactPanel + DebugPanel are the 3 children.**

### Step 5: Conversation list rebuild (the big one)

(Estimated: 2 sessions, 2-3 commits)

Replace `ConversationList.tsx` table with `Inbox.tsx`:
- Mailbox sections (main / by AI agent / by pipeline stage)
- Search + tabs persisted to localStorage
- Right-click context menu
- Live counts updated by tenant WS events
- Unread tracking
- Lock indicator

**Acceptance: same UX as v1's left rail, with v2's TanStack Query under the hood.**

### Step 6: WhatsAppStatusBadge

(Estimated: small, ~1 commit)

- Backend: `GET /api/v1/whatsapp/status` (Meta Cloud reachability + last webhook timestamp)
- Backend: `GET /api/v1/automation-config/status` (circuit breaker open?)
- Frontend: badge in AppShell header polling every 10s

**Acceptance: header shows live "WhatsApp conectado" / "Reconectando…" / "WA pausado".**

---

## Summary for the next session

1. Read this doc fully.
2. Read the working contract at the top.
3. Pick **Step 1** (backend prep) — that's the dependency for everything else.
4. Do exactly Step 1, no scope creep.
5. Stop and report. Wait for the user to verify before Step 2.

**Trust is rebuilt one verified step at a time. Not 60 at a time.**

---

## Quick verification commands (so the next session doesn't have to re-discover)

```powershell
# v1 location
$v1 = "C:\Users\Sprt\Documents\Proyectos IA\1. Trabajando\2. Asistente de ventas"
# v2 location
$v2 = "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2"

# Verify file sizes match what this doc claims
wc -l "$v1\frontend\src\pages\Conversations\*.jsx"
wc -l "$v2\frontend\src\features\conversations\components\*.tsx"

# Read v1 components in full (they're committed in v1 repo, untouched)
Get-Content "$v1\frontend\src\pages\Conversations\DebugPanel.jsx" | more

# Bring v2 up
powershell -ExecutionPolicy Bypass -File "$v2\scripts\start-demo.ps1"

# v2 demo creds
# admin@demo.com / admin123 (operator)
# dele.zored@hotmail.com / dinamo123 (superadmin — promoted in earlier session)
```

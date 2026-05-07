# Phase 4 — Operator Frontend (Design)

**Status:** Approved 2026-05-07
**Branch:** `feat/phase-4-frontend`
**Owners:** Single-dev iteration via Claude

## Why

The bot is functional end-to-end (Phases 1-3d.1) but invisible to humans. Tenants like Dinamo can't see live conversations, can't pick up handoffs, can't tune their pipeline JSONB without writing SQL, and can't measure cost or conversion. **Without a frontend, the system isn't operable.** Phase 4 fixes that.

## What

A multi-tenant operator dashboard with role-based access:
- **Superadmin** (internal AtendIA ops): cross-tenant view, system metrics, tenant CRUD.
- **Operator** (e.g. Francisco at Dinamo): scoped to one `tenant_id`, day-to-day operations.

Nine core pillars + 2 add-ons. Templates registry deferred to 3d.2.

| # | Pillar | Brief |
|---|---|---|
| 1 | Live conversations | Filterable list + detail view; WebSocket-driven updates |
| 2 | Handoff queue | Bandeja de escalaciones renderizando `HandoffSummary` |
| 3 | Operator intervention | Operator types, bot pauses (`conversation_state.bot_paused`) |
| 4 | Tenant config UI | Pipeline JSONB editor (stages + flow_mode_rules + docs_per_plan), brand_facts, tone |
| 5 | Turn debug panel | `turn_traces` inspector — NLU/Composer/Vision/router decisions visible |
| 6 | Customer view | Search, full history, extracted fields surface |
| 7 | Analytics | Funnel, cost dashboard (NLU+Composer+Vision+Tools), volume, hourly heatmap |
| 8 | User management | `tenant_users` CRUD + superadmin cross-tenant |
| 9 | Audit log | Cross-tenant `events` timeline for superadmin, scoped for operators |
| 11 | Notifications | Push/sound/banner on handoff_requested + error_occurred |
| 12 | Bulk export | CSV of conversations/turn_traces (operator self-service reporting) |

## Stack

**Approach B chosen** — Vite SPA + TanStack ecosystem. Rationale (compared against Next.js 15 RSC and Remix):
- This is a login-gated internal dashboard. RSC/SSR add complexity without benefit (no SEO, no public pages).
- TanStack Router provides best-in-class TypeScript safety: route params, search params, loaders all type-checked end-to-end. Fits the "totalmente encontrable" requirement.
- Vite HMR is instant; iteration on tone/brand_facts/prompt fixtures stays fast.
- Static build → can be served from FastAPI's `StaticFiles`, a CDN, or split out later. No deployment lock-in.

**Frontend core:**
- Vite 6 · React 19 · TypeScript strict
- TanStack Router v1 (file-based, type-safe)
- TanStack Query v5 (server state) + TanStack Table v8 (data tables)
- React Hook Form + Zod (forms; types generated from `contracts/*.schema.json`)
- Zustand (lightweight client state — only auth and UI flags)

**UI:**
- Tailwind CSS v4 (CSS-first config, no `tailwind.config.js`)
- shadcn/ui (copy-paste primitives, modifiable)
- Tremor (SaaS dashboard charts — funnel, KPI cards)
- Sonner (toasts), Lucide-react (icons)

**Realtime + integration:**
- Native WebSocket client wrapped in a typed hook (`useTenantStream`)
- MSW (mock service worker for tests + Storybook isolation)

**Quality:**
- Biome (lint+format, replaces ESLint+Prettier — 10× faster)
- Vitest + React Testing Library (unit/component)
- Playwright (E2E, gated by `RUN_E2E=1`)
- Storybook 8 (component dev, docs, visual baseline)

**Tooling:**
- pnpm (faster + content-addressable store than npm)
- TypeScript path aliases: `@/features/*`, `@/lib/*`, `@/components/*`, `@/api/*`
- husky + lint-staged (pre-commit hooks: biome check + tsc --noEmit)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (operator)                                             │
│  Vite SPA: TanStack Router + Query + WebSocket client           │
└─────────────┬─────────────────────────────────────┬─────────────┘
              │ HTTPS REST (login, CRUD, queries)   │ WSS (realtime)
              ▼                                     ▼
┌─────────────────────────────────┐   ┌──────────────────────────┐
│ FastAPI new routes              │   │ FastAPI WS routes        │
│ /api/v1/auth/*                  │   │ /ws/tenants/:tid?token=  │
│ /api/v1/conversations/*         │   │ /ws/conversations/:cid?  │
│ /api/v1/handoffs/*              │   └────────┬─────────────────┘
│ /api/v1/turn-traces/*           │            │
│ /api/v1/tenants/:tid/* (config) │            ▼
│ /api/v1/customers/*             │   ┌──────────────────────────┐
│ /api/v1/users/*                 │   │ Redis Pub/Sub (existing) │
│ /api/v1/analytics/*             │   │ Channels:                │
│ /api/v1/audit-log/*             │   │   tenant:<uuid>          │
│ /api/v1/exports/*               │   │   conversation:<uuid>    │
└─────────────┬───────────────────┘   └──────────────────────────┘
              ▼
        Postgres (existing 17+ tables)
```

**Frontend deploy:** `vite build` produces `frontend/dist/`. FastAPI's `StaticFiles` serves it at `/`. Single Docker container = single-binary deploy. Migration path: split out to CDN later without code changes.

**Auth:**
- Login → `POST /api/v1/auth/login` returns JWT in **httpOnly cookie** (XSS protection) + a CSRF token in response body for non-GET requests
- JWT claims: `{tenant_id: UUID|null, user_id: UUID, role: "superadmin"|"operator", exp}`
- Superadmin: `tenant_id=null`, has access to all tenants
- Operator: `tenant_id=<uuid>`, scoped to that tenant
- WebSocket: query param `?token=<jwt>` (same as existing pattern in `realtime/auth.py`)
- Refresh: silent renewal via `/api/v1/auth/refresh` before expiry

**Backend additions (~20 new endpoints):**
- `auth/`: login, logout, refresh, me
- `conversations/`: list (paginated, filterable), detail, intervene, pause/resume bot
- `handoffs/`: list (status filter), assign, resolve
- `turn-traces/`: by conversation, by ID with full payload
- `tenants/:tid/`: pipeline GET/PUT, brand_facts GET/PUT, tone GET/PUT
- `customers/`: search, detail
- `users/`: list, create, update, delete (RBAC enforced)
- `analytics/`: funnel, cost-by-period, volume, heatmap
- `audit-log/`: events stream
- `exports/`: CSV generation (async via arq)

**WebSocket extensions:**
- New `/ws/tenants/:tid` endpoint subscribes to `tenant:<tid>` channel — fans out every event from any conversation in the tenant
- Existing `/ws/conversations/:cid` stays for detail-view drill-down
- Both auth via JWT query param (`/realtime/auth.py:issue_token` already supports this; extend to accept tenant-scope claim)

**Operator intervention:**
- New column `conversation_state.bot_paused: boolean default false` (migration 018)
- `POST /api/v1/conversations/:cid/intervene` body `{text}` → sets `bot_paused=true`, enqueues outbound directly via `enqueue_outbound`
- `POST /api/v1/conversations/:cid/resume-bot` → `bot_paused=false`
- Runner reads `bot_paused` early and short-circuits if true (still records `turn_traces` with `bot_paused=true` flag for audit)

## Module structure

Feature-based, not layer-based. Each feature is self-contained.

```
frontend/
├── src/
│   ├── features/
│   │   ├── conversations/
│   │   │   ├── api.ts                     # fetch helpers
│   │   │   ├── components/
│   │   │   │   ├── ConversationList.tsx
│   │   │   │   ├── ConversationDetail.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   └── InterventionComposer.tsx
│   │   │   ├── hooks/
│   │   │   │   ├── useConversations.ts
│   │   │   │   └── useConversationStream.ts
│   │   │   ├── routes/
│   │   │   │   ├── index.tsx              # /conversations
│   │   │   │   └── $conversationId.tsx    # /conversations/:id
│   │   │   ├── types.ts
│   │   │   └── README.md                  # feature owner docs
│   │   ├── handoffs/
│   │   ├── intervention/
│   │   ├── tenant-config/
│   │   ├── turn-debug/
│   │   ├── customers/
│   │   ├── analytics/
│   │   ├── users/
│   │   ├── audit-log/
│   │   ├── notifications/                 # global notification center
│   │   └── exports/                       # CSV download flows
│   ├── components/
│   │   └── ui/                            # shadcn primitives (Button, Input, ...)
│   ├── layouts/
│   │   ├── AppShell.tsx                   # sidebar + header + main
│   │   └── AuthLayout.tsx                 # login screen layout
│   ├── lib/
│   │   ├── cn.ts
│   │   ├── format.ts                      # date/currency helpers
│   │   └── api-client.ts                  # axios/fetch wrapper with CSRF + auth
│   ├── api/
│   │   └── ws-client.ts                   # WebSocket wrapper hook
│   ├── stores/
│   │   ├── auth.ts                        # Zustand: user + jwt
│   │   └── ui.ts                          # Zustand: sidebar collapsed, theme
│   ├── routes/
│   │   ├── __root.tsx
│   │   ├── login.tsx
│   │   └── (auth)/                        # route group, all gated
│   ├── types/
│   │   └── generated/                     # from contracts/*.schema.json
│   └── main.tsx
├── tests/
│   ├── e2e/                               # Playwright
│   └── setup.ts                           # MSW + RTL setup
├── public/
├── biome.json
├── vite.config.ts
├── tsconfig.json
├── package.json
└── README.md
```

**Findability rules:**
- Every `features/<name>/` has a `README.md` (1 paragraph: what it does, key files, how to extend)
- Path aliases enforce features can't deep-import each other's internals — only public exports via `index.ts`
- Cross-feature data flows only via TanStack Query (shared cache) or Zustand (auth/UI)
- New features always start by copying a template from `features/_template/`

## Data flow

**Pattern: server-truth via REST + push updates via WS, optimistic mutations.**

1. User loads `/conversations` → `useConversations()` hook → `GET /api/v1/conversations?tenant_id=...&limit=50&cursor=...`. TanStack Query caches.
2. App opens `wss://.../ws/tenants/<tid>?token=<jwt>` once at mount. Backend subscribes to Redis `tenant:<tid>` channel.
3. Existing publishers (`publish_event` in webhook handler, runner) already emit `message_received`/`message_sent` to per-conversation channel; new patch fans them out to `tenant:<tid>` too.
4. Frontend receives `{type, data}`:
   - `message_received` / `message_sent` / `turn_completed` → `queryClient.invalidateQueries(['conversations', tid])` + targeted update of detail view if open
   - `handoff_requested` → toast + invalidate handoffs queue + sound (notifications feature)
   - `error_occurred` → log to audit-log live view if open
5. Operator types in InterventionComposer → optimistic append to detail view → `POST /api/v1/conversations/:cid/intervene` → on success, server confirms via WS push.
6. Reconnection: TanStack Query `refetchOnWindowFocus`; WS auto-reconnect with exponential backoff (1s, 2s, 5s, 10s capped). On permanent disconnect → toast "conexión perdida", offer "recargar".

**Source of truth = DB.** WS is just push notification; on uncertainty, refetch from REST.

## Error handling

- **Frontend:** Global `<ErrorBoundary>` per route group. TanStack Query retry policy: 3 attempts on network errors, exponential backoff, no retry on 4xx. Sonner toasts for user-visible errors.
- **API contract:** problem+json (RFC 7807) with `type`, `title`, `status`, `detail`, `instance`. Frontend decodes and renders.
- **401:** redirect to `/login` (preserving `?next=`). **403:** "no tienes permiso" toast. **5xx:** toast + retry button + sentry breadcrumb.
- **WebSocket:** silent reconnect first 3 attempts; on permanent fail → toast banner; data freshness via REST refetch.
- **Optimistic mutations:** rollback on error via TanStack Query `onError`. User sees the original state restored + error toast.
- **Backend logging:** all 5xx logged with conversation_id/tenant_id; events table gets an `error_occurred` row for audit.

## Testing strategy

| Layer | Tool | Coverage |
|---|---|---|
| Unit (utils, pure hooks) | Vitest | ~30 tests |
| Component (with MSW + RTL) | Vitest | ~80 tests across all features |
| Integration (route + data flow) | Vitest + MSW | ~20 tests |
| E2E (Playwright) | Gated `RUN_E2E=1` | login → live conversation → intervene → handoff → resolve. ~10 critical flows. |
| Backend new endpoints | pytest | ~50 tests for ~20 endpoints |
| Visual regression | Storybook + Chromatic (optional) | per-component snapshot |

**Coverage target:** 85% gate (matches backend). E2E and visual regression skip in CI by default.

## Self-question loop (recurring practice)

Before each major commit (= each pillar in the implementation plan):

1. **Reviewer agent pass** — dispatch `code-reviewer` agent with the diff, asking "is this the best fit for the project's objective (multi-tenant WhatsApp sales bot, modular, findable)?". Apply suggestions before merge.
2. **Risk check** — call out at least one concrete risk in the commit message ("this couples X to Y; if we ever Z, we'll need to refactor...")
3. **Findability test** — can a new contributor land in this feature folder and understand it from the README + types in <5 minutes? If no, fix.
4. **YAGNI sweep** — anything in this commit that's not used by another commit? Defer or delete.

Encoded in the implementation plan as a checkpoint between pillars.

## Out of scope (explicit)

- WhatsApp Templates registry UI (Phase 3d.2 — must ship before Phase 3 is "done")
- Outbound multimedia (Phase 3d.3)
- Per-customer timezone (out-of-window follow-ups context)
- End-customer-facing UI (they're on WhatsApp)
- Marketing site / public docs
- Mobile native apps (responsive web is enough for v1)
- Chromatic paid plan (Storybook visual regression is optional)

## Risks

1. **WebSocket fan-out at scale:** every operator opens a tenant-wide WS. 50 operators × 1k events/min = 50k push/min. Redis Pub/Sub handles this fine; FastAPI WS connection limit per worker is the bottleneck. Mitigation: horizontal scale uvicorn workers; document limit in README.
2. **Pipeline JSONB editor footgun:** operator can save invalid `flow_mode_rules` and break the bot. Mitigation: client-side Zod validation generated from `contracts/pipeline_definition.schema.json` + server-side Pydantic validation + dry-run preview button.
3. **Operator intervention vs in-flight bot turn:** operator sends a message while runner is mid-turn. Race could double-send. Mitigation: `bot_paused` check is a session-level row lock at runner start; intervention also locks; whichever wins, the other waits.
4. **Tenant data leak via WS:** if a JWT for tenant A is replayed for tenant B's WS endpoint, must reject. Mitigation: WS endpoint validates `jwt.tenant_id == :tid` (path param) before accepting.
5. **Bundle size:** Tremor + shadcn + TanStack adds up. Target initial bundle <300KB gzip. Mitigation: code-split per route via TanStack Router lazy imports.

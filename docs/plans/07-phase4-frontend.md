# Phase 4 — Operator Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Multi-tenant operator dashboard for AtendIA — full-feature, modular, "totalmente encontrable", with role-based access (superadmin + tenant operator) and 11 pillars (live conversations, handoffs, intervention, tenant config, turn debug, customers, analytics, users, audit log, notifications, bulk export).

**Architecture:** Vite SPA (React 19 + TypeScript) consuming FastAPI REST + WebSocket. Feature-based folder structure, JWT in httpOnly cookie, TanStack Router/Query for type-safe routing+data, Tailwind v4 + shadcn/ui + Tremor for UI. Frontend bundles to `frontend/dist/` and is served by FastAPI's `StaticFiles` (single-Docker deploy).

**Tech Stack:** Vite 6 · React 19 · TS strict · TanStack Router/Query/Table · React Hook Form + Zod · Tailwind CSS v4 · shadcn/ui · Tremor · Sonner · Biome · Vitest · Playwright · Storybook 8 · pnpm.

**Design doc:** [`docs/plans/2026-05-07-phase4-frontend-design.md`](./2026-05-07-phase4-frontend-design.md)

**Pre-requisitos:**
- Working tree limpio en branch `feat/phase-4-frontend` (ya creada).
- Phase 3d.1 mergeada (tag `phase-3d1-followups`, commit `5b10e39`).
- Docker Compose corriendo (postgres + redis).
- pnpm instalado globalmente: `npm install -g pnpm@latest` (versión ≥9).
- Node ≥20.

**Convenciones:**
- TDD estricto. Cada feature arranca con test rojo.
- Commits chicos por tarea. Commit message en formato `feat(scope): ...` / `test(scope): ...` / `chore(scope): ...`.
- **Self-question loop:** antes de cada commit grande, dispatch `code-reviewer` agent con el diff. Aplica feedback antes de mergear.
- Lint (Biome + tsc) gates al cierre de cada bloque.

---

## Mapa de tareas (4 milestones, 60 tareas)

| Phase | Bloque | Tareas | Foco | Tag |
|---|---|---|---|---|
| **4a** | A | T1–T5 | Backend auth + scaffolding | — |
| **4a** | B | T6–T13 | Frontend scaffolding | — |
| **4a** | C | T14–T19 | Pillar 1: Live conversations | — |
| **4a** | D | T20–T27 | Pillar 2+3: Handoffs + Intervention | `phase-4a-foundation` |
| **4b** | E | T28–T33 | Pillar 4: Tenant config UI | — |
| **4b** | F | T34–T37 | Pillar 5: Turn debug panel | — |
| **4b** | G | T38–T41 | Pillar 6: Customers | `phase-4b-config-debug` |
| **4c** | H | T42–T46 | Pillar 7: Analytics | — |
| **4c** | I | T47–T48 | Pillar 8: Users | — |
| **4c** | J | T49–T50 | Pillar 9: Audit log | `phase-4c-ops` |
| **4d** | K | T51–T53 | Add-ons: Notifications + Bulk export | — |
| **4d** | L | T54–T60 | E2E + Visual regression + cierre | `phase-4-frontend` |

---

# Bloque A — Backend foundation (T1–T5)

## Task 1: Migration 018 — `conversation_state.bot_paused`

**Files:**
- Create: `core/atendia/db/migrations/versions/018_conversation_state_bot_paused.py`
- Modify: `core/atendia/db/models/conversation.py`

**Step 1: Generate alembic revision**
```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
  uv run alembic revision -m "conversation_state bot_paused"
```
Rename to `018_conversation_state_bot_paused.py`. Set `revises = "8c2e4d61f9a3"` (017's rev id).

**Step 2: Edit migration**
```python
def upgrade() -> None:
    op.add_column(
        "conversation_state",
        sa.Column("bot_paused", sa.Boolean, nullable=False, server_default=sa.false()),
    )

def downgrade() -> None:
    op.drop_column("conversation_state", "bot_paused")
```

**Step 3: Update model**
In `db/models/conversation.py`, add to `ConversationStateRow`:
```python
bot_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```
Add `Boolean` to the `from sqlalchemy import` line.

**Step 4: Apply + commit**
```bash
uv run alembic upgrade head
git add core/atendia/db/migrations/versions/018_conversation_state_bot_paused.py core/atendia/db/models/conversation.py
git commit -m "feat(db): conversation_state.bot_paused for operator intervention (migration 018)"
```

## Task 2: JWT auth with role claim + httpOnly cookies

**Files:**
- Create: `core/atendia/api/auth_routes.py`
- Create: `core/atendia/api/_auth_helpers.py`
- Modify: `core/atendia/realtime/auth.py` (extend to accept role + tenant_id claims)
- Test: `core/tests/api/test_auth_routes.py`

**Step 1: Test (TDD red)**
```python
async def test_login_returns_jwt_cookie_and_csrf_token(test_client, db_session):
    # seed tenant + user with bcrypt password
    ...
    resp = await test_client.post("/api/v1/auth/login", json={
        "email": "francisco@dinamo.com", "password": "test123",
    })
    assert resp.status_code == 200
    assert "atendia_session" in resp.cookies
    assert resp.json()["csrf_token"]
    assert resp.json()["user"]["role"] == "operator"
    assert resp.json()["user"]["tenant_id"] is not None
```

**Step 2: Run, see fail (route missing)**

**Step 3: Implement**
- Add `password_hash: Mapped[str]` to `TenantUser` model (migration 019 — combine with this task)
- Build `_auth_helpers.hash_password / verify_password` using `passlib[bcrypt]` (add to pyproject)
- Build `_auth_helpers.issue_jwt(user_id, tenant_id, role)` using `jose` (already in deps via realtime auth)
- Build `_auth_helpers.get_current_user(request)` reading httpOnly cookie + verifying signature
- Routes: `POST /login`, `POST /logout`, `POST /refresh`, `GET /me`

**Step 4: Tests pass (4 tests: login_ok, login_bad_pwd, logout_clears_cookie, me_returns_claims)**

**Step 5: Commit**
```bash
git commit -m "feat(api): JWT auth with role claim + httpOnly cookie + CSRF token"
```

## Task 3: API router scaffolding + tenant-scoping dependency

**Files:**
- Modify: `core/atendia/main.py` (mount `/api/v1` router)
- Create: `core/atendia/api/_deps.py` (dependencies: `current_user`, `current_tenant_id`, `require_superadmin`)

**Step 1: Test fixture for authenticated client**
Add `test_client_operator` and `test_client_superadmin` fixtures to `core/tests/api/conftest.py`.

**Step 2: Implement deps**
```python
async def current_user(request: Request, session: AsyncSession = Depends(get_db_session)) -> AuthUser:
    token = request.cookies.get("atendia_session")
    if not token: raise HTTPException(401)
    claims = decode_jwt(token)
    return AuthUser(**claims)

async def current_tenant_id(user: AuthUser = Depends(current_user), tid: UUID | None = None) -> UUID:
    """For operator endpoints — tenant_id forced from JWT, not query."""
    if user.role == "operator": return user.tenant_id
    if user.role == "superadmin" and tid: return tid
    raise HTTPException(403, "tenant_id required for superadmin endpoints")

async def require_superadmin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "superadmin": raise HTTPException(403)
    return user
```

**Step 3: Mount router**
In `main.py`:
```python
from atendia.api import auth_routes
app.include_router(auth_routes.router, prefix="/api/v1/auth", tags=["auth"])
```

**Step 4: Smoke + commit**
```bash
uv run pytest tests/api/test_auth_routes.py -v
git commit -m "feat(api): /api/v1 mounting + auth deps (current_user, current_tenant_id, require_superadmin)"
```

## Task 4: CSRF middleware

**Files:**
- Create: `core/atendia/api/_csrf.py`
- Modify: `core/atendia/main.py`
- Test: `core/tests/api/test_csrf.py`

**Step 1: Test**
- POST without `X-CSRF-Token` header → 403
- POST with valid token (returned by login) → 200
- GET works without token

**Step 2: Implement double-submit cookie pattern**
```python
class CSRFMiddleware(BaseHTTPMiddleware):
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    async def dispatch(self, request, call_next):
        if request.method not in self.SAFE_METHODS and request.url.path.startswith("/api/"):
            cookie = request.cookies.get("atendia_csrf")
            header = request.headers.get("x-csrf-token")
            if not cookie or cookie != header:
                return JSONResponse({"detail": "csrf"}, status_code=403)
        return await call_next(request)
```

**Step 3: Login sets `atendia_csrf` cookie + returns token in body. Frontend echoes in header.**

**Step 4: Commit**

## Task 5: Block A close — bundle test, ruff, commit

```bash
cd core && uv run pytest tests/api -q
git tag --no-sign 4a-block-a-done  # local marker
```

---

# Bloque B — Frontend scaffolding (T6–T13)

## Task 6: pnpm + Vite + React 19 + TS init

**Files:**
- Create: `frontend/` directory, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`

**Step 1: pnpm init**
```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2"
pnpm create vite@latest frontend --template react-ts
cd frontend
pnpm install
pnpm add react@19 react-dom@19
```

**Step 2: tsconfig strict**
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "paths": {
      "@/*": ["./src/*"]
    },
    "baseUrl": "."
  },
  "include": ["src", "tests"]
}
```

**Step 3: vite.config.ts with proxy + alias**
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: {
      "/api": "http://localhost:8001",
      "/ws": { target: "ws://localhost:8001", ws: true },
    },
  },
});
```

**Step 4: Smoke + commit**
```bash
pnpm dev  # ctrl-c after seeing "ready"
git add frontend/
git commit -m "chore(frontend): scaffold Vite 6 + React 19 + TS strict"
```

## Task 7: Biome + Vitest + Playwright + Storybook config

**Files:**
- Create: `frontend/biome.json`, `frontend/vitest.config.ts`, `frontend/playwright.config.ts`, `frontend/.storybook/main.ts`, `frontend/.storybook/preview.ts`
- Modify: `frontend/package.json` (scripts)

**Step 1: Add deps**
```bash
cd frontend
pnpm add -D @biomejs/biome vitest @vitest/ui jsdom @testing-library/react @testing-library/jest-dom \
            @playwright/test \
            storybook@latest @storybook/react-vite @storybook/addon-essentials \
            msw
```

**Step 2: biome.json**
```json
{
  "$schema": "https://biomejs.dev/schemas/1.9.4/schema.json",
  "organizeImports": { "enabled": true },
  "linter": { "enabled": true, "rules": { "recommended": true } },
  "formatter": { "enabled": true, "indentStyle": "space", "indentWidth": 2, "lineWidth": 100 }
}
```

**Step 3: vitest.config.ts**
```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    coverage: { reporter: ["text", "html"], thresholds: { lines: 85 } },
  },
});
```

**Step 4: package.json scripts**
```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:ci": "vitest run --coverage",
    "test:e2e": "playwright test",
    "lint": "biome check .",
    "lint:fix": "biome check --write .",
    "typecheck": "tsc -b --noEmit",
    "storybook": "storybook dev -p 6006",
    "build-storybook": "storybook build"
  }
}
```

**Step 5: Commit**

## Task 8: Tailwind v4 + shadcn/ui setup

**Step 1: Install**
```bash
pnpm add -D tailwindcss@4 @tailwindcss/vite
pnpm add class-variance-authority clsx tailwind-merge lucide-react
pnpm add -D @types/node
```

**Step 2: vite.config plugin**
Add `@tailwindcss/vite` to plugins. Tailwind v4 is CSS-first — no `tailwind.config.js` needed.

**Step 3: src/index.css**
```css
@import "tailwindcss";

@theme {
  --color-primary: oklch(0.55 0.22 263);
  /* ... other design tokens ... */
}
```

**Step 4: shadcn/ui init**
```bash
pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add button input card sheet dialog dropdown-menu \
    table tabs select textarea form badge separator skeleton avatar \
    sonner toast tooltip command popover calendar scroll-area
```

**Step 5: lib/cn.ts**
```typescript
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
```

**Step 6: Commit**

## Task 9: TanStack Router scaffolding + auth-gated route group

**Files:**
- Create: `frontend/src/routes/__root.tsx`, `frontend/src/routes/login.tsx`, `frontend/src/routes/(auth)/route.tsx`, `frontend/src/routes/(auth)/index.tsx`
- Modify: `frontend/src/main.tsx`

**Step 1: Install**
```bash
pnpm add @tanstack/react-router @tanstack/router-devtools
pnpm add -D @tanstack/router-plugin
```

**Step 2: vite plugin**
```typescript
import { TanStackRouterVite } from "@tanstack/router-plugin/vite";
plugins: [TanStackRouterVite(), react(), tailwindcss()],
```

**Step 3: Routes (file-based auto-discovery)**
```typescript
// src/routes/__root.tsx
import { createRootRoute, Outlet } from "@tanstack/react-router";
export const Route = createRootRoute({ component: () => <Outlet /> });

// src/routes/(auth)/route.tsx — gated route group
import { createFileRoute, redirect } from "@tanstack/react-router";
import { authStore } from "@/stores/auth";
export const Route = createFileRoute("/(auth)")({
  beforeLoad: async () => {
    const user = await authStore.getState().fetchMe();
    if (!user) throw redirect({ to: "/login" });
  },
  component: () => <AppShell />,
});
```

**Step 4: main.tsx**
```typescript
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
const router = createRouter({ routeTree });
ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode><RouterProvider router={router} /></StrictMode>
);
```

**Step 5: Commit**

## Task 10: API client (REST + WebSocket wrapper)

**Files:**
- Create: `frontend/src/lib/api-client.ts`
- Create: `frontend/src/api/ws-client.ts`
- Test: `frontend/tests/lib/api-client.test.ts`

**Step 1: api-client (axios with interceptors)**
```typescript
import axios from "axios";
export const api = axios.create({ baseURL: "/api/v1", withCredentials: true });
api.interceptors.request.use((config) => {
  const csrf = document.cookie.match(/atendia_csrf=([^;]+)/)?.[1];
  if (csrf) config.headers["X-CSRF-Token"] = csrf;
  return config;
});
api.interceptors.response.use(undefined, (err) => {
  if (err.response?.status === 401) window.location.href = "/login";
  return Promise.reject(err);
});
```

**Step 2: WebSocket hook**
```typescript
export function useTenantStream(tenantId: string, onEvent: (e: TenantEvent) => void) {
  useEffect(() => {
    let ws: WebSocket; let backoff = 1000; let cancelled = false;
    function connect() {
      ws = new WebSocket(`/ws/tenants/${tenantId}`);
      ws.onmessage = (m) => onEvent(JSON.parse(m.data));
      ws.onclose = () => { if (!cancelled) setTimeout(connect, Math.min(backoff *= 2, 10_000)); };
      ws.onopen = () => { backoff = 1000; };
    }
    connect();
    return () => { cancelled = true; ws.close(); };
  }, [tenantId, onEvent]);
}
```

**Step 3: Commit**

## Task 11: Auth Zustand store + login page

**Files:**
- Create: `frontend/src/stores/auth.ts`, `frontend/src/routes/login.tsx`

**Step 1: store**
```typescript
import { create } from "zustand";
import { api } from "@/lib/api-client";
type User = { id: string; tenant_id: string | null; role: "superadmin" | "operator"; email: string };
type State = { user: User | null; csrf: string | null };
type Actions = { login: (e: string, p: string) => Promise<void>; logout: () => Promise<void>; fetchMe: () => Promise<User | null> };
export const authStore = create<State & Actions>((set) => ({
  user: null, csrf: null,
  async login(email, password) {
    const { data } = await api.post("/auth/login", { email, password });
    set({ user: data.user, csrf: data.csrf_token });
  },
  async logout() { await api.post("/auth/logout"); set({ user: null, csrf: null }); },
  async fetchMe() {
    try { const { data } = await api.get("/auth/me"); set({ user: data }); return data; }
    catch { return null; }
  },
}));
```

**Step 2: Login page** (form using shadcn `Form` + `Input` + `Button`).

**Step 3: Commit**

## Task 12: AppShell layout (sidebar + header)

Sidebar with 9 pillar links; header with user dropdown + tenant switcher (visible only for superadmin); main outlet.

## Task 13: Type generation from `contracts/*.schema.json`

**Files:**
- Create: `frontend/scripts/generate-types.mjs`, `frontend/src/types/generated/`

**Step 1: Install json-schema-to-typescript**
```bash
pnpm add -D json-schema-to-typescript
```

**Step 2: Script**
```javascript
import { compileFromFile } from "json-schema-to-typescript";
import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
const SRC = "../contracts"; const DST = "src/types/generated";
const files = (await readdir(SRC)).filter(f => f.endsWith(".schema.json"));
for (const f of files) {
  const ts = await compileFromFile(path.join(SRC, f));
  await writeFile(path.join(DST, f.replace(".schema.json", ".ts")), ts);
}
```

**Step 3: package.json script**: `"types": "node scripts/generate-types.mjs"`. Run before build.

**Step 4: Commit. Bloque B done.**

```bash
cd frontend && pnpm typecheck && pnpm lint && pnpm test
git tag --no-sign 4a-block-b-done
```

---

# Bloque C — Pillar 1: Live conversations (T14–T19)

## Task 14: Backend `GET /api/v1/conversations` paginated + filtered

**Files:**
- Create: `core/atendia/api/conversations_routes.py`
- Test: `core/tests/api/test_conversations_routes.py`

**Step 1: Test**
```python
async def test_list_conversations_scoped_to_tenant(client_operator, seed_data):
    resp = await client_operator.get("/api/v1/conversations?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert all(c["tenant_id"] == client_operator.tenant_id for c in body["items"])
    assert "next_cursor" in body
```

**Step 2: Implement**
```python
@router.get("")
async def list_conversations(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    status: str | None = None,
    has_pending_handoff: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> ConversationListResponse:
    # cursor = base64(last_activity_at_iso); ORDER BY last_activity_at DESC
    ...
```

**Step 3: Tests for filter combinations + pagination + RBAC (operator can't see other tenants)**

**Step 4: Commit**

## Task 15: Backend WebSocket `/ws/tenants/:tid` (fan-out)

**Files:**
- Modify: `core/atendia/realtime/ws_routes.py`
- Modify: `core/atendia/realtime/publisher.py` (fan-out to tenant channel too)
- Test: `core/tests/realtime/test_ws_tenant_endpoint.py`

**Step 1: Test**
```python
async def test_ws_tenant_receives_events_from_any_conversation(...):
    ws = await client.websocket_connect(f"/ws/tenants/{tid}?token={jwt}")
    await publish_event(redis, tenant_id=tid, conversation_id=conv_a, event={"type": "message_received", ...})
    msg = await ws.receive_json()
    assert msg["type"] == "message_received"
```

**Step 2: Implement endpoint subscribing to `tenant:<tid>` channel**

**Step 3: Modify publisher to also publish to tenant channel:**
```python
async def publish_event(redis, *, tenant_id, conversation_id, event):
    await redis.publish(f"conversation:{conversation_id}", json.dumps(event))
    await redis.publish(f"tenant:{tenant_id}", json.dumps({**event, "conversation_id": str(conversation_id)}))
```

**Step 4: Tests + commit**

## Task 16: ~Combined into T15.~ Skip.

## Task 17: Frontend conversations list page

**Files:**
- Create: `frontend/src/features/conversations/api.ts`, `hooks/useConversations.ts`, `components/ConversationList.tsx`, `routes/index.tsx`
- Test: `frontend/tests/features/conversations/ConversationList.test.tsx`

**Step 1: Test (component renders mocked list)**

**Step 2: Implement**
```typescript
// api.ts
export const conversationsApi = {
  list: (params: ListParams) => api.get<ConversationListResponse>("/conversations", { params }).then(r => r.data),
};

// hooks/useConversations.ts
export function useConversations(filters: Filters) {
  return useInfiniteQuery({
    queryKey: ["conversations", filters],
    queryFn: ({ pageParam }) => conversationsApi.list({ ...filters, cursor: pageParam }),
    getNextPageParam: (last) => last.next_cursor,
    initialPageParam: null,
  });
}
```

**Step 3: Component using TanStack Table for the list view, virtualized scroll for >1k rows**

**Step 4: Commit**

## Task 18: Frontend conversation detail page

**Files:**
- Create: `frontend/src/features/conversations/components/ConversationDetail.tsx`, `MessageBubble.tsx`, `routes/$conversationId.tsx`

**Step 1-4: Standard pattern (test + impl + commit). Renders messages reverse-chronologically, shows extracted_data sidebar, current flow_mode indicator.**

## Task 19: Frontend `useConversationStream` hook (per-conversation WS)

Used inside ConversationDetail to push new messages live. Wraps the existing `/ws/conversations/:cid` endpoint.

**Bloque C done. Tag intermedio:** none — keep momentum to D.

---

# Bloque D — Pillar 2 + 3: Handoffs + Intervention (T20–T27)

## Task 20: Backend `GET /api/v1/handoffs` (queue)

Filtered by status (`pending|assigned|resolved`), tenant-scoped. Returns full `HandoffSummary` payload from `human_handoffs.payload`.

## Task 21: Backend assign + resolve handoffs

`POST /handoffs/:id/assign {user_id}` and `POST /handoffs/:id/resolve {note}`. Updates status + sets `assigned_user_id` / `resolved_at`.

## Task 22: Backend `POST /api/v1/conversations/:cid/intervene`

```python
@router.post("/{conversation_id}/intervene")
async def intervene(conversation_id: UUID, body: InterveneBody, ...):
    # 1. set bot_paused=True
    # 2. enqueue outbound directly
    # 3. emit event MESSAGE_SENT (with source="operator")
    # 4. publish to redis channels
```

## Task 23: Backend `POST /:cid/resume-bot`

Sets `bot_paused=False`. The next inbound goes through normal runner.

## Task 24: Runner reads `bot_paused`

Modify `conversation_runner.run_turn` early:
```python
if state_obj.bot_paused:
    # record minimal turn_trace with bot_paused=True flag, return
    ...
```

Add column `turn_traces.bot_paused: bool` (migration 020) for audit.

## Task 25: Frontend handoff queue page

Cards rendering `HandoffSummary` (reason, customer, last_inbound, suggested_next_action, docs_recibidos/pendientes).

## Task 26: Frontend HandoffDetail with full context

Click a card → modal/sheet with full conversation preview + assign + resolve actions.

## Task 27: Frontend InterventionComposer

Inside ConversationDetail, when bot is active: button "Tomar control". On click: `POST /intervene` for each message typed; button "Devolver al bot" → `/resume-bot`.

**Self-question loop:** dispatch `code-reviewer` agent reviewing T20-T27 diff. Apply feedback.

**Bloque D done. TAG: `phase-4a-foundation`. Verify suite green; commit; tag.**

```bash
cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && uv run pytest -q
cd ../frontend && pnpm test:ci && pnpm typecheck && pnpm lint
git tag -a phase-4a-foundation -m "Phase 4a — auth + scaffolding + live conversations + handoffs + intervention"
```

---

# Bloque E — Pillar 4: Tenant config UI (T28–T33)

## Task 28-30: Backend tenant config GET/PUT (pipeline, brand_facts, tone)

For each:
- `GET /api/v1/tenants/:tid/pipeline` → returns active `tenant_pipelines.definition` JSONB validated against `PipelineDefinition`.
- `PUT /api/v1/tenants/:tid/pipeline` → validates body, creates a NEW version row (don't UPDATE — keep history), marks new active.
- Same pattern for brand_facts (`tenant_branding.default_messages.brand_facts`) and tone (`tenant_branding.voice`).

## Task 31: Frontend Pipeline editor

Use **react-json-view** + Zod-validated form for `flow_mode_rules` array. Dry-run preview button: send sample inbound, returns what mode would be picked. Reuses `flow_router.pick_flow_mode` server-side.

## Task 32: Frontend BrandFacts editor

Simple form (key/value pairs, predefined keys: catalog_url, address, etc.).

## Task 33: Frontend Tone editor

Form + live preview of the system prompt that would result.

---

# Bloque F — Pillar 5: Turn debug panel (T34–T37)

## Task 34: Backend `GET /api/v1/turn-traces?conversation_id=...&from=...&to=...`

Paginated, ordered by `turn_number`. Returns row metadata (no payloads — separate fetch for detail).

## Task 35: Backend `GET /api/v1/turn-traces/:id`

Full payload including `nlu_input/output`, `composer_input/output`, `state_before/after`, `outbound_messages`.

## Task 36: Frontend TurnTraceList

Embedded in ConversationDetail as a tab. Each row: turn_number, flow_mode, latency, cost.

## Task 37: Frontend TurnTraceInspector (modal)

4 tabs: NLU (intent + entities + ambiguities), Composer (system prompt + output), Vision (if any), Router (which rule fired). Pretty-printed JSON for raw view.

---

# Bloque G — Pillar 6: Customers (T38–T41)

## Task 38: Backend `GET /api/v1/customers?q=...&tenant_id=...`

Search by phone or name (uses `customers` + `conversation_state.extracted_data->>'nombre'`).

## Task 39: Backend `GET /api/v1/customers/:id`

Returns customer + all conversations + last extracted_data + total cost.

## Task 40-41: Frontend search + detail pages

**Bloque G done. TAG: `phase-4b-config-debug`.**

---

# Bloque H — Pillar 7: Analytics (T42–T46)

## Task 42: Backend funnel endpoint

```sql
SELECT
  COUNT(DISTINCT CASE WHEN extracted_data->>'plan_credito' IS NOT NULL THEN conversation_id END) AS plan_assigned,
  COUNT(DISTINCT CASE WHEN extracted_data->>'modelo_moto' IS NOT NULL THEN conversation_id END) AS quoted,
  COUNT(DISTINCT CASE WHEN (extracted_data->'papeleria_completa')::bool THEN conversation_id END) AS papeleria_completa
FROM conversation_state cs JOIN conversations c ON c.id = cs.conversation_id
WHERE c.tenant_id = :tid AND c.created_at BETWEEN :from AND :to
```

## Task 43: Backend cost endpoint

Aggregates `turn_traces.{nlu_cost_usd, composer_cost_usd, tool_cost_usd, vision_cost_usd}` by day.

## Task 44: Backend volume + heatmap

By hour-of-day grouping.

## Task 45: Frontend AnalyticsDashboard layout

Tremor `<Card>` grid: KPI tiles + 4 charts.

## Task 46: Frontend FunnelChart, CostDashboard, VolumeChart, Heatmap

Tremor components.

---

# Bloque I — Pillar 8: Users (T47–T48)

## Task 47: Backend users CRUD

`GET/POST/PATCH/DELETE /api/v1/users` — superadmin sees all, operator sees own tenant only. Roles: `superadmin | tenant_admin | operator`. Add `role` column to `tenant_users` (migration 021).

## Task 48: Frontend users page

shadcn Table + Dialog for create/edit. Password reset via email magic link (defer email sending to 4d.notifications work).

---

# Bloque J — Pillar 9: Audit log (T49–T50)

## Task 49: Backend `GET /api/v1/audit-log?tenant_id=...&type=...&from=...&to=...`

Reads `events` table. RBAC: superadmin sees all; operator sees own tenant.

## Task 50: Frontend audit-log timeline

Vertical timeline with event icons + JSON payload expand. Live tail toggle.

**Bloque J done. TAG: `phase-4c-ops`.**

---

# Bloque K — Add-ons: Notifications + Bulk export (T51–T53)

## Task 51: Notifications system

- Browser Notifications API (with permission prompt)
- Sound (Sonner toast + optional `<audio>` ping)
- Topics: handoff_requested, error_occurred, conversation_assigned_to_me
- User preferences: `tenant_users.notification_prefs JSONB` (migration 022)

## Task 52: Backend bulk export

`POST /api/v1/exports/conversations` body `{tenant_id, from, to}` → enqueues arq job → arq generates CSV → uploads to local `/storage/exports/<id>.csv` → emits `export_ready` event with download URL.

## Task 53: Frontend exports page

List of past exports + new export button + download link.

---

# Bloque L — Quality + cierre (T54–T60)

## Task 54: E2E Playwright critical flows

10 flows:
1. Login → dashboard
2. View conversation → see messages
3. Pick up handoff → assign → resolve
4. Intervene in conversation → message sent → resume bot
5. Edit pipeline JSONB → save → dry-run preview
6. Edit brand_facts → save → reflected in next composer turn
7. Search customer → see history
8. View analytics dashboard → period filter works
9. Create user → login as new user → permissions enforced
10. Export CSV → download succeeds

## Task 55: Storybook stories for top 20 components

Run `pnpm build-storybook` in CI.

## Task 56: Coverage gate + Biome clean + tsc clean

Frontend gate: `pnpm test:ci` 85%+, `pnpm lint`, `pnpm typecheck`. Backend gate: `uv run pytest --cov` 85%+.

## Task 57: Bundle size check + code splitting

Use `vite-plugin-visualizer`. Target initial bundle <300KB gzip. Code-split per route via `lazy(() => import(...))` in TanStack Router.

## Task 58: README + memory updates

Top-level README: tick Phase 4 with caveats; core/README: backend new endpoints documented; frontend/README: full setup guide; memory file updated.

## Task 59: FastAPI serves frontend bundle

```python
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

## Task 60: Final verification + tag

```bash
docker compose up -d
cd core && uv run alembic upgrade head && uv run pytest --cov=atendia -q
cd ../frontend && pnpm install && pnpm build && pnpm test:ci && pnpm lint && pnpm typecheck
git tag -a phase-4-frontend -m "Phase 4 — Operator Frontend (11 pillars + bulk export + notifications)"
```

---

## Block A — deviations from plan (locked in 2026-05-07)

When implementing Block A, the following swaps were necessary or strongly preferable:

- **`bcrypt` direct, NOT `passlib[bcrypt]`** — passlib is unmaintained and
  raises `AttributeError: module 'bcrypt' has no attribute '__about__'`
  against bcrypt 5.x (the current major). The direct `bcrypt` API is what
  the bcrypt maintainers themselves recommend.
- **`pyjwt`, NOT `python-jose`** — the plan said "jose (already in deps via
  realtime auth)". This was inaccurate: `realtime/auth.py` uses pyjwt. Jose
  has had multiple unpatched CVEs and is effectively abandoned. Pyjwt is the
  modern standard.
- **`pydantic[email]`** added to deps so `EmailStr` works in the login body.

## Block A — deferred work

These came out of the Block A code review and are NOT blockers for `4a-block-a-done`:

- **MEDIUM (pre-existing)** — `/api/v1/runner/*` accepts arbitrary
  `RunTurnRequest` POSTs with no auth. Currently CSRF-exempted to keep
  internal tests working, but the exempt entry codifies a pre-Phase-4 gap.
  Gate behind `enable_runner_routes: bool = False` and skip mounting in
  prod. Track separately, NOT in Phase 4.
- **MEDIUM (Block I)** — `/api/v1/auth/refresh` re-uses the same JWT
  claims forever. No `iat`/`jti`, no rotation tracking, no revocation list.
  If a session cookie leaks, an attacker can refresh until password change.
  Add `jti` + a revocation table when the Users pillar lands in Block I.

## Notas finales

**Tiempo estimado:** 6-10 días dev intensivo dedicado.

**Costo OpenAI:** $0 — frontend no llama LLMs.

**Self-question loop puntos:** después de cada bloque (A-L), dispatch code-reviewer agent. Aplicar feedback antes de tag.

**Honesty checkpoint:** al final del bloque D (tag `phase-4a-foundation`) tienes lo MÍNIMO operable. Si te quedas sin tiempo, ese tag es ya producción-ready para piloto pequeño. Bloques E-L agregan valor pero no son bloqueantes.

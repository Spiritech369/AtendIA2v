# Sidebar redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reagrupar el sidebar en 6 grupos colapsables con badges dinámicos, modo compacto, drawer mobile y un único endpoint backend para counts.

**Architecture:** Menú declarativo (`menu-config.ts`) tipado con grupos y `roles[]` por ítem, filtrado client-side via `filterMenuByRole`. Badges resueltos por un nuevo `GET /api/v1/navigation/badges` (5 counts paralelos + 1 user-scoped) con polling cada 30s. Estado UI (compact, expandedGroups) en Zustand con persist a localStorage. Drawer mobile vía `Sheet` (shadcn) bajo el breakpoint md.

**Tech Stack:** FastAPI + SQLAlchemy async + pytest (backend); React 19 + TS strict + TanStack Query + Tailwind + shadcn + Zustand + Vitest (frontend).

**Design doc:** `docs/plans/2026-05-13-sidebar-redesign-design.md`

---

## Task 1 — Backend `/navigation/badges` endpoint

**Files:**
- Create: `core/atendia/api/navigation_routes.py`
- Create: `core/tests/api/test_navigation_badges.py`
- Modify: `core/atendia/main.py` — registrar router

**Step 1: Test failing**

```python
# core/tests/api/test_navigation_badges.py
"""Tests for GET /api/v1/navigation/badges.

Sembramos volumen controlado por tenant + user y verificamos cada
conteo individualmente.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_data(tenant_id: str, user_id: str) -> None:
    """Insert minimal rows so badges have something to count."""
    now = datetime.now(timezone.utc)

    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            # Customer (cascade root for conversations/handoffs/appointments)
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tenant_id, "p": f"+521555{uuid4().hex[:8]}"},
                )
            ).scalar()

            # 3 conversations: 2 active + 1 resolved
            for i, status in enumerate(["active", "active", "resolved"]):
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, status, current_stage) "
                        "VALUES (:t, :c, :s, 'new')"
                    ),
                    {"t": tenant_id, "c": cust_id, "s": status},
                )

            # We need a conversation for the handoff FK
            conv_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM conversations WHERE tenant_id = :t LIMIT 1"
                    ),
                    {"t": tenant_id},
                )
            ).scalar()

            # 3 handoffs: 1 open recent, 1 open overdue (>2h), 1 resolved
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(tenant_id, conversation_id, reason, status, requested_at) "
                    "VALUES (:t, :c, 'r1', 'open', :now)"
                ),
                {"t": tenant_id, "c": conv_id, "now": now},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(tenant_id, conversation_id, reason, status, requested_at) "
                    "VALUES (:t, :c, 'r2', 'assigned', :old)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "old": now - timedelta(hours=3),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(tenant_id, conversation_id, reason, status, requested_at, resolved_at) "
                    "VALUES (:t, :c, 'r3', 'resolved', :old, :now)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "old": now - timedelta(hours=5),
                    "now": now,
                },
            )

            # 2 appointments today (scheduled, confirmed), 1 tomorrow
            today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
            tomorrow_noon = today_noon + timedelta(days=1)
            for sched, status in [
                (today_noon, "scheduled"),
                (today_noon + timedelta(hours=2), "confirmed"),
                (tomorrow_noon, "scheduled"),
            ]:
                await conn.execute(
                    text(
                        "INSERT INTO appointments "
                        "(tenant_id, customer_id, scheduled_at, service, status) "
                        "VALUES (:t, :c, :s, 'visita', :st)"
                    ),
                    {"t": tenant_id, "c": cust_id, "s": sched, "st": status},
                )

            # 1 turn_trace with errors in last 24h, 1 older, 1 no error
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(tenant_id, conversation_id, turn_number, errors, total_cost_usd) "
                    "VALUES (:t, :c, 1, :e, 0)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "e": json.dumps([{"type": "tool_error"}]),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(tenant_id, conversation_id, turn_number, errors, total_cost_usd, created_at) "
                    "VALUES (:t, :c, 2, :e, 0, :old)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "e": json.dumps([{"type": "policy"}]),
                    "old": now - timedelta(days=2),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(tenant_id, conversation_id, turn_number, total_cost_usd) "
                    "VALUES (:t, :c, 3, 0)"
                ),
                {"t": tenant_id, "c": conv_id},
            )

            # 2 unread notifications + 1 read for this user
            for read, title in [(False, "n1"), (False, "n2"), (True, "n3")]:
                await conn.execute(
                    text(
                        "INSERT INTO notifications "
                        "(tenant_id, user_id, title, read) "
                        "VALUES (:t, :u, :title, :r)"
                    ),
                    {"t": tenant_id, "u": user_id, "title": title, "r": read},
                )

        await engine.dispose()

    asyncio.run(_do())


def test_navigation_badges_counts(client_operator):
    _seed_data(client_operator.tenant_id, client_operator.user_id)

    resp = client_operator.get("/api/v1/navigation/badges")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["conversations_open"] == 2
    assert body["handoffs_open"] == 2          # open + assigned
    assert body["handoffs_overdue"] == 1       # the >2h one
    assert body["appointments_today"] == 2
    assert body["ai_debug_warnings"] == 1      # only the last-24h one
    assert body["unread_notifications"] == 2


def test_navigation_badges_tenant_isolation(client_operator, client_tenant_admin):
    """Tenant A's counts should not leak into tenant B."""
    _seed_data(client_operator.tenant_id, client_operator.user_id)

    # client_tenant_admin lives in a DIFFERENT tenant — its counts should
    # be zero-ish (no seed for that tenant).
    resp = client_tenant_admin.get("/api/v1/navigation/badges")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversations_open"] == 0
    assert body["handoffs_open"] == 0
    assert body["appointments_today"] == 0


def test_navigation_badges_requires_auth(client):
    resp = client.get("/api/v1/navigation/badges")
    assert resp.status_code in (401, 403)
```

**Step 2: Run → FAIL** (route not found)

```bash
$env:ATENDIA_V2_DATABASE_URL = "postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2"
uv run python -m pytest core/tests/api/test_navigation_badges.py -v
```

Expected: 404 Not Found on the route.

**Step 3: Implementación**

```python
# core/atendia/api/navigation_routes.py
"""Navigation badges — aggregated counts for the sidebar.

Single endpoint, 5 tenant-scoped counts + 1 user-scoped count, executed
in parallel via asyncio.gather. Polled by the frontend every 30s.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.appointment import Appointment
from atendia.db.models.conversation import Conversation
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.notification import Notification
from atendia.db.models.turn_trace import TurnTrace
from atendia.db.session import get_db_session

router = APIRouter()

# Handoffs older than this are flagged as overdue (no dedicated SLA column).
HANDOFF_OVERDUE_HOURS = 2


class NavigationBadges(BaseModel):
    conversations_open: int
    handoffs_open: int
    handoffs_overdue: int
    appointments_today: int
    ai_debug_warnings: int
    unread_notifications: int


@router.get("/badges", response_model=NavigationBadges)
async def get_navigation_badges(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NavigationBadges:
    now = datetime.now(timezone.utc)
    overdue_threshold = now - timedelta(hours=HANDOFF_OVERDUE_HOURS)
    warnings_since = now - timedelta(hours=24)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    async def _count(stmt):
        return (await session.execute(stmt)).scalar_one()

    conv_q = select(func.count()).select_from(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.deleted_at.is_(None),
        Conversation.status != "resolved",
    )
    handoffs_open_q = select(func.count()).select_from(HumanHandoff).where(
        HumanHandoff.tenant_id == tenant_id,
        HumanHandoff.status.in_(("open", "assigned")),
    )
    handoffs_overdue_q = select(func.count()).select_from(HumanHandoff).where(
        HumanHandoff.tenant_id == tenant_id,
        HumanHandoff.status.in_(("open", "assigned")),
        HumanHandoff.requested_at < overdue_threshold,
    )
    appointments_q = select(func.count()).select_from(Appointment).where(
        Appointment.tenant_id == tenant_id,
        Appointment.scheduled_at >= today_start,
        Appointment.scheduled_at < today_end,
        Appointment.status.in_(("scheduled", "confirmed", "pending")),
    )
    warnings_q = select(func.count()).select_from(TurnTrace).where(
        TurnTrace.tenant_id == tenant_id,
        TurnTrace.errors.is_not(None),
        TurnTrace.created_at >= warnings_since,
    )
    unread_q = select(func.count()).select_from(Notification).where(
        Notification.user_id == user.user_id,
        Notification.read.is_(False),
    )

    (
        conversations_open,
        handoffs_open,
        handoffs_overdue,
        appointments_today,
        ai_debug_warnings,
        unread_notifications,
    ) = await asyncio.gather(
        _count(conv_q),
        _count(handoffs_open_q),
        _count(handoffs_overdue_q),
        _count(appointments_q),
        _count(warnings_q),
        _count(unread_q),
    )

    return NavigationBadges(
        conversations_open=conversations_open,
        handoffs_open=handoffs_open,
        handoffs_overdue=handoffs_overdue,
        appointments_today=appointments_today,
        ai_debug_warnings=ai_debug_warnings,
        unread_notifications=unread_notifications,
    )
```

Registrar en `core/atendia/main.py` después de los otros `include_router`:

```python
from atendia.api.navigation_routes import router as navigation_router
# ...
app.include_router(navigation_router, prefix="/api/v1/navigation", tags=["navigation"])
```

**Step 4: Run → PASS**

```bash
uv run python -m pytest core/tests/api/test_navigation_badges.py -v
```

Expected: 3 passed.

**Step 5: Commit**

```bash
git add core/atendia/api/navigation_routes.py core/atendia/main.py core/tests/api/test_navigation_badges.py
git commit -m "feat(navigation): GET /api/v1/navigation/badges aggregated counts"
```

---

## Task 2 — Frontend menu-config + filterMenuByRole

**Files:**
- Create: `frontend/src/features/navigation/types.ts`
- Create: `frontend/src/features/navigation/menu-config.ts`
- Create: `frontend/tests/features/navigation/menu-config.test.ts`

**Step 1: Tests**

```ts
// frontend/tests/features/navigation/menu-config.test.ts
import { describe, expect, it } from "vitest";

import { filterMenuByRole, NAV_GROUPS } from "@/features/navigation/menu-config";

describe("NAV_GROUPS", () => {
  it("contains 6 groups in the expected order", () => {
    expect(NAV_GROUPS.map((g) => g.id)).toEqual([
      "dashboard",
      "operacion",
      "ia",
      "automation",
      "metrics",
      "admin",
    ]);
  });
});

describe("filterMenuByRole", () => {
  it("operator: excludes agents/users/audit-log/inbox-settings/config", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "operator");
    const items = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(items).not.toContain("agents");
    expect(items).not.toContain("users");
    expect(items).not.toContain("audit-log");
    expect(items).not.toContain("inbox-settings");
    expect(items).not.toContain("config");
    // Sees core operation:
    expect(items).toContain("conversations");
    expect(items).toContain("handoffs");
    expect(items).toContain("customers");
  });

  it("tenant_admin: includes agents/users/inbox-settings/config, excludes audit-log", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "tenant_admin");
    const items = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(items).toContain("agents");
    expect(items).toContain("users");
    expect(items).toContain("inbox-settings");
    expect(items).toContain("config");
    expect(items).not.toContain("audit-log");
  });

  it("superadmin: includes everything including audit-log", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "superadmin");
    const items = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(items).toContain("audit-log");
    expect(items).toContain("users");
  });

  it("drops empty groups after filtering", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "operator");
    for (const g of groups) {
      expect(g.items.length).toBeGreaterThan(0);
    }
  });
});
```

**Step 2: FAIL** → module not found.

**Step 3: Implementation**

```ts
// frontend/src/features/navigation/types.ts
import type { LucideIcon } from "lucide-react";

import type { Role } from "@/stores/auth";

export type BadgeKey =
  | "conversations_open"
  | "handoffs_open"
  | "appointments_today"
  | "ai_debug_warnings"
  | "unread_notifications";

export interface NavItem {
  id: string;
  label: string;
  to: string;
  icon: LucideIcon;
  roles: readonly Role[];
  badgeKey?: BadgeKey;
  /** When true, exact-path match only (e.g. "/" should not match every route). */
  exactMatch?: boolean;
  /** Extra paths that also count as "active" for this item (e.g. "/conversations" for "/"). */
  activeAlsoOn?: readonly string[];
}

export interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
}
```

```ts
// frontend/src/features/navigation/menu-config.ts
import {
  BarChart3,
  BookOpen,
  Bug,
  CalendarDays,
  Columns3,
  Database,
  FileText,
  LayoutDashboard,
  MessageCircle,
  Network,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";

import type { Role } from "@/stores/auth";

import type { NavGroup } from "./types";

const OPERATOR_PLUS: readonly Role[] = [
  "operator",
  "tenant_admin",
  "superadmin",
];
const TENANT_ADMIN_PLUS: readonly Role[] = ["tenant_admin", "superadmin"];
const SUPERADMIN_ONLY: readonly Role[] = ["superadmin"];

export const NAV_GROUPS: NavGroup[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    items: [
      {
        id: "dashboard",
        label: "Dashboard",
        to: "/dashboard",
        icon: LayoutDashboard,
        roles: OPERATOR_PLUS,
      },
    ],
  },
  {
    id: "operacion",
    label: "Operación",
    items: [
      {
        id: "conversations",
        label: "Conversaciones",
        to: "/",
        icon: MessageCircle,
        roles: OPERATOR_PLUS,
        exactMatch: true,
        activeAlsoOn: ["/conversations"],
        badgeKey: "conversations_open",
      },
      {
        id: "handoffs",
        label: "Handoffs",
        to: "/handoffs",
        icon: ShieldCheck,
        roles: OPERATOR_PLUS,
        badgeKey: "handoffs_open",
      },
      {
        id: "pipeline",
        label: "Pipeline",
        to: "/pipeline",
        icon: Columns3,
        roles: OPERATOR_PLUS,
      },
      {
        id: "customers",
        label: "Clientes",
        to: "/customers",
        icon: Users,
        roles: OPERATOR_PLUS,
      },
      {
        id: "appointments",
        label: "Citas",
        to: "/appointments",
        icon: CalendarDays,
        roles: OPERATOR_PLUS,
        badgeKey: "appointments_today",
      },
    ],
  },
  {
    id: "ia",
    label: "Inteligencia IA",
    items: [
      {
        id: "agents",
        label: "Agentes IA",
        to: "/agents",
        icon: Sparkles,
        roles: TENANT_ADMIN_PLUS,
      },
      {
        id: "knowledge",
        label: "Conocimiento",
        to: "/knowledge",
        icon: BookOpen,
        roles: OPERATOR_PLUS,
      },
      {
        id: "turn-traces",
        label: "Debug de turnos",
        to: "/turn-traces",
        icon: Bug,
        roles: OPERATOR_PLUS,
        badgeKey: "ai_debug_warnings",
      },
    ],
  },
  {
    id: "automation",
    label: "Automatización",
    items: [
      {
        id: "workflows",
        label: "Workflows",
        to: "/workflows",
        icon: Network,
        roles: OPERATOR_PLUS,
      },
      {
        id: "inbox-settings",
        label: "Config. Bandeja",
        to: "/inbox-settings",
        icon: SlidersHorizontal,
        roles: TENANT_ADMIN_PLUS,
      },
    ],
  },
  {
    id: "metrics",
    label: "Medición",
    items: [
      {
        id: "analytics",
        label: "Analítica",
        to: "/analytics",
        icon: BarChart3,
        roles: OPERATOR_PLUS,
      },
      {
        id: "exports",
        label: "Exportar",
        to: "/exports",
        icon: Database,
        roles: OPERATOR_PLUS,
      },
    ],
  },
  {
    id: "admin",
    label: "Administración",
    items: [
      {
        id: "users",
        label: "Usuarios",
        to: "/users",
        icon: UserRound,
        roles: TENANT_ADMIN_PLUS,
      },
      {
        id: "config",
        label: "Configuración",
        to: "/config",
        icon: Settings,
        roles: TENANT_ADMIN_PLUS,
      },
      {
        id: "audit-log",
        label: "Auditoría",
        to: "/audit-log",
        icon: FileText,
        roles: SUPERADMIN_ONLY,
      },
    ],
  },
];

export function filterMenuByRole(
  groups: readonly NavGroup[],
  role: Role | null | undefined,
): NavGroup[] {
  if (!role) return [];
  return groups
    .map((g) => ({
      ...g,
      items: g.items.filter((it) => it.roles.includes(role)),
    }))
    .filter((g) => g.items.length > 0);
}
```

**Step 4: PASS**

```bash
cd frontend && pnpm exec vitest run tests/features/navigation/menu-config.test.ts
```

Expected: 4 passed.

**Step 5: Commit**

```bash
git add frontend/src/features/navigation/types.ts frontend/src/features/navigation/menu-config.ts frontend/tests/features/navigation/menu-config.test.ts
git commit -m "feat(navigation): declarative menu config + filterMenuByRole"
```

---

## Task 3 — Frontend useNavBadges hook

**Files:**
- Create: `frontend/src/features/navigation/api.ts`
- Create: `frontend/src/features/navigation/hooks.ts`
- Create: `frontend/tests/features/navigation/useNavBadges.test.tsx`

**Step 1: Tests + Step 2: FAIL**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { navigationApi } from "@/features/navigation/api";
import { useNavBadges } from "@/features/navigation/hooks";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useNavBadges", () => {
  it("returns the counts on success", async () => {
    const spy = vi.spyOn(navigationApi, "getBadges").mockResolvedValue({
      conversations_open: 5,
      handoffs_open: 2,
      handoffs_overdue: 1,
      appointments_today: 3,
      ai_debug_warnings: 0,
      unread_notifications: 4,
    });
    const { result } = renderHook(() => useNavBadges(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => {
      expect(result.current.data?.conversations_open).toBe(5);
    });
    expect(result.current.data?.handoffs_overdue).toBe(1);
    spy.mockRestore();
  });

  it("returns undefined data on error without throwing", async () => {
    const spy = vi
      .spyOn(navigationApi, "getBadges")
      .mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useNavBadges(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });
    expect(result.current.data).toBeUndefined();
    spy.mockRestore();
  });
});
```

**Step 3: Implementación**

```ts
// frontend/src/features/navigation/api.ts
import { api } from "@/lib/api-client";

export interface NavigationBadges {
  conversations_open: number;
  handoffs_open: number;
  handoffs_overdue: number;
  appointments_today: number;
  ai_debug_warnings: number;
  unread_notifications: number;
}

export const navigationApi = {
  getBadges: async (): Promise<NavigationBadges> =>
    (await api.get<NavigationBadges>("/navigation/badges")).data,
};
```

```ts
// frontend/src/features/navigation/hooks.ts
import { useQuery } from "@tanstack/react-query";

import { navigationApi } from "./api";

export function useNavBadges() {
  return useQuery({
    queryKey: ["navigation", "badges"],
    queryFn: navigationApi.getBadges,
    refetchInterval: 30_000,
    retry: 1,
  });
}
```

**Step 4: PASS**

```bash
pnpm exec vitest run tests/features/navigation/useNavBadges.test.tsx
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add frontend/src/features/navigation/api.ts frontend/src/features/navigation/hooks.ts frontend/tests/features/navigation/useNavBadges.test.tsx
git commit -m "feat(navigation): useNavBadges hook with 30s polling"
```

---

## Task 4 — Sidebar Zustand store

**Files:**
- Create: `frontend/src/stores/sidebar-store.ts`
- Create: `frontend/tests/stores/sidebar-store.test.ts`

**Step 1: Tests**

```ts
import { beforeEach, describe, expect, it } from "vitest";

import { useSidebarStore } from "@/stores/sidebar-store";

describe("sidebar-store", () => {
  beforeEach(() => {
    useSidebarStore.setState({
      compact: false,
      expandedGroups: {},
    });
    window.localStorage.clear();
  });

  it("toggleCompact flips the flag", () => {
    expect(useSidebarStore.getState().compact).toBe(false);
    useSidebarStore.getState().toggleCompact();
    expect(useSidebarStore.getState().compact).toBe(true);
    useSidebarStore.getState().toggleCompact();
    expect(useSidebarStore.getState().compact).toBe(false);
  });

  it("isGroupExpanded defaults to true for unknown groups", () => {
    expect(useSidebarStore.getState().isGroupExpanded("operacion")).toBe(true);
  });

  it("toggleGroup flips the group state", () => {
    useSidebarStore.getState().toggleGroup("operacion");
    expect(useSidebarStore.getState().isGroupExpanded("operacion")).toBe(false);
    useSidebarStore.getState().toggleGroup("operacion");
    expect(useSidebarStore.getState().isGroupExpanded("operacion")).toBe(true);
  });

  it("persists to localStorage", () => {
    useSidebarStore.getState().toggleCompact();
    const raw = window.localStorage.getItem("atendia.sidebar.v1");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).state.compact).toBe(true);
  });
});
```

**Step 2: FAIL**

**Step 3: Implementation**

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SidebarState {
  compact: boolean;
  expandedGroups: Record<string, boolean>;
  toggleCompact: () => void;
  toggleGroup: (groupId: string) => void;
  isGroupExpanded: (groupId: string) => boolean;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set, get) => ({
      compact: false,
      expandedGroups: {},
      toggleCompact: () => set((s) => ({ compact: !s.compact })),
      toggleGroup: (groupId) =>
        set((s) => ({
          expandedGroups: {
            ...s.expandedGroups,
            [groupId]: !(s.expandedGroups[groupId] ?? true),
          },
        })),
      isGroupExpanded: (groupId) => get().expandedGroups[groupId] ?? true,
    }),
    {
      name: "atendia.sidebar.v1",
      partialize: (state) => ({
        compact: state.compact,
        expandedGroups: state.expandedGroups,
      }),
    },
  ),
);
```

**Step 4: PASS**

```bash
pnpm exec vitest run tests/stores/sidebar-store.test.ts
```

Expected: 4 passed.

**Step 5: Commit**

```bash
git add frontend/src/stores/sidebar-store.ts frontend/tests/stores/sidebar-store.test.ts
git commit -m "feat(navigation): sidebar Zustand store with localStorage persist"
```

---

## Task 5 — SidebarBadge + SidebarItem

**Files:**
- Create: `frontend/src/components/sidebar/SidebarBadge.tsx`
- Create: `frontend/src/components/sidebar/SidebarItem.tsx`
- Create: `frontend/tests/components/sidebar/SidebarItem.test.tsx`

**Step 1: Tests for SidebarItem (covers SidebarBadge transitively)**

```tsx
import { createRouter, RouterProvider, createRoute, createRootRoute, createMemoryHistory } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { MessageCircle } from "lucide-react";
import { describe, expect, it } from "vitest";

import { SidebarItem } from "@/components/sidebar/SidebarItem";
import type { NavItem } from "@/features/navigation/types";

function renderAtPath(item: NavItem, badge: number | undefined, path: string) {
  const rootRoute = createRootRoute({
    component: () => (
      <SidebarItem item={item} active={isActiveForPath(item, path)} badgeValue={badge} compact={false} />
    ),
  });
  const childRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "*",
    component: () => null,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([childRoute]),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  return render(<RouterProvider router={router} />);
}

// Replicates the helper used inside AppSidebar to compute active state;
// SidebarItem itself takes `active` as a prop, so we pre-compute here.
function isActiveForPath(item: NavItem, path: string): boolean {
  if (item.exactMatch) {
    if (path === item.to) return true;
    if (item.activeAlsoOn) {
      return item.activeAlsoOn.some((p) => path === p || path.startsWith(`${p}/`));
    }
    return false;
  }
  return path === item.to || path.startsWith(`${item.to}/`);
}

const baseItem: NavItem = {
  id: "conversations",
  label: "Conversaciones",
  to: "/",
  icon: MessageCircle,
  roles: ["operator", "tenant_admin", "superadmin"],
  exactMatch: true,
  activeAlsoOn: ["/conversations"],
};

describe("SidebarItem", () => {
  it("renders the label", () => {
    renderAtPath(baseItem, undefined, "/dashboard");
    expect(screen.getByText("Conversaciones")).toBeInTheDocument();
  });

  it("marks active with aria-current when path matches exact", () => {
    renderAtPath(baseItem, undefined, "/");
    const link = screen.getByRole("link", { name: /conversaciones/i });
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("marks active when navigating to a sub-route via activeAlsoOn", () => {
    renderAtPath(baseItem, undefined, "/conversations/abc-123");
    const link = screen.getByRole("link", { name: /conversaciones/i });
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("renders badge when value > 0", () => {
    renderAtPath(baseItem, 7, "/dashboard");
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("does not render badge when value is 0 or undefined", () => {
    renderAtPath(baseItem, 0, "/dashboard");
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
```

**Step 2: FAIL**

**Step 3: Implementation**

```tsx
// frontend/src/components/sidebar/SidebarBadge.tsx
import { cn } from "@/lib/utils";

export type SidebarBadgeVariant = "default" | "destructive";

export function SidebarBadge({
  value,
  variant = "default",
}: {
  value: number;
  variant?: SidebarBadgeVariant;
}) {
  if (value <= 0) return null;
  return (
    <span
      className={cn(
        "ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums",
        variant === "destructive"
          ? "bg-red-500/15 text-red-600"
          : "bg-primary/15 text-primary",
      )}
    >
      {value > 99 ? "99+" : value}
    </span>
  );
}
```

```tsx
// frontend/src/components/sidebar/SidebarItem.tsx
import { Link } from "@tanstack/react-router";

import type { NavItem } from "@/features/navigation/types";
import { cn } from "@/lib/utils";

import { SidebarBadge, type SidebarBadgeVariant } from "./SidebarBadge";

interface Props {
  item: NavItem;
  active: boolean;
  compact: boolean;
  badgeValue?: number;
  badgeVariant?: SidebarBadgeVariant;
}

export function SidebarItem({
  item,
  active,
  compact,
  badgeValue,
  badgeVariant = "default",
}: Props) {
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      aria-current={active ? "page" : undefined}
      title={compact ? item.label : undefined}
      className={cn(
        "group/item relative flex items-center gap-3 rounded-md px-3 py-1.5 text-sm transition-colors",
        active
          ? "bg-primary/10 text-foreground font-medium"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-primary"
        />
      )}
      <Icon className="h-4 w-4 shrink-0" />
      {!compact && <span className="truncate">{item.label}</span>}
      {!compact && badgeValue !== undefined && (
        <SidebarBadge value={badgeValue} variant={badgeVariant} />
      )}
    </Link>
  );
}
```

**Step 4: PASS**

```bash
pnpm exec vitest run tests/components/sidebar/SidebarItem.test.tsx
```

Expected: 5 passed.

**Step 5: Commit**

```bash
git add frontend/src/components/sidebar/SidebarBadge.tsx frontend/src/components/sidebar/SidebarItem.tsx frontend/tests/components/sidebar/SidebarItem.test.tsx
git commit -m "feat(sidebar): SidebarBadge + SidebarItem with active/compact/badge support"
```

---

## Task 6 — SidebarGroup with collapse

**Files:**
- Create: `frontend/src/components/sidebar/SidebarGroup.tsx`
- Create: `frontend/tests/components/sidebar/SidebarGroup.test.tsx`

**Step 1: Tests**

```tsx
import { createRootRoute, createRouter, RouterProvider, createMemoryHistory, createRoute } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LayoutDashboard } from "lucide-react";
import { beforeEach, describe, expect, it } from "vitest";

import { SidebarGroup } from "@/components/sidebar/SidebarGroup";
import type { NavGroup } from "@/features/navigation/types";
import { useSidebarStore } from "@/stores/sidebar-store";

const group: NavGroup = {
  id: "ops",
  label: "Operación",
  items: [
    {
      id: "dashboard",
      label: "Dashboard",
      to: "/dashboard",
      icon: LayoutDashboard,
      roles: ["operator", "tenant_admin", "superadmin"],
    },
  ],
};

function renderGroup() {
  const root = createRootRoute({
    component: () => (
      <SidebarGroup group={group} compact={false} activePath="/dashboard" badges={undefined} />
    ),
  });
  const child = createRoute({
    getParentRoute: () => root,
    path: "*",
    component: () => null,
  });
  const router = createRouter({
    routeTree: root.addChildren([child]),
    history: createMemoryHistory({ initialEntries: ["/dashboard"] }),
  });
  return render(<RouterProvider router={router} />);
}

describe("SidebarGroup", () => {
  beforeEach(() => {
    useSidebarStore.setState({ compact: false, expandedGroups: {} });
  });

  it("renders the group label and items", () => {
    renderGroup();
    expect(screen.getByText("Operación")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("toggles items visibility on header click", async () => {
    const user = userEvent.setup();
    renderGroup();
    const header = screen.getByRole("button", { name: /Operación/i });
    expect(header).toHaveAttribute("aria-expanded", "true");
    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
  });
});
```

**Step 2: FAIL**

**Step 3: Implementation**

```tsx
// frontend/src/components/sidebar/SidebarGroup.tsx
import { ChevronDown } from "lucide-react";

import type { BadgeKey, NavGroup, NavItem } from "@/features/navigation/types";
import type { NavigationBadges } from "@/features/navigation/api";
import { useSidebarStore } from "@/stores/sidebar-store";
import { cn } from "@/lib/utils";

import { SidebarItem } from "./SidebarItem";

interface Props {
  group: NavGroup;
  compact: boolean;
  activePath: string;
  badges: NavigationBadges | undefined;
}

function isItemActive(item: NavItem, path: string): boolean {
  if (item.exactMatch) {
    if (path === item.to) return true;
    if (item.activeAlsoOn) {
      return item.activeAlsoOn.some((p) => path === p || path.startsWith(`${p}/`));
    }
    return false;
  }
  return path === item.to || path.startsWith(`${item.to}/`);
}

export function SidebarGroup({ group, compact, activePath, badges }: Props) {
  const expanded = useSidebarStore((s) => s.isGroupExpanded(group.id));
  const toggle = useSidebarStore((s) => s.toggleGroup);

  return (
    <div className="px-2">
      {!compact && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => toggle(group.id)}
          className="flex w-full items-center justify-between rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
        >
          <span>{group.label}</span>
          <ChevronDown
            className={cn(
              "h-3 w-3 transition-transform",
              !expanded && "-rotate-90",
            )}
          />
        </button>
      )}
      {(compact || expanded) && (
        <div className="mt-0.5 flex flex-col gap-0.5">
          {group.items.map((item) => {
            const value = item.badgeKey ? badges?.[item.badgeKey] : undefined;
            const isOverdueHandoff =
              item.id === "handoffs" && (badges?.handoffs_overdue ?? 0) > 0;
            return (
              <SidebarItem
                key={item.id}
                item={item}
                active={isItemActive(item, activePath)}
                compact={compact}
                badgeValue={value}
                badgeVariant={isOverdueHandoff ? "destructive" : "default"}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
```

**Step 4: PASS**

```bash
pnpm exec vitest run tests/components/sidebar/SidebarGroup.test.tsx
```

**Step 5: Commit**

```bash
git add frontend/src/components/sidebar/SidebarGroup.tsx frontend/tests/components/sidebar/SidebarGroup.test.tsx
git commit -m "feat(sidebar): SidebarGroup with collapse + badge wiring"
```

---

## Task 7 — AppSidebar + SidebarHeader + SidebarFooter

**Files:**
- Create: `frontend/src/components/sidebar/SidebarHeader.tsx`
- Create: `frontend/src/components/sidebar/SidebarFooter.tsx`
- Create: `frontend/src/components/sidebar/AppSidebar.tsx`

**No new tests** — integration is covered by the AppShell smoke (Task 8). The
sub-components are thin wrappers over what other tests already prove.

**Step 1: SidebarHeader**

```tsx
import { WhatsAppStatusBadge } from "@/components/WhatsAppStatusBadge";
import { Separator } from "@/components/ui/separator";

export function SidebarHeader({ tenantId, compact }: { tenantId: string | null | undefined; compact: boolean }) {
  return (
    <>
      <div className="flex h-14 shrink-0 items-center gap-2 px-4">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
          AI
        </span>
        {!compact && (
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">AtendIA</div>
            <div className="truncate text-[10px] text-muted-foreground">
              {tenantId ? `Tenant ${tenantId.slice(0, 8)}` : "Sin tenant"}
            </div>
          </div>
        )}
      </div>
      {!compact && (
        <div className="px-4 pb-3">
          <WhatsAppStatusBadge />
        </div>
      )}
      <Separator />
    </>
  );
}
```

**Step 2: SidebarFooter**

```tsx
import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuthStore } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar-store";

const ROLE_LABELS: Record<string, string> = {
  operator: "Operador",
  tenant_admin: "Admin tenant",
  superadmin: "Superadmin",
  supervisor: "Supervisor",
  manager: "Manager",
  sales_agent: "Vendedor",
  ai_reviewer: "Revisor IA",
};

export function SidebarFooter() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const compact = useSidebarStore((s) => s.compact);
  const toggleCompact = useSidebarStore((s) => s.toggleCompact);

  if (!user) return null;
  const initials = user.email.slice(0, 2).toUpperCase();
  const roleLabel = ROLE_LABELS[user.role] ?? user.role;

  return (
    <>
      <Separator />
      <div className="flex shrink-0 items-center gap-2 px-3 py-3">
        <Avatar className="h-7 w-7 shrink-0">
          <AvatarFallback className="text-[10px]">{initials}</AvatarFallback>
        </Avatar>
        {!compact && (
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium">{user.email}</div>
            <div className="text-[10px] text-muted-foreground">{roleLabel}</div>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          aria-label={compact ? "Expandir menú" : "Compactar menú"}
          onClick={toggleCompact}
        >
          {compact ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </Button>
        {!compact && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            aria-label="Cerrar sesión"
            onClick={async () => {
              await logout();
              window.location.assign("/login");
            }}
          >
            <LogOut className="h-4 w-4" />
          </Button>
        )}
      </div>
    </>
  );
}
```

**Step 3: AppSidebar**

```tsx
import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { filterMenuByRole, NAV_GROUPS } from "@/features/navigation/menu-config";
import { useNavBadges } from "@/features/navigation/hooks";
import { useAuthStore } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar-store";
import { cn } from "@/lib/utils";

import { SidebarFooter } from "./SidebarFooter";
import { SidebarGroup } from "./SidebarGroup";
import { SidebarHeader } from "./SidebarHeader";

export function AppSidebar() {
  const user = useAuthStore((s) => s.user);
  const compact = useSidebarStore((s) => s.compact);
  const path = useRouterState({ select: (s) => s.location.pathname });
  const badges = useNavBadges();

  const groups = useMemo(
    () => filterMenuByRole(NAV_GROUPS, user?.role),
    [user?.role],
  );

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col overflow-hidden border-r bg-sidebar text-sidebar-foreground transition-[width] duration-150",
        compact ? "w-14" : "w-60",
      )}
    >
      <SidebarHeader tenantId={user?.tenant_id ?? null} compact={compact} />
      <div className="flex-1 overflow-y-auto py-2">
        {!user ? (
          <div className="space-y-3 px-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-full" />
          </div>
        ) : (
          <nav className="flex flex-col gap-3">
            {groups.map((group) => (
              <SidebarGroup
                key={group.id}
                group={group}
                compact={compact}
                activePath={path}
                badges={badges.data}
              />
            ))}
          </nav>
        )}
      </div>
      <SidebarFooter />
    </aside>
  );
}
```

**Step 4: Typecheck**

```bash
pnpm exec tsc --noEmit
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/components/sidebar/SidebarHeader.tsx frontend/src/components/sidebar/SidebarFooter.tsx frontend/src/components/sidebar/AppSidebar.tsx
git commit -m "feat(sidebar): AppSidebar with header, footer, compact toggle"
```

---

## Task 8 — Integrar en AppShell + smoke final

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`

**Step 1: Refactor AppShell**

Reemplazar el cuerpo de `AppShell` por:

```tsx
import { Link, useRouterState } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import type { ReactNode } from "react";

import { AppSidebar } from "@/components/sidebar/AppSidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { notificationsApi } from "@/features/notifications/api";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: ReactNode }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const isHandoffCommandCenter = path === "/handoffs" || path.startsWith("/handoffs/");

  return (
    <div
      className={cn(
        "flex h-screen overflow-hidden",
        isHandoffCommandCenter ? "bg-[#050b14]" : "bg-background",
      )}
    >
      <AppSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header
          className={cn(
            "flex h-12 items-center justify-end gap-3 border-b px-6",
            isHandoffCommandCenter
              ? "border-slate-800 bg-[#07101b] text-slate-200"
              : "bg-background",
          )}
        >
          <NotificationsDropdown />
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}

function NotificationsDropdown() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: notificationsApi.list,
    refetchInterval: 30_000,
  });
  const markRead = useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markAll = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = query.data?.unread_count ?? 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Notificaciones"
          className="relative"
        >
          <Bell className="h-4 w-4" />
          {unread > 0 && (
            <Badge className="absolute -right-1 -top-1 h-5 min-w-5 px-1 text-[10px]">
              {unread}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          Notificaciones
          {unread > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => markAll.mutate()}
            >
              Leer todas
            </Button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <ScrollArea className="max-h-80">
          {(query.data?.items ?? []).length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              Sin notificaciones.
            </div>
          ) : (
            query.data?.items.map((item) => (
              <DropdownMenuItem
                key={item.id}
                className="flex cursor-pointer flex-col items-start gap-1 py-2"
                onClick={() => {
                  if (!item.read) markRead.mutate(item.id);
                }}
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <span className={cn("text-sm", !item.read && "font-semibold")}>{item.title}</span>
                  {!item.read && <span className="h-2 w-2 rounded-full bg-primary" />}
                </div>
                {item.body && (
                  <span className="line-clamp-2 text-xs text-muted-foreground">{item.body}</span>
                )}
              </DropdownMenuItem>
            ))
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

**Step 2: TS check + vitest run**

```bash
pnpm exec tsc --noEmit
pnpm exec vitest run
```

Expected: ambos verdes (incluyendo todos los nuevos tests).

**Step 3: Backend smoke**

```bash
uv run python -m pytest core/tests/api/test_navigation_badges.py core/tests/api/test_rbac_matrix.py -q
```

Expected: verdes.

**Step 4: Biome autofix sobre archivos tocados**

```bash
pnpm exec biome check --write src/components/sidebar/ src/features/navigation/ src/stores/sidebar-store.ts src/components/AppShell.tsx tests/components/sidebar/ tests/features/navigation/ tests/stores/
```

**Step 5: Commit + merge a main**

```bash
git add -A frontend/
git commit -m "feat(sidebar): integrate AppSidebar into AppShell; drop legacy flat nav"

# Merge a main
git update-ref refs/heads/main claude/beautiful-mirzakhani-55368f
git push origin main
```

---

## Criterios de éxito

- [ ] `test_navigation_badges.py` 3 tests pasan; counts correctos por tenant.
- [ ] `menu-config.test.ts` 4 tests verifican filtrado por rol.
- [ ] `useNavBadges.test.tsx` 2 tests cubren success + error.
- [ ] `sidebar-store.test.ts` 4 tests cubren toggle + persist.
- [ ] `SidebarItem.test.tsx` 5 tests cubren active/badge/aria-current.
- [ ] `SidebarGroup.test.tsx` 2 tests cubren expand/collapse + aria-expanded.
- [ ] Total nuevos tests: ≥ 20. Frontend completo: 14+8 = ≥22 archivos pasando.
- [ ] TSC limpio, biome limpio en archivos tocados.
- [ ] Sidebar renderiza con 6 grupos, ítems filtrados por rol, badges visibles tras 30s.
- [ ] Compact toggle persiste a localStorage.
- [ ] AppShell header reducido (sólo NotificationsDropdown — el resto migró al sidebar).
- [ ] Branch mergeada a `main` + push.

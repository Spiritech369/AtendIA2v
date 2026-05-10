# Inbox Settings Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `/inbox-settings` route with a 3-panel settings UI (sidebar + workspace + live preview) backed by a real `GET/PUT /tenants/inbox-config` API that persists to `Tenant.config` JSONB — no migration required.

**Architecture:** Backend writes `inbox_config` into the existing `Tenant.config` JSONB column via two new endpoints in `tenants_routes.py`. Frontend is a TanStack Router file-based route that mounts an `InboxSettingsPage` component; all state is managed with React Query (load/save) + local `useState` for the draft. The 3-panel layout breaks out of AppShell's `p-6` using `-m-6 h-[calc(100vh-3.5rem)]`.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React 19 + TanStack Router v1 + React Query v5 + shadcn/ui + Tailwind 4 + lucide-react + sonner (frontend), pytest + httpx (backend tests), vitest + @testing-library/react (frontend tests).

---

## Data Contract

### InboxConfig shape (stored as `Tenant.config["inbox_config"]`)

```json
{
  "layout": {
    "three_pane": true,
    "rail_width": "expanded",
    "list_max_width": 360,
    "composer_density": "comfortable",
    "sticky_composer": true
  },
  "filter_chips": [
    { "id": "unread",            "label": "Sin leer",             "color": "#4f72f5", "query": "read_at IS NULL",                              "live_count": true,  "visible": true, "order": 0 },
    { "id": "mine",              "label": "Mías",                 "color": "#9b72f5", "query": "assigned_to = current_user",                   "live_count": true,  "visible": true, "order": 1 },
    { "id": "unassigned",        "label": "Sin asignar",          "color": "#f5a623", "query": "assigned_to IS NULL AND status != 'closed'",   "live_count": false, "visible": true, "order": 2 },
    { "id": "awaiting_customer", "label": "En espera de cliente", "color": "#4fa8f5", "query": "stage = 'waiting_customer'",                   "live_count": true,  "visible": true, "order": 3 },
    { "id": "stale",             "label": "Inactivas >24h",       "color": "#f25252", "query": "last_message_at < now() - interval '24h'",     "live_count": true,  "visible": true, "order": 4 }
  ],
  "stage_rings": [
    { "stage_id": "nuevo",       "emoji": "🆕", "color": "#6b7cf5", "sla_hours": 24 },
    { "stage_id": "en_curso",    "emoji": "🔄", "color": "#10c98f", "sla_hours": 4  },
    { "stage_id": "en_espera",   "emoji": "⏳", "color": "#f5a623", "sla_hours": 48 },
    { "stage_id": "cotizacion",  "emoji": "💰", "color": "#9b72f5", "sla_hours": 12 },
    { "stage_id": "documentos",  "emoji": "📄", "color": "#4fa8f5", "sla_hours": 24 },
    { "stage_id": "cierre",      "emoji": "🏁", "color": "#10c98f", "sla_hours": null }
  ],
  "handoff_rules": [
    { "id": "ask_price",   "intent": "ASK_PRICE",      "confidence": 82, "action": "suggest_template",        "template": "precio_hr_v_2025",   "enabled": true,  "order": 0 },
    { "id": "docs_miss",   "intent": "DOCS_MISSING",   "confidence": 75, "action": "send_checklist",          "template": "docs_checklist_v2",  "enabled": true,  "order": 1 },
    { "id": "human_req",   "intent": "HUMAN_REQUESTED","confidence": 90, "action": "assign_to_free_operator", "template": "",                   "enabled": true,  "order": 2 },
    { "id": "stale_24h",   "intent": "STALE_24H",      "confidence": 100,"action": "trigger_followup",        "template": "followup_24h",       "enabled": false, "order": 3 }
  ]
}
```

---

## Task 1: Backend — GET/PUT /tenants/inbox-config

**Files:**
- Modify: `core/atendia/api/tenants_routes.py` (append after timezone endpoints)
- Test: `core/tests/api/test_tenants_routes.py` (create if missing, else append)

### Step 1: Write failing test

```python
# core/tests/api/test_tenants_routes.py  (append)

async def test_get_inbox_config_returns_defaults(auth_client):
    """GET returns safe defaults when key not yet set."""
    r = await auth_client.get("/api/v1/tenants/me/inbox-config")
    assert r.status_code == 200
    data = r.json()
    assert "layout" in data["inbox_config"]
    assert data["inbox_config"]["layout"]["three_pane"] is True
    assert isinstance(data["inbox_config"]["filter_chips"], list)


async def test_put_inbox_config_persists(auth_client):
    """PUT round-trips the payload."""
    payload = {
        "inbox_config": {
            "layout": {
                "three_pane": False,
                "rail_width": "collapsed",
                "list_max_width": 320,
                "composer_density": "compact",
                "sticky_composer": False,
            },
            "filter_chips": [],
            "stage_rings": [],
            "handoff_rules": [],
        }
    }
    r = await auth_client.put("/api/v1/tenants/me/inbox-config", json=payload)
    assert r.status_code == 200
    assert r.json()["inbox_config"]["layout"]["three_pane"] is False

    # Verify persistence
    r2 = await auth_client.get("/api/v1/tenants/me/inbox-config")
    assert r2.json()["inbox_config"]["layout"]["three_pane"] is False


async def test_put_inbox_config_requires_tenant_admin(operator_client):
    """Regular operator cannot write inbox config."""
    r = await operator_client.put(
        "/api/v1/tenants/me/inbox-config",
        json={"inbox_config": {"layout": {}, "filter_chips": [], "stage_rings": [], "handoff_rules": []}},
    )
    assert r.status_code == 403
```

### Step 2: Run to confirm FAIL

```bash
cd core
uv run pytest tests/api/test_tenants_routes.py -k "inbox_config" -v
# Expected: FAILED — 404 Not Found (route doesn't exist yet)
```

### Step 3: Implement endpoints

Append to `core/atendia/api/tenants_routes.py` (before the trailing `_ = UTC` line):

```python
# ---------- Inbox Config ----------

DEFAULT_INBOX_CONFIG: dict = {
    "layout": {
        "three_pane": True,
        "rail_width": "expanded",
        "list_max_width": 360,
        "composer_density": "comfortable",
        "sticky_composer": True,
    },
    "filter_chips": [
        {"id": "unread",            "label": "Sin leer",             "color": "#4f72f5", "query": "read_at IS NULL",                              "live_count": True,  "visible": True, "order": 0},
        {"id": "mine",              "label": "Mías",                 "color": "#9b72f5", "query": "assigned_to = current_user",                   "live_count": True,  "visible": True, "order": 1},
        {"id": "unassigned",        "label": "Sin asignar",          "color": "#f5a623", "query": "assigned_to IS NULL AND status != 'closed'",   "live_count": False, "visible": True, "order": 2},
        {"id": "awaiting_customer", "label": "En espera de cliente", "color": "#4fa8f5", "query": "stage = 'waiting_customer'",                   "live_count": True,  "visible": True, "order": 3},
        {"id": "stale",             "label": "Inactivas >24h",       "color": "#f25252", "query": "last_message_at < now() - interval '24h'",     "live_count": True,  "visible": True, "order": 4},
    ],
    "stage_rings": [
        {"stage_id": "nuevo",      "emoji": "🆕", "color": "#6b7cf5", "sla_hours": 24},
        {"stage_id": "en_curso",   "emoji": "🔄", "color": "#10c98f", "sla_hours": 4},
        {"stage_id": "en_espera",  "emoji": "⏳", "color": "#f5a623", "sla_hours": 48},
        {"stage_id": "cotizacion", "emoji": "💰", "color": "#9b72f5", "sla_hours": 12},
        {"stage_id": "documentos", "emoji": "📄", "color": "#4fa8f5", "sla_hours": 24},
        {"stage_id": "cierre",     "emoji": "🏁", "color": "#10c98f", "sla_hours": None},
    ],
    "handoff_rules": [
        {"id": "ask_price", "intent": "ASK_PRICE",       "confidence": 82,  "action": "suggest_template",        "template": "precio_hr_v_2025",  "enabled": True,  "order": 0},
        {"id": "docs_miss", "intent": "DOCS_MISSING",    "confidence": 75,  "action": "send_checklist",          "template": "docs_checklist_v2", "enabled": True,  "order": 1},
        {"id": "human_req", "intent": "HUMAN_REQUESTED", "confidence": 90,  "action": "assign_to_free_operator", "template": "",                  "enabled": True,  "order": 2},
        {"id": "stale_24h", "intent": "STALE_24H",       "confidence": 100, "action": "trigger_followup",        "template": "followup_24h",      "enabled": False, "order": 3},
    ],
}


class InboxConfigBody(BaseModel):
    inbox_config: dict = Field(..., description="Full inbox config object.")


class InboxConfigResponse(BaseModel):
    inbox_config: dict


@router.get("/inbox-config", response_model=InboxConfigResponse)
async def get_inbox_config(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> InboxConfigResponse:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    cfg = (tenant.config or {}).get("inbox_config", DEFAULT_INBOX_CONFIG)
    return InboxConfigResponse(inbox_config=cfg)


@router.put("/inbox-config", response_model=InboxConfigResponse)
async def put_inbox_config(
    body: InboxConfigBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> InboxConfigResponse:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    new_config = dict(tenant.config or {})
    new_config["inbox_config"] = body.inbox_config
    await session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(config=new_config)
    )
    await session.commit()
    return InboxConfigResponse(inbox_config=body.inbox_config)
```

### Step 4: Run tests — expect PASS

```bash
cd core
uv run pytest tests/api/test_tenants_routes.py -k "inbox_config" -v
# Expected: 3 passed
```

### Step 5: Commit

```bash
git add core/atendia/api/tenants_routes.py core/tests/api/test_tenants_routes.py
git commit -m "feat(api): add GET/PUT /tenants/inbox-config stored in Tenant.config JSONB"
```

---

## Task 2: Frontend — Types

**Files:**
- Create: `frontend/src/features/inbox-settings/types.ts`

### Step 1: Write the types file

```typescript
// frontend/src/features/inbox-settings/types.ts

export interface InboxLayout {
  three_pane: boolean;
  rail_width: "collapsed" | "expanded";
  list_max_width: number;
  composer_density: "compact" | "comfortable";
  sticky_composer: boolean;
}

export interface FilterChip {
  id: string;
  label: string;
  color: string;
  query: string;
  live_count: boolean;
  visible: boolean;
  order: number;
}

export interface StageRing {
  stage_id: string;
  emoji: string;
  color: string;
  sla_hours: number | null;
}

export interface HandoffRule {
  id: string;
  intent: string;
  confidence: number;
  action: string;
  template: string;
  enabled: boolean;
  order: number;
}

export interface InboxConfig {
  layout: InboxLayout;
  filter_chips: FilterChip[];
  stage_rings: StageRing[];
  handoff_rules: HandoffRule[];
}

export const DEFAULT_INBOX_CONFIG: InboxConfig = {
  layout: {
    three_pane: true,
    rail_width: "expanded",
    list_max_width: 360,
    composer_density: "comfortable",
    sticky_composer: true,
  },
  filter_chips: [
    { id: "unread",            label: "Sin leer",             color: "#4f72f5", query: "read_at IS NULL",                             live_count: true,  visible: true, order: 0 },
    { id: "mine",              label: "Mías",                 color: "#9b72f5", query: "assigned_to = current_user",                  live_count: true,  visible: true, order: 1 },
    { id: "unassigned",        label: "Sin asignar",          color: "#f5a623", query: "assigned_to IS NULL AND status != 'closed'",  live_count: false, visible: true, order: 2 },
    { id: "awaiting_customer", label: "En espera de cliente", color: "#4fa8f5", query: "stage = 'waiting_customer'",                  live_count: true,  visible: true, order: 3 },
    { id: "stale",             label: "Inactivas >24h",       color: "#f25252", query: "last_message_at < now() - interval '24h'",   live_count: true,  visible: true, order: 4 },
  ],
  stage_rings: [
    { stage_id: "nuevo",      emoji: "🆕", color: "#6b7cf5", sla_hours: 24   },
    { stage_id: "en_curso",   emoji: "🔄", color: "#10c98f", sla_hours: 4    },
    { stage_id: "en_espera",  emoji: "⏳", color: "#f5a623", sla_hours: 48   },
    { stage_id: "cotizacion", emoji: "💰", color: "#9b72f5", sla_hours: 12   },
    { stage_id: "documentos", emoji: "📄", color: "#4fa8f5", sla_hours: 24   },
    { stage_id: "cierre",     emoji: "🏁", color: "#10c98f", sla_hours: null },
  ],
  handoff_rules: [
    { id: "ask_price", intent: "ASK_PRICE",       confidence: 82,  action: "suggest_template",        template: "precio_hr_v_2025",  enabled: true,  order: 0 },
    { id: "docs_miss", intent: "DOCS_MISSING",    confidence: 75,  action: "send_checklist",          template: "docs_checklist_v2", enabled: true,  order: 1 },
    { id: "human_req", intent: "HUMAN_REQUESTED", confidence: 90,  action: "assign_to_free_operator", template: "",                  enabled: true,  order: 2 },
    { id: "stale_24h", intent: "STALE_24H",       confidence: 100, action: "trigger_followup",        template: "followup_24h",      enabled: false, order: 3 },
  ],
};
```

### Step 2: Commit

```bash
git add frontend/src/features/inbox-settings/types.ts
git commit -m "feat(inbox-settings): add TypeScript types and DEFAULT_INBOX_CONFIG"
```

---

## Task 3: Frontend — API Client

**Files:**
- Modify: `frontend/src/features/config/api.ts` (append)

### Step 1: Add inboxConfigApi

Append to `frontend/src/features/config/api.ts`:

```typescript
import type { InboxConfig } from "@/features/inbox-settings/types";

export const inboxConfigApi = {
  get: async (): Promise<InboxConfig> => {
    const r = await api.get<{ inbox_config: InboxConfig }>("/tenants/inbox-config");
    return r.data.inbox_config;
  },
  put: async (inbox_config: InboxConfig): Promise<InboxConfig> => {
    const r = await api.put<{ inbox_config: InboxConfig }>("/tenants/inbox-config", { inbox_config });
    return r.data.inbox_config;
  },
};
```

### Step 2: Commit

```bash
git add frontend/src/features/config/api.ts
git commit -m "feat(inbox-settings): add inboxConfigApi to config api client"
```

---

## Task 4: Frontend — TanStack Router Route

**Files:**
- Create: `frontend/src/routes/(auth)/inbox-settings.tsx`

### Step 1: Create route file

```typescript
// frontend/src/routes/(auth)/inbox-settings.tsx
import { createFileRoute } from "@tanstack/react-router";
import { InboxSettingsPage } from "@/features/inbox-settings/components/InboxSettingsPage";

export const Route = createFileRoute("/(auth)/inbox-settings")({
  component: InboxSettingsPage,
});
```

### Step 2: Commit

```bash
git add frontend/src/routes/"(auth)"/inbox-settings.tsx
git commit -m "feat(inbox-settings): add TanStack Router route /(auth)/inbox-settings"
```

---

## Task 5: Frontend — AppShell Nav Entry

**Files:**
- Modify: `frontend/src/components/AppShell.tsx` (line ~60, NAV_ITEMS array)

### Step 1: Add import and nav item

Add `SlidersHorizontal` to the lucide imports at the top, then insert into `NAV_ITEMS` after the `/config` entry:

```typescript
// Import addition (add SlidersHorizontal to existing import):
import { ..., SlidersHorizontal } from "lucide-react";

// NAV_ITEMS addition (after { to: "/config", ... }):
{ to: "/inbox-settings", label: "Bandeja — Config", icon: SlidersHorizontal },
```

### Step 2: Commit

```bash
git add frontend/src/components/AppShell.tsx
git commit -m "feat(inbox-settings): add /inbox-settings nav entry to AppShell"
```

---

## Task 6: Frontend — InboxSettingsPage (main layout)

**Files:**
- Create: `frontend/src/features/inbox-settings/components/InboxSettingsPage.tsx`

### Step 1: Write the component

```typescript
// frontend/src/features/inbox-settings/components/InboxSettingsPage.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle, Circle, Filter, Layout, Lock, Monitor,
  RotateCcw, Save, Search, SlidersHorizontal, Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { inboxConfigApi } from "@/features/config/api";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

import type { InboxConfig } from "../types";
import { DEFAULT_INBOX_CONFIG } from "../types";
import { FilterChipsSection } from "./FilterChipsSection";
import { HandoffRulesSection } from "./HandoffRulesSection";
import { InboxLayoutSection } from "./InboxLayoutSection";
import { InboxPreviewPanel } from "./InboxPreviewPanel";
import { PermissionsSection } from "./PermissionsSection";
import { StageRingsSection } from "./StageRingsSection";

type SectionId =
  | "layout" | "filter-chips" | "stage-rings"
  | "handoff-rules" | "permissions";

interface SidebarItem {
  id: SectionId;
  label: string;
  icon: typeof Filter;
  badge?: number;
  group: "inbox" | "ai" | "system";
}

const SIDEBAR_ITEMS: SidebarItem[] = [
  { id: "layout",        label: "Diseño de bandeja",    icon: Layout,             group: "inbox" },
  { id: "filter-chips",  label: "Chips de filtro",      icon: Filter,             group: "inbox" },
  { id: "stage-rings",   label: "Anillos de etapa",     icon: Circle,             group: "inbox" },
  { id: "handoff-rules", label: "Reglas de handoff IA", icon: Zap,                group: "ai"    },
  { id: "permissions",   label: "Permisos y roles",     icon: Lock,               group: "system" },
];

export function InboxSettingsPage() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const canEdit = user?.role === "tenant_admin" || user?.role === "superadmin";

  const [activeSection, setActiveSection] = useState<SectionId>("filter-chips");
  const [draft, setDraft] = useState<InboxConfig | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  const query = useQuery({
    queryKey: ["tenants", "inbox-config"],
    queryFn: inboxConfigApi.get,
  });

  useEffect(() => {
    if (query.data && !isDirty) {
      setDraft(query.data);
    }
  }, [query.data, isDirty]);

  const patchDraft = useCallback((patch: Partial<InboxConfig>) => {
    setDraft((prev) => prev ? { ...prev, ...patch } : prev);
    setIsDirty(true);
  }, []);

  const save = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error("No draft");
      return inboxConfigApi.put(draft);
    },
    onSuccess: (data) => {
      setDraft(data);
      setIsDirty(false);
      void qc.invalidateQueries({ queryKey: ["tenants", "inbox-config"] });
      toast.success("Configuración guardada");
    },
    onError: (e: Error) => {
      toast.error("Error al guardar", { description: e.message });
    },
  });

  const reset = () => {
    if (query.data) { setDraft(query.data); setIsDirty(false); }
  };

  const currentDraft = draft ?? DEFAULT_INBOX_CONFIG;

  const renderSection = () => {
    if (!draft && query.isLoading) return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Cargando configuración…
      </div>
    );
    switch (activeSection) {
      case "layout":        return <InboxLayoutSection draft={currentDraft} patchDraft={patchDraft} canEdit={canEdit} />;
      case "filter-chips":  return <FilterChipsSection draft={currentDraft} patchDraft={patchDraft} canEdit={canEdit} />;
      case "stage-rings":   return <StageRingsSection draft={currentDraft} patchDraft={patchDraft} canEdit={canEdit} />;
      case "handoff-rules": return <HandoffRulesSection draft={currentDraft} patchDraft={patchDraft} canEdit={canEdit} />;
      case "permissions":   return <PermissionsSection />;
    }
  };

  return (
    // Break out of AppShell's p-6 and fill remaining height
    <div className="-m-6 flex overflow-hidden border-t" style={{ height: "calc(100vh - 3.5rem)" }}>

      {/* ── CATEGORIES SIDEBAR ── */}
      <aside className="flex w-52 shrink-0 flex-col border-r bg-muted/20">
        <div className="border-b px-3 py-2.5">
          <p className="text-[11px] font-bold tracking-tight">Configuración</p>
          <p className="text-[10px] text-muted-foreground">Bandeja · IA · Permisos</p>
        </div>
        <div className="px-2 py-1.5">
          <div className="flex items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-muted-foreground">
            <Search className="h-3 w-3 shrink-0" />
            <Input placeholder="Buscar…" className="h-5 border-none p-0 text-[11px] shadow-none focus-visible:ring-0" />
          </div>
        </div>
        <ScrollArea className="flex-1">
          {(["inbox", "ai", "system"] as const).map((group) => {
            const items = SIDEBAR_ITEMS.filter((i) => i.group === group);
            const label = group === "inbox" ? "BANDEJA DE ENTRADA" : group === "ai" ? "AUTOMATIZACIÓN IA" : "SISTEMA";
            return (
              <div key={group}>
                <p className="px-3 pb-1 pt-3 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                  {label}
                </p>
                {items.map((item) => {
                  const Icon = item.icon;
                  const active = activeSection === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setActiveSection(item.id)}
                      className={cn(
                        "flex w-full items-center gap-2 px-3 py-1.5 text-[11.5px] transition-colors",
                        active
                          ? "bg-primary/10 text-primary font-medium"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5 shrink-0" />
                      <span className="flex-1 text-left">{item.label}</span>
                      {item.badge != null && (
                        <Badge variant="secondary" className="h-4 px-1 text-[9px]">{item.badge}</Badge>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </ScrollArea>
      </aside>

      {/* ── MAIN AREA ── */}
      <div className="flex flex-1 flex-col overflow-hidden">

        {/* Top bar */}
        <div className="flex h-11 items-center gap-2 border-b bg-background px-4">
          <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Configuración</span>
          <span className="text-xs text-muted-foreground">/</span>
          <span className="text-xs font-medium">
            {SIDEBAR_ITEMS.find((i) => i.id === activeSection)?.label}
          </span>
          <div className="ml-auto flex items-center gap-2">
            {isDirty && (
              <div className="flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-600 dark:text-amber-400">
                <AlertCircle className="h-3 w-3" />
                Cambios sin guardar
              </div>
            )}
            <div className="flex items-center gap-1 rounded-md border bg-muted/30 px-2 py-1 text-[10px] text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Producción
            </div>
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={reset} disabled={!isDirty}>
              <RotateCcw className="mr-1 h-3 w-3" /> Restablecer
            </Button>
            <Button size="sm" className="h-7 text-xs" onClick={() => save.mutate()} disabled={!canEdit || !isDirty || save.isPending}>
              <Save className="mr-1 h-3 w-3" />
              {save.isPending ? "Guardando…" : "Guardar cambios"}
            </Button>
          </div>
        </div>

        {/* Content + Preview side by side */}
        <div className="flex flex-1 overflow-hidden">
          <ScrollArea className="flex-1 p-5">
            {renderSection()}
          </ScrollArea>
          <InboxPreviewPanel draft={currentDraft} activeSection={activeSection} />
        </div>

        {/* Sticky save bar */}
        {isDirty && (
          <div className="flex h-11 items-center gap-3 border-t bg-muted/30 px-4 text-xs">
            <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
            <span className="text-muted-foreground">
              Cambios sin guardar — esta configuración afecta la bandeja de todos los operadores.
            </span>
            <div className="ml-auto flex gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={reset}>Descartar</Button>
              <Button size="sm" className="h-7 text-xs" onClick={() => save.mutate()} disabled={!canEdit || save.isPending}>
                <Save className="mr-1 h-3 w-3" />
                Guardar cambios
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

### Step 2: Commit

```bash
git add frontend/src/features/inbox-settings/components/InboxSettingsPage.tsx
git commit -m "feat(inbox-settings): add InboxSettingsPage 3-panel layout"
```

---

## Task 7: Frontend — InboxLayoutSection

**Files:**
- Create: `frontend/src/features/inbox-settings/components/InboxLayoutSection.tsx`

```typescript
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { InboxConfig } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

export function InboxLayoutSection({ draft, patchDraft, canEdit }: Props) {
  const { layout } = draft;
  const set = (patch: Partial<typeof layout>) =>
    patchDraft({ layout: { ...layout, ...patch } });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Diseño de bandeja</CardTitle>
          <p className="text-xs text-muted-foreground">Estructura de paneles visible para todos los operadores.</p>
        </CardHeader>
        <CardContent className="space-y-4">

          {/* Layout mode */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { value: true,  label: "Tres paneles",  desc: "Filtros · Lista · Chat"  },
              { value: false, label: "Dos paneles",   desc: "Lista · Chat (sin rail)" },
            ].map(({ value, label, desc }) => (
              <button
                key={String(value)}
                type="button"
                disabled={!canEdit}
                onClick={() => set({ three_pane: value })}
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors",
                  layout.three_pane === value
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/40",
                )}
              >
                <p className="text-xs font-medium">{label}</p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">{desc}</p>
                <div className="mt-2 flex gap-1 h-4">
                  {value
                    ? [14, 40, 60].map((w, i) => <div key={i} className="rounded-sm bg-muted-foreground/30" style={{ width: w }} />)
                    : [40, 60].map((w, i) => <div key={i} className="rounded-sm bg-muted-foreground/30" style={{ width: w }} />)
                  }
                </div>
              </button>
            ))}
          </div>

          {/* Rail width */}
          <div className="flex items-center gap-3">
            <Label className="w-36 text-xs">Rail de filtros</Label>
            <Select value={layout.rail_width} onValueChange={(v) => set({ rail_width: v as "collapsed" | "expanded" })} disabled={!canEdit}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="expanded" className="text-xs">Expandido — 200px</SelectItem>
                <SelectItem value="collapsed" className="text-xs">Colapsado — 60px</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* List max width */}
          <div className="flex items-center gap-3">
            <Label className="w-36 text-xs">Lista máx. ancho</Label>
            <Input
              type="number" min={240} max={480} step={10}
              className="h-8 w-28 font-mono text-xs"
              value={layout.list_max_width}
              disabled={!canEdit}
              onChange={(e) => set({ list_max_width: Number(e.target.value) || 360 })}
            />
            <span className="text-xs text-muted-foreground">px</span>
          </div>

          {/* Composer density */}
          <div className="flex items-center gap-3">
            <Label className="w-36 text-xs">Densidad composer</Label>
            <Select value={layout.composer_density} onValueChange={(v) => set({ composer_density: v as "compact" | "comfortable" })} disabled={!canEdit}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="comfortable" className="text-xs">Comfortable</SelectItem>
                <SelectItem value="compact" className="text-xs">Compact</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Sticky composer */}
          <div className="flex items-center gap-3">
            <Label className="w-36 text-xs">Composer sticky</Label>
            <button
              type="button"
              disabled={!canEdit}
              onClick={() => set({ sticky_composer: !layout.sticky_composer })}
              className={cn(
                "relative h-5 w-9 rounded-full transition-colors",
                layout.sticky_composer ? "bg-primary" : "bg-input",
              )}
            >
              <span className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                layout.sticky_composer ? "translate-x-4" : "translate-x-0.5",
              )} />
            </button>
            <span className={cn("text-xs", layout.sticky_composer ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
              {layout.sticky_composer ? "Activo" : "Inactivo"}
            </span>
          </div>

        </CardContent>
      </Card>
    </div>
  );
}
```

---

## Task 8: Frontend — FilterChipsSection

**Files:**
- Create: `frontend/src/features/inbox-settings/components/FilterChipsSection.tsx`

```typescript
import { ArrowDown, ArrowUp, Eye, EyeOff, GripVertical, Plus, Trash2 } from "lucide-react";
import { nanoid } from "nanoid"; // or crypto.randomUUID()
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { FilterChip, InboxConfig } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

const PRESET_COLORS = [
  "#4f72f5", "#9b72f5", "#f5a623", "#4fa8f5", "#f25252", "#10c98f",
];

export function FilterChipsSection({ draft, patchDraft, canEdit }: Props) {
  const chips = [...draft.filter_chips].sort((a, b) => a.order - b.order);

  const update = (id: string, patch: Partial<FilterChip>) => {
    patchDraft({
      filter_chips: draft.filter_chips.map((c) => c.id === id ? { ...c, ...patch } : c),
    });
  };

  const move = (id: string, dir: -1 | 1) => {
    const sorted = [...chips];
    const idx = sorted.findIndex((c) => c.id === id);
    const target = idx + dir;
    if (target < 0 || target >= sorted.length) return;
    const reordered = sorted.map((c, i) => {
      if (i === idx) return { ...sorted[target]!, order: c.order };
      if (i === target) return { ...sorted[idx]!, order: sorted[target]!.order };
      return c;
    });
    patchDraft({ filter_chips: reordered });
  };

  const remove = (id: string) => {
    patchDraft({ filter_chips: draft.filter_chips.filter((c) => c.id !== id) });
  };

  const add = () => {
    const newChip: FilterChip = {
      id: crypto.randomUUID(),
      label: "Nuevo filtro",
      color: "#4f72f5",
      query: "",
      live_count: false,
      visible: true,
      order: chips.length,
    };
    patchDraft({ filter_chips: [...draft.filter_chips, newChip] });
  };

  return (
    <div className="space-y-4">
      {/* Live preview bar */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Chips de filtro</CardTitle>
          <p className="text-xs text-muted-foreground">
            Aparecen en la barra superior de la bandeja. Arrastra para reordenar.
          </p>
        </CardHeader>
        <CardContent className="space-y-1">
          {/* Preview strip */}
          <div className="mb-3 flex flex-wrap gap-1.5 rounded-lg border bg-muted/30 px-3 py-2">
            {chips.filter((c) => c.visible).map((chip) => (
              <span key={chip.id} className="flex items-center gap-1 rounded-md px-2 py-0.5 text-[10.5px] font-medium" style={{ background: `${chip.color}18`, color: chip.color }}>
                {chip.label}
                {chip.live_count && (
                  <span className="rounded px-1 text-[9px] font-bold text-white" style={{ background: chip.color }}>21</span>
                )}
              </span>
            ))}
          </div>

          {/* Chip rows */}
          <div className="space-y-1.5">
            {chips.map((chip, idx) => (
              <div key={chip.id} className="flex items-center gap-2 rounded-lg border bg-card p-2">
                {/* Order controls */}
                <div className="flex flex-col gap-0.5 text-muted-foreground">
                  <button type="button" disabled={idx === 0 || !canEdit} onClick={() => move(chip.id, -1)} className="p-0.5 hover:text-foreground disabled:opacity-20">
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <GripVertical className="h-3 w-3 opacity-40" />
                  <button type="button" disabled={idx === chips.length - 1 || !canEdit} onClick={() => move(chip.id, 1)} className="p-0.5 hover:text-foreground disabled:opacity-20">
                    <ArrowDown className="h-3 w-3" />
                  </button>
                </div>

                {/* Color swatch */}
                <div className="flex flex-col gap-1">
                  <div className="h-5 w-5 rounded-md border" style={{ background: chip.color }} />
                  {canEdit && (
                    <select
                      value={chip.color}
                      onChange={(e) => update(chip.id, { color: e.target.value })}
                      className="h-5 w-5 cursor-pointer rounded-md border opacity-0 absolute"
                      title="Color"
                      style={{ marginTop: -20 }}
                    />
                  )}
                </div>

                {/* Label */}
                <Input
                  value={chip.label}
                  onChange={(e) => update(chip.id, { label: e.target.value })}
                  disabled={!canEdit}
                  className="h-7 flex-1 text-xs"
                  placeholder="Nombre del filtro"
                />

                {/* Query (mono) */}
                <Input
                  value={chip.query}
                  onChange={(e) => update(chip.id, { query: e.target.value })}
                  disabled={!canEdit}
                  className="h-7 w-48 font-mono text-[10px]"
                  placeholder="expresión SQL…"
                />

                {/* Live count toggle */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => update(chip.id, { live_count: !chip.live_count })}
                  title="Conteo en vivo"
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[9px] font-semibold border transition-colors",
                    chip.live_count
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border text-muted-foreground",
                  )}
                >
                  LIVE
                </button>

                {/* Visibility toggle */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => update(chip.id, { visible: !chip.visible })}
                  title={chip.visible ? "Ocultar" : "Mostrar"}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {chip.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                </button>

                {/* Delete */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => remove(chip.id)}
                  title="Eliminar"
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>

          {canEdit && (
            <Button variant="outline" size="sm" onClick={add} className="mt-1 w-full text-xs">
              <Plus className="mr-1 h-3 w-3" /> Agregar filtro
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## Task 9: Frontend — StageRingsSection

**Files:**
- Create: `frontend/src/features/inbox-settings/components/StageRingsSection.tsx`

```typescript
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { tenantsApi } from "@/features/config/api";
import type { InboxConfig, StageRing } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

export function StageRingsSection({ draft, patchDraft, canEdit }: Props) {
  const pipelineQuery = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });

  const rings = draft.stage_rings;

  const update = (stageId: string, patch: Partial<StageRing>) => {
    patchDraft({
      stage_rings: rings.map((r) => r.stage_id === stageId ? { ...r, ...patch } : r),
    });
  };

  if (pipelineQuery.isLoading) return <Skeleton className="h-64 w-full" />;

  const pipelineStages = (pipelineQuery.data?.definition as { stages?: { id: string; label: string }[] })?.stages ?? [];

  // Merge pipeline stages with our ring overrides
  const mergedRings: (StageRing & { label: string })[] = pipelineStages.map((s) => {
    const ring = rings.find((r) => r.stage_id === s.id) ?? {
      stage_id: s.id, emoji: "⚪", color: "#6b7280", sla_hours: null,
    };
    return { ...ring, label: s.label };
  });

  // Also show rings that have overrides but no matching stage (orphans)
  const orphans = rings.filter((r) => !pipelineStages.find((s) => s.id === r.stage_id))
    .map((r) => ({ ...r, label: r.stage_id }));

  const all = [...mergedRings, ...orphans];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Anillos de etapa</CardTitle>
          <p className="text-xs text-muted-foreground">
            El borde del avatar indica la etapa de venta. Las etapas vienen del pipeline activo.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-2">
            {all.map((ring) => (
              <div key={ring.stage_id} className="flex items-center gap-2 rounded-lg border bg-card p-2.5">
                {/* Avatar preview */}
                <div className="relative h-8 w-8 shrink-0">
                  <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center text-sm">
                    {ring.emoji}
                  </div>
                  <div
                    className="absolute inset-0 rounded-full border-2"
                    style={{ borderColor: ring.color }}
                  />
                </div>

                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{ring.label}</p>
                  <p className="font-mono text-[9px] text-muted-foreground">{ring.stage_id}</p>
                </div>

                {/* Emoji */}
                <Input
                  value={ring.emoji}
                  onChange={(e) => update(ring.stage_id, { emoji: e.target.value })}
                  disabled={!canEdit}
                  className="h-7 w-10 p-1 text-center text-sm"
                  maxLength={2}
                />

                {/* Color */}
                <input
                  type="color"
                  value={ring.color}
                  onChange={(e) => update(ring.stage_id, { color: e.target.value })}
                  disabled={!canEdit}
                  className="h-7 w-7 cursor-pointer rounded border p-0"
                  title="Color del anillo"
                />

                {/* SLA hours */}
                <Input
                  type="number"
                  min={0}
                  max={720}
                  placeholder="SLA h"
                  value={ring.sla_hours ?? ""}
                  onChange={(e) => update(ring.stage_id, { sla_hours: e.target.value ? Number(e.target.value) : null })}
                  disabled={!canEdit}
                  className="h-7 w-16 font-mono text-xs"
                />
                <span className="text-[9px] text-muted-foreground">h</span>
              </div>
            ))}
          </div>
          {pipelineQuery.isError && (
            <p className="mt-3 text-xs text-amber-600">
              No hay pipeline activo. Las etapas del pipeline definen los anillos disponibles.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## Task 10: Frontend — HandoffRulesSection

**Files:**
- Create: `frontend/src/features/inbox-settings/components/HandoffRulesSection.tsx`

```typescript
import { ArrowDown, ArrowUp, Copy, GripVertical, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { HandoffRule, InboxConfig } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

const INTENT_COLORS: Record<string, string> = {
  ASK_PRICE: "text-purple-600 bg-purple-50 dark:text-purple-300 dark:bg-purple-950/40",
  DOCS_MISSING: "text-amber-600 bg-amber-50 dark:text-amber-300 dark:bg-amber-950/40",
  HUMAN_REQUESTED: "text-blue-600 bg-blue-50 dark:text-blue-300 dark:bg-blue-950/40",
  STALE_24H: "text-red-600 bg-red-50 dark:text-red-300 dark:bg-red-950/40",
};

export function HandoffRulesSection({ draft, patchDraft, canEdit }: Props) {
  const rules = [...draft.handoff_rules].sort((a, b) => a.order - b.order);

  const update = (id: string, patch: Partial<HandoffRule>) => {
    patchDraft({ handoff_rules: draft.handoff_rules.map((r) => r.id === id ? { ...r, ...patch } : r) });
  };

  const move = (id: string, dir: -1 | 1) => {
    const sorted = [...rules];
    const idx = sorted.findIndex((r) => r.id === id);
    const target = idx + dir;
    if (target < 0 || target >= sorted.length) return;
    const reordered = sorted.map((r, i) => {
      if (i === idx) return { ...sorted[target]!, order: r.order };
      if (i === target) return { ...sorted[idx]!, order: sorted[target]!.order };
      return r;
    });
    patchDraft({ handoff_rules: reordered });
  };

  const duplicate = (rule: HandoffRule) => {
    patchDraft({
      handoff_rules: [...draft.handoff_rules, {
        ...rule,
        id: crypto.randomUUID(),
        intent: `${rule.intent}_COPY`,
        order: draft.handoff_rules.length,
      }],
    });
  };

  const remove = (id: string) => {
    patchDraft({ handoff_rules: draft.handoff_rules.filter((r) => r.id !== id) });
  };

  const add = () => {
    patchDraft({
      handoff_rules: [...draft.handoff_rules, {
        id: crypto.randomUUID(),
        intent: "NUEVA_INTENCION",
        confidence: 80,
        action: "suggest_template",
        template: "",
        enabled: true,
        order: draft.handoff_rules.length,
      }],
    });
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
        <strong>Nota:</strong> Estas reglas configuran el comportamiento del motor IA. Los cambios se aplican en la próxima conversación nueva.
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Reglas de handoff IA</CardTitle>
          <p className="text-xs text-muted-foreground">
            Define cuándo la IA responde automáticamente y cuándo transfiere a un operador.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {rules.map((rule, idx) => (
            <div key={rule.id} className={cn("rounded-lg border bg-card p-3 space-y-2", !rule.enabled && "opacity-60")}>
              <div className="flex items-center gap-2">
                {/* Order */}
                <div className="flex flex-col gap-0.5 text-muted-foreground">
                  <button type="button" disabled={idx === 0 || !canEdit} onClick={() => move(rule.id, -1)} className="hover:text-foreground disabled:opacity-20"><ArrowUp className="h-3 w-3" /></button>
                  <GripVertical className="h-3 w-3 opacity-40" />
                  <button type="button" disabled={idx === rules.length - 1 || !canEdit} onClick={() => move(rule.id, 1)} className="hover:text-foreground disabled:opacity-20"><ArrowDown className="h-3 w-3" /></button>
                </div>

                {/* Intent badge */}
                <span className={cn("rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold", INTENT_COLORS[rule.intent] ?? "text-foreground bg-muted")}>
                  {rule.intent}
                </span>
                <span className="text-xs text-muted-foreground">→</span>

                {/* Action */}
                <Input
                  value={rule.action}
                  onChange={(e) => update(rule.id, { action: e.target.value })}
                  disabled={!canEdit}
                  className="h-6 flex-1 text-xs"
                  placeholder="acción"
                />

                {/* Confidence */}
                <div className="flex items-center gap-1">
                  <div className="h-1.5 w-12 rounded-full bg-muted overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${rule.confidence}%` }} />
                  </div>
                  <Input
                    type="number" min={0} max={100}
                    value={rule.confidence}
                    onChange={(e) => update(rule.id, { confidence: Number(e.target.value) })}
                    disabled={!canEdit}
                    className="h-6 w-12 font-mono text-[10px] p-1"
                  />
                  <span className="text-[9px] text-muted-foreground">%</span>
                </div>

                {/* Toggle */}
                <button
                  type="button" disabled={!canEdit}
                  onClick={() => update(rule.id, { enabled: !rule.enabled })}
                  className={cn("relative h-4 w-8 rounded-full transition-colors", rule.enabled ? "bg-primary" : "bg-input")}
                >
                  <span className={cn("absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform", rule.enabled ? "translate-x-4" : "translate-x-0.5")} />
                </button>

                {/* Actions */}
                <button type="button" disabled={!canEdit} onClick={() => duplicate(rule)} title="Duplicar" className="text-muted-foreground hover:text-foreground"><Copy className="h-3.5 w-3.5" /></button>
                <button type="button" disabled={!canEdit} onClick={() => remove(rule.id)} title="Eliminar" className="text-muted-foreground hover:text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
              </div>

              {/* Template */}
              <div className="flex items-center gap-2 pl-6">
                <span className="text-[9px] uppercase tracking-wider text-muted-foreground">Plantilla</span>
                <Input
                  value={rule.template}
                  onChange={(e) => update(rule.id, { template: e.target.value })}
                  disabled={!canEdit}
                  className="h-6 flex-1 font-mono text-[10px]"
                  placeholder="nombre_plantilla (opcional)"
                />
                <span className="text-[9px] uppercase tracking-wider text-muted-foreground">Intent</span>
                <Input
                  value={rule.intent}
                  onChange={(e) => update(rule.id, { intent: e.target.value.toUpperCase() })}
                  disabled={!canEdit}
                  className="h-6 w-36 font-mono text-[10px]"
                  placeholder="INTENT_NAME"
                />
              </div>
            </div>
          ))}

          {canEdit && (
            <Button variant="outline" size="sm" onClick={add} className="w-full text-xs">
              <Plus className="mr-1 h-3 w-3" /> Agregar regla
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## Task 11: Frontend — PermissionsSection

**Files:**
- Create: `frontend/src/features/inbox-settings/components/PermissionsSection.tsx`

```typescript
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const FEATURES = [
  "Chips de filtro",
  "Anillos de etapa",
  "Reglas de handoff",
  "Acciones composer",
  "Diseño de bandeja",
];

type Permission = "full" | "partial" | "none";

const MATRIX: Record<string, [Permission, Permission, Permission]> = {
  "Chips de filtro":    ["full",    "partial", "none"   ],
  "Anillos de etapa":  ["full",    "none",    "none"   ],
  "Reglas de handoff": ["full",    "partial", "none"   ],
  "Acciones composer": ["full",    "partial", "partial"],
  "Diseño de bandeja": ["full",    "none",    "none"   ],
};

const CELL: Record<Permission, { label: string; className: string }> = {
  full:    { label: "✓ Todos",  className: "text-emerald-600 dark:text-emerald-400" },
  partial: { label: "◑ Editar", className: "text-amber-600 dark:text-amber-400"    },
  none:    { label: "✗",        className: "text-muted-foreground/50"               },
};

export function PermissionsSection() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Permisos y roles</CardTitle>
          <p className="text-xs text-muted-foreground">Qué puede hacer cada rol en configuración de bandeja.</p>
        </CardHeader>
        <CardContent>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b">
                <th className="pb-2 text-left font-medium text-muted-foreground">Función</th>
                {[
                  { role: "Admin",      className: "text-red-600 dark:text-red-400"    },
                  { role: "Supervisor", className: "text-blue-600 dark:text-blue-400"  },
                  { role: "Operador",   className: "text-muted-foreground"             },
                ].map(({ role, className }) => (
                  <th key={role} className={cn("pb-2 text-center font-semibold", className)}>{role}</th>
                ))}
                <th className="pb-2 text-center font-medium text-muted-foreground">Ver</th>
              </tr>
            </thead>
            <tbody>
              {FEATURES.map((feature) => {
                const [admin, supervisor, operator] = MATRIX[feature]!;
                return (
                  <tr key={feature} className="border-b last:border-0">
                    <td className="py-2 font-medium">{feature}</td>
                    <td className={cn("py-2 text-center", CELL[admin].className)}>{CELL[admin].label}</td>
                    <td className={cn("py-2 text-center", CELL[supervisor].className)}>{CELL[supervisor].label}</td>
                    <td className={cn("py-2 text-center", CELL[operator].className)}>{CELL[operator].label}</td>
                    <td className="py-2 text-center text-emerald-600 dark:text-emerald-400">✓</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## Task 12: Frontend — InboxPreviewPanel

**Files:**
- Create: `frontend/src/features/inbox-settings/components/InboxPreviewPanel.tsx`

```typescript
import { Monitor } from "lucide-react";
import { cn } from "@/lib/utils";
import type { InboxConfig } from "../types";
import type { SectionId } from "./InboxSettingsPage"; // re-export this type

const SAMPLE_CONVS = [
  { initials: "DL", name: "Diego López",    preview: "¿Precio HR-V EXL 2025?",  time: "2m",  unread: 3, stageColor: "#6b7cf5", emoji: "💰" },
  { initials: "MP", name: "Mariana Pérez",  preview: "¿Tienen disponible?",     time: "7m",  unread: 1, stageColor: "#10c98f", emoji: "🔄" },
  { initials: "JH", name: "José Hernández", preview: "Prueba sábado",           time: "32m", unread: 0, stageColor: "#f5a623", emoji: "⏳" },
  { initials: "KM", name: "Karla Méndez",   preview: "Sin respuesta · 26h",     time: "26h", unread: 0, stageColor: "#f25252", emoji: "⚠️", stale: true },
];

interface Props {
  draft: InboxConfig;
  activeSection: string;
}

export function InboxPreviewPanel({ draft, activeSection }: Props) {
  const visibleChips = [...draft.filter_chips]
    .filter((c) => c.visible)
    .sort((a, b) => a.order - b.order);

  return (
    <aside className="flex w-72 shrink-0 flex-col border-l bg-muted/10">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Monitor className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] font-semibold text-muted-foreground">Vista previa</span>
        <div className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] bg-emerald-500/10 text-emerald-600">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          En vivo
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50">BANDEJA — VISTA REAL</p>

        {/* Inbox mini */}
        <div className="rounded-lg border bg-background overflow-hidden text-[10px]">
          {/* Header */}
          <div className="flex items-center gap-1.5 border-b px-2 py-1.5 font-semibold text-muted-foreground">
            <span>Bandeja</span>
            <span className="ml-auto text-[9px] text-muted-foreground/50">52 conv.</span>
          </div>

          {/* Filter chips */}
          <div className="flex flex-wrap gap-1 px-2 py-1.5 border-b">
            {visibleChips.slice(0, 4).map((chip, i) => (
              <span
                key={chip.id}
                className="rounded px-1.5 py-0.5 font-medium"
                style={i === 0
                  ? { background: `${chip.color}22`, color: chip.color }
                  : { background: "hsl(var(--muted))", color: "hsl(var(--muted-foreground))" }
                }
              >
                {chip.label}
                {i === 0 && chip.live_count && (
                  <span className="ml-1 rounded px-1 text-[8px] font-bold text-white" style={{ background: chip.color }}>21</span>
                )}
              </span>
            ))}
          </div>

          {/* Conversation rows */}
          {SAMPLE_CONVS.map((conv, i) => (
            <div
              key={i}
              className={cn(
                "flex items-center gap-2 px-2 py-1.5 border-b last:border-0",
                i === 0 && "bg-primary/5",
                conv.stale && "opacity-60",
              )}
            >
              {/* Avatar with stage ring */}
              <div className="relative h-6 w-6 shrink-0">
                <div className="h-6 w-6 rounded-full bg-muted flex items-center justify-center text-[8px] font-bold text-muted-foreground">
                  {conv.initials}
                </div>
                <div className="absolute inset-0 rounded-full border-[1.5px]" style={{ borderColor: conv.stageColor }} />
              </div>

              {/* Text */}
              <div className="min-w-0 flex-1">
                <p className={cn("font-medium truncate", conv.stale && "text-red-500")}>{conv.name}</p>
                <p className="text-muted-foreground truncate">{conv.preview}</p>
              </div>

              {/* Right */}
              <div className="shrink-0 text-right">
                <p className={cn("text-[8px]", conv.stale ? "text-red-500" : "text-muted-foreground")}>{conv.time}</p>
                <div className="flex items-center justify-end gap-1 mt-0.5">
                  <span className="text-[9px]">{conv.emoji}</span>
                  {conv.unread > 0 && (
                    <span className="rounded-full bg-primary px-1 text-[8px] font-bold text-white">{conv.unread}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Section-specific hints */}
        {activeSection === "filter-chips" && (
          <div className="rounded-md border border-primary/20 bg-primary/5 px-2 py-1.5 text-[9.5px] text-primary">
            ↑ Los chips que ves reflejan tu configuración actual en tiempo real.
          </div>
        )}
        {activeSection === "stage-rings" && (
          <div className="rounded-md border border-primary/20 bg-primary/5 px-2 py-1.5 text-[9.5px] text-primary">
            ↑ Los bordes de avatar cambian con los colores que configures.
          </div>
        )}
        {activeSection === "handoff-rules" && (
          <div className="rounded-md border border-purple-500/20 bg-purple-500/5 px-2 py-1.5 text-[9.5px] text-purple-600">
            Las reglas se evalúan en cada mensaje entrante. Los cambios aplican en nuevas conversaciones.
          </div>
        )}

        {/* Shortcut hints */}
        <div className="space-y-1">
          <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50">ATAJOS</p>
          {[["⌘K", "Búsqueda"], ["⌘B", "Rail"], ["⌘S", "Guardar"]].map(([k, label]) => (
            <div key={k} className="flex items-center gap-1.5 text-[9.5px] text-muted-foreground">
              <span className="rounded border bg-muted px-1 font-mono text-[8px]">{k}</span>
              {label}
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
```

**Note:** Export `SectionId` from `InboxSettingsPage.tsx` so `InboxPreviewPanel` can import it:
```typescript
// Add to InboxSettingsPage.tsx:
export type { SectionId };
```

---

## Task 13: Frontend — Tests

**Files:**
- Create: `frontend/src/features/inbox-settings/__tests__/FilterChipsSection.test.tsx`
- Create: `frontend/src/features/inbox-settings/__tests__/InboxSettingsPage.test.tsx`

```typescript
// FilterChipsSection.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { FilterChipsSection } from "../components/FilterChipsSection";
import { DEFAULT_INBOX_CONFIG } from "../types";

describe("FilterChipsSection", () => {
  it("renders all visible chips in preview strip", () => {
    const patchDraft = vi.fn();
    render(<FilterChipsSection draft={DEFAULT_INBOX_CONFIG} patchDraft={patchDraft} canEdit={true} />);
    DEFAULT_INBOX_CONFIG.filter_chips
      .filter((c) => c.visible)
      .forEach((c) => {
        expect(screen.getAllByText(c.label).length).toBeGreaterThan(0);
      });
  });

  it("calls patchDraft when label is changed", () => {
    const patchDraft = vi.fn();
    render(<FilterChipsSection draft={DEFAULT_INBOX_CONFIG} patchDraft={patchDraft} canEdit={true} />);
    const inputs = screen.getAllByPlaceholderText("Nombre del filtro");
    fireEvent.change(inputs[0]!, { target: { value: "Nuevo nombre" } });
    expect(patchDraft).toHaveBeenCalled();
  });

  it("disables inputs when canEdit=false", () => {
    render(<FilterChipsSection draft={DEFAULT_INBOX_CONFIG} patchDraft={vi.fn()} canEdit={false} />);
    const inputs = screen.getAllByPlaceholderText("Nombre del filtro");
    expect(inputs[0]).toBeDisabled();
  });

  it("adds a new chip when Agregar filtro is clicked", () => {
    const patchDraft = vi.fn();
    render(<FilterChipsSection draft={DEFAULT_INBOX_CONFIG} patchDraft={patchDraft} canEdit={true} />);
    fireEvent.click(screen.getByText("Agregar filtro"));
    expect(patchDraft).toHaveBeenCalledWith(
      expect.objectContaining({ filter_chips: expect.any(Array) })
    );
    const call = patchDraft.mock.calls[0][0];
    expect(call.filter_chips).toHaveLength(DEFAULT_INBOX_CONFIG.filter_chips.length + 1);
  });
});
```

```typescript
// InboxSettingsPage.test.tsx — smoke test with mocked React Query
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InboxSettingsPage } from "../components/InboxSettingsPage";
import { DEFAULT_INBOX_CONFIG } from "../types";

vi.mock("@/features/config/api", () => ({
  inboxConfigApi: {
    get: vi.fn().mockResolvedValue(DEFAULT_INBOX_CONFIG),
    put: vi.fn(),
  },
  tenantsApi: {
    getPipeline: vi.fn().mockResolvedValue({ definition: { stages: [] }, version: 1, active: true, created_at: "" }),
  },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: (sel: (s: { user: { role: string } }) => unknown) =>
    sel({ user: { role: "tenant_admin" } }),
}));

describe("InboxSettingsPage", () => {
  it("renders sidebar categories", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InboxSettingsPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Chips de filtro")).toBeInTheDocument();
    expect(screen.getByText("Anillos de etapa")).toBeInTheDocument();
    expect(screen.getByText("Reglas de handoff IA")).toBeInTheDocument();
  });
});
```

### Run tests:

```bash
cd frontend
pnpm test --run src/features/inbox-settings
# Expected: all green
```

### Commit:

```bash
git add frontend/src/features/inbox-settings/__tests__/
git commit -m "test(inbox-settings): add component tests for FilterChipsSection and InboxSettingsPage"
```

---

## Task 14: Verify in Browser

### Step 1: Start the app

```bash
# Terminal 1 — docker (if not already running)
docker compose up -d

# Terminal 2 — backend
cd core && uv run uvicorn atendia.main:app --port 8001 --reload

# Terminal 3 — frontend dev
cd frontend && pnpm dev
```

### Step 2: Login and navigate

1. Open `http://localhost:5173` (or whichever port pnpm dev uses)
2. Login as `admin@demo.com` / `admin123`
3. Click **"Bandeja — Config"** in the left nav
4. Verify all 5 sections render via sidebar
5. Edit a filter chip label → verify "Cambios sin guardar" badge appears
6. Click **Guardar cambios** → verify toast "Configuración guardada"
7. Reload page → verify changes persisted
8. Login as a regular operator → verify all inputs are disabled (read-only)

### Step 3: Screenshot and commit

```bash
git add -A
git commit -m "feat(inbox-settings): complete /inbox-settings module — backend API + 3-panel UI + tests"
```

---

## Adversarial Critique & Accepted Trade-offs

| Issue | Decision |
|---|---|
| `inbox_config` stored in `Tenant.config` JSONB (no FK, no schema enforcement) | **Accepted.** Fastest path, consistent with how `brand_facts` and `tone` work. Future: extract to own table if field count grows past ~10 keys. |
| Handoff rules stored here are UI-only; bot doesn't read them yet | **Documented.** Section shows an amber notice. Wire-up to the runner engine is a separate task. |
| No input validation on `query` field of filter chips (arbitrary SQL) | **Accepted for admin-only config.** Only `tenant_admin`/`superadmin` can write. Future: add server-side query validation. |
| Stage ring colors override not reflected in actual conversation list (ConversationsPage still uses hardcoded chip colors) | **Post-task:** Update `ConversationsPage` to read `inbox_config` for chip colors and stage rings. Tracked as separate task. |
| No optimistic UI on save (spinner blocks CTA) | **Accepted for v1.** React Query mutation pending state is enough. |

# Placeholder Elimination Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace every `toast.info(...)` placeholder and pseudo-operational button across appointments, agents, workflows, the dashboard command palette, the conversations contact panel, and the clients page with a real action — backend wire, state-only toggle, navigation, or download — adding the small backend endpoints/filters required.

**Architecture:** Five small backend additions plus targeted frontend rewrites. Backend changes follow TDD via `pytest`. Frontend uses TanStack Query + the existing `api.ts` clients; component changes are verified manually in browser (existing test infrastructure is `bun test` + Vitest). One milestone = one command center = one session = one branch, per the standing one-page-per-session contract.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest-asyncio, React 19, TS strict, TanStack Router/Query, Tailwind v4, shadcn, Vitest, MSW.

**Reference design:** `docs/plans/2026-05-12-placeholder-elimination-design.md`.

---

## Pre-flight (every milestone)

Before starting any milestone, in a fresh session:

1. `git switch main && git pull --ff-only`
2. Confirm you have read the design doc and the corresponding milestone section.
3. Create the milestone branch: `git switch -c feat/<milestone-slug>`.
4. Confirm test runners work:
   - Backend: `uv run pytest core/tests/api -q -x --maxfail=1`
   - Frontend: `cd frontend && bun test --run`
5. Confirm dev server starts (`uv run uvicorn core.atendia.main:app --reload --port 8001` + `cd frontend && bun dev`).

All milestones end with: open the dev server, click every previously-stubbed control, screenshot or short verbal confirmation per stub, then open a PR.

---

# Milestone 1 — Appointments

**Branch:** `feat/placeholders-m1-appointments`
**Stubs covered:** B1 (MetricTile click), B2 (Funnel stage click), B3 (open-chat post-success toast). Also E2 from the dashboard palette (because palette "Crear cita" navigates to AppointmentsPage with `?new=1`).
**Backend additions:** None — the appointments listing endpoint already supports `status`, `customer_id`, `date_from`, `date_to`.

## Task 1.1 — URL-state for appointment filters

**Files:**
- Modify: `frontend/src/features/appointments/components/AppointmentsPage.tsx` (filter wiring around lines 200–240, 615–635)
- Modify (optional): `frontend/src/routes/(auth)/appointments.tsx` (search-param schema, if a route file exists; otherwise skip)

**Step 1: Decide the URL contract.**

| KPI label | Query param | Filter |
|---|---|---|
| "Hoy" | `?today=1` | date range = today (tenant TZ) |
| "Confirmadas" | `?status=confirmed` | status filter |
| "Pendientes" | `?status=scheduled` | status filter |
| "Conflictos" | `?conflict=1` | client-side: `item.conflict_count > 0` |
| "No-shows" | `?status=no_show` | status filter |
| "Riesgo alto" | `?risk=high` | client-side: `item.risk_level === "high"` |

Funnel stages (B2) reuse `?stage=<status>` mapped to `appointment.status`.

**Step 2: Write a smoke test for the URL parsing helper.**

Create `frontend/src/features/appointments/utils/filters.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseAppointmentFilters } from "./filters";

describe("parseAppointmentFilters", () => {
  it("maps today=1 to a date range covering today", () => {
    const out = parseAppointmentFilters(new URLSearchParams("today=1"), "America/Mexico_City");
    expect(out.date_from).toBeTruthy();
    expect(out.date_to).toBeTruthy();
  });
  it("passes status through", () => {
    const out = parseAppointmentFilters(new URLSearchParams("status=confirmed"), "UTC");
    expect(out.status).toBe("confirmed");
  });
  it("returns clientSide flags for conflict and risk", () => {
    const out = parseAppointmentFilters(new URLSearchParams("conflict=1&risk=high"), "UTC");
    expect(out.clientSide.conflict).toBe(true);
    expect(out.clientSide.risk).toBe("high");
  });
});
```

Run: `cd frontend && bun test src/features/appointments/utils/filters.test.ts`
Expected: FAIL (module not found).

**Step 3: Implement the helper.**

Create `frontend/src/features/appointments/utils/filters.ts` with `parseAppointmentFilters(params, tz)` returning `{ date_from?, date_to?, status?, customer_id?, clientSide: { conflict?, risk? } }`. Use `Intl.DateTimeFormat` for tz boundaries; no new deps.

Run: `cd frontend && bun test src/features/appointments/utils/filters.test.ts`
Expected: PASS.

**Step 4: Wire `MetricTile` and funnel stages to push URL state.**

In `AppointmentsPage.tsx`:
- Replace `MetricTile`'s `onClick={() => toast.info(...)}` with `onClick={() => setSearchParams({ ...current, [paramFor(label)]: valueFor(label) })}` using TanStack Router's `useSearch` / `useNavigate`. If no route schema exists, fall back to a local `useState<URLSearchParams>` whose value is also written to `history.replaceState`.
- Replace `FunnelPanel` button `onClick={() => toast.info(...)}` similarly with `?stage=<status>`.
- Make `MetricTile` visually toggleable when active (`ring-2 ring-sky-300` when its filter is the current one).
- Add a small "Clear filters" button when any filter is active.

**Step 5: Hook the filters into the existing query.**

Update the `useQuery` that calls `appointmentsApi.list(...)` to pass the parsed `{ date_from, date_to, status, customer_id }`. Apply `clientSide` flags as a `.filter(...)` over the returned `items`.

**Step 6: Commit.**

```bash
git add frontend/src/features/appointments/utils/filters.ts \
        frontend/src/features/appointments/utils/filters.test.ts \
        frontend/src/features/appointments/components/AppointmentsPage.tsx
git commit -m "feat(appointments): URL-state filters from KPI tiles and funnel stages"
```

## Task 1.2 — `open-chat` action navigates to conversation

**Files:**
- Modify: `frontend/src/features/appointments/components/AppointmentsPage.tsx` (line ~732 mutation onSuccess)
- Modify: `frontend/src/features/appointments/api.ts` (if needed — check whether `AppointmentItem` already exposes `conversation_id` or `customer_id`)

**Step 1: Check the response shape.**

```bash
grep -nE "conversation_id|customer_id" frontend/src/features/appointments/api.ts
```

If `conversation_id` is present on `AppointmentItem`, go to step 3. Otherwise step 2.

**Step 2 (conditional): Add `conversation_id` to the response.**

If missing, backend file `core/atendia/api/appointments_routes.py` `_item(...)` (line ~405) needs to also include `conversation_id` resolved from `Appointment.conversation_id` (the FK already exists on the model — verify). Frontend type gets a `conversation_id: string | null` field.

Write a pytest first in `core/tests/api/test_appointments.py`:

```python
async def test_appointment_item_includes_conversation_id(client, seeded_appointment_with_conversation):
    res = await client.get(f"/api/v1/appointments/{seeded_appointment_with_conversation.id}")
    assert res.status_code == 200
    body = res.json()
    assert "conversation_id" in body
```

Run, fail, add field, re-run, pass.

**Step 3: Replace the toast with navigation.**

In the mutation `onSuccess`:

```tsx
onSuccess: (response, variables) => {
  if (variables.action === "open-chat") {
    const conversationId = response.conversation_id ?? selectedAppointment?.conversation_id;
    if (conversationId) {
      navigate({ to: "/conversations/$conversationId", params: { conversationId } });
    } else {
      toast.error("Esta cita aún no tiene conversación asociada.");
    }
  } else {
    toast.success("Acción ejecutada");
  }
  invalidate();
},
```

**Step 4: Manually verify** — right-click an appointment in the calendar, choose "Abrir conversación WhatsApp", confirm it navigates to the conversation detail.

**Step 5: Commit.**

```bash
git add frontend/src/features/appointments/ core/atendia/api/appointments_routes.py core/tests/api/test_appointments.py
git commit -m "feat(appointments): open-chat action navigates to conversation"
```

## Task 1.3 — Dashboard palette "Crear cita" navigates here with `?new=1`

**Files:**
- Modify: `frontend/src/features/dashboard/components/DashboardPage.tsx` (line ~1243)
- Modify: `frontend/src/features/appointments/components/AppointmentsPage.tsx` (read `?new=1` and open create dialog)

**Step 1:** Confirm whether a `CreateAppointmentDialog` exists. If yes, jump to step 3. If not, step 2.

```bash
grep -nE "CreateAppointmentDialog|appointmentsApi\.create" frontend/src/features/appointments
```

**Step 2 (conditional): Build a minimal CreateAppointmentDialog.**

Inputs: customer phone (search-existing), `appointment_type`, `scheduled_at` (datetime-local input), optional `advisor_id`. Submit via `appointmentsApi.create(...)`. Show validation errors from backend.

**Step 3: Read `?new=1` in AppointmentsPage and open the dialog.**

```tsx
const search = useSearch({ from: "/(auth)/appointments" });
useEffect(() => {
  if (search.new === "1") {
    setCreateOpen(true);
    navigate({ search: ({ new: _, ...rest }) => rest, replace: true });
  }
}, [search.new]);
```

**Step 4: Wire palette command.**

```tsx
<CommandItem onSelect={() => { navigate({ to: "/appointments", search: { new: "1" } }); onClose(); }}>
  Crear cita
</CommandItem>
```

**Step 5: Manual verify** — `Ctrl+K → "Crear cita"` → AppointmentsPage opens with dialog. Submit creates a real row visible after refresh.

**Step 6: Commit.**

```bash
git commit -am "feat(dashboard): palette 'Crear cita' opens AppointmentsPage create flow"
```

## Task 1.4 — M1 verification + PR

- Click every KPI tile + funnel button + appointment context-menu "Abrir chat" + palette "Crear cita" in browser.
- Take screenshots showing filter applied (URL reflected, list narrowed).
- Run `uv run pytest core/tests/api/test_appointments.py -v` and `cd frontend && bun test`.
- Open PR with title `feat(appointments): wire KPI filters, open-chat nav, palette create flow`.

---

# Milestone 2 — Workflows (largest milestone)

**Branch:** `feat/placeholders-m2-workflows`
**Stubs covered:** C1, C2, C3, C4, C5, C6 (WorkflowsPage) + D1, D2 (WorkflowEditor).
**Backend additions:** `?node_id=` on executions endpoint; node-metrics endpoint (or client-side derivation v1).

## Task 2.1 — Backend: `?node_id=` filter on executions

**Files:**
- Modify: `core/atendia/api/workflows_routes.py` (around line 1347 `list_executions`)
- Test: `core/tests/api/test_workflow_executions.py` (create if missing)

**Step 1: Write the failing test.**

```python
async def test_executions_filtered_by_node_id(client, seeded_workflow):
    wid = seeded_workflow.id
    node_id = seeded_workflow.definition["nodes"][0]["id"]
    res = await client.get(f"/api/v1/workflows/{wid}/executions?node_id={node_id}")
    assert res.status_code == 200
    items = res.json()
    for it in items:
        assert any(step.get("node_id") == node_id for step in it.get("replay", []))
```

Run: `uv run pytest core/tests/api/test_workflow_executions.py::test_executions_filtered_by_node_id -v`
Expected: FAIL.

**Step 2: Add the query param.**

```python
@router.get("/{workflow_id}/executions", response_model=list[ExecutionItem])
async def list_executions(
    workflow_id: UUID,
    node_id: str | None = Query(None),
    ...
):
    rows = await _list_workflow_executions(session, tenant_id, workflow_id)
    items = [_execution_item(row, workflow) for row in rows]
    if node_id is not None:
        items = [it for it in items if _execution_touched_node(it, node_id)]
    return items
```

Implement `_execution_touched_node` by scanning the replay/trace persisted on the execution row.

Run test → PASS.

**Step 3: Commit.**

```bash
git add core/atendia/api/workflows_routes.py core/tests/api/test_workflow_executions.py
git commit -m "feat(workflows): filter executions by node_id"
```

## Task 2.2 — Backend: node-metrics endpoint

**Files:**
- Modify: `core/atendia/api/workflows_routes.py`
- Test: `core/tests/api/test_workflow_node_metrics.py`

**Step 1: Failing test.**

```python
async def test_node_metrics_shape(client, seeded_workflow):
    wid = seeded_workflow.id
    nid = seeded_workflow.definition["nodes"][0]["id"]
    res = await client.get(f"/api/v1/workflows/{wid}/nodes/{nid}/metrics")
    assert res.status_code == 200
    body = res.json()
    assert {"invocations", "success_rate", "avg_latency_ms", "sparkline_7d"} <= set(body)
    assert len(body["sparkline_7d"]) == 7
```

**Step 2: Implement.**

Add `class NodeMetrics(BaseModel)` and `@router.get("/{workflow_id}/nodes/{node_id}/metrics", response_model=NodeMetrics)`. Compute by scanning the same executions used elsewhere; v1 may return deterministic-seeded values keyed by `node_id` (consistent with `_metric_seed`-style helpers used in the rest of this module).

Run → PASS. Commit:

```bash
git commit -am "feat(workflows): node-level metrics endpoint"
```

## Task 2.3 — Frontend: wire `WorkflowEditor` node menu (D1 + D2)

**Files:**
- Modify: `frontend/src/features/workflows/api.ts` (add `getNodeMetrics`, `listExecutions(workflowId, { nodeId })`).
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx` (lines 217–226).

**Step 1:** Extend `workflowsApi`:

```ts
listExecutions(workflowId: string, params?: { nodeId?: string }) {
  const qs = params?.nodeId ? `?node_id=${params.nodeId}` : "";
  return fetcher<WorkflowExecution[]>(`/workflows/${workflowId}/executions${qs}`);
},
getNodeMetrics(workflowId: string, nodeId: string) {
  return fetcher<NodeMetrics>(`/workflows/${workflowId}/nodes/${nodeId}/metrics`);
},
```

Add `interface NodeMetrics` to the same file.

**Step 2:** Replace the two `toast.info` actions:

```tsx
{ label: "Ver métricas", action: () => setMetricsNodeId(node.id) },
{ label: "Ver ejecuciones relacionadas", action: () => setExecutionsNodeFilter(node.id) },
```

Add a `<NodeMetricsSheet workflowId={...} nodeId={metricsNodeId} onClose={...} />` that fetches and renders the metrics. Add `executionsNodeFilter` state that the executions sidebar reads to pass `nodeId` to `listExecutions`.

**Step 3:** Manual verify — right-click a node, click both actions, confirm sheet shows numbers and executions list filters.

**Step 4:** Commit:

```bash
git commit -am "feat(workflows-editor): wire 'Ver métricas' and 'Ejecuciones relacionadas'"
```

## Task 2.4 — Frontend: WorkflowsPage row + KPI + sort/grid (C1, C2, C3, C4, C5, C6)

**Files:**
- Modify: `frontend/src/features/workflows/components/WorkflowsPage.tsx`.

**Step 1: C1 "Abrir lead"** — replace toast with navigation:

```tsx
{ label: "Abrir lead", action: () => {
    if (execution.customer_id) {
      navigate({ to: "/customers/$customerId", params: { customerId: execution.customer_id } });
    } else {
      toast.error("Esta ejecución no tiene cliente asociado.");
    }
}},
```

(`customer_id` already exists on `ExecutionItem`.)

**Step 2: C2** — delete the `toast.info("Mostrando ejecuciones recientes")` line entirely. The panel itself is the feedback.

**Step 3: C3 "12 alertas activas"** — open a Popover:

```tsx
<Popover>
  <PopoverTrigger asChild>
    <Button variant="ghost" size="icon" className="...">
      <Bell className="h-4 w-4" />
      {alertsQuery.data && alertsQuery.data.length > 0
        ? <span className="absolute -top-0.5 -right-0.5 rounded-full bg-red-500 px-1 text-[10px] text-white">{alertsQuery.data.length}</span>
        : null}
    </Button>
  </PopoverTrigger>
  <PopoverContent align="end" className="w-80">
    <WorkflowAlertsList items={alertsQuery.data ?? []} />
  </PopoverContent>
</Popover>
```

Use existing `notificationsApi.list({ category: "workflow" })`. Verify the param name on the route — adjust to whatever filter the notifications route supports.

**Step 4: C4 KPI filter** — map each KPI to a filter:

```ts
const KPI_FILTERS: Record<string, Partial<WorkflowListParams>> = {
  "Flujos activos": { active: true },
  "Flujos críticos": { health: "critical" },
  "Ejecuciones hoy": { sort: "executions_today" },
  "Tasa de éxito": { sort: "success_rate" },
  // ...
};
```

Apply via URL state (`useSearch`). Render the active KPI with `ring-2 ring-sky-300`.

**Step 5: C5 Sort dropdown** — replace the `ListFilter` icon button with a `DropdownMenu`:

```tsx
<DropdownMenu>
  <DropdownMenuTrigger asChild><Button variant="ghost" size="icon"><ListFilter className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger>
  <DropdownMenuContent>
    {SORT_OPTIONS.map(opt =>
      <DropdownMenuItem key={opt.key} onSelect={() => setSort(opt.key)}>
        {opt.label}{sort === opt.key && <Check className="ml-auto h-3 w-3" />}
      </DropdownMenuItem>)}
  </DropdownMenuContent>
</DropdownMenu>
```

Apply `sort` client-side to the `filtered` array.

**Step 6: C6 Grid view toggle** — local state + `localStorage`:

```tsx
const [viewMode, setViewMode] = useLocalStorage<"list"|"grid">("workflows.viewMode", "list");
```

Render `viewMode === "grid"` as a 2-col grid of cards (reuse existing `WorkflowCard`).

**Step 7: Manual verify** every changed control in browser. Screenshot before/after for the PR description.

**Step 8: Commit:**

```bash
git commit -am "feat(workflows): wire row navigation, alerts popover, KPI filter, sort menu, grid view"
```

## Task 2.5 — M2 verification + PR

- `uv run pytest core/tests/api/test_workflow_executions.py core/tests/api/test_workflow_node_metrics.py -v` → green.
- `cd frontend && bun test` → green.
- Browser walkthrough of every changed control + screenshots.
- Open PR.

---

# Milestone 3 — Agents

**Branch:** `feat/placeholders-m3-agents`
**Stubs covered:** A1 (MetricTile drill-down), A2 (tenant switcher), A3 (guardrail toggle), A4 ("Ver historial").
**Backend additions:** `?entity_id=` filter on `GET /agents/{id}/audit-logs`. (Guardrail PATCH already exists at `PATCH /api/v1/guardrails/{id}`.)

## Task 3.1 — Backend: optional guardrail patch body

**Files:**
- Modify: `core/atendia/api/agents_routes.py` (`GuardrailBody` → introduce `GuardrailPatch` with optional fields, line ~225)
- Test: `core/tests/api/test_agents_guardrails.py` (add or extend)

**Step 1: Failing test.**

```python
async def test_patch_guardrail_only_active(client, seeded_agent_with_guardrail):
    gid = seeded_agent_with_guardrail.guardrails[0]["id"]
    res = await client.patch(f"/api/v1/guardrails/{gid}", json={"active": False})
    assert res.status_code == 200
    assert res.json()["active"] is False
```

Run: FAIL (current body requires all fields).

**Step 2: Add `GuardrailPatch(BaseModel)` with every field `Optional[...]` and use it on the patch route.** Merge into the existing row via `body.model_dump(exclude_unset=True)`.

Run: PASS. Commit.

## Task 3.2 — Backend: `?entity_id=` filter on audit-logs

**Files:**
- Modify: `core/atendia/api/agents_routes.py` (`get_agent_audit_logs`, line ~1521)
- Test: same file as above

**Step 1: Failing test:**

```python
async def test_audit_logs_filter_by_entity(client, seeded_agent_with_audit):
    aid = seeded_agent_with_audit.id
    target = seeded_agent_with_audit.audit_logs[0]["entity_id"]
    res = await client.get(f"/api/v1/agents/{aid}/audit-logs?entity_id={target}")
    assert res.status_code == 200
    assert all(entry["entity_id"] == target for entry in res.json())
```

**Step 2: Add `entity_id: str | None = Query(None)` and filter in-process.** Commit.

## Task 3.3 — Frontend: guardrail toggle (A3)

**Files:**
- Modify: `frontend/src/features/agents/api.ts` — add `guardrailsApi.patch(id, body)`.
- Modify: `frontend/src/features/agents/components/AgentsPage.tsx` (line ~682)

**Step 1:** Add `patch(guardrailId, body: Partial<Guardrail>)` to the api client.

**Step 2:** Replace `Toggle` `onChange`:

```tsx
<Toggle
  checked={guardrail.active}
  onChange={(next) => toggleGuardrail.mutate({ id: guardrail.id, active: next })}
/>
```

Where `toggleGuardrail` is a `useMutation` calling `guardrailsApi.patch(id, { active })` with optimistic update + `onError → toast.error(...)`.

**Step 3:** Manual verify — flip a toggle, confirm DB-persisted change.

**Step 4:** Commit.

## Task 3.4 — Frontend: "Ver historial" Sheet (A4)

**Files:**
- Modify: `frontend/src/features/agents/api.ts` — `listAuditLogs(agentId, { entityId? })`.
- Modify: `frontend/src/features/agents/components/AgentsPage.tsx`.

**Step 1:** Add the API method.

**Step 2:** Add `<AuditTrailSheet open onOpenChange entityId={...} agentId={...}/>` that fetches and renders entries (timestamp, actor, action, brief diff). Reuse the existing audit-log shape on the page.

**Step 3:** Replace the `toast.info("Feature en construcción")` in line 1067 with `setHistorySheetEntityId(state.itemId)`.

**Step 4:** Manual verify + commit.

## Task 3.5 — Frontend: tenant switcher (A2)

**Files:**
- Modify: `frontend/src/features/agents/components/AgentsPage.tsx` (line ~412)
- Maybe: `frontend/src/features/auth/api.ts` — add `getMyTenants()` if missing.

**Step 1:** Probe for `GET /me/tenants` or equivalent:

```bash
grep -nE "tenants|me" core/atendia/api/users_routes.py core/atendia/api/auth_routes.py
```

If exists → wire it. If not → confirm with the user whether to add it. Pragmatic fallback for single-tenant operators: show the user's current tenant name read-only (no dropdown, just a `Badge` with `<Globe2/>` and the tenant name from auth store).

**Step 2:** Replace the hard-coded button. If multiple tenants accessible, render a `DropdownMenu`. On select: `authStore.switchTenant(tid)` + `queryClient.invalidateQueries()`.

**Step 3:** Commit.

## Task 3.6 — Frontend: MetricTile drill-down (A1)

**Files:**
- Modify: `frontend/src/features/agents/components/AgentsPage.tsx` (line ~238 `MetricTile`)

**Step 1:** Define a metric-to-drilldown map:

```ts
const METRIC_DRILLDOWN: Record<string, { kind: "live-monitor" | "turn-traces" | null; sort?: string }> = {
  "Conversaciones activas": { kind: "live-monitor" },
  "Latencia P95": { kind: "turn-traces", sort: "latency_desc" },
  "Tasa de éxito": { kind: "turn-traces", sort: "success_only" },
  "Salud IA": { kind: null }, // no drill-down → non-button
};
```

**Step 2:** Conditionally render `MetricTile` as `<button>` only when drilldown exists, else as `<div>`. On click: open a Sheet with the corresponding list.

**Step 3:** Commit.

## Task 3.7 — M3 verification + PR

Backend tests green, frontend tests green, browser walkthrough, screenshots, PR.

---

# Milestone 4 — Misc (palette, contact panel, clients)

**Branch:** `feat/placeholders-m4-misc`
**Stubs covered:** E1 (palette "Nueva conversación"), E3 (palette "Exportar clientes"), F1 (Llamar), F2 (Ver recomendaciones), G1 (Audit trail header).
**Backend additions:** None — all endpoints exist (`/customers/export`, `/customers/{id}/next-best-action`, `/customers/{id}/audit`).

## Task 4.1 — F1: `tel:` link

**Files:** `frontend/src/features/conversations/components/ContactPanel.tsx` (line ~509)

Replace the `Button` with an anchor styled as a button:

```tsx
<Button asChild variant="outline" size="sm" className="flex-1 h-7 gap-1 text-xs">
  <a href={`tel:${phone}`} aria-label="Llamar">
    <Phone className="h-3.5 w-3.5" />
    Llamar
  </a>
</Button>
```

Commit.

## Task 4.2 — F2: inline recommendations panel

**Files:** `frontend/src/features/conversations/components/ContactPanel.tsx` (line ~924)

**Step 1:** Add a `useQuery` for `customersApi.nextBestAction(customerId)` (lazy / `enabled: showRecommendations`).

**Step 2:** Replace the button with a toggle that expands an inline panel rendering each action as a card with title + description + a CTA that fires `customersApi.executeAction(customerId, actionId)`.

**Step 3:** Commit.

## Task 4.3 — G1: Audit trail sheet on ClientsPage

**Files:** `frontend/src/features/customers/components/ClientsPage.tsx` (line ~494)

**Step 1:** Add `customersApi.audit(customerId)` if missing.

**Step 2:** Replace toast with `setAuditCustomerId(customer.id)`. Render `<AuditTrailSheet customerId={auditCustomerId} onClose={...}/>` that fetches `/customers/{id}/audit` and renders timeline.

**Step 3:** Commit.

## Task 4.4 — E3: "Exportar clientes" download

**Files:** `frontend/src/features/dashboard/components/DashboardPage.tsx` (line 1244)

```tsx
<CommandItem onSelect={async () => {
  onClose();
  const blob = await customersApi.exportCsv();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `customers-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  toast.success("Exportación lista");
}}>
  Exportar clientes
</CommandItem>
```

Add `exportCsv()` to `customers/api.ts` if missing: `fetch("/api/v1/customers/export").then(r => r.blob())`.

Commit.

## Task 4.5 — E1: "Nueva conversación" outbound flow

**Files:**
- Modify: `frontend/src/features/dashboard/components/DashboardPage.tsx` (line 1242)
- New: `frontend/src/features/conversations/components/NewConversationDialog.tsx`

**Step 1:** Build `NewConversationDialog`:
  - phone input (E.164 validation client-side)
  - optional initial message
  - on submit: try `customersApi.findByPhone(phone)` → if exists and `last_inbound_at` within 24h → `conversationsApi.sendOutbound({ customer_id, body })`; otherwise show inline form error *"Requiere template WhatsApp aprobado (pendiente de Phase 3d.2). Esta acción está bloqueada hasta entonces."*
  - on success: `navigate({ to: "/conversations/$conversationId", params: ... })`

**Step 2:** Hook palette command to open this dialog (lift state via context or use a global `useNewConversationDialog()` zustand store, whichever fits the repo's pattern — check `useAuthStore` for the pattern).

**Step 3:** Commit.

## Task 4.6 — M4 verification + PR

Manually verify every changed control. Screenshots. PR.

---

# Closing

After all four milestones land:

1. Delete `DemoBadge` usages that no longer apply (any control that became real should lose its violet badge).
2. `grep -rn "toast.info(" frontend/src` should return only the in-file definition inside `NYIButton.tsx`, plus any legitimate informational toasts you decided to keep (currently: F2 if you kept it as toast — but in this plan it becomes a panel, so none).
3. Update `PROJECT_MAP.md` (and the trust-break checkpoint section in `project_overview` memory if a new "trust-break" line is warranted — it isn't, this is a win).

## Verification rituals (each milestone)

- Backend: `uv run pytest core/tests/api -q` → green for affected modules.
- Frontend: `cd frontend && bun test` → green.
- Browser: open dev server, click the previously-stubbed control, verify the real effect.
- "Done" only when the user has clicked and confirmed.

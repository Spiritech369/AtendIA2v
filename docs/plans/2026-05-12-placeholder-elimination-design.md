# Design: Placeholder elimination across command centers

**Date:** 2026-05-12
**Status:** Approved (blueprint)
**Implementation plan:** `2026-05-12-placeholder-elimination-implementation.md` (next)

## Premise

Every UI control in the operator dashboard must map to a real data fetch,
state mutation, API call, or interaction. `toast.info(...)` placeholders that
pretend to be operational are bugs: they imply functionality the product does
not have. The directive is:

> Si un botón parece operativo, debe ejecutar backend o mostrarse como
> placeholder interno. UI no es decoración; cada elemento mapea a datos
> reales, estado, API o interacción.

`NYIButton` (amber) is reserved for features that are genuinely deferred to
a future phase. The default is **wire it real** — adding backend endpoints
where they are missing — and only fall back to `NYIButton` when the feature
is out of scope for current architecture (e.g. WhatsApp templates pending
Phase 3d.2).

## Inventory

KB is already fully wired (no `toast.info` stubs). The placeholders live in
seven frontend files. Backend coverage is already extensive: appointments,
workflows, agents, customers, notifications, and audit-logs all have route
modules.

| Area | File | Stubs |
|---|---|---|
| Appointments | `features/appointments/components/AppointmentsPage.tsx` | 3 |
| Agents | `features/agents/components/AgentsPage.tsx` | 4 |
| Workflows list | `features/workflows/components/WorkflowsPage.tsx` | 5 + 1 drop |
| Workflows editor | `features/workflows/components/WorkflowEditor.tsx` | 2 |
| Dashboard palette | `features/dashboard/components/DashboardPage.tsx` | 3 |
| Conversations contact panel | `features/conversations/components/ContactPanel.tsx` | 2 |
| Clients | `features/customers/components/ClientsPage.tsx` | 1 |

## Resolution per stub

### A. Agents

- **A1** `MetricTile.onClick` (line 243): drill-down. Click opens a Sheet
  listing `GET /agents/{id}/live-monitor` filtered/sorted by the metric. For
  metrics without an obvious drill-down (e.g. composite "Salud IA"), tile is
  rendered as `cursor-default` non-button.
- **A2** Tenant switcher (line 412): real switcher. Dropdown populated by
  `GET /me/tenants`. Single-tenant operators see a read-only badge with the
  current tenant's display name (no click target).
- **A3** Guardrail toggle (line 682): real toggle. **Backend add:**
  `PATCH /agents/{agent_id}/guardrails/{rule_id}` accepting `active: bool`.
  Frontend calls `guardrailsApi.patch`.
- **A4** "Ver historial" menu (line 1067): real wire. Sheet opens with
  `GET /agents/{id}/audit-logs?entity_id=<rule_or_field_id>`. **Backend add:**
  `?entity_id=` filter on the audit-logs endpoint.

### B. Appointments

- **B1** `MetricTile.onClick` (line 230): real filter. KPI click sets a URL
  query param consumed by the calendar/feed queries (`?status=confirmed`,
  `?conflict=true`, `?today=1`...).
- **B2** Funnel stage click (line 622): real filter. Sets `?stage=<status>`
  on the appointments query.
- **B3** `open-chat` mutation success (line 732): real navigation. Instead
  of showing an info toast, navigate to `/conversations/$conversationId`.
  Uses `appointment.conversation_id`; if not on the model, add the FK
  resolution server-side in the action handler.

### C. Workflows list

- **C1** "Abrir lead" row action (line 283): real navigation. `navigate('/customers/$customerId')` using `execution.customer_id`. If the
  schema only carries `lead_name`, add `customer_id` to `ExecutionItem`.
- **C2** "Mostrando ejecuciones recientes" toast (line 619): **drop**. The
  side panel that opens is itself the feedback.
- **C3** Bell button "12 alertas activas" (line 684): real popover.
  Populated by `GET /notifications?category=workflow`. Count comes from the
  response, not a hard-coded "12".
- **C4** `KpiCard.onClick` (line 692): real filter. Map each KPI label to a
  workflow-list filter (active=true, health=critical, etc.). URL state.
- **C5** Sort icon (line 707): real sort. Dropdown with options (Salud /
  Nombre / Ejecuciones hoy / Tasa de éxito). Client-side sort for v1; can
  promote to `?sort=` server-side when list grows.
- **C6** Grid icon (line 710): real view toggle. Local state + localStorage
  persistence. Grid view = 2-col card layout.

### D. Workflow editor

- **D1** "Ver métricas" node action (line 223): real metrics sheet.
  **Backend add:** `GET /workflows/{wid}/nodes/{nid}/metrics` returning
  `{invocations, success_rate, avg_latency_ms, sparkline_7d}`. If derivation
  from existing execution traces is trivial, do it client-side for v1 and
  defer the dedicated endpoint.
- **D2** "Ver ejecuciones relacionadas" (line 224): real filter. **Backend
  add:** `?node_id=` filter on `GET /workflows/{id}/executions`. Frontend
  applies the filter on the executions sidebar.

### E. Dashboard command palette

- **E1** "Nueva conversación" (line 1242): real outbound flow with a
  hard constraint. Open a Dialog: phone input + optional initial message.
  - If recipient has an inbound in the last 24h → send free-text outbound
    via the existing outbound queue.
  - If outside 24h → show a real validation error
    *"Requiere template WhatsApp aprobado (pendiente de Phase 3d.2)"* — not
    a `toast.info`, a real form error that blocks submission.
- **E2** "Crear cita" (line 1243): real navigation.
  `navigate('/appointments?new=1')`; AppointmentsPage opens its existing
  CreateDialog when the query param is present. If no `CreateAppointmentDialog`
  exists yet, add it (POST + parse-natural-language already supported).
- **E3** "Exportar clientes" (line 1244): real download. Fetch
  `GET /customers/export` and trigger a blob download.

### F. Conversations contact panel

- **F1** "Llamar" button (line 513): real `tel:` link. No backend.
- **F2** "Ver recomendaciones" (line 927): real panel. Replace the toast
  with an inline expanded panel populated by `GET /customers/{id}/next-best-action`.

### G. Clients

- **G1** "Audit trail" header button (line 494): real sheet. Opens with
  `GET /customers/{id}/audit`.

## Backend additions summary

Five small additions:

1. `PATCH /agents/{agent_id}/guardrails/{rule_id}` (body: `{active: bool}`)
2. `?entity_id=<uuid>` filter on `GET /agents/{agent_id}/audit-logs`
3. `GET /workflows/{workflow_id}/nodes/{node_id}/metrics`
4. `?node_id=<uuid>` filter on `GET /workflows/{workflow_id}/executions`
5. `customer_id` field on `ExecutionItem` response schema (if absent)

Plus, possibly, a `conversation_id` lookup in the `open-chat` appointment
action response if it is not already exposed.

## Milestones (one command center per session per working contract)

- **M1 — Appointments**: B1, B2, B3 + E2 (create-from-palette navigates here).
- **M2 — Workflows**: C1-C6 + D1 + D2 (largest milestone).
- **M3 — Agents**: A1-A4.
- **M4 — Misc**: E1, E3, F1, F2, G1.

Each milestone is a separate session and a separate branch. "Done" means
verified in the browser by the user before moving on.

## Out of scope

- WhatsApp template registry (Phase 3d.2) — referenced in E1 as a real
  validation error, not implemented here.
- Multi-tenant admin onboarding flow — A2 wires the switcher to whatever
  `GET /me/tenants` already returns.
- Storybook entries, screenshot snapshots, full E2E for these flows.

## Verification (per milestone)

1. Backend: pytest passes locally for the affected route module.
2. Frontend: `bun test` passes; new types match runtime responses.
3. Browser: user clicks every previously-stubbed button and confirms it now
   produces a real, visible effect. Output: screenshot or short verbal
   confirmation per stub.

No "green emoji" success until the user signs off the milestone.

# Workflow Builder (respond.io-style) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the existing AtendIA Workflows module into a respond.io-style visual automation builder — fix what's broken today (rename, working context menu, no fake data on a new tenant), then expand the trigger/step catalog to cover the spec (AI Agent invocation, more triggers, conditional branches, failure paths).

**Architecture:** The backend already has a real execution engine (`core/atendia/workflows/engine.py`), persistence (`Workflow`, `WorkflowExecution`, `WorkflowVersion`), arq queue, REST routes, and a typed React client. Gaps are 95% UI and 5% engine additions (new node types, new trigger types). We will (1) wire the UI handlers that today show `toast.info("Feature en construcción")` to real navigation/state, (2) add inline rename to the editor header, (3) make a new-tenant empty state honest (no cosmetic sparkline fillers), (4) add an `invoke_agent` node type that calls the existing `Agent` model, (5) add the next priority triggers/steps from the respond.io list.

**Tech Stack:** React 19 + Vite + TypeScript, TanStack Query, Tailwind 4, Radix UI, @xyflow/react, Vitest. Backend: FastAPI + SQLAlchemy 2.0 (async) + Postgres + arq.

---

## Scope Note

The full respond.io spec (≈19 step types, ≈11 trigger types, templates, import/export, versioning UI, audit log, conversion events) is a multi-week effort. This plan **executes Phase 1 in this session** (fixes the user's complaints + AI Agent step + 2 high-value triggers) and **scopes Phases 2-4** so the user can prioritize after seeing Phase 1 in their hands.

---

## Phase 1 — Make it functional (this session)

Goal: every button that today shows "Feature en construcción" must either do something or be removed; user can rename a workflow inline; new tenant sees honest empty state; user can drop an "Invocar Agente IA" node and pick one of their published agents.

### Task 1.1 — Inline rename of workflow name in editor header

**Files:**
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx:228-243` (the header that today renders `<h2>Editor: {workflow.name}</h2>` as read-only)
- API already exists: `workflowsApi.patch(id, { name })` at `frontend/src/features/workflows/api.ts:169`

**Step 1: Add `renameWorkflow` mutation inside `WorkflowEditor`** (mirrors the existing `patchNode` pattern at line 112)

```ts
const renameWorkflow = useMutation({
  mutationFn: (name: string) => workflowsApi.patch(workflow.id, { name }),
  onSuccess: () => {
    void invalidate();
    toast.success("Nombre actualizado");
  },
  onError: (error) => toast.error("No se pudo renombrar", { description: error.message }),
});
```

**Step 2: Replace the `<h2>` with an editable, click-to-edit input.** Add local `nameDraft` state, sync from `workflow.name` on `workflow.id` change, commit on blur or Enter, revert on Escape. Block edit when `workflow.active` (respond.io rule: cannot edit Published).

**Step 3: Manual verification** — open `/workflows`, click on the title in the editor header, type a new name, blur. Reload — name persists.

**Step 4: Commit**

```bash
git add frontend/src/features/workflows/components/WorkflowEditor.tsx
git commit -m "feat(workflows): inline rename of workflow in editor header"
```

### Task 1.2 — Remove cosmetic sparkline filler from KPI cards

**Files:**
- Modify: `frontend/src/features/workflows/components/WorkflowsPage.tsx:92` — the `safe = values.length ? values : [20, 30, 25, 36, 44, 40, 52]` fallback that paints fake history for tenants with zero data.

**Step 1: Change the fallback to an empty/flat state.** Render a muted dashed baseline when `values` is empty; do not invent numbers. KPI count cards already show 0; we just need the sparkline to not lie.

**Step 2: Verify on `dele.zored` (new tenant)** — KPI cards show 0/0 with no fake trendline.

**Step 3: Commit**

```bash
git commit -m "fix(workflows): honest empty-state sparkline on new tenants"
```

### Task 1.3 — Wire the two stub context-menu actions

**Files:**
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx:223-224` (the two `toast.info("Feature en construcción")` items)

**Step 1: "Ver métricas"** → focus the node, scroll the right panel so the node card with its conversion%/entered/completed columns is in view. Use existing per-node metrics already rendered in the row (no new endpoint needed).

**Step 2: "Ver ejecuciones relacionadas"** → emit an upward callback that the parent `WorkflowsPage` already supports (it has `executionsQuery` + execution drawer). Pass a `node_id` filter; in `WorkflowsPage`, the executions list filters `replay[].node_id` to only show executions that touched that node.

**Step 3: Add prop on `WorkflowEditorProps`:** `onShowExecutions?: (nodeId: string) => void`. Wire it from `WorkflowsPage`.

**Step 4: Manual verification** — right-click a node, click each action, confirm both work and neither shows "en construcción".

**Step 5: Commit**

```bash
git commit -m "feat(workflows): wire 'Ver métricas' and 'Ver ejecuciones relacionadas' context actions"
```

### Task 1.4 — `invoke_agent` node type (backend)

**Files:**
- Modify: `core/atendia/workflows/engine.py:71-93` — add `"invoke_agent"` to `NODE_TYPES`.
- Modify: `core/atendia/workflows/engine.py` — add an execution handler for `invoke_agent` that loads `Agent` by `config.agent_id`, verifies tenant ownership, sets `conversation_state.assigned_agent_id`, optionally publishes a `bot_paused=false` event, and records via `WorkflowActionRun(action_key=f"invoke_agent:{agent_id}")` for idempotency.
- Modify: `core/atendia/api/workflows_routes.py` — add `GET /workflows/_available_agents` returning published `Agent` rows of the current tenant: `{id, name, role, status}` (only `status="production"`).
- Test: `core/atendia/tests/test_workflows_routes.py` — add a test that posts a workflow with `invoke_agent` node, asserts validation passes if `agent_id` belongs to tenant and fails (400) if it doesn't.

**Step 1: Write the failing test** — `test_invoke_agent_rejects_cross_tenant_agent` and `test_invoke_agent_accepts_owned_agent`.

**Step 2: Run** `pytest core/atendia/tests/test_workflows_routes.py -k invoke_agent -v` — expect failure (unknown node type).

**Step 3: Add to `NODE_TYPES` + reference validation in `validate_references` (the function already does this for `assign_agent.user_id`).** Resolve `Agent` by `id` AND `tenant_id`.

**Step 4: Implement runtime handler** in `execute_workflow`'s match/switch — sets `assigned_agent_id` on the conversation_state, increments `steps_completed`, idempotent via `WorkflowActionRun`.

**Step 5: Run tests, all pass.**

**Step 6: Commit**

```bash
git commit -m "feat(workflows/engine): add invoke_agent node type backed by Agent model"
```

### Task 1.5 — `invoke_agent` in the frontend editor

**Files:**
- Modify: `frontend/src/features/workflows/api.ts` — add `listAvailableAgents` and `WorkflowAgentSummary` type.
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx:53-66` (`NODE_META`) — add `invoke_agent` metadata (label "Agente IA", `Bot` icon, blue).
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx:122-135` — when the user clicks "Agregar nodo aquí" they get a small menu now ("Acción Mensaje", "Mover etapa", "Asignar Agente IA", "Esperar"), not only "template_message".
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx:summaryFor` — render `Agente: <name>` from a query lookup.
- New behavior: when the selected node is `invoke_agent`, the right panel renders a typed form (select of agents) **in addition to** the JSON textarea, not instead of it (so power users still have raw access).

**Step 1: Add API client method + query in editor.**

**Step 2: Replace the lone `addNode` button with a small dropdown menu of node templates.** Each menu item just calls `workflowsApi.addNode(workflow.id, {type, title, config})` with the right defaults.

**Step 3: Add a typed sub-form** for `invoke_agent` rendered above the JSON area (select from `listAvailableAgents`, with a disabled placeholder if the agent list is empty: "Aún no tienes agentes en producción"). Form writes into the same `configDraft` JSON so Save flow doesn't change.

**Step 4: Manual verification** — drop an "Asignar Agente IA" node, pick an agent, save, reload, the node persists.

**Step 5: Commit**

```bash
git commit -m "feat(workflows): drop 'Asignar Agente IA' node and typed config form"
```

### Task 1.6 — Lock "Editar" while workflow is Published (respond.io rule)

The spec says: "Published workflows cannot be edited until stopped."

**Files:**
- Modify: `WorkflowEditor.tsx` — disable Save/Add/Delete buttons and the inline-rename input when `workflow.active === true`, with a tooltip "Detén el workflow para editar". The Stop control already exists in the page-level safety panel.

**Step 1: Add a `readOnly = workflow.active` flag and pass it to all mutation triggers.**

**Step 2: Commit**

```bash
git commit -m "feat(workflows): editor is read-only while published"
```

### Task 1.7 — Run typecheck + tests + smoke the UI

**Step 1:** `cd frontend && npm run typecheck`

**Step 2:** `cd frontend && npm test -- --run workflows`

**Step 3:** `cd core && pytest atendia/tests/test_workflows_routes.py -v`

**Step 4:** Boot the dev server, log into `dele.zored`, create a workflow, rename it, drop an agent step, run simulate. All passes.

**Step 5: Final commit** if there were typecheck/test fixups along the way.

---

## Phase 2 — Trigger & step catalog expansion (next session)

Each item is one PR.

- **2.1** Trigger: `conversation_closed` (with source + category conditions)
- **2.2** Trigger: `contact_tag_updated` (added/removed)
- **2.3** Trigger: `contact_field_updated` (filter by field id, standard + custom)
- **2.4** Trigger: `shortcut` (manual launch from Inbox) + optional Shortcut Form
- **2.5** Trigger: `incoming_webhook` (generated URL, JSONPath body mapping)
- **2.6** Step: `branch` (real conditional logic with AND/OR groups + Else branch) — replaces the cosmetic `condition` alias
- **2.7** Step: `ask_question` with timeout branch + invalid branch + multiple-choice sub-branches
- **2.8** Step: `update_lifecycle` (already partially modeled via `move_stage`; add typed pipeline picker)
- **2.9** Step: `add_google_sheets_row` (needs Google OAuth setup separately — defer if not yet configured)
- **2.10** Step: `http_request` (the most useful integration primitive — covers anything not natively supported)
- **2.11** Step: `wait` (already implemented as `delay` in engine; just expose a typed form: minutes/hours/days)
- **2.12** Step: `jump_to` (with loop protection — engine cap already exists)
- **2.13** Step: `trigger_another_workflow` + `manual_trigger` (chained workflows)

## Phase 3 — Reliability & visibility (next-next session)

- **3.1** Failure branches on every fail-capable step (`send_message`, `ask_question`, `assign_to`, `http_request`, ...)
- **3.2** Test mode UI: pick a test lead, simulate trigger payload, show execution path with variables at each node, branch decisions, errors before publish
- **3.3** Workflow Settings panel: exit conditions (stop on outgoing user message, stop on incoming message, stop on manual assignment), per-contact "trigger once"
- **3.4** Audit log UI: per-execution drawer with step path, variables, assignment changes, tags, lifecycle, messages, external calls, failure/exit reason
- **3.5** Loop detection: warn at validation time on Jump-To cycles and workflow-to-workflow back-references

## Phase 4 — Catalog & polish

- **4.1** Import/Export JSON (with size + step-count validation, invalid-reference stripping, name-collision numbering)
- **4.2** Workflow Templates (Welcome, Lead Qualification, Round Robin, Meta Ads Routing, TikTok Ads Routing, Lifecycle Follow-up)
- **4.3** Version history UI: list, compare-diff, restore-to-draft
- **4.4** Meta Click-to-Chat Ads trigger + Conversions API event step
- **4.5** TikTok Messaging Ads trigger + Lower Funnel event step
- **4.6** Visual graph upgrade: swap the linear list for `@xyflow/react` (already a dep), with minimap, zoom, drag-to-reorder, branch visualization, keyboard shortcuts (Ctrl+Z/Y/S, Del)

---

## Out of scope (this branch)

- Real Google Sheets / Meta / TikTok OAuth wiring (UX scaffolds OK, real auth flows separate)
- AI Objective Legacy step (deprecated in the spec; don't build new code on it)
- Mobile/responsive layout (desktop-first as per spec)

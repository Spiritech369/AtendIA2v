# Mock / Demo Isolation Design

**Date:** 2026-05-11  
**Status:** Approved — pending implementation plan  
**Scope:** Agents, Workflows, Handoffs, Appointments, Knowledge

---

## Problem

Several modules mix simulated data and unimplemented actions directly inside production route files:

- `DEMO_ADVISORS` / `DEMO_VEHICLES` — hardcoded constants in `appointments_routes.py`
- `_ensure_demo_agents()` / `_ensure_demo_workflows()` — auto-seed on every LIST request
- `_ensure_demo_data()` in appointments / customers — gated by `user.email == "admin@demo.com"` (fragile)
- `mock_whatsapp` — WhatsApp action endpoints log `{"provider": "mock_whatsapp"}` silently
- Hardcoded demo operator list in `_handoffs/command_center.py`
- `mode="mock"` as default in KB `test_query` — available to any tenant
- 25+ `toast.info(...)` buttons in the frontend that simulate actions without calling any API

Before adding new features, this behavior must be clearly marked and isolated so that:
1. A real production tenant never accidentally receives demo data or simulated actions.
2. The path to a real implementation is an obvious, typed swap — not a grep-and-rewrite.
3. Developers can distinguish two concepts: **DEMO** (implemented but simulated) vs **NYI** (not yet built).

---

## Two Concepts

| Concept | Meaning | Visual signal |
|---|---|---|
| **DEMO** | Feature exists with a simulated implementation. Data is fake. Actions are no-ops. Replaceable by a real impl via a typed provider swap. | Violet badge — "Datos de demostración" |
| **NYI** | Feature is not built yet. The button/action has no backend. Independent of demo mode. | Amber lock — "Feature en construcción" |

---

## Decision: Approach B — DB flag + `_demo/` module + protocols

### Rejected alternatives

**Approach A (env-var + passive markers):** Fixtures stay mixed in route files. `is_demo` is lost if env var is not set. No contracts — the real impl path is invisible.

**Approach C (per-feature tenant config JSONB):** Over-engineered for the current phase. No tenant needs heterogeneous feature flags today.

---

## Section 1 — DB flag and central gate

### Migration 040

```sql
ALTER TABLE tenants ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE tenants SET is_demo = TRUE WHERE name = 'demo';
```

Alembic migration `040_demo_tenant_flag.py`. Downgrade drops the column.

### FastAPI dependency

```python
# api/_deps.py
async def demo_tenant(tenant: Tenant = Depends(get_current_tenant)) -> bool:
    return tenant.is_demo
```

All routes that previously checked `user.email.lower() == "admin@demo.com"` replace that gate with `tenant.is_demo`.

The `_ensure_demo_*` functions are **removed from route handlers entirely**. They are called only from `scripts/seed_full_mock_data.py` at seed time. Routes do not auto-seed on LIST.

---

## Section 2 — `_demo/` module and provider protocols

### New module layout

```
core/atendia/_demo/
    __init__.py
    fixtures.py     # all demo constants: DEMO_ADVISORS, DEMO_VEHICLES,
                    # demo operator list, demo agent/workflow definitions
    providers.py    # DemoAdvisorProvider, DemoVehicleProvider,
                    # DemoMessageActionProvider

core/atendia/providers/
    __init__.py
    advisors.py     # AdvisorProvider(Protocol)
    vehicles.py     # VehicleProvider(Protocol)
    messaging.py    # MessageActionProvider(Protocol)
```

### Protocol example

```python
# providers/advisors.py
from typing import Protocol

class AdvisorProvider(Protocol):
    async def list_advisors(self) -> list[dict]: ...
    async def get_advisor(self, advisor_id: str) -> dict | None: ...
```

### Provider injection

```python
# api/_deps.py
def get_advisor_provider(is_demo: bool = Depends(demo_tenant)) -> AdvisorProvider:
    if is_demo:
        return DemoAdvisorProvider()
    raise HTTPException(501, "Advisors backed by DB not yet implemented")
```

When a real implementation is ready, `get_advisor_provider` returns it instead of the demo. Routes do not change.

### Providers to create

| Protocol | Demo impl | Used in |
|---|---|---|
| `AdvisorProvider` | `DemoAdvisorProvider` | `appointments_routes.py` |
| `VehicleProvider` | `DemoVehicleProvider` | `appointments_routes.py` |
| `MessageActionProvider` | `DemoMessageActionProvider` | `appointments_routes.py` (remind, location, documents) |

---

## Section 3 — API contract

### `_demo: true` field

Endpoints that serve demo data or simulate actions include `"_demo": true` in their response. Only added where the response mixes real and mock behavior:

| Endpoint | Change |
|---|---|
| `GET /advisors` | Returns list + `"_demo": true` when `is_demo` |
| `GET /vehicles` | Returns list + `"_demo": true` when `is_demo` |
| `POST /appointments/:id/remind` | Returns `{"status": "simulated", "_demo": true}` |
| `POST /appointments/:id/send-location` | Returns `{"status": "simulated", "_demo": true}` |
| `POST /appointments/:id/request-documents` | Returns `{"status": "simulated", "_demo": true}` |
| `POST /handoffs/:id/draft` | `source: "mock" | "stored"` already correct — no change |
| `POST /kb/test-query` | 400 if `mode="mock"` and `is_demo=False` |

### Handoffs command center

The hardcoded demo operator list (`andrea@demo.com`, `carlos@demo.com`, etc.) moves to `_demo/fixtures.py`. The `GET /handoffs/agents` endpoint returns:
- Demo list from `_demo/fixtures.py` if `is_demo`
- Real tenant users from DB if not `is_demo`

`source: Literal["mock", "stored"]` in `DraftResponse` is kept as-is — semantically correct.

### KB command center

- `mode="mock"` in `test_query` is gated: only accepted if `is_demo=True`
- Non-demo tenants receive `400 Bad Request: mock mode not available in production`
- Default changes from `mode="mock"` to `mode="sources_only"` for all tenants

---

## Section 4 — Frontend

### Two new components

**`DemoBadge.tsx`** — violet chip, tooltip "Datos de demostración — no reflejan operación real":

```tsx
<DemoBadge />         // inline next to a title or value
<DemoBadge wrap>      // wraps a block with a subtle violet border
```

Renders conditionally on `tenant.is_demo` from `stores/auth.ts`. Also rendered when API response includes `_demo: true`.

**`NYIButton.tsx`** — replaces `onClick={() => toast.info(...)}`:

```tsx
<NYIButton label="Importar CSV" icon={Upload} />
// Amber/gray button with lock icon
// Tooltip: "Feature en construcción — disponible próximamente"
// Does not call any API
```

### Where `DemoBadge` is applied

- Advisor and vehicle panels in `AppointmentsPage`
- `[Mock]` agents section in `AgentsPage`
- Demo workflows in `WorkflowsPage`
- Handoff draft card when `source="mock"` in `HandoffCard`
- KB test query panel when `mode="mock"`

### Where `NYIButton` replaces `toast.info`

| File | Buttons converted |
|---|---|
| `AppointmentsPage.tsx` | Import CSV, advanced filters, recommended action items, funnel stage items |
| `AgentsPage.tsx` | Upload document, view failures, view history, open conversation |
| `WorkflowsPage.tsx` | Pause variants (4 items), open lead, saved view, import JSON, alerts, grid view, sort by health, KPI filter |
| `WorkflowEditor.tsx` | View metrics, view related executions |
| `DashboardPage.tsx` | Command palette: new conversation, create appointment, export customers |
| `ContactPanel.tsx` | Open WhatsApp conversation, call phone, suggested next action |

---

## Section 5 — File change summary

### Backend — edited

| File | Change |
|---|---|
| `db/models/tenant.py` | Add `is_demo: Mapped[bool] = mapped_column(Boolean, default=False)` |
| `api/_deps.py` | Add `demo_tenant()` dependency |
| `api/appointments_routes.py` | Remove `DEMO_ADVISORS`, `DEMO_VEHICLES`, `_ensure_demo_data`, `mock_whatsapp`; inject `AdvisorProvider`, `VehicleProvider`, `MessageActionProvider` |
| `api/agents_routes.py` | Remove `_ensure_demo_agents`; LIST does not auto-seed |
| `api/workflows_routes.py` | Remove `_ensure_demo_workflows`, `_demo_definition`; LIST does not auto-seed |
| `api/customers_routes.py` | Replace `email == "admin@demo.com"` gate with `tenant.is_demo` |
| `api/_handoffs/command_center.py` | Move demo operator list to `_demo/fixtures.py`; gate by `is_demo` |
| `api/_kb/command_center.py` | Gate `mode="mock"` with `is_demo`; default to `sources_only` |
| `scripts/seed_full_mock_data.py` | Set `is_demo=True` for tenant `demo` |

### Backend — new

| File | Contents |
|---|---|
| `db/migrations/versions/040_demo_tenant_flag.py` | Migration + data update |
| `_demo/__init__.py` | empty |
| `_demo/fixtures.py` | All demo constants moved from route files |
| `_demo/providers.py` | `DemoAdvisorProvider`, `DemoVehicleProvider`, `DemoMessageActionProvider` |
| `providers/__init__.py` | empty |
| `providers/advisors.py` | `AdvisorProvider(Protocol)` |
| `providers/vehicles.py` | `VehicleProvider(Protocol)` |
| `providers/messaging.py` | `MessageActionProvider(Protocol)` |

### Frontend — new

| File | Contents |
|---|---|
| `components/DemoBadge.tsx` | Violet badge component |
| `components/NYIButton.tsx` | Amber NYI button component |

### Frontend — edited

`AgentsPage.tsx`, `WorkflowsPage.tsx`, `WorkflowEditor.tsx`, `AppointmentsPage.tsx`, `HandoffCard.tsx`, `DashboardPage.tsx`, `ContactPanel.tsx` — `toast.info` → `NYIButton`, `DemoBadge` added where applicable.

---

## Tests

- Unit test per demo provider (`list_advisors`, `list_vehicles`, `send_reminder`)
- Migration 040 included in existing roundtrip test
- Gate test: `mode="mock"` on non-demo tenant returns 400
- Gate test: demo actions on non-demo tenant return 501

---

## Out of scope

- Implementing real providers (Phase 5+)
- Converting `NYIButton` items into real features
- E2E visual tests for badges

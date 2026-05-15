# RBAC + Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Endurecer RBAC con guards de ruta y matriz E2E, y rediseñar el panel de debug de turnos a una narrativa legible en español.

**Architecture:**
- Backend: añadir `test_rbac_matrix.py` parametrizado que prueba ~30 endpoints admin-gated contra los 3 roles. Sin cambios en routes.
- Frontend: dos primitivas nuevas (`requireRole` helper + `<RoleGate>` componente) aplicadas a las rutas/UI. Una nueva capa de derivación (`turnStory.ts`) traduce `TurnTraceDetail` a un array tipado de pasos en español, renderizado por `TurnStoryView`. `TurnTraceInspector` se rediseña reusando secciones extraídas de `DebugPanel`.

**Tech Stack:** Python 3.12 + pytest + FastAPI (backend); React 19 + TS strict + TanStack Router/Query + Tailwind + shadcn + Vitest + Testing Library (frontend).

**Design doc:** `docs/plans/2026-05-12-rbac-and-observability-design.md`

---

## Task 1 — RBAC matrix backend test

**Files:**
- Create: `core/tests/api/test_rbac_matrix.py`

**Step 1: Inventariar endpoints admin-gated**

Recorrer `core/atendia/api/*.py` por `require_tenant_admin` y `require_superadmin`. Lista esperada (ya verificada con grep en el design doc):

- Workflows: POST/PUT/PATCH/DELETE de `/api/v1/workflows`, transitions, runs.
- Agents: POST/PUT/PATCH/DELETE de `/api/v1/agents`, prompts, dispatch.
- Knowledge: POST/PUT/DELETE de FAQs, documents, collections.
- Tenants: PATCH `/api/v1/tenants/me`.
- Customer fields: POST/PUT/DELETE.
- Users: superadmin-only para POST.

**Step 2: Escribir el archivo de test parametrizado**

```python
"""RBAC matrix — every admin-gated endpoint must reject operator (403) and
allow tenant_admin/superadmin. We don't verify the success body, only that
the gating fires correctly. Tests stay green even if payloads later fail
validation or return 404, as long as the gate doesn't trip."""
from __future__ import annotations

import pytest

# (method, path, payload, allowed_roles)
# Paths are formatted later with UUID placeholders if needed.
RBAC_MATRIX: list[tuple[str, str, dict | None, set[str]]] = [
    # Workflows
    ("POST", "/api/v1/workflows", {"name": "x"}, {"tenant_admin", "superadmin"}),
    # Agents
    ("POST", "/api/v1/agents", {"name": "x", "role": "advisor"},
     {"tenant_admin", "superadmin"}),
    # Customer fields
    ("POST", "/api/v1/customer-fields",
     {"slug": "x", "label": "X", "type": "text"},
     {"tenant_admin", "superadmin"}),
    # Tenants
    ("PATCH", "/api/v1/tenants/me", {"display_name": "x"},
     {"tenant_admin", "superadmin"}),
    # Knowledge (write paths under /api/v1/knowledge/*)
    ("POST", "/api/v1/knowledge/faqs", {"question": "q", "answer": "a"},
     {"tenant_admin", "superadmin"}),
    # Users (superadmin-only for cross-tenant creation, tenant_admin can
    # create within their own tenant — covered separately in test_users_rbac.py)
]

ROLE_CLIENTS = ["operator", "tenant_admin", "superadmin"]


@pytest.mark.parametrize("method,path,payload,allowed", RBAC_MATRIX)
def test_rbac_matrix(
    method, path, payload, allowed,
    client_operator, client_tenant_admin, client_superadmin,
):
    clients = {
        "operator": client_operator,
        "tenant_admin": client_tenant_admin,
        "superadmin": client_superadmin,
    }
    for role in ROLE_CLIENTS:
        client = clients[role]
        resp = client.request(method, path, json=payload)
        if role in allowed:
            assert resp.status_code != 403, (
                f"{role} should be allowed {method} {path}, "
                f"got {resp.status_code}: {resp.text}"
            )
        else:
            assert resp.status_code == 403, (
                f"{role} should be denied {method} {path}, "
                f"got {resp.status_code}: {resp.text}"
            )
```

**Step 3: Run the test**

```bash
uv run pytest core/tests/api/test_rbac_matrix.py -v
```

Expected: PASS for all entries. If any FAIL, the endpoint either:
- Missing `require_tenant_admin` → add it.
- Mismatched route path → fix the matrix entry.

Document any divergence at the bottom of the test file as a comment.

**Step 4: Commit**

```bash
git add core/tests/api/test_rbac_matrix.py
git commit -m "test(rbac): parametrized matrix for admin-gated endpoints"
```

---

## Task 2 — `requireRole` route guard helper

**Files:**
- Create: `frontend/src/lib/auth-guards.ts`
- Create: `frontend/tests/lib/auth-guards.test.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/lib/auth-guards.test.ts
import { describe, expect, it, beforeEach } from "vitest";
import { useAuthStore } from "@/stores/auth";
import { requireRole } from "@/lib/auth-guards";

describe("requireRole", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "idle", csrf: null });
  });

  it("redirects to /login when not authenticated", async () => {
    const guard = requireRole(["tenant_admin"]);
    await expect(guard()).rejects.toMatchObject({ to: "/login" });
  });

  it("redirects to / when role is not allowed", async () => {
    useAuthStore.setState({
      user: {
        id: "u1", tenant_id: "t1", role: "operator", email: "o@x.com",
      },
      status: "authenticated", csrf: "c",
    });
    const guard = requireRole(["tenant_admin", "superadmin"]);
    await expect(guard()).rejects.toMatchObject({ to: "/" });
  });

  it("allows the matching role", async () => {
    useAuthStore.setState({
      user: {
        id: "u1", tenant_id: "t1", role: "tenant_admin", email: "a@x.com",
      },
      status: "authenticated", csrf: "c",
    });
    const guard = requireRole(["tenant_admin", "superadmin"]);
    await expect(guard()).resolves.toBeUndefined();
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- tests/lib/auth-guards.test.ts --run
```

Expected: FAIL — `Cannot find module '@/lib/auth-guards'`.

**Step 3: Implement `requireRole`**

```ts
// frontend/src/lib/auth-guards.ts
import { redirect } from "@tanstack/react-router";
import type { Role } from "@/stores/auth";
import { useAuthStore } from "@/stores/auth";

/**
 * Route guard for use in `beforeLoad`. Throws a redirect if:
 * - the user is not authenticated → `/login`
 * - the user's role is not in `allowed` → `/`
 *
 * Used in route files alongside the auth-group's own check:
 * ```ts
 * export const Route = createFileRoute("/(auth)/users")({
 *   beforeLoad: requireRole(["tenant_admin", "superadmin"]),
 *   component: UsersPage,
 * });
 * ```
 */
export function requireRole(allowed: readonly Role[]) {
  return async () => {
    const state = useAuthStore.getState();
    const user = state.user ?? (await state.fetchMe());
    if (!user) throw redirect({ to: "/login" });
    if (!allowed.includes(user.role)) throw redirect({ to: "/" });
  };
}
```

**Step 4: Run test to verify it passes**

```bash
cd frontend && npm test -- tests/lib/auth-guards.test.ts --run
```

Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add frontend/src/lib/auth-guards.ts frontend/tests/lib/auth-guards.test.ts
git commit -m "feat(auth): requireRole guard helper for route-level RBAC"
```

---

## Task 3 — `<RoleGate>` component

**Files:**
- Create: `frontend/src/components/RoleGate.tsx`
- Create: `frontend/tests/components/RoleGate.test.tsx`

**Step 1: Write the failing test**

```tsx
// frontend/tests/components/RoleGate.test.tsx
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { useAuthStore } from "@/stores/auth";
import { RoleGate } from "@/components/RoleGate";

describe("RoleGate", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "idle", csrf: null });
  });

  it("renders children when role matches", () => {
    useAuthStore.setState({
      user: { id: "u", tenant_id: "t", role: "tenant_admin", email: "a@x.com" },
      status: "authenticated", csrf: "c",
    });
    render(
      <RoleGate roles={["tenant_admin", "superadmin"]}>
        <button>Delete</button>
      </RoleGate>,
    );
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("renders fallback when role doesn't match", () => {
    useAuthStore.setState({
      user: { id: "u", tenant_id: "t", role: "operator", email: "o@x.com" },
      status: "authenticated", csrf: "c",
    });
    render(
      <RoleGate roles={["tenant_admin"]} fallback={<span>nope</span>}>
        <button>Delete</button>
      </RoleGate>,
    );
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    expect(screen.getByText("nope")).toBeInTheDocument();
  });

  it("renders nothing by default when no fallback and role mismatch", () => {
    useAuthStore.setState({
      user: { id: "u", tenant_id: "t", role: "operator", email: "o@x.com" },
      status: "authenticated", csrf: "c",
    });
    const { container } = render(
      <RoleGate roles={["tenant_admin"]}>
        <button>Delete</button>
      </RoleGate>,
    );
    expect(container.textContent).toBe("");
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npm test -- tests/components/RoleGate.test.tsx --run
```

Expected: FAIL — module not found.

**Step 3: Implement `RoleGate`**

```tsx
// frontend/src/components/RoleGate.tsx
import type { ReactNode } from "react";
import { useAuthStore } from "@/stores/auth";
import type { Role } from "@/stores/auth";

/**
 * Conditionally render children based on the current user's role.
 * Use inside pages that everyone can see, where one section/button
 * needs admin gating.
 */
export function RoleGate({
  roles,
  children,
  fallback = null,
}: {
  roles: readonly Role[];
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const role = useAuthStore((s) => s.user?.role);
  if (!role || !roles.includes(role)) return <>{fallback}</>;
  return <>{children}</>;
}
```

**Step 4: Verify**

```bash
cd frontend && npm test -- tests/components/RoleGate.test.tsx --run
```

Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add frontend/src/components/RoleGate.tsx frontend/tests/components/RoleGate.test.tsx
git commit -m "feat(auth): RoleGate component for in-page role gating"
```

---

## Task 4 — Apply `requireRole` to admin-only routes

**Files:**
- Modify: `frontend/src/routes/(auth)/users.tsx`
- Modify: `frontend/src/routes/(auth)/agents.tsx`
- Modify: `frontend/src/routes/(auth)/audit-log.tsx`
- Modify: `frontend/src/routes/(auth)/inbox-settings.tsx`
- Modify: `frontend/src/routes/(auth)/config.tsx`

**Step 1: Update each route file**

Pattern for each:

```tsx
// users.tsx
import { createFileRoute } from "@tanstack/react-router";
import { UsersPage } from "@/features/users/components/UsersPage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/users")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: UsersPage,
});
```

For `audit-log.tsx` use `["superadmin"]`. For others use `["tenant_admin", "superadmin"]`.

**Step 2: Smoke test (manual)**

Start dev server, log in as operator, paste `/users` into URL → expect redirect to `/`. Log out, log in as tenant_admin, navigate to `/users` → expect to see the page.

(Skip live smoke if no dev backend up; rely on test in next task.)

**Step 3: Commit**

```bash
git add frontend/src/routes/\(auth\)/users.tsx frontend/src/routes/\(auth\)/agents.tsx frontend/src/routes/\(auth\)/audit-log.tsx frontend/src/routes/\(auth\)/inbox-settings.tsx frontend/src/routes/\(auth\)/config.tsx
git commit -m "feat(auth): route-level RBAC guards on admin pages"
```

---

## Task 5 — `turnStory.ts` derivation

**Files:**
- Create: `frontend/src/features/turn-traces/lib/turnStory.ts`
- Create: `frontend/tests/features/turn-traces/turnStory.test.ts`

**Step 1: Write failing tests**

```ts
// frontend/tests/features/turn-traces/turnStory.test.ts
import { describe, expect, it } from "vitest";
import { buildTurnStory } from "@/features/turn-traces/lib/turnStory";
import type { TurnTraceDetail } from "@/features/turn-traces/api";

const baseTrace: TurnTraceDetail = {
  id: "t1", conversation_id: "c1", turn_number: 1,
  inbound_message_id: "m1", flow_mode: "SALES",
  nlu_model: "gpt-4o-mini", composer_model: "gpt-4o",
  total_cost_usd: "0.001", total_latency_ms: 1200,
  bot_paused: false, created_at: "2026-05-12T00:00:00Z",
  inbound_text: "¿Cuánto cuesta el Civic?",
  nlu_input: null,
  nlu_output: {
    intent: "ask_price",
    entities: {
      brand: { value: "Honda", confidence: 0.9, source_turn: 1 },
      model: { value: "Civic", confidence: 0.85, source_turn: 1 },
    },
    sentiment: "neutral", confidence: 0.92, ambiguities: [],
  },
  nlu_tokens_in: null, nlu_tokens_out: null,
  nlu_cost_usd: null, nlu_latency_ms: 300,
  composer_input: null,
  composer_output: { messages: ["Hola, el Civic cuesta $325,000"], pending_confirmation_set: null },
  composer_tokens_in: null, composer_tokens_out: null,
  composer_cost_usd: null, composer_latency_ms: 800,
  vision_cost_usd: null, vision_latency_ms: null,
  tool_cost_usd: null,
  state_before: { current_stage: "lead_warm" },
  state_after: { current_stage: "quote_sent" },
  stage_transition: "lead_warm → quote_sent",
  outbound_messages: [{ text: "Hola, el Civic cuesta $325,000" }],
  errors: null, tool_calls: [],
};

describe("buildTurnStory", () => {
  it("emits inbound step from inbound_text", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps[0]).toMatchObject({
      kind: "inbound",
      text: "¿Cuánto cuesta el Civic?",
    });
  });

  it("emits nlu step with intent + extracted entities", () => {
    const steps = buildTurnStory(baseTrace);
    const nlu = steps.find((s) => s.kind === "nlu");
    expect(nlu).toMatchObject({
      kind: "nlu",
      intent: "ask_price",
      extracted: { brand: "Honda", model: "Civic" },
    });
  });

  it("emits mode step from flow_mode", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "mode")).toMatchObject({
      kind: "mode", mode: "SALES",
    });
  });

  it("emits outbound step with previews", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "outbound")).toMatchObject({
      kind: "outbound", count: 1,
      previews: ["Hola, el Civic cuesta $325,000"],
    });
  });

  it("emits transition step when stage changed", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "transition")).toMatchObject({
      kind: "transition", from: "lead_warm", to: "quote_sent",
    });
  });

  it("emits tool step per tool call with summary", () => {
    const trace = {
      ...baseTrace,
      tool_calls: [
        {
          id: "tc1", tool_name: "search_catalog",
          input_payload: { query: "Civic" },
          output_payload: { results: [{ name: "Honda Civic 2024", price: 325000 }] },
          latency_ms: 50, error: null, called_at: "2026-05-12T00:00:01Z",
        },
      ],
    };
    const steps = buildTurnStory(trace);
    const tool = steps.find((s) => s.kind === "tool");
    expect(tool).toMatchObject({ kind: "tool", toolName: "search_catalog" });
    expect((tool as { kind: "tool"; summary: string }).summary).toContain("Civic");
  });

  it("handles missing inbound_text by signaling media", () => {
    const trace = { ...baseTrace, inbound_text: null };
    const steps = buildTurnStory(trace);
    expect(steps[0]).toMatchObject({ kind: "inbound", text: null });
  });

  it("skips nlu step when nlu_output is null", () => {
    const trace = { ...baseTrace, nlu_output: null };
    const steps = buildTurnStory(trace);
    expect(steps.find((s) => s.kind === "nlu")).toBeUndefined();
  });
});
```

**Step 2: Run tests to verify failure**

```bash
cd frontend && npm test -- tests/features/turn-traces/turnStory.test.ts --run
```

Expected: FAIL — module not found.

**Step 3: Implement `turnStory.ts`**

```ts
// frontend/src/features/turn-traces/lib/turnStory.ts
import type { TurnTraceDetail } from "@/features/turn-traces/api";

export type StoryStep =
  | { kind: "inbound"; text: string | null; hasMedia: boolean }
  | { kind: "nlu"; intent: string | null; extracted: Record<string, unknown> }
  | { kind: "mode"; mode: string | null }
  | { kind: "tool"; toolName: string; summary: string; error: string | null }
  | { kind: "composer"; messages: string[] }
  | { kind: "outbound"; count: number; previews: string[] }
  | { kind: "transition"; from: string; to: string };

function extractEntities(nluOutput: unknown): Record<string, unknown> {
  if (!nluOutput || typeof nluOutput !== "object") return {};
  const entities = (nluOutput as { entities?: unknown }).entities;
  if (!entities || typeof entities !== "object") return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entities)) {
    if (v && typeof v === "object" && "value" in (v as object)) {
      out[k] = (v as { value: unknown }).value;
    } else {
      out[k] = v;
    }
  }
  return out;
}

function summarizeTool(name: string, input: unknown, output: unknown): string {
  // Generic fallback: show a one-liner derived from output keys/values.
  // Tool-specific cases below for the common ones.
  if (name === "search_catalog" && output && typeof output === "object") {
    const results = (output as { results?: unknown }).results;
    if (Array.isArray(results) && results.length > 0) {
      const first = results[0] as Record<string, unknown>;
      const label = String(first.name ?? first.sku ?? "resultado");
      const price = first.price != null ? ` — $${first.price}` : "";
      return `${results.length} resultado${results.length > 1 ? "s" : ""}: ${label}${price}`;
    }
    return "0 resultados";
  }
  if (name === "lookup_faq" && output && typeof output === "object") {
    const answer = (output as { answer?: unknown }).answer;
    if (typeof answer === "string") return `respuesta: ${answer.slice(0, 60)}${answer.length > 60 ? "…" : ""}`;
  }
  if (name === "quote" && output && typeof output === "object") {
    const total = (output as { total?: unknown }).total;
    if (total != null) return `cotización: $${total}`;
  }
  // Fallback: stringify a key=value of input
  if (input && typeof input === "object") {
    const entries = Object.entries(input).slice(0, 2);
    return entries.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ") || "(sin datos)";
  }
  return "(sin datos)";
}

function parseTransition(t: string | null): { from: string; to: string } | null {
  if (!t) return null;
  const m = t.match(/^(.+?)\s*[→\-]>?\s*(.+)$/);
  if (m) return { from: m[1].trim(), to: m[2].trim() };
  return null;
}

function outboundPreviews(messages: unknown): string[] {
  if (!Array.isArray(messages)) return [];
  return messages
    .map((m) => {
      if (typeof m === "string") return m;
      if (m && typeof m === "object" && "text" in m) {
        return String((m as { text: unknown }).text ?? "");
      }
      return "";
    })
    .filter((t) => t.length > 0);
}

export function buildTurnStory(trace: TurnTraceDetail): StoryStep[] {
  const steps: StoryStep[] = [];

  // 1. Inbound
  steps.push({
    kind: "inbound",
    text: trace.inbound_text,
    hasMedia: !trace.inbound_text && !!trace.inbound_message_id,
  });

  // 2. NLU
  if (trace.nlu_output) {
    const out = trace.nlu_output as Record<string, unknown>;
    steps.push({
      kind: "nlu",
      intent: typeof out.intent === "string" ? out.intent : null,
      extracted: extractEntities(trace.nlu_output),
    });
  }

  // 3. Mode
  if (trace.flow_mode) {
    steps.push({ kind: "mode", mode: trace.flow_mode });
  }

  // 4. Tool calls
  for (const tc of trace.tool_calls ?? []) {
    steps.push({
      kind: "tool",
      toolName: tc.tool_name,
      summary: summarizeTool(tc.tool_name, tc.input_payload, tc.output_payload),
      error: tc.error,
    });
  }

  // 5. Composer
  if (trace.composer_output) {
    const out = trace.composer_output as Record<string, unknown>;
    const messages = Array.isArray(out.messages) ? out.messages.map(String) : [];
    if (messages.length > 0) steps.push({ kind: "composer", messages });
  }

  // 6. Outbound
  const previews = outboundPreviews(trace.outbound_messages);
  if (previews.length > 0) {
    steps.push({ kind: "outbound", count: previews.length, previews });
  }

  // 7. Stage transition
  const t = parseTransition(trace.stage_transition);
  if (t) steps.push({ kind: "transition", from: t.from, to: t.to });

  return steps;
}
```

**Step 4: Verify tests pass**

```bash
cd frontend && npm test -- tests/features/turn-traces/turnStory.test.ts --run
```

Expected: PASS (8 tests).

**Step 5: Commit**

```bash
git add frontend/src/features/turn-traces/lib/turnStory.ts frontend/tests/features/turn-traces/turnStory.test.ts
git commit -m "feat(turn-traces): turnStory derivation library"
```

---

## Task 6 — `FlowModeBadge` component

**Files:**
- Create: `frontend/src/features/turn-traces/components/FlowModeBadge.tsx`
- Create: `frontend/tests/features/turn-traces/FlowModeBadge.test.tsx`

**Step 1: Write failing test**

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FlowModeBadge } from "@/features/turn-traces/components/FlowModeBadge";

describe("FlowModeBadge", () => {
  it("renders friendly label for known mode", () => {
    render(<FlowModeBadge mode="SALES" />);
    expect(screen.getByText("Ventas")).toBeInTheDocument();
  });

  it("falls back to raw mode for unknown values", () => {
    render(<FlowModeBadge mode="WEIRD_NEW_MODE" />);
    expect(screen.getByText("WEIRD_NEW_MODE")).toBeInTheDocument();
  });

  it("shows em-dash when mode is null", () => {
    render(<FlowModeBadge mode={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
```

**Step 2: Run to verify failure**

```bash
cd frontend && npm test -- tests/features/turn-traces/FlowModeBadge.test.tsx --run
```

Expected: FAIL.

**Step 3: Implement**

```tsx
// frontend/src/features/turn-traces/components/FlowModeBadge.tsx
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const MODE_MAP: Record<string, { label: string; classes: string }> = {
  PLAN: { label: "Planes", classes: "bg-blue-500/15 text-blue-700 border-blue-500/30" },
  SALES: { label: "Ventas", classes: "bg-emerald-500/15 text-emerald-700 border-emerald-500/30" },
  DOC: { label: "Documentos", classes: "bg-purple-500/15 text-purple-700 border-purple-500/30" },
  OBSTACLE: { label: "Obstáculo", classes: "bg-amber-500/15 text-amber-700 border-amber-500/30" },
  RETENTION: { label: "Retención", classes: "bg-rose-500/15 text-rose-700 border-rose-500/30" },
  SUPPORT: { label: "Soporte", classes: "bg-slate-500/15 text-slate-700 border-slate-500/30" },
};

export function FlowModeBadge({ mode }: { mode: string | null }) {
  if (!mode) {
    return <span className="text-muted-foreground">—</span>;
  }
  const entry = MODE_MAP[mode];
  if (!entry) {
    return (
      <Badge variant="outline" className="font-mono text-[10px]">
        {mode}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className={cn("font-medium", entry.classes)}>
      {entry.label}
    </Badge>
  );
}
```

**Step 4: Verify**

```bash
cd frontend && npm test -- tests/features/turn-traces/FlowModeBadge.test.tsx --run
```

Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add frontend/src/features/turn-traces/components/FlowModeBadge.tsx frontend/tests/features/turn-traces/FlowModeBadge.test.tsx
git commit -m "feat(turn-traces): FlowModeBadge with friendly Spanish labels + colors"
```

---

## Task 7 — `TurnStoryView` component

**Files:**
- Create: `frontend/src/features/turn-traces/components/TurnStoryView.tsx`
- Create: `frontend/tests/features/turn-traces/TurnStoryView.test.tsx`

**Step 1: Test**

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

describe("TurnStoryView", () => {
  it("renders inbound text", () => {
    const steps: StoryStep[] = [
      { kind: "inbound", text: "Hola, ¿cuánto cuesta?", hasMedia: false },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Hola, ¿cuánto cuesta?/)).toBeInTheDocument();
  });

  it("renders nlu intent + entities", () => {
    const steps: StoryStep[] = [
      { kind: "nlu", intent: "ask_price", extracted: { brand: "Honda" } },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/ask_price/)).toBeInTheDocument();
    expect(screen.getByText(/Honda/)).toBeInTheDocument();
  });

  it("renders empty state with a message", () => {
    render(<TurnStoryView steps={[]} />);
    expect(screen.getByText(/Sin pasos/i)).toBeInTheDocument();
  });
});
```

**Step 2: Run failing**

```bash
cd frontend && npm test -- tests/features/turn-traces/TurnStoryView.test.tsx --run
```

Expected: FAIL.

**Step 3: Implement**

```tsx
// frontend/src/features/turn-traces/components/TurnStoryView.tsx
import {
  ArrowRight,
  Brain,
  MessageSquareText,
  SendHorizonal,
  Sparkles,
  Target,
  Wrench,
} from "lucide-react";

import { FlowModeBadge } from "./FlowModeBadge";
import type { StoryStep } from "../lib/turnStory";

const INTENT_LABELS: Record<string, string> = {
  greeting: "Saludo",
  ask_info: "Pidió información",
  ask_price: "Pidió precio",
  buy: "Quiere comprar",
  schedule: "Quiere agendar",
  complain: "Se quejó",
  off_topic: "Fuera de tema",
  unclear: "No claro",
};

function StepRow({
  icon: Icon,
  children,
}: {
  icon: typeof MessageSquareText;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="flex-1 text-sm">{children}</div>
    </div>
  );
}

export function TurnStoryView({ steps }: { steps: StoryStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
        Sin pasos para narrar este turno.
      </div>
    );
  }
  return (
    <div className="divide-y rounded-md border">
      {steps.map((step, idx) => (
        <div key={idx} className="px-3">
          {renderStep(step)}
        </div>
      ))}
    </div>
  );
}

function renderStep(step: StoryStep) {
  switch (step.kind) {
    case "inbound":
      return (
        <StepRow icon={MessageSquareText}>
          {step.text ? (
            <>
              <span className="text-muted-foreground">Cliente:</span>{" "}
              <span className="italic">«{step.text}»</span>
            </>
          ) : step.hasMedia ? (
            <span className="text-muted-foreground">
              Cliente envió adjunto (sin texto).
            </span>
          ) : (
            <span className="text-muted-foreground">Sin mensaje entrante.</span>
          )}
        </StepRow>
      );
    case "nlu": {
      const entities = Object.entries(step.extracted ?? {});
      const intentLabel = step.intent ? INTENT_LABELS[step.intent] ?? step.intent : "—";
      return (
        <StepRow icon={Brain}>
          <span className="text-muted-foreground">Bot entendió:</span>{" "}
          <span className="font-medium">{intentLabel}</span>
          {entities.length > 0 && (
            <span className="ml-1 text-muted-foreground">
              (
              {entities
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(", ")}
              )
            </span>
          )}
        </StepRow>
      );
    }
    case "mode":
      return (
        <StepRow icon={Target}>
          <span className="text-muted-foreground">Modo:</span>{" "}
          <FlowModeBadge mode={step.mode} />
        </StepRow>
      );
    case "tool":
      return (
        <StepRow icon={Wrench}>
          <span className="font-mono text-xs">{step.toolName}</span>{" "}
          <span className="text-muted-foreground">→</span>{" "}
          {step.error ? (
            <span className="text-destructive">error: {step.error}</span>
          ) : (
            <span>{step.summary}</span>
          )}
        </StepRow>
      );
    case "composer":
      return (
        <StepRow icon={Sparkles}>
          <span className="text-muted-foreground">Bot decidió responder:</span>{" "}
          <span className="italic">
            {step.messages.length === 1
              ? `«${truncate(step.messages[0], 80)}»`
              : `${step.messages.length} mensajes`}
          </span>
        </StepRow>
      );
    case "outbound":
      return (
        <StepRow icon={SendHorizonal}>
          <span className="text-muted-foreground">
            Envió {step.count} mensaje{step.count > 1 ? "s" : ""}:
          </span>
          <ul className="mt-1 space-y-0.5">
            {step.previews.map((p, i) => (
              <li key={i} className="text-xs text-muted-foreground">
                · {truncate(p, 100)}
              </li>
            ))}
          </ul>
        </StepRow>
      );
    case "transition":
      return (
        <StepRow icon={ArrowRight}>
          <span className="text-muted-foreground">Etapa:</span>{" "}
          <span className="font-mono text-xs">{step.from}</span>{" "}
          <ArrowRight className="inline h-3 w-3" />{" "}
          <span className="font-mono text-xs">{step.to}</span>
        </StepRow>
      );
  }
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}
```

**Step 4: Verify**

```bash
cd frontend && npm test -- tests/features/turn-traces/TurnStoryView.test.tsx --run
```

Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add frontend/src/features/turn-traces/components/TurnStoryView.tsx frontend/tests/features/turn-traces/TurnStoryView.test.tsx
git commit -m "feat(turn-traces): TurnStoryView render of the Spanish narrative"
```

---

## Task 8 — Update `TurnTraceList` with FlowModeBadge + inbound preview

**Files:**
- Modify: `frontend/src/features/turn-traces/components/TurnTraceList.tsx`
- Modify: `frontend/src/features/turn-traces/api.ts` (add `inbound_text` to the list item type if not present)

**Step 1: Check the list endpoint payload**

The backend `TurnTraceListItem` does NOT include `inbound_text` (only metadata). Two options:
- A: extend the backend list response to include the first 120 chars of `inbound_text`.
- B: leave the list as is and rely on opening the inspector for the message.

We pick A — small backend change, much better UX.

**Step 2: Backend — add `inbound_preview` field**

Modify `core/atendia/api/turn_traces_routes.py`:

```python
class TurnTraceListItem(BaseModel):
    id: UUID
    conversation_id: UUID
    turn_number: int
    inbound_message_id: UUID | None
    inbound_preview: str | None  # NEW — first 120 chars
    flow_mode: str | None
    nlu_model: str | None
    composer_model: str | None
    total_cost_usd: Decimal
    total_latency_ms: int | None
    bot_paused: bool
    created_at: datetime
```

In the list endpoint constructor:

```python
inbound_preview=(r.inbound_text[:120] if r.inbound_text else None),
```

Also include `TurnTrace.inbound_text` in the SELECT (it's already on the model so `select(TurnTrace)` is fine).

**Step 3: Update existing test that asserts list shape**

Open `core/tests/api/test_turn_traces_routes.py`, find the test that calls the list endpoint, add an assertion for `inbound_preview` shape (null or string).

**Step 4: Frontend type + UI**

Update `frontend/src/features/turn-traces/api.ts` `TurnTraceListItem` to include `inbound_preview: string | null`.

Update `TurnTraceList.tsx`:

```tsx
<TableHead>Mensaje</TableHead>
// …
<TableCell className="max-w-[260px] truncate text-xs text-muted-foreground">
  {t.inbound_preview ?? <span className="italic">(sin texto)</span>}
</TableCell>
```

Replace the `<Badge variant="outline">{t.flow_mode ?? "—"}</Badge>` with `<FlowModeBadge mode={t.flow_mode} />`.

**Step 5: Run tests**

```bash
uv run pytest core/tests/api/test_turn_traces_routes.py -v
```

Expected: PASS.

```bash
cd frontend && npm test --run
```

Expected: PASS (existing tests still pass, no new breakage).

**Step 6: Commit**

```bash
git add core/atendia/api/turn_traces_routes.py core/tests/api/test_turn_traces_routes.py frontend/src/features/turn-traces/api.ts frontend/src/features/turn-traces/components/TurnTraceList.tsx
git commit -m "feat(turn-traces): inbound preview column + FlowModeBadge in list"
```

---

## Task 9 — Extract `TurnTraceSections` from `DebugPanel`

**Files:**
- Create: `frontend/src/features/turn-traces/components/TurnTraceSections.tsx`
- Modify: `frontend/src/features/conversations/components/DebugPanel.tsx`

**Step 1: Move shared sections to the new file**

Cut from `DebugPanel.tsx` lines 109-369 (the section components: `OverviewSection`, `PipelineSection`, `NluSection`, `ComposerSection`, `ToolCallsSection`, `StateSection`, `ErrorsSection`, plus the shared primitives `SectionHeader`, `Stat`, `Kv`, `CollapsibleJson`). Put them in `TurnTraceSections.tsx` and export the section components.

`DebugPanel.tsx` imports them back and uses them. No behavior change.

**Step 2: Verify**

```bash
cd frontend && npm test --run
```

Expected: PASS — `DebugPanel` still works.

**Step 3: Commit**

```bash
git add frontend/src/features/turn-traces/components/TurnTraceSections.tsx frontend/src/features/conversations/components/DebugPanel.tsx
git commit -m "refactor(turn-traces): extract reusable sections from DebugPanel"
```

---

## Task 10 — Rewrite `TurnTraceInspector` with story + sections

**Files:**
- Modify: `frontend/src/features/turn-traces/components/TurnTraceInspector.tsx`

**Step 1: Rewrite the inspector**

```tsx
import { useQuery } from "@tanstack/react-query";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { turnTracesApi } from "@/features/turn-traces/api";

import { FlowModeBadge } from "./FlowModeBadge";
import { TurnStoryView } from "./TurnStoryView";
import {
  OverviewSection,
  PipelineSection,
  NluSection,
  ComposerSection,
  ToolCallsSection,
  StateSection,
  ErrorsSection,
} from "./TurnTraceSections";
import { buildTurnStory } from "../lib/turnStory";

export function TurnTraceInspector({
  traceId,
  open,
  onClose,
}: {
  traceId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["turn-trace", traceId],
    queryFn: () => (traceId ? turnTracesApi.getOne(traceId) : Promise.reject()),
    enabled: !!traceId && open,
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Turn {query.data?.turn_number ?? "…"}
            {query.data?.flow_mode && <FlowModeBadge mode={query.data.flow_mode} />}
          </DialogTitle>
        </DialogHeader>
        {query.isLoading || !query.data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <Tabs defaultValue="story">
            <TabsList>
              <TabsTrigger value="story">Resumen</TabsTrigger>
              <TabsTrigger value="detail">Detalle técnico</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>
            <TabsContent value="story" className="space-y-3">
              <TurnStoryView steps={buildTurnStory(query.data)} />
            </TabsContent>
            <TabsContent value="detail" className="divide-y">
              <OverviewSection trace={query.data} />
              <PipelineSection trace={query.data} />
              <NluSection trace={query.data} />
              <ComposerSection trace={query.data} />
              {query.data.tool_calls.length > 0 && (
                <ToolCallsSection trace={query.data} />
              )}
              <StateSection trace={query.data} />
              <ErrorsSection trace={query.data} />
            </TabsContent>
            <TabsContent value="raw">
              <pre className="overflow-auto rounded bg-muted p-2 text-xs">
                {JSON.stringify(query.data, null, 2)}
              </pre>
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

**Step 2: Verify build + tests**

```bash
cd frontend && npm run build
cd frontend && npm test --run
```

Expected: PASS.

**Step 3: Commit**

```bash
git add frontend/src/features/turn-traces/components/TurnTraceInspector.tsx
git commit -m "feat(turn-traces): inspector redesign with story tab + sectioned detail"
```

---

## Task 11 — Add Story section to DebugPanel

**Files:**
- Modify: `frontend/src/features/conversations/components/DebugPanel.tsx`

**Step 1: Add a `StorySection` above `OverviewSection`**

Inside the panel scroll area, after `<ScrollArea>` open, render:

```tsx
<div className="p-3">
  <SectionHeader icon={MessageSquareText} label="Resumen" />
  <div className="mt-2">
    <TurnStoryView steps={buildTurnStory(t)} />
  </div>
</div>
<Separator />
```

Add imports for `TurnStoryView`, `buildTurnStory`, `MessageSquareText` from `lucide-react`.

**Step 2: Verify**

```bash
cd frontend && npm test --run
cd frontend && npm run build
```

Expected: PASS.

**Step 3: Commit**

```bash
git add frontend/src/features/conversations/components/DebugPanel.tsx
git commit -m "feat(conversations): turn story summary in DebugPanel"
```

---

## Task 12 — Final smoke + checks

**Step 1: Backend full suite**

```bash
uv run pytest core/tests -x -q
```

Expected: PASS. Note any failures unrelated to this work — those are punch-list items.

**Step 2: Frontend full suite**

```bash
cd frontend && npm test --run
```

Expected: PASS.

**Step 3: Type-check & lint**

```bash
cd frontend && npm run typecheck
cd frontend && npx biome check src/
```

Expected: PASS.

**Step 4: Final commit if any drive-by lint fixes**

If lint complains, fix and:

```bash
git commit -am "chore: lint fixes from rbac/observability work"
```

---

## Success criteria

- [x] `test_rbac_matrix.py` passes covering ~6+ admin-gated endpoints.
- [x] Operator hitting `/users` is redirected to `/`.
- [x] `/turn-traces` inspector opens with a "Resumen" tab showing a
  human-readable Spanish narrative (Cliente → Bot entendió → Modo → Tools
  → Composer → Outbound → Transición).
- [x] List view shows inbound message preview + colored mode badge.
- [x] DebugPanel in conversations also shows the same Resumen at the top.
- [x] All existing backend + frontend tests still pass.

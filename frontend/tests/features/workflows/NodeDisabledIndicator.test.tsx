/**
 * W15 — Node-disabled visual indicator.
 *
 * Workflow nodes can be toggled enabled/disabled (WorkflowEditor's context
 * menu writes `node.enabled` via patchNode). The canvas already dimmed a
 * disabled node (`opacity-50`) but gave no explicit cue, so operators could
 * not tell at a glance which steps were off.
 *
 * `node.enabled` is an optional boolean: absent/`true` = enabled, only
 * `=== false` = disabled. The indicator must reflect that exact field — no
 * new state.
 *
 * The test renders WorkflowEditor (same wiring as the W6/W8 form tests:
 * `renderPage` + MSW stubbing the sibling-list queries) with a definition
 * holding one disabled and one enabled node, and asserts the "Desactivado"
 * indicator appears for the disabled node only.
 */
import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { WorkflowItem } from "@/features/workflows/api";
import { WorkflowEditor } from "@/features/workflows/components/WorkflowEditor";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/workflows", () => HttpResponse.json([])),
  http.get("/api/v1/pipeline/stages", () => HttpResponse.json([])),
  http.get("/api/v1/agents", () => HttpResponse.json([])),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

function buildWorkflow(
  overrides: Partial<WorkflowItem> & Pick<WorkflowItem, "id" | "name">,
): WorkflowItem {
  const { id, name, ...rest } = overrides;
  return {
    id,
    tenant_id: "t-1",
    name,
    description: null,
    trigger_type: "message_received",
    trigger_config: {},
    definition: { nodes: [], edges: [] },
    active: false,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    status: "draft",
    health: { score: 100, status: "healthy", reasons: [], suggested_actions: [] },
    metrics: {
      executions_today: 0,
      success_rate: 0,
      failure_rate: 0,
      avg_duration_seconds: 0,
      dropoff_rate: 0,
      leads_affected_today: 0,
      failed_handoffs: 0,
      documents_blocked: 0,
      missed_followups: 0,
      appointments_not_confirmed: 0,
      blocked_opportunity_mxn: 0,
      critical_failures_24h: 0,
      ai_low_confidence_events: 0,
      last_run_minutes_ago: 0,
      sparkline: [],
    },
    published_version: 0,
    draft_version: 1,
    last_editor: null,
    last_published_at: null,
    validation: {
      status: "ready",
      summary: "",
      critical_count: 0,
      warning_count: 0,
      ok_count: 0,
      issues: [],
      checks: [],
    },
    variables: [],
    dependencies: [],
    safety_rules: {},
    version_history: [],
    webhook_url: null,
    ...rest,
  };
}

function workflowWithDisabledNode(): WorkflowItem {
  return buildWorkflow({
    id: "wf-1",
    name: "Workflow con nodo desactivado",
    definition: {
      nodes: [
        {
          id: "n-on",
          type: "message",
          title: "Saludo inicial",
          config: { text: "Hola" },
        },
        {
          id: "n-off",
          type: "message",
          title: "Paso apagado",
          enabled: false,
          config: { text: "No corre" },
        },
      ],
      edges: [{ from: "n-on", to: "n-off" }],
    },
  });
}

describe("node disabled visual indicator", () => {
  it("shows a 'Desactivado' indicator on a disabled node", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithDisabledNode()} onRunSimulation={() => {}} />);

    const disabledCard = await screen.findByRole("button", { name: /Paso apagado/i });
    expect(within(disabledCard).getByText(/desactivado/i)).toBeInTheDocument();
  });

  it("does NOT show the indicator on an enabled node", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithDisabledNode()} onRunSimulation={() => {}} />);

    const enabledCard = await screen.findByRole("button", { name: /Saludo inicial/i });
    expect(within(enabledCard).queryByText(/desactivado/i)).not.toBeInTheDocument();
  });
});

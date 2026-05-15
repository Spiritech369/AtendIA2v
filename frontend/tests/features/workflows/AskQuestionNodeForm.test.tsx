/**
 * W8 Task 7 — ask_question node config form.
 *
 * The form is inline in WorkflowEditor (mirrors trigger_workflow form from
 * Task 6). Renders the editor with a workflow whose draft contains an
 * `ask_question` node as the first (auto-selected) node, then asserts:
 *   1. the three form fields render (textarea / variable input / type
 *      select).
 *   2. the MVP helper text spells out the text-only validation scope.
 *   3. non-text type options (email/number/phone/boolean) are disabled —
 *      MVP supports only `text`; the rest carry a "disponible en una
 *      versión futura" hint.
 */
import { screen } from "@testing-library/react";
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

function workflowWithAskNode(): WorkflowItem {
  return buildWorkflow({
    id: "wf-ask",
    name: "Captura datos del lead",
    definition: {
      nodes: [
        {
          id: "n-ask",
          type: "ask_question",
          title: "Preguntar al cliente",
          config: { question: "", variable: "", type: "text" },
        },
      ],
      edges: [],
    },
  });
}

describe("ask_question node config form", () => {
  it("renders the question textarea, variable input, and type select", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithAskNode()} onRunSimulation={() => {}} />);

    expect(await screen.findByLabelText(/pregunta al cliente/i)).toBeInTheDocument();
    expect(await screen.findByLabelText(/^variable/i)).toBeInTheDocument();
    expect(await screen.findByLabelText(/tipo/i)).toBeInTheDocument();
  });

  it("shows the MVP helper text about text-only validation", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithAskNode()} onRunSimulation={() => {}} />);

    expect(
      await screen.findByText(/pausa esperando|texto.*validado|disponible en una versión futura/i),
    ).toBeInTheDocument();
  });

  it("disables non-text type options", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithAskNode()} onRunSimulation={() => {}} />);

    const typeSelect = await screen.findByLabelText(/tipo/i);
    const options = typeSelect.querySelectorAll("option");
    const nonTextOptions = Array.from(options).filter((o) => o.value !== "text");
    expect(nonTextOptions.length).toBeGreaterThan(0);
    for (const opt of nonTextOptions) {
      expect((opt as HTMLOptionElement).disabled).toBe(true);
    }
  });
});

/**
 * W6 Task 6 — trigger_workflow node config form.
 *
 * The form is inline in WorkflowEditor (matches the pattern used by
 * delay/move_stage/http_request/etc.). The test renders the editor with
 * a workflow whose draft contains a `trigger_workflow` node selected,
 * stubs `/api/v1/workflows` so the editor's sibling list query resolves,
 * and asserts:
 *   1. the dropdown appears with workflows fetched from the API
 *   2. the current workflow is filtered out (no self-trigger at edit
 *      time; backend recursion guard handles deeper cycles).
 *   3. the helper text spells out the MVP scope (parent context not
 *      passed to child).
 */
import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { WorkflowItem } from "@/features/workflows/api";
import { WorkflowEditor } from "@/features/workflows/components/WorkflowEditor";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const CURRENT_WORKFLOW_ID = "wf-self";

const PEER_WORKFLOWS: WorkflowItem[] = [
  buildWorkflow({ id: CURRENT_WORKFLOW_ID, name: "Este workflow" }),
  buildWorkflow({ id: "wf-recordatorios", name: "Recordatorios" }),
  buildWorkflow({ id: "wf-bienvenida", name: "Bienvenida" }),
];

const server = setupServer(
  http.get("/api/v1/workflows", () => HttpResponse.json(PEER_WORKFLOWS)),
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

function workflowWithTriggerNode(): WorkflowItem {
  return buildWorkflow({
    id: CURRENT_WORKFLOW_ID,
    name: "Este workflow",
    definition: {
      nodes: [
        {
          id: "n-trigger",
          type: "trigger_workflow",
          title: "Disparar otro workflow",
          config: { target_workflow_id: null },
        },
      ],
      edges: [],
    },
  });
}

describe("trigger_workflow node config form", () => {
  it("renders a dropdown populated from the workflows API", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithTriggerNode()} onRunSimulation={() => {}} />);

    // The peer workflows show up as <option> children in the dropdown.
    expect(await screen.findByRole("option", { name: /Recordatorios/ })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: /Bienvenida/ })).toBeInTheDocument();
  });

  it("excludes the current workflow from the dropdown (no self-trigger)", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithTriggerNode()} onRunSimulation={() => {}} />);

    // Wait for the list to render then assert the self entry is filtered.
    await screen.findByRole("option", { name: /Recordatorios/ });
    expect(screen.queryByRole("option", { name: /Este workflow/ })).not.toBeInTheDocument();
  });

  it("shows the MVP helper text about parent context not being passed", async () => {
    renderPage(<WorkflowEditor workflow={workflowWithTriggerNode()} onRunSimulation={() => {}} />);

    // Helper text below the dropdown explains the MVP constraint.
    expect(
      await screen.findByText(/El workflow hijo arranca con su propio contexto/i),
    ).toBeInTheDocument();
  });
});

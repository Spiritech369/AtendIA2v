/**
 * P6 — dependency view inside the stage editor.
 *
 * The /tenants/pipeline/impacted-references/:stage_id endpoint already
 * existed (it powers the stage-delete impact dialog). P6 surfaces the
 * SAME data inside the stage editor so an operator sees how many
 * conversations sit in the stage and which workflows reference it
 * BEFORE changing behavior_mode / rules — not only when deleting.
 *
 * StageDependencyView is the extracted read-only section. It reuses
 * tenantsApi.getStageImpact (no API-client duplication) and a useQuery
 * keyed on the stage id. These tests mock the real endpoint shape
 * (stage_id / conversation_count / workflow_references[]).
 */
import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { StageDependencyView } from "@/features/pipeline/components/StageDependencyView";
import { withQueryClient } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/tenants/pipeline/impacted-references/:stageId", ({ params }) =>
    HttpResponse.json({
      stage_id: params.stageId,
      conversation_count: 12,
      workflow_references: [
        {
          workflow_id: "11111111-1111-1111-1111-111111111111",
          name: "Reactivación 7d",
          active: true,
          reference_kind: "trigger",
          detail: "trigger_config.to",
        },
        {
          workflow_id: "22222222-2222-2222-2222-222222222222",
          name: "Mover a cierre",
          active: false,
          reference_kind: "move_stage_node",
          detail: "node_id=action_3",
        },
      ],
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("stage editor dependency view", () => {
  it("shows conversation + workflow dependency counts for the stage", async () => {
    render(withQueryClient(<StageDependencyView stageId="negociacion" />));

    // Wait for the query to resolve, then read the section as a whole.
    // The copy intentionally splits the count into a <span> and uses a
    // singular/plural ternary, so `getByText` on a single node can't
    // match the full phrase — assert on the section's textContent.
    expect(await screen.findByText("Reactivación 7d")).toBeInTheDocument();

    const section = document.querySelector('[data-field="stage-dependencies"]') as HTMLElement;
    expect(section).not.toBeNull();
    const text = section.textContent ?? "";

    // Conversation count surfaced.
    expect(text).toMatch(/12/);
    expect(text).toMatch(/conversaci[oó]n/i);

    // Workflow refs surfaced (count + names).
    expect(text).toMatch(/workflow/i);
    expect(screen.getByText("Mover a cierre")).toBeInTheDocument();
  });

  it("shows an empty state when the stage has no dependencies", async () => {
    server.use(
      http.get("/api/v1/tenants/pipeline/impacted-references/:stageId", ({ params }) =>
        HttpResponse.json({
          stage_id: params.stageId,
          conversation_count: 0,
          workflow_references: [],
        }),
      ),
    );

    render(withQueryClient(<StageDependencyView stageId="negociacion" />));

    expect(await screen.findByText(/sin dependencias/i)).toBeInTheDocument();
  });
});

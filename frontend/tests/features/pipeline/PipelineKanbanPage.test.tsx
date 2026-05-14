/**
 * Sprint B.1 — PipelineKanbanPage smoke test. Mocks /api/v1/* to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { PipelineKanbanPage } from "@/features/pipeline/components/PipelineKanbanPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/tenants/pipeline", () =>
    HttpResponse.json({ version: 1, stages: [], fallback: "escalate_to_human" }),
  ),
  http.get("/api/v1/conversations", () => HttpResponse.json({ items: [], total: 0 })),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("PipelineKanbanPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<PipelineKanbanPage />);
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

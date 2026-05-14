/**
 * Sprint B.1 — KnowledgeBasePage smoke test. Mocks /api/v1/knowledge/* to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { KnowledgeBasePage } from "@/features/knowledge/components/KnowledgeBasePage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/knowledge/items", () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.get("/api/v1/knowledge/health", () =>
    HttpResponse.json({
      overall_score: 0,
      label: "Sin contenido",
      status: "warning",
      change_vs_yesterday: 0,
      metrics: [],
      updated_at: "2026-05-14T00:00:00Z",
    }),
  ),
  http.get("/api/v1/knowledge/*", () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("KnowledgeBasePage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<KnowledgeBasePage />);
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

/**
 * Sprint B.1 — AgentsPage smoke test. Mocks /api/v1/* to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AgentsPage } from "@/features/agents/components/AgentsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/agents", () => HttpResponse.json({ items: [], total: 0 })),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("AgentsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<AgentsPage />);
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

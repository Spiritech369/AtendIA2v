/**
 * Sprint B.1 — ClientsPage smoke test.
 *
 * Mocks /api/v1/customers + a few related endpoints and proves the page
 * mounts without throwing. Pattern matches DashboardPage.test.tsx.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import { ClientsPage } from "@/features/customers/components/ClientsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/customers", () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.get("/api/v1/customers/field-definitions", () =>
    HttpResponse.json({ items: [] }),
  ),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("ClientsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<ClientsPage />);
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

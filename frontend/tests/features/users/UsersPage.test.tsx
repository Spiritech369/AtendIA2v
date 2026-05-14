/**
 * Sprint B.1 — UsersPage smoke test. Mocks /api/v1/* to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { UsersPage } from "@/features/users/components/UsersPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/users", () => HttpResponse.json({ items: [], total: 0 })),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("UsersPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    // tenant_admin role required for the page guard
    const { container } = renderPage(<UsersPage />, {
      auth: { role: "tenant_admin" },
    });
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

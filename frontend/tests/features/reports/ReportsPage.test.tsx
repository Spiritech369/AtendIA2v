/**
 * Sprint B.1 — ReportsPage smoke test. Mocks /api/v1/* to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ReportsPage } from "@/features/reports/components/ReportsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("ReportsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<ReportsPage />);
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

/**
 * Sprint B.1 — AppointmentsPage smoke test.
 *
 * Same pattern as DashboardPage.test.tsx: mocks every /api/v1/* call to
 * empty data and proves the page mounts without throwing. Catches the
 * class of regression where a refactor breaks the import graph or a
 * required-prop change silently red-screens this page.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";

import { AppointmentsPage } from "@/features/appointments/components/AppointmentsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/appointments", () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.get("/api/v1/appointments/advisors", () => HttpResponse.json([])),
  http.get("/api/v1/appointments/vehicles", () => HttpResponse.json([])),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("AppointmentsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<AppointmentsPage />);
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

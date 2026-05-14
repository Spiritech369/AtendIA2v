/**
 * Sprint B.1 — DashboardPage smoke test.
 *
 * Asserts the page renders without throwing under realistic API mocks.
 * The page kicks off ~7 parallel queries (dashboard summary, funnel,
 * volume, conversations, appointments, leads, workflows) — mocking all
 * of them to return empty payloads is the cheap proof that the layout
 * code-path is exercised end-to-end at least once. Future regressions
 * (e.g. a missing prop on a chart component, a broken Link target) will
 * surface here instead of hiding until QA opens the page.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { DashboardPage } from "@/features/dashboard/components/DashboardPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const empty = (extra: Record<string, unknown> = {}) => ({
  items: [],
  total: 0,
  ...extra,
});

const server = setupServer(
  http.get("/api/v1/dashboard/summary", () =>
    HttpResponse.json({
      customers_total: 0,
      conversations_today: 0,
      conversations_active: 0,
      conversations_unanswered: 0,
      appointments_today: 0,
      handoffs_open: 0,
    }),
  ),
  http.get("/api/v1/analytics/funnel", () => HttpResponse.json({ stages: [] })),
  http.get("/api/v1/analytics/volume", () =>
    HttpResponse.json({ series: [] }),
  ),
  http.get("/api/v1/conversations", () => HttpResponse.json(empty())),
  http.get("/api/v1/appointments", () => HttpResponse.json(empty())),
  http.get("/api/v1/customers", () => HttpResponse.json(empty())),
  http.get("/api/v1/workflows", () => HttpResponse.json(empty())),
  // Catch-all empty 200 so a forgotten endpoint doesn't blow the test.
  http.get("/api/v1/*", () => HttpResponse.json(empty())),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("DashboardPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<DashboardPage />);
    // RouterProvider mounts async — wait for the first child to land
    // before asserting. The proof is "something rendered without error".
    await waitFor(() => expect(container.firstChild).not.toBeNull());
    expect(container.innerHTML).not.toContain("Error: Objects are not valid");
  });
});

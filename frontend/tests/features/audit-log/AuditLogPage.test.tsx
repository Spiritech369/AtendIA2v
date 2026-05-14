/**
 * Sprint B.1 — AuditLogPage smoke test. Mocks /api/v1/audit-log to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AuditLogPage } from "@/features/audit-log/AuditLogPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/audit-log", () =>
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

describe("AuditLogPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    // superadmin scope per the audit doc
    const { container } = renderPage(<AuditLogPage />, {
      auth: { role: "superadmin" },
    });
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

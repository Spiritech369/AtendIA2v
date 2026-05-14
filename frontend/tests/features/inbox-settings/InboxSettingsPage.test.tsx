/**
 * Sprint B.1 — InboxSettingsPage smoke test. Mocks /api/v1/* to empty.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { InboxSettingsPage } from "@/features/inbox-settings/components/InboxSettingsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/*", () => HttpResponse.json({})),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("InboxSettingsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    // tenant_admin role required to edit inbox config
    const { container } = renderPage(<InboxSettingsPage />, {
      auth: { role: "tenant_admin" },
    });
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

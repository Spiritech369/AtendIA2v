/**
 * Sprint B.1 — ConversationsPage smoke test. Mocks /api/v1/conversations to empty.
 *
 * ConversationsPage is the highest-traffic page; a dedicated render
 * test catches regressions in the shared layout (FilterRail + List).
 * Individual children (ConversationList, ContactPanel, etc.) already
 * have their own tests — this one pins the top-level page composition.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ConversationsPage } from "@/features/conversations/components/ConversationsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/conversations", () =>
    HttpResponse.json({ items: [], next_cursor: null }),
  ),
  http.get("/api/v1/tenants/pipeline", () =>
    HttpResponse.json({ version: 1, stages: [], fallback: "escalate_to_human" }),
  ),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("ConversationsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<ConversationsPage />);
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });
});

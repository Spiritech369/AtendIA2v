/**
 * Component test for ConversationList (Phase 4 T17). Mocks the list endpoint
 * via MSW and renders within a QueryClient + minimal RouterProvider so
 * Link's typed routing works.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  type AnyRouter,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ConversationList } from "@/features/conversations/components/ConversationList";
import { useAuthStore } from "@/stores/auth";

const server = setupServer(
  http.get("/api/v1/conversations", () =>
    HttpResponse.json({
      items: [
        {
          id: "conv-1",
          tenant_id: "t-1",
          customer_id: "cust-1",
          customer_phone: "+5215551111111",
          customer_name: "María",
          status: "active",
          current_stage: "qualify",
          bot_paused: false,
          last_activity_at: "2026-05-07T12:00:00+00:00",
          last_message_text: "Hola, quiero info",
          last_message_direction: "inbound",
          has_pending_handoff: false,
        },
        {
          id: "conv-2",
          tenant_id: "t-1",
          customer_id: "cust-2",
          customer_phone: "+5215552222222",
          customer_name: null,
          status: "active",
          current_stage: "quote",
          bot_paused: true,
          last_activity_at: "2026-05-07T11:30:00+00:00",
          last_message_text: "Espérame tantito",
          last_message_direction: "outbound",
          has_pending_handoff: true,
        },
      ],
      next_cursor: null,
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  // Reset zustand store so different tests don't bleed user state
  useAuthStore.setState({ user: null, csrf: null, status: "idle" });
});
afterAll(() => server.close());

function renderInRouter(): AnyRouter {
  // Build a one-route router that mounts the component at `/`. We don't
  // navigate; just need the Router context for Link's beforeLoad/typing.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  // Pre-populate the auth store so useTenantStream's tenantId selector
  // returns something (and thus does NOT open a WS, since path is "").
  useAuthStore.setState({
    user: {
      id: "u1",
      tenant_id: "t-1",
      role: "operator",
      email: "op@dinamo.com",
    },
    csrf: "x",
    status: "authenticated",
  });

  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={queryClient}>
        <ConversationList />
      </QueryClientProvider>
    ),
  });
  const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/" });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
  });
  render(<RouterProvider router={router} />);
  return router;
}

describe("ConversationList", () => {
  it("renders rows fetched from the API", async () => {
    renderInRouter();

    expect(await screen.findByText("María")).toBeInTheDocument();
    expect(screen.getByText("Hola, quiero info")).toBeInTheDocument();
    expect(screen.getByText("Espérame tantito")).toBeInTheDocument();
    // Phone shown for the unnamed customer
    expect(screen.getByText("+5215552222222")).toBeInTheDocument();
    // Stage column populated
    expect(screen.getAllByText("qualify").length).toBeGreaterThan(0);
  });

  it("shows the Handoff badge when has_pending_handoff is true", async () => {
    renderInRouter();
    await waitFor(() => screen.getByText("Espérame tantito"));
    expect(screen.getByText(/Handoff/i)).toBeInTheDocument();
  });

  it("shows the Pausado badge when bot_paused is true", async () => {
    renderInRouter();
    await waitFor(() => screen.getByText("Espérame tantito"));
    expect(screen.getByText(/Pausado/)).toBeInTheDocument();
  });
});

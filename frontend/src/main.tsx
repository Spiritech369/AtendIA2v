import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import { routeTree } from "./routeTree.gen";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Default to "cache for 5 min, don't refetch when the tab regains
      // focus." Conversation/handoff freshness is driven by the WebSocket
      // (``useTenantStream``) which invalidates the relevant query keys
      // on every server event — refetchOnWindowFocus on top of that just
      // adds spinners and DB load every time the operator switches tabs.
      // Pages that DO need live polling (``WhatsAppStatusBadge``,
      // notifications, document indexing) opt in via ``refetchInterval``.
      staleTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  context: { queryClient },
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("missing #root element");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);

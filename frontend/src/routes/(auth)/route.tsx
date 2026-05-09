import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

import { AppShell } from "@/components/AppShell";
import { RouteErrorFallback } from "@/components/RouteErrorFallback";
import { useAuthStore } from "@/stores/auth";

/**
 * Gated route group — every URL inside `(auth)/` requires a logged-in
 * operator. The parens mean the group does NOT appear in the URL: a route
 * defined at `(auth)/conversations.tsx` matches `/conversations`, not
 * `/auth/conversations`.
 *
 * `beforeLoad` runs before render and before any child loaders, so a
 * redirect here short-circuits the dashboard fetch and pushes the user
 * to /login. `fetchMe` returns `null` when the cookie is missing or
 * expired (axios interceptor swallows the 401 in api-client).
 */
export const Route = createFileRoute("/(auth)")({
  beforeLoad: async () => {
    const state = useAuthStore.getState();
    const user = state.user ?? (await state.fetchMe());
    if (!user) throw redirect({ to: "/login" });
  },
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
  // A crash inside a child route renders the fallback INSIDE the AppShell —
  // sidebar + header stay usable so the operator can navigate away.
  errorComponent: ({ error, reset }) => (
    <AppShell>
      <RouteErrorFallback error={error} reset={reset} />
    </AppShell>
  ),
});

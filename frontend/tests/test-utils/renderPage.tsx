/**
 * Sprint B.1 — Shared helper for page-level render tests.
 *
 * Why this helper exists:
 *
 * * Page components depend on TanStack Router context (for <Link/> typing),
 *   TanStack Query (for data hooks), and an authenticated user (so guards +
 *   `useTenantStream` selectors don't bail out into a "not logged in"
 *   placeholder).
 *
 * * Re-wiring those three contexts in every page test is verbose and
 *   error-prone — small differences mask real bugs. This helper pins one
 *   wiring so every page test starts from the same baseline.
 *
 * Usage:
 *
 *   import { renderPage } from "../../test-utils/renderPage";
 *   renderPage(<DashboardPage />);
 *
 * The `auth` and `queryClient` options exist so a test can override the
 * defaults (e.g. simulate a tenant_admin instead of operator, or
 * pre-seed query cache).
 */
import {
  QueryClient,
  QueryClientProvider,
  type QueryClient as TQueryClient,
} from "@tanstack/react-query";
import {
  type AnyRouter,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import { useAuthStore, type AuthUser, type Role } from "@/stores/auth";

interface RenderPageOptions {
  /** Pre-seeded auth user. Defaults to a tenant-scoped operator. */
  auth?: Partial<AuthUser> & { role?: Role };
  /** Pre-built QueryClient. Defaults to one with retry disabled. */
  queryClient?: TQueryClient;
}

export interface RenderPageResult extends RenderResult {
  router: AnyRouter;
  queryClient: TQueryClient;
}

export function renderPage(
  ui: ReactElement,
  { auth, queryClient }: RenderPageOptions = {},
): RenderPageResult {
  const qc =
    queryClient ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0, staleTime: 0 },
        mutations: { retry: false },
      },
    });

  useAuthStore.setState({
    user: {
      id: auth?.id ?? "u1",
      tenant_id: auth?.tenant_id ?? "t-1",
      role: auth?.role ?? "operator",
      email: auth?.email ?? "op@dinamo.com",
    },
    csrf: "test-csrf",
    status: "authenticated",
  });

  const rootRoute = createRootRoute({
    component: () => <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  });
  const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/" });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
  });

  const result = render(<RouterProvider router={router} />);
  return Object.assign(result, { router, queryClient: qc });
}

export function resetAuth(): void {
  useAuthStore.setState({ user: null, csrf: null, status: "idle" });
}

/**
 * Convenience for unwrapping a child in a non-TanStack render. Useful when
 * a page test needs to inspect a memoized child without a full router.
 */
export function withQueryClient(node: ReactNode, qc?: TQueryClient): ReactElement {
  const client =
    qc ??
    new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

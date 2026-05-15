/**
 * Sprint C.1 — Playwright smoke test for the 7 routes listed in the
 * audit: Conversations, Handoffs, Customers, Appointments, Knowledge,
 * Agents, Workflows.
 *
 * Scope is intentionally minimal:
 *
 * * Log in once via the API (POST /api/v1/auth/login). The browser
 *   keeps the session cookie + CSRF header thereafter.
 * * Navigate to each route via `page.goto`.
 * * Assert the page responded 200 AND mounted (sidebar item is marked
 *   active AND no React error boundary visible).
 *
 * What this catches that Vitest can't:
 *
 * * Vite production-build differences (CSS bundling, code-splitting,
 *   chunked routes).
 * * Real backend integration (`/api/v1/auth/me`, CSRF, cookies).
 * * Router re-entry from a clean tab (TanStack Router's
 *   `beforeLoad` guards, type-narrowed search params).
 *
 * Prerequisites: backend running on :8001 with the seed user from
 * `core/scripts/seed_zored_user.py` already inserted. See README.md
 * in this directory.
 */
import { expect, test } from "@playwright/test";

const SEED_EMAIL = process.env.E2E_USER_EMAIL ?? "dele.zored@hotmail.com";
const SEED_PASSWORD = process.env.E2E_USER_PASSWORD ?? "dinamo123";

const ROUTES = [
  { path: "/conversations", label: "Conversaciones" },
  { path: "/handoffs", label: "Handoffs" },
  { path: "/customers", label: "Clientes" },
  { path: "/appointments", label: "Citas" },
  { path: "/knowledge", label: "Conocimiento" },
  { path: "/agents", label: "Agentes" },
  { path: "/workflows", label: "Workflows" },
] as const;

test.beforeEach(async ({ page }) => {
  // Cheaper than driving the login form — and decouples this smoke from
  // any LoginPage rerender. Failure here means the BACKEND auth route
  // is broken, which is its own bug independent of the routes under
  // test.
  const resp = await page.request.post("/api/v1/auth/login", {
    data: { email: SEED_EMAIL, password: SEED_PASSWORD },
  });
  expect(resp.ok(), `login failed: ${resp.status()} ${await resp.text()}`).toBe(true);
});

for (const route of ROUTES) {
  test(`smoke ${route.path} renders without error`, async ({ page }) => {
    const navResp = await page.goto(route.path);
    expect(navResp?.status() ?? 0).toBeLessThan(400);

    // No React error boundary visible. We render boundaries with the
    // string "Algo salió mal" (RouteErrorFallback) — assert that's NOT
    // anywhere on the page.
    await expect(page.getByText(/Algo salió mal/i)).toHaveCount(0);

    // Sidebar reflects the active route. Every nav item has an
    // `aria-current="page"` when its path matches the current URL.
    await expect(
      page.locator(`a[aria-current="page"]`).filter({ hasText: route.label }),
    ).toBeVisible({ timeout: 10_000 });
  });
}

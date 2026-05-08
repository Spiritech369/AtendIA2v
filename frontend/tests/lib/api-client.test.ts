/**
 * Smoke tests for the axios client wiring. Real auth-flow E2E lands in T54.
 *
 * These tests use MSW to intercept axios calls and assert the request
 * interceptor wired up the X-CSRF-Token header from the atendia_csrf cookie.
 */
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { api } from "@/lib/api-client";

let lastCsrfHeader: string | null = null;

const server = setupServer(
  http.post("/api/v1/auth/login", ({ request }) => {
    lastCsrfHeader = request.headers.get("x-csrf-token");
    return HttpResponse.json({ csrf_token: "fresh", user: { id: "u1" } });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  lastCsrfHeader = null;
  document.cookie = "atendia_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/;";
});
afterAll(() => server.close());

describe("api-client", () => {
  it("echoes the atendia_csrf cookie in X-CSRF-Token on POST", async () => {
    document.cookie = "atendia_csrf=token-abc-123; path=/;";
    await api.post("/auth/login", { email: "x", password: "y" });
    expect(lastCsrfHeader).toBe("token-abc-123");
  });

  it("does not send X-CSRF-Token when cookie is missing", async () => {
    await api.post("/auth/login", { email: "x", password: "y" });
    expect(lastCsrfHeader).toBeNull();
  });
});

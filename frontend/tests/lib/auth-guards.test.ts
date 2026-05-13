import { beforeEach, describe, expect, it } from "vitest";

import { requireRole } from "@/lib/auth-guards";
import { useAuthStore } from "@/stores/auth";

describe("requireRole", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "idle", csrf: null });
  });

  it("redirects to /login when not authenticated", async () => {
    const guard = requireRole(["tenant_admin"]);
    await expect(guard()).rejects.toMatchObject({ options: { to: "/login" } });
  });

  it("redirects to / when role is not allowed", async () => {
    useAuthStore.setState({
      user: { id: "u1", tenant_id: "t1", role: "operator", email: "o@x.com" },
      status: "authenticated",
      csrf: "c",
    });
    const guard = requireRole(["tenant_admin", "superadmin"]);
    await expect(guard()).rejects.toMatchObject({ options: { to: "/" } });
  });

  it("allows the matching role", async () => {
    useAuthStore.setState({
      user: {
        id: "u1",
        tenant_id: "t1",
        role: "tenant_admin",
        email: "a@x.com",
      },
      status: "authenticated",
      csrf: "c",
    });
    const guard = requireRole(["tenant_admin", "superadmin"]);
    await expect(guard()).resolves.toBeUndefined();
  });

  it("allows superadmin for tenant_admin-or-above routes", async () => {
    useAuthStore.setState({
      user: {
        id: "u1",
        tenant_id: "t1",
        role: "superadmin",
        email: "s@x.com",
      },
      status: "authenticated",
      csrf: "c",
    });
    const guard = requireRole(["tenant_admin", "superadmin"]);
    await expect(guard()).resolves.toBeUndefined();
  });
});

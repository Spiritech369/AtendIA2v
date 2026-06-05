import { beforeEach, describe, expect, it } from "vitest";

import { requireCapability, requireRole } from "@/lib/auth-guards";
import { useAuthStore } from "@/stores/auth";
import { useCapabilitiesStore } from "@/stores/capabilities";

describe("requireRole", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "idle", csrf: null });
    useCapabilitiesStore.getState().reset();
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

describe("requireCapability", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "idle", csrf: null });
    useCapabilitiesStore.getState().reset();
  });

  it("redirects to /login when not authenticated", async () => {
    const guard = requireCapability("route.users", ["tenant_admin"]);
    await expect(guard()).rejects.toMatchObject({ options: { to: "/login" } });
  });

  it("allows when backend capabilities include the route", async () => {
    useAuthStore.setState({
      user: { id: "u1", tenant_id: "t1", role: "operator", email: "o@x.com" },
      status: "authenticated",
      csrf: "c",
    });
    useCapabilitiesStore.setState({
      fetchForTenant: async () => ({
        schema_version: "test",
        tenant_id: "t1",
        feature_flags: {
          show_nyi_controls: false,
          demo_mode: false,
          mock_knowledge_model: false,
        },
        limits: { max_pipeline_stages: 30, max_workflow_nodes: 100 },
        current_user: { id: "u1", role: "operator", capabilities: ["route.users"] },
      }),
    });

    const guard = requireCapability("route.users", ["tenant_admin"]);
    await expect(guard()).resolves.toBeUndefined();
  });

  it("redirects when backend capabilities omit the route", async () => {
    useAuthStore.setState({
      user: { id: "u1", tenant_id: "t1", role: "tenant_admin", email: "a@x.com" },
      status: "authenticated",
      csrf: "c",
    });
    useCapabilitiesStore.setState({
      fetchForTenant: async () => ({
        schema_version: "test",
        tenant_id: "t1",
        feature_flags: {
          show_nyi_controls: false,
          demo_mode: false,
          mock_knowledge_model: false,
        },
        limits: { max_pipeline_stages: 30, max_workflow_nodes: 100 },
        current_user: { id: "u1", role: "tenant_admin", capabilities: [] },
      }),
    });

    const guard = requireCapability("route.users", ["tenant_admin"]);
    await expect(guard()).rejects.toMatchObject({ options: { to: "/" } });
  });
});

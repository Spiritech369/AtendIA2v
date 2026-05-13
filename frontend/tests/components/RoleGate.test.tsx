import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { RoleGate } from "@/components/RoleGate";
import { useAuthStore } from "@/stores/auth";

describe("RoleGate", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "idle", csrf: null });
  });

  it("renders children when role matches", () => {
    useAuthStore.setState({
      user: {
        id: "u",
        tenant_id: "t",
        role: "tenant_admin",
        email: "a@x.com",
      },
      status: "authenticated",
      csrf: "c",
    });
    render(
      <RoleGate roles={["tenant_admin", "superadmin"]}>
        <button type="button">Delete</button>
      </RoleGate>,
    );
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("renders fallback when role doesn't match", () => {
    useAuthStore.setState({
      user: { id: "u", tenant_id: "t", role: "operator", email: "o@x.com" },
      status: "authenticated",
      csrf: "c",
    });
    render(
      <RoleGate roles={["tenant_admin"]} fallback={<span>nope</span>}>
        <button type="button">Delete</button>
      </RoleGate>,
    );
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    expect(screen.getByText("nope")).toBeInTheDocument();
  });

  it("renders nothing by default when no fallback and role mismatch", () => {
    useAuthStore.setState({
      user: { id: "u", tenant_id: "t", role: "operator", email: "o@x.com" },
      status: "authenticated",
      csrf: "c",
    });
    const { container } = render(
      <RoleGate roles={["tenant_admin"]}>
        <button type="button">Delete</button>
      </RoleGate>,
    );
    expect(container.textContent).toBe("");
  });

  it("renders nothing when user is logged out", () => {
    const { container } = render(
      <RoleGate roles={["operator", "tenant_admin"]}>
        <span>shown</span>
      </RoleGate>,
    );
    expect(container.textContent).toBe("");
  });
});

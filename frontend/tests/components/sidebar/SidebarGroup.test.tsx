import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LayoutDashboard, ShieldCheck } from "lucide-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    to,
    children,
    "aria-current": ariaCurrent,
    className,
    title,
  }: {
    to: string;
    children: React.ReactNode;
    "aria-current"?: "page";
    className?: string;
    title?: string;
  }) => (
    <a href={to} aria-current={ariaCurrent} className={className} title={title}>
      {children}
    </a>
  ),
}));

import { SidebarGroup } from "@/components/sidebar/SidebarGroup";
import type { NavGroup } from "@/features/navigation/types";
import { useSidebarStore } from "@/stores/sidebar-store";

const group: NavGroup = {
  id: "ops",
  label: "Operación",
  items: [
    {
      id: "dashboard",
      label: "Dashboard",
      to: "/dashboard",
      icon: LayoutDashboard,
      roles: ["operator", "tenant_admin", "superadmin"],
    },
    {
      id: "handoffs",
      label: "Handoffs",
      to: "/handoffs",
      icon: ShieldCheck,
      roles: ["operator", "tenant_admin", "superadmin"],
      badgeKey: "handoffs_open",
    },
  ],
};

const badges = {
  conversations_open: 0,
  handoffs_open: 3,
  handoffs_overdue: 1,
  appointments_today: 0,
  ai_debug_warnings: 0,
  unread_notifications: 0,
};

describe("SidebarGroup", () => {
  beforeEach(() => {
    useSidebarStore.setState({ compact: false, expandedGroups: {} });
  });

  it("renders group label and items when expanded", () => {
    render(
      <SidebarGroup
        group={group}
        compact={false}
        activePath="/dashboard"
        badges={badges}
      />,
    );
    expect(screen.getByText("Operación")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Handoffs")).toBeInTheDocument();
  });

  it("renders the handoff badge with destructive variant when overdue > 0", () => {
    render(
      <SidebarGroup
        group={group}
        compact={false}
        activePath="/dashboard"
        badges={badges}
      />,
    );
    const chip = screen.getByText("3");
    expect(chip.className).toContain("text-red-600");
  });

  it("toggles expanded state on header click", async () => {
    const user = userEvent.setup();
    render(
      <SidebarGroup
        group={group}
        compact={false}
        activePath="/dashboard"
        badges={badges}
      />,
    );
    const header = screen.getByRole("button", { name: /Operación/i });
    expect(header).toHaveAttribute("aria-expanded", "true");
    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    // Items disappear when collapsed (non-compact mode)
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });

  it("compact mode hides the header and shows items as icons", () => {
    render(
      <SidebarGroup
        group={group}
        compact
        activePath="/dashboard"
        badges={badges}
      />,
    );
    expect(screen.queryByRole("button", { name: /Operación/i })).not.toBeInTheDocument();
    // Items render but only via icon + title (label not visible)
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link").length).toBe(2);
  });
});

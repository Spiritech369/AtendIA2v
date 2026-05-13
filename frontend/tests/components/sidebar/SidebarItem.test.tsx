import { render, screen } from "@testing-library/react";
import { MessageCircle } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

// Stub TanStack Router's <Link> with a plain anchor so we don't need
// a full router context just to exercise the visual contract of the row.
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

import { isItemActive, SidebarItem } from "@/components/sidebar/SidebarItem";
import type { NavItem } from "@/features/navigation/types";

const baseItem: NavItem = {
  id: "conversations",
  label: "Conversaciones",
  to: "/",
  icon: MessageCircle,
  roles: ["operator", "tenant_admin", "superadmin"],
  exactMatch: true,
  activeAlsoOn: ["/conversations"],
};

describe("isItemActive", () => {
  it("matches exact path for exactMatch items", () => {
    expect(isItemActive(baseItem, "/")).toBe(true);
    expect(isItemActive(baseItem, "/dashboard")).toBe(false);
  });

  it("matches activeAlsoOn prefixes", () => {
    expect(isItemActive(baseItem, "/conversations/abc-123")).toBe(true);
    expect(isItemActive(baseItem, "/conversations")).toBe(true);
  });

  it("matches prefix for non-exact items", () => {
    const it: NavItem = { ...baseItem, exactMatch: false, to: "/customers" };
    expect(isItemActive(it, "/customers")).toBe(true);
    expect(isItemActive(it, "/customers/abc")).toBe(true);
    expect(isItemActive(it, "/customers-other")).toBe(false);
  });
});

describe("SidebarItem", () => {
  it("renders the label and icon when expanded", () => {
    render(<SidebarItem item={baseItem} active={false} compact={false} />);
    expect(screen.getByText("Conversaciones")).toBeInTheDocument();
  });

  it("sets aria-current=page when active", () => {
    render(<SidebarItem item={baseItem} active compact={false} />);
    expect(screen.getByRole("link", { name: /conversaciones/i })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("omits the label and badge in compact mode", () => {
    render(<SidebarItem item={baseItem} active={false} compact badgeValue={5} />);
    expect(screen.queryByText("Conversaciones")).not.toBeInTheDocument();
    expect(screen.queryByText("5")).not.toBeInTheDocument();
  });

  it("renders a badge when value > 0", () => {
    render(<SidebarItem item={baseItem} active={false} compact={false} badgeValue={7} />);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("does not render the badge when value is 0", () => {
    render(<SidebarItem item={baseItem} active={false} compact={false} badgeValue={0} />);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("uses title for tooltip in compact mode", () => {
    render(<SidebarItem item={baseItem} active={false} compact />);
    expect(screen.getByRole("link")).toHaveAttribute("title", "Conversaciones");
  });
});

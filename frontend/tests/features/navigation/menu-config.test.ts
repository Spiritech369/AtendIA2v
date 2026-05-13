import { describe, expect, it } from "vitest";

import { filterMenuByRole, NAV_GROUPS } from "@/features/navigation/menu-config";

describe("NAV_GROUPS", () => {
  it("contains 6 groups in the expected order", () => {
    expect(NAV_GROUPS.map((g) => g.id)).toEqual([
      "dashboard",
      "operacion",
      "ia",
      "automation",
      "metrics",
      "admin",
    ]);
  });
});

describe("filterMenuByRole", () => {
  it("operator: excludes admin-only items", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "operator");
    const items = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(items).not.toContain("agents");
    expect(items).not.toContain("users");
    expect(items).not.toContain("audit-log");
    expect(items).not.toContain("inbox-settings");
    expect(items).not.toContain("config");
    expect(items).toContain("conversations");
    expect(items).toContain("handoffs");
    expect(items).toContain("customers");
    expect(items).toContain("appointments");
    expect(items).toContain("workflows");
    expect(items).toContain("knowledge");
    expect(items).toContain("turn-traces");
  });

  it("tenant_admin: includes admin items, excludes audit-log", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "tenant_admin");
    const items = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(items).toContain("agents");
    expect(items).toContain("users");
    expect(items).toContain("inbox-settings");
    expect(items).toContain("config");
    expect(items).not.toContain("audit-log");
  });

  it("superadmin: includes everything", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "superadmin");
    const items = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(items).toContain("audit-log");
    expect(items).toContain("users");
    expect(items).toContain("agents");
    expect(items).toContain("config");
  });

  it("returns empty when role is missing", () => {
    expect(filterMenuByRole(NAV_GROUPS, null)).toEqual([]);
    expect(filterMenuByRole(NAV_GROUPS, undefined)).toEqual([]);
  });

  it("drops empty groups after filtering", () => {
    const groups = filterMenuByRole(NAV_GROUPS, "operator");
    for (const g of groups) {
      expect(g.items.length).toBeGreaterThan(0);
    }
  });
});

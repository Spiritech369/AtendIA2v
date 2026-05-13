import { beforeEach, describe, expect, it } from "vitest";

import { useSidebarStore } from "@/stores/sidebar-store";

describe("sidebar-store", () => {
  beforeEach(() => {
    useSidebarStore.setState({
      compact: false,
      expandedGroups: {},
    });
    window.localStorage.clear();
  });

  it("toggleCompact flips the flag", () => {
    expect(useSidebarStore.getState().compact).toBe(false);
    useSidebarStore.getState().toggleCompact();
    expect(useSidebarStore.getState().compact).toBe(true);
    useSidebarStore.getState().toggleCompact();
    expect(useSidebarStore.getState().compact).toBe(false);
  });

  it("isGroupExpanded defaults to true for unknown groups", () => {
    expect(useSidebarStore.getState().isGroupExpanded("operacion")).toBe(true);
  });

  it("toggleGroup flips the group state", () => {
    useSidebarStore.getState().toggleGroup("operacion");
    expect(useSidebarStore.getState().isGroupExpanded("operacion")).toBe(false);
    useSidebarStore.getState().toggleGroup("operacion");
    expect(useSidebarStore.getState().isGroupExpanded("operacion")).toBe(true);
  });

  it("persists to localStorage", () => {
    useSidebarStore.getState().toggleCompact();
    const raw = window.localStorage.getItem("atendia.sidebar.v1");
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw as string);
    expect(parsed.state.compact).toBe(true);
  });

  it("each group is tracked independently", () => {
    const { toggleGroup, isGroupExpanded } = useSidebarStore.getState();
    toggleGroup("ia");
    expect(isGroupExpanded("ia")).toBe(false);
    expect(isGroupExpanded("operacion")).toBe(true);
  });
});

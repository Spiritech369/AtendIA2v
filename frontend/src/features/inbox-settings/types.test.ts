import { describe, expect, it } from "vitest";

import { DEFAULT_INBOX_CONFIG, normalizeInboxConfig } from "./types";

describe("normalizeInboxConfig", () => {
  it("falls back to default arrays when a legacy config stores objects", () => {
    const normalized = normalizeInboxConfig({
      layout: { three_pane: false },
      filter_chips: { enabled_filters: ["stage"] },
      handoff_rules: { auto_assign: true },
      stage_rings: { show_sla: true, show_risk: true },
    });

    expect(normalized.layout.three_pane).toBe(false);
    expect(normalized.stage_rings).toEqual(DEFAULT_INBOX_CONFIG.stage_rings);
    expect(normalized.handoff_rules).toEqual(DEFAULT_INBOX_CONFIG.handoff_rules);
    expect(normalized.filter_chips).toEqual(DEFAULT_INBOX_CONFIG.filter_chips);
  });

  it("keeps valid configured arrays cloneable for UI consumers", () => {
    const normalized = normalizeInboxConfig({
      stage_rings: [{ stage_id: "propuesta", emoji: "$", color: "#6366f1", sla_hours: 24 }],
    });

    expect(normalized.stage_rings.find((ring) => ring.stage_id === "propuesta")).toEqual({
      stage_id: "propuesta",
      emoji: "$",
      color: "#6366f1",
      sla_hours: 24,
    });
  });
});

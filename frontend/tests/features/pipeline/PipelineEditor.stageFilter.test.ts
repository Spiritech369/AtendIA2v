import { describe, expect, it } from "vitest";

import { type StageDraft, stageMatchesQuery } from "@/features/pipeline/components/PipelineEditor";

function stage(overrides: Partial<StageDraft> = {}): StageDraft {
  return {
    id: "calificacion_inicial",
    label: "Calificación inicial",
    timeout_hours: 0,
    is_terminal: false,
    color: "#3b82f6",
    ...overrides,
  };
}

describe("stageMatchesQuery", () => {
  it("matches everything when the query is empty or whitespace", () => {
    expect(stageMatchesQuery(stage(), "")).toBe(true);
    expect(stageMatchesQuery(stage(), "   ")).toBe(true);
  });

  it("matches the visible label case-insensitively", () => {
    expect(stageMatchesQuery(stage(), "calif")).toBe(true);
    expect(stageMatchesQuery(stage(), "INICIAL")).toBe(true);
  });

  it("matches the stage_id case-insensitively", () => {
    expect(stageMatchesQuery(stage(), "calificacion_ini")).toBe(true);
    expect(stageMatchesQuery(stage(), "CALIFICACION")).toBe(true);
  });

  it("returns false when neither label nor id contains the query", () => {
    expect(stageMatchesQuery(stage(), "papeleria")).toBe(false);
  });

  it("trims the query before matching", () => {
    expect(stageMatchesQuery(stage({ label: "Cierre" }), "  cier  ")).toBe(true);
  });
});

import { describe, expect, it } from "vitest";

import {
  BEHAVIOR_MODES,
  HANDOFF_REASON_PRESETS,
  VISION_CATEGORIES,
  parsePipeline,
  serialisePipelineDraft,
  validatePipelineDraft,
  type PipelineDraft,
  type StageDraft,
} from "@/features/pipeline/components/PipelineEditor";

// Empty-but-valid draft we layer field overrides on top of, so each
// test stays focused on the field under exam without re-stating the
// whole shape.
function baseDraft(overrides: Partial<PipelineDraft> = {}): PipelineDraft {
  const stage: StageDraft = {
    id: "papeleria_completa",
    label: "Papelería completa",
    timeout_hours: 0,
    is_terminal: false,
    color: "#10b981",
  };
  return {
    stages: [stage, ...(overrides.stages ?? [])].slice(0, 1),
    docs_per_plan: {},
    documents_catalog: [],
    vision_doc_mapping: {},
    extra: {},
    ...overrides,
  };
}

describe("constants stay in lockstep with the backend", () => {
  it("BEHAVIOR_MODES contains all six FlowMode values", () => {
    // Mirror of core/atendia/contracts/flow_mode.py — drifting either
    // side without the other breaks save validation silently.
    expect([...BEHAVIOR_MODES]).toEqual([
      "PLAN",
      "SALES",
      "DOC",
      "OBSTACLE",
      "RETENTION",
      "SUPPORT",
    ]);
  });

  it("VISION_CATEGORIES matches the Vision contract doc categories", () => {
    expect([...VISION_CATEGORIES]).toEqual([
      "ine",
      "comprobante",
      "recibo_nomina",
      "estado_cuenta",
      "constancia_sat",
      "factura",
      "imss",
    ]);
  });

  it("HANDOFF_REASON_PRESETS covers the docs_complete reason", () => {
    expect(HANDOFF_REASON_PRESETS.map((r) => r.value)).toContain(
      "docs_complete_for_plan",
    );
  });
});

describe("parsePipeline → serialise roundtrip for new fields", () => {
  it("preserves stage.behavior_mode when valid", () => {
    const parsed = parsePipeline({
      stages: [
        {
          id: "calificacion_inicial",
          label: "Calificación",
          color: "#3b82f6",
          behavior_mode: "PLAN",
        },
      ],
    });
    expect(parsed.stages[0]!.behavior_mode).toBe("PLAN");
    const out = serialisePipelineDraft(parsed) as Record<string, unknown>;
    const stages = out.stages as Array<Record<string, unknown>>;
    expect(stages[0]!.behavior_mode).toBe("PLAN");
  });

  it("strips unknown behavior_mode strings on parse so the dropdown stays valid", () => {
    const parsed = parsePipeline({
      stages: [
        { id: "stage1", label: "S", color: "#000", behavior_mode: "NOPE" },
      ],
    });
    expect(parsed.stages[0]!.behavior_mode).toBe("");
    const out = serialisePipelineDraft(parsed) as Record<string, unknown>;
    const stages = out.stages as Array<Record<string, unknown>>;
    expect("behavior_mode" in stages[0]!).toBe(false);
  });

  it("preserves pause_bot_on_enter + handoff_reason together", () => {
    const parsed = parsePipeline({
      stages: [
        {
          id: "papeleria_completa",
          label: "Papelería completa",
          color: "#10b981",
          pause_bot_on_enter: true,
          handoff_reason: "docs_complete_for_plan",
        },
      ],
    });
    expect(parsed.stages[0]!.pause_bot_on_enter).toBe(true);
    expect(parsed.stages[0]!.handoff_reason).toBe("docs_complete_for_plan");
    const stages = (serialisePipelineDraft(parsed) as { stages: Array<Record<string, unknown>> }).stages;
    expect(stages[0]!.pause_bot_on_enter).toBe(true);
    expect(stages[0]!.handoff_reason).toBe("docs_complete_for_plan");
  });

  it("omits empty handoff_reason from the serialised stage", () => {
    const draft = baseDraft();
    draft.stages[0]!.pause_bot_on_enter = true;
    draft.stages[0]!.handoff_reason = "   "; // whitespace
    const stages = (serialisePipelineDraft(draft) as { stages: Array<Record<string, unknown>> }).stages;
    expect("handoff_reason" in stages[0]!).toBe(false);
    expect(stages[0]!.pause_bot_on_enter).toBe(true);
  });

  it("preserves vision_doc_mapping with multi-key INE order", () => {
    const parsed = parsePipeline({
      stages: [{ id: "stage1", label: "S", color: "#000" }],
      documents_catalog: [
        { key: "DOCS_INE_FRENTE", label: "INE frente" },
        { key: "DOCS_INE_REVERSO", label: "INE reverso" },
      ],
      vision_doc_mapping: {
        ine: ["DOCS_INE_FRENTE", "DOCS_INE_REVERSO"],
      },
    });
    expect(parsed.vision_doc_mapping.ine).toEqual([
      "DOCS_INE_FRENTE",
      "DOCS_INE_REVERSO",
    ]);
    const out = serialisePipelineDraft(parsed) as Record<string, unknown>;
    expect(out.vision_doc_mapping).toEqual({
      ine: ["DOCS_INE_FRENTE", "DOCS_INE_REVERSO"],
    });
  });

  it("filters non-DOCS_* values from vision_doc_mapping on parse", () => {
    const parsed = parsePipeline({
      stages: [{ id: "stage1", label: "S", color: "#000" }],
      vision_doc_mapping: {
        ine: ["DOCS_INE_FRENTE", "junk_value", "DOCS_INE_REVERSO"],
      },
    });
    expect(parsed.vision_doc_mapping.ine).toEqual([
      "DOCS_INE_FRENTE",
      "DOCS_INE_REVERSO",
    ]);
  });

  it("drops empty vision_doc_mapping entirely on serialise", () => {
    const draft = baseDraft({ vision_doc_mapping: {} });
    const out = serialisePipelineDraft(draft) as Record<string, unknown>;
    expect("vision_doc_mapping" in out).toBe(false);
  });
});

describe("validate rejects misconfigurations", () => {
  it("flags handoff_reason without pause_bot_on_enter", () => {
    const draft = baseDraft();
    draft.stages[0]!.handoff_reason = "docs_complete_for_plan";
    draft.stages[0]!.pause_bot_on_enter = false;
    expect(validatePipelineDraft(draft)).toMatch(/handoff_reason solo aplica/);
  });

  it("flags vision_doc_mapping referencing a doc not in catalog", () => {
    const draft = baseDraft({
      documents_catalog: [
        { key: "DOCS_COMPROBANTE", label: "Comprobante", hint: "" },
      ],
      vision_doc_mapping: { ine: ["DOCS_INE_FRENTE"] },
    });
    expect(validatePipelineDraft(draft)).toMatch(/Mapeo Vision \(ine\)/);
  });

  it("accepts a valid pipeline draft with all new fields", () => {
    const draft = baseDraft({
      documents_catalog: [
        { key: "DOCS_INE_FRENTE", label: "INE frente", hint: "" },
        { key: "DOCS_INE_REVERSO", label: "INE reverso", hint: "" },
      ],
      vision_doc_mapping: {
        ine: ["DOCS_INE_FRENTE", "DOCS_INE_REVERSO"],
      },
    });
    draft.stages[0]!.pause_bot_on_enter = true;
    draft.stages[0]!.handoff_reason = "docs_complete_for_plan";
    draft.stages[0]!.behavior_mode = "DOC";
    expect(validatePipelineDraft(draft)).toBeNull();
  });

  it("rejects unknown vision category names", () => {
    const draft = baseDraft({
      documents_catalog: [
        { key: "DOCS_X", label: "x", hint: "" },
      ],
      vision_doc_mapping: { unknown_category: ["DOCS_X"] },
    });
    expect(validatePipelineDraft(draft)).toMatch(/categoría "unknown_category"/);
  });
});

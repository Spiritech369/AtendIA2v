import { describe, expect, it } from "vitest";

import {
  parseExpedienteDraft,
  serialiseExpediente,
} from "@/features/expediente/components/ExpedientePage";

describe("ExpedientePage helpers", () => {
  it("parses canonical document requirements from the tenant pipeline", () => {
    const draft = parseExpedienteDraft({
      document_requirements_field: "Plan_Credito",
      document_requirements: {
        "Nomina Tarjeta": ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO"],
        "Sin Comprobantes": ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO"],
        Contado: [],
      },
      documents_catalog: [
        { key: "INE_AMBOS_LADOS", label: "INE ambos lados" },
        { key: "COMPROBANTE_DOMICILIO", label: "Comprobante de domicilio" },
      ],
    });

    expect(draft.docs_plan_field).toBe("Plan_Credito");
    expect(Object.keys(draft.docs_per_plan)).toHaveLength(3);
    expect(draft.docs_per_plan.Contado).toEqual([]);
    expect(draft.docs_per_plan["Sin Comprobantes"]).toHaveLength(2);
  });

  it("serializes both legacy and canonical document requirement keys", () => {
    const serialized = serialiseExpediente({
      docs_plan_field: "Plan_Credito",
      docs_per_plan: { Contado: [] },
      documents_catalog: [{ key: "INE_AMBOS_LADOS", label: "INE ambos lados" }],
    });

    expect(serialized.docs_plan_field).toBe("Plan_Credito");
    expect(serialized.document_requirements_field).toBe("Plan_Credito");
    expect(serialized.docs_per_plan).toEqual({ Contado: [] });
    expect(serialized.document_requirements).toEqual({ Contado: [] });
  });
});


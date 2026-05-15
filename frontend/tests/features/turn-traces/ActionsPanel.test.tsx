import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { ActionsPanel } from "@/features/turn-traces/components/TurnPanels";

// Minimal viable TurnTraceDetail with only the fields the panel reads.
// Use `as any` to keep the test legible; runtime ignores unused fields.
function traceWithActions(action_payload: Record<string, unknown>): TurnTraceDetail {
  return {
    composer_output: { messages: [], action_payload },
  } as unknown as TurnTraceDetail;
}

describe("ActionsPanel", () => {
  it("renders one chip per action with a short preview", () => {
    const trace = traceWithActions({
      quote: { plan: "Premium", monto_mensual: 2400, plazo_meses: 12 },
      lookup_faq: { faq_id: "abc", question: "¿Qué documentos?", score: 0.91 },
    });
    render(<ActionsPanel trace={trace} />);
    expect(screen.getByText("quote")).toBeInTheDocument();
    expect(screen.getByText("lookup_faq")).toBeInTheDocument();
    // The preview text lives in the <summary>; the JSON drilldown
    // (rendered but collapsed inside <details>) also contains these
    // tokens, so we use getAllByText and assert at least one match.
    expect(screen.getAllByText(/Premium/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/¿Qué documentos\?/).length).toBeGreaterThan(0);
  });

  it("renders empty-state when action_payload is empty", () => {
    const trace = traceWithActions({});
    render(<ActionsPanel trace={trace} />);
    expect(screen.getByText(/sin acciones/i)).toBeInTheDocument();
  });

  it("renders empty-state when composer_output is null (legacy)", () => {
    const trace = { composer_output: null } as unknown as TurnTraceDetail;
    render(<ActionsPanel trace={trace} />);
    expect(screen.getByText(/sin acciones/i)).toBeInTheDocument();
  });
});

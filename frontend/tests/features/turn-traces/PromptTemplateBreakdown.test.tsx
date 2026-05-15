import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { PromptTemplateBreakdown } from "@/features/turn-traces/components/TurnPanels";

const SAMPLE_PROMPT = `### IDENTIDAD
Eres Mariana, asesora de ventas. Trato cercano, sin promesas vagas.

### REGLAS QUE NO PUEDES ROMPER
- No inventes precios.
- No prometas plazos sin confirmar disponibilidad.

### CONOCIMIENTO DEL TENANT
FAQ 1: Lorem ipsum dolor sit amet, consectetur adipiscing elit.
FAQ 2: Sed do eiusmod tempor incididunt ut labore et dolore magna.

### CONTEXTO DEL CLIENTE
Nombre: Pedro
Plan actual: Premium`;

function traceWithPrompt(content: string | null): TurnTraceDetail {
  return {
    composer_input: content == null ? null : { messages: [{ role: "system", content }] },
  } as unknown as TurnTraceDetail;
}

describe("PromptTemplateBreakdown", () => {
  it("parses sections by ### markers and labels each one", () => {
    render(<PromptTemplateBreakdown trace={traceWithPrompt(SAMPLE_PROMPT)} />);
    expect(screen.getByText(/IDENTIDAD/i)).toBeInTheDocument();
    expect(screen.getByText(/REGLAS/i)).toBeInTheDocument();
    expect(screen.getByText(/CONOCIMIENTO/i)).toBeInTheDocument();
    expect(screen.getByText(/CONTEXTO/i)).toBeInTheDocument();
  });

  it("renders empty state when composer_input is null", () => {
    render(<PromptTemplateBreakdown trace={traceWithPrompt(null)} />);
    expect(screen.getByText(/sin prompt analizable/i)).toBeInTheDocument();
  });

  it("renders empty state when prompt has no markers", () => {
    render(<PromptTemplateBreakdown trace={traceWithPrompt("just plain text no markers")} />);
    expect(screen.getByText(/sin prompt analizable/i)).toBeInTheDocument();
  });
});

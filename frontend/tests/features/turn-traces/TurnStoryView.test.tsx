import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

describe("TurnStoryView", () => {
  it("renders empty state with a message", () => {
    render(<TurnStoryView steps={[]} />);
    expect(screen.getByText(/Sin pasos/i)).toBeInTheDocument();
  });

  it("renders inbound text", () => {
    const steps: StoryStep[] = [
      { kind: "inbound", text: "Hola, ¿cuánto cuesta?", hasMedia: false },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Hola, ¿cuánto cuesta?/)).toBeInTheDocument();
  });

  it("renders inbound media note when text is missing and hasMedia is true", () => {
    const steps: StoryStep[] = [{ kind: "inbound", text: null, hasMedia: true }];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/adjunto/i)).toBeInTheDocument();
  });

  it("renders nlu intent + entities", () => {
    const steps: StoryStep[] = [
      { kind: "nlu", intent: "ask_price", extracted: { brand: "Honda" } },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Pidió precio/)).toBeInTheDocument();
    expect(screen.getByText(/Honda/)).toBeInTheDocument();
  });

  it("renders mode badge label", () => {
    const steps: StoryStep[] = [{ kind: "mode", mode: "SALES" }];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText("Ventas")).toBeInTheDocument();
  });

  it("renders tool summary and error states", () => {
    const steps: StoryStep[] = [
      {
        kind: "tool",
        toolName: "search_catalog",
        summary: "1 resultado: Civic",
        error: null,
      },
      { kind: "tool", toolName: "quote", summary: "", error: "missing SKU" },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Civic/)).toBeInTheDocument();
    expect(screen.getByText(/missing SKU/)).toBeInTheDocument();
  });

  it("renders outbound previews", () => {
    const steps: StoryStep[] = [
      {
        kind: "outbound",
        count: 2,
        previews: ["Saludo", "¿Apartas?"],
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Envió 2 mensajes/)).toBeInTheDocument();
    expect(screen.getByText(/Saludo/)).toBeInTheDocument();
    expect(screen.getByText(/¿Apartas\?/)).toBeInTheDocument();
  });

  it("renders stage transition with from and to", () => {
    const steps: StoryStep[] = [{ kind: "transition", from: "lead_warm", to: "quote_sent" }];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText("lead_warm")).toBeInTheDocument();
    expect(screen.getByText("quote_sent")).toBeInTheDocument();
  });
});

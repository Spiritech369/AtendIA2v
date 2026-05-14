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

  it("renders nlu intent with a confidence bar and entity count", () => {
    const steps: StoryStep[] = [
      { kind: "nlu", intent: "ask_price", confidence: 0.87, entityCount: 2 },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Pidió precio/)).toBeInTheDocument();
    expect(screen.getByText(/87%/)).toBeInTheDocument();
    expect(screen.getByText(/2 entidades/)).toBeInTheDocument();
  });

  it("renders mode badge label and rationale", () => {
    const steps: StoryStep[] = [
      { kind: "mode", mode: "SALES", rationale: "acción decidida: quote" },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText("Ventas")).toBeInTheDocument();
    expect(screen.getByText(/quote/)).toBeInTheDocument();
  });

  it("renders knowledge hits with score values", () => {
    const steps: StoryStep[] = [
      {
        kind: "knowledge",
        action: "lookup_faq",
        hits: [
          { source: "faq", title: "¿Aceptan transferencia?", score: 0.84 },
          { source: "faq", title: "¿Cuál es el horario?", score: 0.71 },
        ],
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/Conocimiento consultado/)).toBeInTheDocument();
    expect(screen.getByText(/transferencia/)).toBeInTheDocument();
    expect(screen.getByText(/0\.84/)).toBeInTheDocument();
  });

  it("renders knowledge emptyHint when no hits", () => {
    const steps: StoryStep[] = [
      {
        kind: "knowledge",
        action: "lookup_faq",
        hits: [],
        emptyHint: "no FAQ above similarity threshold 0.5",
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/similarity threshold/i)).toBeInTheDocument();
  });

  it("renders composer outbound messages", () => {
    const steps: StoryStep[] = [
      {
        kind: "composer",
        model: "gpt-4o",
        latencyMs: 1100,
        costUsd: 0.0014,
        messages: ["Saludo", "¿Apartas?"],
        pendingConfirmation: null,
        rawLlmResponse: null,
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText("Saludo")).toBeInTheDocument();
    expect(screen.getByText("¿Apartas?")).toBeInTheDocument();
    expect(screen.getByText(/gpt-4o/)).toBeInTheDocument();
  });

  it("surfaces a raw-vs-final toggle when raw_llm_response differs from messages", () => {
    const steps: StoryStep[] = [
      {
        kind: "composer",
        model: "gpt-4o",
        latencyMs: 1100,
        costUsd: 0.0014,
        messages: ["Saludo"],
        pendingConfirmation: null,
        // Raw differs (extra trailing chunk) — diff toggle should render.
        rawLlmResponse: '{"messages":["Saludo"],"debug":"trailing"}',
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/raw LLM/i)).toBeInTheDocument();
  });

  it("renders stage transition with from and to", () => {
    const steps: StoryStep[] = [{ kind: "transition", from: "lead_warm", to: "quote_sent" }];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText("lead_warm")).toBeInTheDocument();
    expect(screen.getByText("quote_sent")).toBeInTheDocument();
  });
});

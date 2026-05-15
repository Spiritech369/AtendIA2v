import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

const baseComposer: Extract<StoryStep, { kind: "composer" }> = {
  kind: "composer",
  messages: ["hola"],
  model: "gpt-4o",
  latencyMs: 100,
  costUsd: 0.001,
  pendingConfirmation: null,
  rawLlmResponse: null,
  provider: "openai",
  agentName: null,
  agentRole: null,
};

describe("StepComposer agent name + role", () => {
  it("renders agent name + role when both present", () => {
    render(
      <TurnStoryView steps={[{ ...baseComposer, agentName: "Mariana", agentRole: "Ventas" }]} />,
    );
    expect(screen.getByText(/Mariana/)).toBeInTheDocument();
    expect(screen.getByText(/Ventas/)).toBeInTheDocument();
  });

  it("renders only the name when role is null", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, agentName: "Mariana", agentRole: null }]} />);
    expect(screen.getByText(/Mariana/)).toBeInTheDocument();
  });

  it("omits the agent line when no name is provided", () => {
    render(<TurnStoryView steps={[baseComposer]} />);
    expect(screen.queryByText(/Agente:/i)).not.toBeInTheDocument();
  });
});

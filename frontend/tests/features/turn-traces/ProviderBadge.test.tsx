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
};

describe("StepComposer provider badge", () => {
  it("renders an 'openai' badge when provider is openai", () => {
    render(<TurnStoryView steps={[baseComposer]} />);
    expect(screen.getByText(/openai/i)).toBeInTheDocument();
  });
  it("renders a 'canned' badge when provider is canned", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, provider: "canned" }]} />);
    expect(screen.getByText(/canned/i)).toBeInTheDocument();
  });
  it("renders a 'fallback' badge when provider is fallback", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, provider: "fallback" }]} />);
    expect(screen.getByText(/fallback/i)).toBeInTheDocument();
  });
  it("omits the badge when provider is null (legacy rows)", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, provider: null }]} />);
    expect(screen.queryByText(/^openai|^canned|^fallback/i)).not.toBeInTheDocument();
  });
});

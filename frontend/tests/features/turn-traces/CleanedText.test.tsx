import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

const baseInbound: Extract<StoryStep, { kind: "inbound" }> = {
  kind: "inbound",
  text: "¡HOLA!",
  cleanedText: "hola",
  hasMedia: false,
  turnNumber: 1,
  totalTurns: 1,
};

describe("StepInbound cleaned-text card", () => {
  it("shows the cleaned text in a secondary card when it differs from the raw", () => {
    render(<TurnStoryView steps={[baseInbound]} />);
    // The cleaned text appears below the raw bubble — wrapped in
    // guillemets so the operator can see it's a literal string.
    expect(screen.getByText(/«hola»/)).toBeInTheDocument();
    // A small label identifies what the secondary card is.
    expect(screen.getByText(/texto limpio/i)).toBeInTheDocument();
  });

  it("hides the secondary card when cleaned equals raw (no clutter)", () => {
    render(<TurnStoryView steps={[{ ...baseInbound, text: "hola", cleanedText: "hola" }]} />);
    expect(screen.queryByText(/texto limpio/i)).not.toBeInTheDocument();
  });

  it("hides the secondary card when cleanedText is null (legacy rows)", () => {
    render(<TurnStoryView steps={[{ ...baseInbound, cleanedText: null }]} />);
    expect(screen.queryByText(/texto limpio/i)).not.toBeInTheDocument();
  });
});

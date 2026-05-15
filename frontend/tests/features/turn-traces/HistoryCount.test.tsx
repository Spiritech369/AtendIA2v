import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

describe("StepInbound history count chip", () => {
  it("renders 'turno 3 de 12' format chip when totalTurns is known", () => {
    const steps: StoryStep[] = [
      {
        kind: "inbound",
        text: "hola",
        hasMedia: false,
        turnNumber: 3,
        totalTurns: 12,
        cleanedText: null,
      },
    ];
    render(<TurnStoryView steps={steps} />);
    // The chip uses a compact "N / M" format so it fits in the
    // primary line without crowding. Title attribute carries the
    // long form for hover.
    expect(screen.getByText("3 / 12")).toBeInTheDocument();
  });

  it("omits the chip when totalTurns is null (degrades cleanly)", () => {
    const steps: StoryStep[] = [
      {
        kind: "inbound",
        text: "hola",
        hasMedia: false,
        turnNumber: 1,
        totalTurns: null,
        cleanedText: null,
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.queryByText(/ \/ /)).not.toBeInTheDocument();
  });
});

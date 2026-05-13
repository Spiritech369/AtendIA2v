import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FlowModeBadge } from "@/features/turn-traces/components/FlowModeBadge";

describe("FlowModeBadge", () => {
  it("renders friendly label for known mode", () => {
    render(<FlowModeBadge mode="SALES" />);
    expect(screen.getByText("Ventas")).toBeInTheDocument();
  });

  it("renders all six known modes", () => {
    const modes: Array<[string, string]> = [
      ["PLAN", "Planes"],
      ["DOC", "Documentos"],
      ["OBSTACLE", "Obstáculo"],
      ["RETENTION", "Retención"],
      ["SUPPORT", "Soporte"],
    ];
    for (const [mode, label] of modes) {
      const { unmount } = render(<FlowModeBadge mode={mode} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("falls back to raw mode for unknown values", () => {
    render(<FlowModeBadge mode="WEIRD_NEW_MODE" />);
    expect(screen.getByText("WEIRD_NEW_MODE")).toBeInTheDocument();
  });

  it("shows em-dash when mode is null", () => {
    render(<FlowModeBadge mode={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

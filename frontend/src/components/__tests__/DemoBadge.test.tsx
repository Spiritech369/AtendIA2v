import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DemoBadge } from "../DemoBadge";

describe("DemoBadge", () => {
  it("renders the Demo chip", () => {
    render(<DemoBadge />);
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });

  it("has the demo tooltip", () => {
    render(<DemoBadge />);
    const chip = screen.getByTitle(/Datos de demostración/i);
    expect(chip).toBeInTheDocument();
  });

  it("wrap mode renders children", () => {
    render(
      <DemoBadge wrap>
        <span>child content</span>
      </DemoBadge>
    );
    expect(screen.getByText("child content")).toBeInTheDocument();
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });
});

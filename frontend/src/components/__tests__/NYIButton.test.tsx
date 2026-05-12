import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { NYIButton } from "../NYIButton";

describe("NYIButton", () => {
  it("renders with the given label", () => {
    render(<NYIButton label="Importar CSV" />);
    expect(screen.getByText("Importar CSV")).toBeInTheDocument();
  });

  it("has the NYI tooltip", () => {
    render(<NYIButton label="Importar CSV" />);
    const btn = screen.getByTitle(/Feature en construcción/i);
    expect(btn).toBeInTheDocument();
  });
});

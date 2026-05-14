import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Sprint B.2 — NYIButton is hidden by default. Setting VITE_SHOW_NYI=true
 * surfaces it for dev review. These tests pin both branches.
 *
 * The component reads `import.meta.env.VITE_SHOW_NYI` at module load,
 * so toggling the env requires a fresh dynamic import per test.
 */
describe("NYIButton", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  describe("default (production) — VITE_SHOW_NYI unset", () => {
    beforeEach(() => {
      vi.stubEnv("VITE_SHOW_NYI", "");
    });

    it("renders nothing so users don't see aspirational chrome", async () => {
      const { NYIButton } = await import("../NYIButton");
      const { container } = render(<NYIButton label="Importar CSV" />);
      expect(container.firstChild).toBeNull();
      expect(screen.queryByText("Importar CSV")).not.toBeInTheDocument();
    });
  });

  describe("dev mode — VITE_SHOW_NYI=true", () => {
    beforeEach(() => {
      vi.stubEnv("VITE_SHOW_NYI", "true");
    });

    it("renders with the given label", async () => {
      const { NYIButton } = await import("../NYIButton");
      render(<NYIButton label="Importar CSV" />);
      expect(screen.getByText("Importar CSV")).toBeInTheDocument();
    });

    it("has the NYI tooltip", async () => {
      const { NYIButton } = await import("../NYIButton");
      render(<NYIButton label="Importar CSV" />);
      const btn = screen.getByTitle(/Feature en construcción/i);
      expect(btn).toBeInTheDocument();
    });
  });
});

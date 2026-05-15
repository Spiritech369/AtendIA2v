import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { ContactPanel } from "@/features/conversations/components/ContactPanel";

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const COLLAPSE = /colapsar panel/i;
const EXPAND = /expandir inteligencia del cliente/i;

describe("ContactPanel collapse", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts expanded and collapses on click", async () => {
    const user = userEvent.setup();
    render(<ContactPanel customerId={undefined} conversation={undefined} />, {
      wrapper: wrap(),
    });
    expect(screen.getByRole("button", { name: COLLAPSE })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: COLLAPSE }));
    expect(screen.getByRole("button", { name: EXPAND })).toBeInTheDocument();
  });

  it("persists the collapsed state across remount", async () => {
    const user = userEvent.setup();
    const view = render(<ContactPanel customerId={undefined} conversation={undefined} />, {
      wrapper: wrap(),
    });
    await user.click(screen.getByRole("button", { name: COLLAPSE }));
    expect(screen.getByRole("button", { name: EXPAND })).toBeInTheDocument();

    // Simulate the panel being unmounted (e.g. operator opens DebugPanel)
    // and later remounted. The collapse preference must survive.
    view.unmount();
    render(<ContactPanel customerId={undefined} conversation={undefined} />, {
      wrapper: wrap(),
    });
    expect(screen.getByRole("button", { name: EXPAND })).toBeInTheDocument();
  });
});

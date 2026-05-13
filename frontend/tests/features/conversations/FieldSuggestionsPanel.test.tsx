import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { fieldSuggestionsApi } from "@/features/conversations/api";
import { FieldSuggestionsPanel } from "@/features/conversations/components/FieldSuggestionsPanel";

const customerId = "11111111-1111-1111-1111-111111111111";

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const sample = {
  id: "s1",
  customer_id: customerId,
  conversation_id: null,
  turn_number: 1,
  key: "plan_credito",
  suggested_value: "10",
  confidence: "0.85",
  evidence_text: "Quiero el plan del 10%",
  status: "pending" as const,
  created_at: "2026-05-13T00:00:00Z",
  decided_at: null,
};

describe("FieldSuggestionsPanel", () => {
  it("renders nothing when there are no suggestions", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([]);
    const { container } = render(
      <FieldSuggestionsPanel customerId={customerId} />,
      { wrapper: wrap() },
    );
    await waitFor(() => expect(fieldSuggestionsApi.list).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("renders a card per suggestion with label + confidence + evidence", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([sample]);
    render(<FieldSuggestionsPanel customerId={customerId} />, {
      wrapper: wrap(),
    });
    await waitFor(() => {
      expect(screen.getByText("Plan de crédito")).toBeInTheDocument();
    });
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText(/Quiero el plan del 10%/)).toBeInTheDocument();
  });

  it("clicking Aceptar calls the accept api", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([sample]);
    const acceptSpy = vi
      .spyOn(fieldSuggestionsApi, "accept")
      .mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(<FieldSuggestionsPanel customerId={customerId} />, {
      wrapper: wrap(),
    });
    await waitFor(() =>
      expect(screen.getByText("Plan de crédito")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /aceptar/i }));
    expect(acceptSpy).toHaveBeenCalledWith("s1");
  });

  it("clicking Rechazar calls the reject api", async () => {
    vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([sample]);
    const rejectSpy = vi
      .spyOn(fieldSuggestionsApi, "reject")
      .mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(<FieldSuggestionsPanel customerId={customerId} />, {
      wrapper: wrap(),
    });
    await waitFor(() =>
      expect(screen.getByText("Plan de crédito")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /rechazar/i }));
    expect(rejectSpy).toHaveBeenCalledWith("s1");
  });
});

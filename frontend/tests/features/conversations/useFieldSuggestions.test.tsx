import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { fieldSuggestionsApi } from "@/features/conversations/api";
import {
  useAcceptFieldSuggestion,
  useFieldSuggestions,
  useRejectFieldSuggestion,
} from "@/features/conversations/hooks/useFieldSuggestions";

const customerId = "11111111-1111-1111-1111-111111111111";

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useFieldSuggestions", () => {
  it("lists suggestions for the given customer", async () => {
    const spy = vi.spyOn(fieldSuggestionsApi, "list").mockResolvedValue([
      {
        id: "s1",
        customer_id: customerId,
        conversation_id: null,
        turn_number: 1,
        key: "plan_credito",
        suggested_value: "10",
        confidence: "0.85",
        evidence_text: null,
        status: "pending",
        created_at: "2026-05-13T00:00:00Z",
        decided_at: null,
      },
    ]);
    const { result } = renderHook(() => useFieldSuggestions(customerId), {
      wrapper: wrap(),
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.length).toBe(1);
    spy.mockRestore();
  });

  it("accept calls the accept endpoint", async () => {
    const spy = vi
      .spyOn(fieldSuggestionsApi, "accept")
      .mockResolvedValue({} as never);
    const { result } = renderHook(() => useAcceptFieldSuggestion(customerId), {
      wrapper: wrap(),
    });
    await act(async () => {
      await result.current.mutateAsync("s1");
    });
    expect(spy).toHaveBeenCalledWith("s1");
    spy.mockRestore();
  });

  it("reject calls the reject endpoint", async () => {
    const spy = vi
      .spyOn(fieldSuggestionsApi, "reject")
      .mockResolvedValue({} as never);
    const { result } = renderHook(() => useRejectFieldSuggestion(customerId), {
      wrapper: wrap(),
    });
    await act(async () => {
      await result.current.mutateAsync("s1");
    });
    expect(spy).toHaveBeenCalledWith("s1");
    spy.mockRestore();
  });
});

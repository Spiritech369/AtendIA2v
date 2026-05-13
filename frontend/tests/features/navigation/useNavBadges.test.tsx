import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { navigationApi } from "@/features/navigation/api";
import { useNavBadges } from "@/features/navigation/hooks";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useNavBadges", () => {
  it("returns counts on success", async () => {
    const spy = vi.spyOn(navigationApi, "getBadges").mockResolvedValue({
      conversations_open: 5,
      handoffs_open: 2,
      handoffs_overdue: 1,
      appointments_today: 3,
      ai_debug_warnings: 0,
      unread_notifications: 4,
    });
    const { result } = renderHook(() => useNavBadges(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => {
      expect(result.current.data?.conversations_open).toBe(5);
    });
    expect(result.current.data?.handoffs_overdue).toBe(1);
    spy.mockRestore();
  });

  it("returns undefined data on error without throwing", async () => {
    const spy = vi.spyOn(navigationApi, "getBadges").mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useNavBadges(), {
      wrapper: makeWrapper(),
    });
    // The hook does one retry — wait long enough for both attempts to fail.
    await waitFor(
      () => {
        expect(result.current.isError).toBe(true);
      },
      { timeout: 5000 },
    );
    expect(result.current.data).toBeUndefined();
    spy.mockRestore();
  });
});

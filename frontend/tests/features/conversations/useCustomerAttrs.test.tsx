import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useCustomerAttrs } from "@/features/conversations/hooks/useCustomerAttrs";
import { customersApi } from "@/features/customers/api";

const customerId = "11111111-1111-1111-1111-111111111111";

function makeWrapper(seed?: Record<string, unknown>) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (seed) {
    qc.setQueryData(["customer", customerId], { id: customerId, attrs: seed });
  }
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return { qc, Wrapper };
}

describe("useCustomerAttrs", () => {
  it("patchAttr merges with current attrs (read-modify-write)", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const { Wrapper } = makeWrapper({ foo: "1", bar: "2" });
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.patchAttr.mutateAsync({ key: "baz", value: "3" });
    });
    expect(spy).toHaveBeenCalledWith(customerId, {
      attrs: { foo: "1", bar: "2", baz: "3" },
    });
    spy.mockRestore();
  });

  it("deleteAttr removes the key from current attrs", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const { Wrapper } = makeWrapper({ foo: "1", bar: "2" });
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.deleteAttr.mutateAsync("foo");
    });
    expect(spy).toHaveBeenCalledWith(customerId, { attrs: { bar: "2" } });
    spy.mockRestore();
  });

  it("patchAttr handles missing customer in cache (treats as empty attrs)", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const { Wrapper } = makeWrapper(undefined);
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.patchAttr.mutateAsync({ key: "x", value: "1" });
    });
    expect(spy).toHaveBeenCalledWith(customerId, { attrs: { x: "1" } });
    spy.mockRestore();
  });

  it("patchAttr overwrites existing key, preserving siblings", async () => {
    const spy = vi.spyOn(customersApi, "patch").mockResolvedValue({} as never);
    const { Wrapper } = makeWrapper({ foo: "old", bar: "keep" });
    const { result } = renderHook(() => useCustomerAttrs(customerId), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.patchAttr.mutateAsync({ key: "foo", value: "new" });
    });
    expect(spy).toHaveBeenCalledWith(customerId, {
      attrs: { foo: "new", bar: "keep" },
    });
    spy.mockRestore();
  });
});

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { type CustomerDetail, customersApi } from "@/features/customers/api";

/**
 * Reads the current attrs dict from the TanStack cache, applies a single
 * key change, and PATCHes the whole dict.
 *
 * Required because the backend replaces `attrs` on PATCH — see
 * `test_patch_customer_attrs_replaces_whole_dict`.
 */
export function useCustomerAttrs(customerId: string) {
  const qc = useQueryClient();

  function currentAttrs(): Record<string, unknown> {
    const cached = qc.getQueryData<CustomerDetail>(["customer", customerId]);
    return (cached?.attrs as Record<string, unknown> | undefined) ?? {};
  }

  const patchAttr = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const next = { ...currentAttrs(), [key]: value };
      return customersApi.patch(customerId, { attrs: next });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) =>
      toast.error("Error al guardar el campo", {
        description: (e as Error).message,
      }),
  });

  const deleteAttr = useMutation({
    mutationFn: async (key: string) => {
      const next = { ...currentAttrs() };
      delete next[key];
      return customersApi.patch(customerId, { attrs: next });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    },
    onError: (e) =>
      toast.error("Error al eliminar el campo", {
        description: (e as Error).message,
      }),
  });

  return { patchAttr, deleteAttr };
}

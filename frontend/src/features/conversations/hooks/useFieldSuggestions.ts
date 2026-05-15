import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { fieldSuggestionsApi } from "@/features/conversations/api";

/**
 * Lists pending NLU suggestions for a customer. C11 — refreshed in
 * realtime by useTenantStream (WS) on message_received /
 * field_extracted / field_updated, plus a resync on socket reconnect.
 * The old 60s refetchInterval poll is gone.
 */
export function useFieldSuggestions(customerId: string | undefined) {
  return useQuery({
    queryKey: ["field-suggestions", customerId],
    queryFn: () => fieldSuggestionsApi.list(customerId as string),
    enabled: !!customerId,
  });
}

export function useAcceptFieldSuggestion(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (suggestionId: string) => fieldSuggestionsApi.accept(suggestionId),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["field-suggestions", customerId],
      });
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
      toast.success("Sugerencia aplicada");
    },
    onError: (e) => toast.error("Error al aceptar", { description: e.message }),
  });
}

export function useRejectFieldSuggestion(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (suggestionId: string) => fieldSuggestionsApi.reject(suggestionId),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["field-suggestions", customerId],
      });
    },
    onError: (e) => toast.error("Error al rechazar", { description: e.message }),
  });
}

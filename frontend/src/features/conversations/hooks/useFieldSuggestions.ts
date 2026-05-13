import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { fieldSuggestionsApi } from "@/features/conversations/api";

/**
 * Lists pending NLU suggestions for a customer. Polls every 60s so
 * a new suggestion landing mid-conversation appears without manual
 * refresh.
 */
export function useFieldSuggestions(customerId: string | undefined) {
  return useQuery({
    queryKey: ["field-suggestions", customerId],
    queryFn: () => fieldSuggestionsApi.list(customerId as string),
    enabled: !!customerId,
    refetchInterval: 60_000,
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

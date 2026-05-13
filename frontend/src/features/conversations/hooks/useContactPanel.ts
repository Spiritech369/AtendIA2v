import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { conversationsApi } from "@/features/conversations/api";
import { type CustomerPatch, customersApi, fieldsApi, notesApi } from "@/features/customers/api";

export function useCustomerDetail(customerId: string | undefined) {
  return useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => customersApi.getOne(customerId!),
    enabled: !!customerId,
  });
}

export function usePatchCustomer(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CustomerPatch) => customersApi.patch(customerId, body),
    onSuccess: () => {
      toast.success("Cliente actualizado");
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error("Error al guardar", { description: e.message }),
  });
}

export function useCustomerNotes(customerId: string | undefined) {
  return useQuery({
    queryKey: ["customer-notes", customerId],
    queryFn: () => notesApi.list(customerId!),
    enabled: !!customerId,
  });
}

export function useCreateNote(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { content: string; pinned?: boolean }) => notesApi.create(customerId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer-notes", customerId] });
    },
    onError: (e) => toast.error("Error al crear nota", { description: e.message }),
  });
}

export function useUpdateNote(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ noteId, ...body }: { noteId: string; content?: string; pinned?: boolean }) =>
      notesApi.update(customerId, noteId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer-notes", customerId] });
    },
    onError: (e) => toast.error("Error al actualizar nota", { description: e.message }),
  });
}

export function useDeleteNote(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (noteId: string) => notesApi.delete(customerId, noteId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["customer-notes", customerId] });
    },
    onError: (e) => toast.error("Error al eliminar nota", { description: e.message }),
  });
}

export function useFieldDefinitions() {
  return useQuery({
    queryKey: ["field-definitions"],
    queryFn: () => fieldsApi.listDefinitions(),
  });
}

export function useFieldValues(customerId: string | undefined) {
  return useQuery({
    queryKey: ["field-values", customerId],
    queryFn: () => fieldsApi.getValues(customerId!),
    enabled: !!customerId,
  });
}

export function usePutFieldValues(customerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, string | null>) => fieldsApi.putValues(customerId, values),
    onSuccess: () => {
      toast.success("Campos actualizados");
      void qc.invalidateQueries({ queryKey: ["field-values", customerId] });
    },
    onError: (e) => toast.error("Error al guardar campos", { description: e.message }),
  });
}

/**
 * PATCH /conversations/:id — for editing stage/assigned_user/assigned_agent
 * from the contact panel. Invalidates both the per-conversation query and
 * the conversations list so the inbox refreshes.
 */
export function usePatchConversation(conversationId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      current_stage?: string;
      assigned_user_id?: string | null;
      assigned_agent_id?: string | null;
    }) => {
      if (!conversationId) throw new Error("conversationId required");
      return conversationsApi.patchConversation(conversationId, body);
    },
    onSuccess: () => {
      if (conversationId) {
        void qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
      }
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error("Error al actualizar conversación", { description: e.message }),
  });
}

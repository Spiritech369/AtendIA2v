import { api } from "@/lib/api-client";

export interface CustomerListItem {
  id: string;
  tenant_id: string;
  phone_e164: string;
  name: string | null;
  created_at: string;
  conversation_count: number;
}

export interface ConversationSummary {
  id: string;
  current_stage: string;
  status: string;
  last_activity_at: string;
  total_cost_usd: string;
}

export interface CustomerDetail extends CustomerListItem {
  attrs: Record<string, unknown>;
  conversations: ConversationSummary[];
  last_extracted_data: Record<string, unknown>;
  total_cost_usd: string;
}

export interface CustomerPatch {
  name?: string;
  attrs?: Record<string, unknown>;
}

export interface CustomerNote {
  id: string;
  customer_id: string;
  tenant_id: string;
  author_user_id: string | null;
  author_email: string | null;
  content: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface FieldDefinition {
  id: string;
  tenant_id: string;
  key: string;
  label: string;
  field_type: string;
  field_options: Record<string, unknown> | null;
  ordering: number;
  created_at: string;
}

export interface FieldValue {
  field_definition_id: string;
  key: string;
  value: string | null;
}

export const customersApi = {
  list: async (params: { q?: string; limit?: number } = {}) =>
    (await api.get<{ items: CustomerListItem[] }>("/customers", { params })).data,
  getOne: async (id: string) => (await api.get<CustomerDetail>(`/customers/${id}`)).data,
  patch: async (id: string, body: CustomerPatch) =>
    (await api.patch<CustomerDetail>(`/customers/${id}`, body)).data,
};

export const notesApi = {
  list: async (customerId: string) =>
    (await api.get<CustomerNote[]>(`/customers/${customerId}/notes`)).data,
  create: async (customerId: string, body: { content: string; pinned?: boolean }) =>
    (await api.post<CustomerNote>(`/customers/${customerId}/notes`, body)).data,
  update: async (customerId: string, noteId: string, body: { content?: string; pinned?: boolean }) =>
    (await api.patch<CustomerNote>(`/customers/${customerId}/notes/${noteId}`, body)).data,
  delete: async (customerId: string, noteId: string) =>
    api.delete(`/customers/${customerId}/notes/${noteId}`),
};

export const fieldsApi = {
  listDefinitions: async () =>
    (await api.get<FieldDefinition[]>("/customer-fields/definitions")).data,
  getValues: async (customerId: string) =>
    (await api.get<FieldValue[]>(`/customers/${customerId}/field-values`)).data,
  putValues: async (customerId: string, values: Record<string, string | null>) =>
    (await api.put<{ updated: number }>(`/customers/${customerId}/field-values`, { values })).data,
};

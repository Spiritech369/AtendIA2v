import { api } from "@/lib/api-client";

export interface CustomerListItem {
  id: string;
  tenant_id: string;
  phone_e164: string;
  name: string | null;
  score: number;
  created_at: string;
  conversation_count: number;
  effective_stage: string | null;
  last_activity_at: string | null;
  assigned_user_email: string | null;
}

export interface ConversationSummary {
  id: string;
  current_stage: string;
  status: string;
  last_activity_at: string;
  total_cost_usd: string;
}

export interface CustomerDetail extends CustomerListItem {
  email: string | null;
  attrs: Record<string, unknown>;
  conversations: ConversationSummary[];
  last_extracted_data: Record<string, unknown>;
  total_cost_usd: string;
}

export interface CustomerPatch {
  name?: string;
  email?: string | null;
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
  list: async (params: {
    q?: string;
    limit?: number;
    stage?: string;
    assigned_user_id?: string;
    sort_by?: string;
    sort_dir?: string;
  } = {}) =>
    (await api.get<{ items: CustomerListItem[] }>("/customers", { params })).data,
  getOne: async (id: string) => (await api.get<CustomerDetail>(`/customers/${id}`)).data,
  patch: async (id: string, body: CustomerPatch) =>
    (await api.patch<CustomerDetail>(`/customers/${id}`, body)).data,
  patchScore: async (id: string, score: number) =>
    (await api.patch<CustomerDetail>(`/customers/${id}/score`, { score })).data,
  importCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return (
      await api.post<{ created: number; updated: number; errors: string[] }>(
        "/customers/import",
        form,
      )
    ).data;
  },
  importPreview: async (file: File): Promise<CustomerImportPreview> => {
    const form = new FormData();
    form.append("file", file);
    return (
      await api.post<CustomerImportPreview>("/customers/import/preview", form)
    ).data;
  },
  exportCsvUrl: () => "/api/v1/customers/export",
};

export interface CustomerImportPreviewRow {
  row: number;
  phone: string;
  name: string | null;
  email: string | null;
  score: number | null;
  will: "create" | "update";
}

export interface CustomerImportPreview {
  valid_rows: CustomerImportPreviewRow[];
  errors: string[];
  total: number;
}

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

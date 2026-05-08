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

export const customersApi = {
  list: async (params: { q?: string; limit?: number } = {}) =>
    (await api.get<{ items: CustomerListItem[] }>("/customers", { params })).data,
  getOne: async (id: string) => (await api.get<CustomerDetail>(`/customers/${id}`)).data,
};

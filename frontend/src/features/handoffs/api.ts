import { api } from "@/lib/api-client";

export interface HandoffItem {
  id: string;
  conversation_id: string;
  tenant_id: string;
  reason: string;
  payload: Record<string, unknown> | null;
  assigned_user_id: string | null;
  status: "open" | "assigned" | "resolved";
  requested_at: string;
  resolved_at: string | null;
}

export interface HandoffListResponse {
  items: HandoffItem[];
  next_cursor: string | null;
}

export interface ListHandoffsParams {
  status?: "open" | "assigned" | "resolved";
  cursor?: string | null;
  limit?: number;
}

export const handoffsApi = {
  list: async (params: ListHandoffsParams = {}): Promise<HandoffListResponse> => {
    const { data } = await api.get<HandoffListResponse>("/handoffs", { params });
    return data;
  },
  assign: async (id: string, user_id: string): Promise<HandoffItem> => {
    const { data } = await api.post<HandoffItem>(`/handoffs/${id}/assign`, { user_id });
    return data;
  },
  resolve: async (id: string, note?: string): Promise<HandoffItem> => {
    const { data } = await api.post<HandoffItem>(`/handoffs/${id}/resolve`, {
      note: note ?? null,
    });
    return data;
  },
};

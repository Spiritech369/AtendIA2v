import { api } from "@/lib/api-client";

export interface ConversationListItem {
  id: string;
  tenant_id: string;
  customer_id: string;
  customer_phone: string;
  customer_name: string | null;
  status: string;
  current_stage: string;
  bot_paused: boolean;
  last_activity_at: string;
  last_message_text: string | null;
  last_message_direction: string | null;
  has_pending_handoff: boolean;
  assigned_user_id: string | null;
  assigned_user_email: string | null;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  unread_count: number;
  tags: string[];
}

export interface ConversationListResponse {
  items: ConversationListItem[];
  next_cursor: string | null;
}

export interface ConversationDetail extends ConversationListItem {
  created_at: string;
  extracted_data: Record<string, unknown>;
  pending_confirmation: string | null;
  last_intent: string | null;
  last_inbound_at: string | null;
  customer_fields: Array<{ key: string; label: string; field_type: string; value: string | null }>;
  customer_notes: Array<{
    id: string;
    author_email: string | null;
    content: string;
    source: string;
    pinned: boolean;
    created_at: string;
    updated_at: string;
  }>;
  required_docs: Array<{ field_name: string; label: string; present: boolean }>;
}

export interface MessageMedia {
  type: "image" | "audio" | "document" | "video";
  url: string;
  original_filename?: string;
  file_size?: number;
  mime_type?: string;
  caption?: string;
}

export interface MessageItem {
  id: string;
  conversation_id: string;
  direction: "inbound" | "outbound" | "system";
  text: string;
  metadata: Record<string, unknown>;
  created_at: string;
  sent_at: string | null;
}

export interface MessageListResponse {
  items: MessageItem[];
  next_cursor: string | null;
}

export interface ListConversationsParams {
  cursor?: string | null;
  limit?: number;
  status?: string;
  has_pending_handoff?: boolean;
  bot_paused?: boolean;
  assigned_user_id?: string;
  unassigned?: boolean;
  tag?: string;
}

export const conversationsApi = {
  list: async (params: ListConversationsParams = {}): Promise<ConversationListResponse> => {
    const { data } = await api.get<ConversationListResponse>("/conversations", { params });
    return data;
  },
  getOne: async (id: string): Promise<ConversationDetail> => {
    const { data } = await api.get<ConversationDetail>(`/conversations/${id}`);
    return data;
  },
  listMessages: async (
    id: string,
    params: { cursor?: string | null; limit?: number } = {},
  ): Promise<MessageListResponse> => {
    const { data } = await api.get<MessageListResponse>(`/conversations/${id}/messages`, {
      params,
    });
    return data;
  },
  patchConversation: async (
    id: string,
    body: {
      current_stage?: string;
      assigned_user_id?: string | null;
      assigned_agent_id?: string | null;
      tags?: string[];
    },
  ): Promise<unknown> => {
    const { data } = await api.patch(`/conversations/${id}`, body);
    return data;
  },
  deleteConversation: async (id: string): Promise<void> => {
    await api.delete(`/conversations/${id}`);
  },
  markRead: async (id: string): Promise<void> => {
    await api.post(`/conversations/${id}/mark-read`);
  },
  forceSummary: async (id: string): Promise<{ status: string }> =>
    (await api.post<{ status: string }>(`/conversations/${id}/force-summary`)).data,
};

// ─────────────────────────────────────────────────────────────────────────────
// Field suggestions (NLU-derived pending values for customer.attrs)
// ─────────────────────────────────────────────────────────────────────────────

export interface FieldSuggestion {
  id: string;
  customer_id: string;
  conversation_id: string | null;
  turn_number: number | null;
  key: string;
  suggested_value: string;
  confidence: string;
  evidence_text: string | null;
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  decided_at: string | null;
}

export const fieldSuggestionsApi = {
  list: async (customerId: string): Promise<FieldSuggestion[]> =>
    (await api.get<FieldSuggestion[]>(`/customers/${customerId}/field-suggestions`)).data,
  accept: async (suggestionId: string): Promise<FieldSuggestion> =>
    (await api.post<FieldSuggestion>(`/field-suggestions/${suggestionId}/accept`)).data,
  reject: async (suggestionId: string): Promise<FieldSuggestion> =>
    (await api.post<FieldSuggestion>(`/field-suggestions/${suggestionId}/reject`)).data,
};

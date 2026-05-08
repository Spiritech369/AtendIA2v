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
};

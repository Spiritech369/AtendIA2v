import { api } from "@/lib/api-client";

export interface TurnTraceListItem {
  id: string;
  conversation_id: string;
  turn_number: number;
  inbound_message_id: string | null;
  /** First 120 chars of inbound_text — for scanning the list view. */
  inbound_preview: string | null;
  flow_mode: string | null;
  nlu_model: string | null;
  composer_model: string | null;
  total_cost_usd: string;
  total_latency_ms: number | null;
  bot_paused: boolean;
  created_at: string;
}

export interface ToolCallItem {
  id: string;
  tool_name: string;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown> | null;
  latency_ms: number | null;
  error: string | null;
  called_at: string;
}

export interface TurnTraceDetail extends TurnTraceListItem {
  inbound_text: string | null;
  nlu_input: Record<string, unknown> | null;
  nlu_output: Record<string, unknown> | null;
  nlu_tokens_in: number | null;
  nlu_tokens_out: number | null;
  nlu_cost_usd: string | null;
  nlu_latency_ms: number | null;
  composer_input: Record<string, unknown> | null;
  composer_output: Record<string, unknown> | null;
  composer_tokens_in: number | null;
  composer_tokens_out: number | null;
  composer_cost_usd: string | null;
  composer_latency_ms: number | null;
  vision_cost_usd: string | null;
  vision_latency_ms: number | null;
  tool_cost_usd: string | null;
  state_before: Record<string, unknown> | null;
  state_after: Record<string, unknown> | null;
  stage_transition: string | null;
  outbound_messages: unknown[] | null;
  errors: unknown[] | null;
  tool_calls: ToolCallItem[];
}

export const turnTracesApi = {
  list: async (conversationId: string): Promise<{ items: TurnTraceListItem[] }> =>
    (
      await api.get<{ items: TurnTraceListItem[] }>("/turn-traces", {
        params: { conversation_id: conversationId },
      })
    ).data,
  getOne: async (id: string): Promise<TurnTraceDetail> =>
    (await api.get<TurnTraceDetail>(`/turn-traces/${id}`)).data,
};

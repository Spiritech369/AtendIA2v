import { api } from "@/lib/api-client";

export interface TurnTraceListItem {
  id: string;
  conversation_id: string;
  turn_number: number;
  flow_mode: string | null;
  nlu_model: string | null;
  composer_model: string | null;
  total_cost_usd: string;
  total_latency_ms: number | null;
  bot_paused: boolean;
  created_at: string;
}

export interface TurnTraceDetail extends TurnTraceListItem {
  inbound_text: string | null;
  nlu_input: Record<string, unknown> | null;
  nlu_output: Record<string, unknown> | null;
  composer_input: Record<string, unknown> | null;
  composer_output: Record<string, unknown> | null;
  state_before: Record<string, unknown> | null;
  state_after: Record<string, unknown> | null;
  outbound_messages: unknown[] | null;
  stage_transition: string | null;
  errors: unknown[] | null;
  nlu_cost_usd: string | null;
  composer_cost_usd: string | null;
  tool_cost_usd: string | null;
  vision_cost_usd: string | null;
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

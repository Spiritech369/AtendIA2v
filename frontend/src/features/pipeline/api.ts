import { api } from "@/lib/api-client";

export interface PipelineConversationCard {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  last_message_text: string | null;
  last_activity_at: string;
  current_stage: string;
  is_stale: boolean;
}

export interface StageGroup {
  stage_id: string;
  stage_label: string;
  total_count: number;
  timeout_hours: number | null;
  /** True for the synthetic group of conversations whose ``current_stage``
   *  is no longer in the active pipeline (rename / removal in config). */
  is_orphan?: boolean;
  conversations: PipelineConversationCard[];
}

export interface BoardParams {
  assigned_user_id?: string;
}

export const pipelineApi = {
  board: async (params: BoardParams = {}) =>
    (await api.get<{ stages: StageGroup[] }>("/pipeline/board", { params })).data,
  alerts: async () =>
    (await api.get<{ items: PipelineConversationCard[] }>("/pipeline/alerts")).data,
};

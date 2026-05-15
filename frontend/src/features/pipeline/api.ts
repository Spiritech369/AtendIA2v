import { api } from "@/lib/api-client";

export interface PipelineConversationCard {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  last_message_text: string | null;
  last_activity_at: string;
  stage_entered_at: string | null;
  current_stage: string;
  assigned_user_id: string | null;
  assigned_user_email: string | null;
  lead_score: number;
  source: string | null;
  campaign: string | null;
  product: string | null;
  credit_type: string | null;
  financing_plan: string | null;
  estimated_value_mxn: number | null;
  document_done: number;
  document_total: number;
  document_percent: number;
  missing_documents: string[];
  appointment_at: string | null;
  appointment_status: string | null;
  appointment_service: string | null;
  has_pending_handoff: boolean;
  is_stale: boolean;
  risk_level: "normal" | "medio" | "alto" | string;
  risks: string[];
  next_best_action: string | null;
}

export interface StageGroup {
  stage_id: string;
  stage_label: string;
  total_count: number;
  timeout_hours: number | null;
  stage_color: string | null;
  stage_icon: string | null;
  is_terminal: boolean;
  health_score: number;
  total_value_mxn: number;
  stale_count: number;
  unassigned_count: number;
  docs_blocked_count: number;
  /** True for the synthetic group of conversations whose ``current_stage``
   *  is no longer in the active pipeline (rename / removal in config). */
  is_orphan?: boolean;
  conversations: PipelineConversationCard[];
}

export interface PipelineBoardResponse {
  stages: StageGroup[];
  updated_at: string;
  active_count: number;
  pending_handoffs: number;
  today_appointments: number;
  documents_blocked: number;
  credits_in_review: number;
  avg_response_seconds: number;
  ai_containment_rate: number;
}

export interface BoardParams {
  assigned_user_id?: string;
}

export const pipelineApi = {
  board: async (params: BoardParams = {}) =>
    (await api.get<PipelineBoardResponse>("/pipeline/board", { params })).data,
  /** Sprint C.3 — fetch the next page of a stage's conversations.
   * `offset` is the count of cards the caller already has. The backend
   * returns the same `StageGroup` shape with `conversations` shifted by
   * `offset` and `total_count` unchanged so the kanban can compare. */
  stagePage: async (stageId: string, params: { offset: number; limit?: number }) =>
    (
      await api.get<StageGroup>(`/pipeline/board/${encodeURIComponent(stageId)}`, {
        params: { offset: params.offset, limit: params.limit ?? 50 },
      })
    ).data,
  alerts: async () =>
    (await api.get<{ items: PipelineConversationCard[] }>("/pipeline/alerts")).data,
  move: async (body: { conversation_id: string; to_stage: string }) =>
    (
      await api.post<{ id: string; from_stage: string; current_stage: string; validated: boolean }>(
        "/pipeline/move",
        body,
      )
    ).data,
};

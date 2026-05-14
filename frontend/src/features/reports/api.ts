import { api } from "@/lib/api-client";

export interface ConversationsCounts {
  today: number;
  this_week: number;
  this_month: number;
}

export interface FirstResponseStat {
  avg_seconds: number | null;
  sample_size: number;
  window_days: number;
}

export interface HandoffStat {
  handoff_rate_pct: number;
  total_conversations: number;
  handed_off: number;
  window_days: number;
}

export interface FunnelStage {
  stage_id: string;
  label: string;
  current_count: number;
  reached_count: number;
  conversion_pct: number | null;
}

export interface ReportsOverview {
  conversations: ConversationsCounts;
  first_response: FirstResponseStat;
  handoff: HandoffStat;
  pipeline_funnel: FunnelStage[];
  tenant_timezone: string;
  generated_at: string;
}

export const reportsApi = {
  getOverview: async () => (await api.get<ReportsOverview>("/reports/overview")).data,
};

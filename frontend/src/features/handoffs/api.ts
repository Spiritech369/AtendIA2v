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

export type HandoffUrgency = "critical" | "high" | "medium" | "low";
export type HandoffStatus = "open" | "assigned" | "resolved" | "escalated";
export type SLAState = "healthy" | "warning" | "breached";
export type Sentiment = "positive" | "neutral" | "negative";
export type InsightTone = "good" | "warning" | "critical" | "info";
export type RiskSeverity = "low" | "medium" | "high" | "critical";

export interface PriorityBreakdown {
  score: number;
  urgency: HandoffUrgency;
  explanation: string[];
}

export interface HumanAgent {
  id: string;
  name: string;
  email: string;
  role: string;
  status: "online" | "offline" | "busy";
  max_active_cases: number;
  current_workload: number;
  skills: string[];
}

export interface AIAgent {
  id: string;
  name: string;
  purpose: string;
  confidence_avg: number;
  total_escalations: number;
  active: boolean;
}

export interface HandoffCommandItem {
  id: string;
  conversation_id: string;
  customer_id: string;
  customer_name: string;
  phone: string;
  channel: string;
  status: HandoffStatus;
  priority_score: number;
  urgency: HandoffUrgency;
  priority_explanation: string[];
  handoff_reason: string;
  detected_intent: string;
  ai_confidence: number;
  wait_time_seconds: number;
  sla_deadline: string;
  sla_status: SLAState;
  recommended_action: string;
  suggested_reply: string;
  why_triggered: string;
  risk_level: "low" | "medium" | "high";
  risk_explanation: string;
  missing_fields: string[];
  resolution_outcome: string | null;
  feedback_type: string | null;
  assigned_user_id: string | null;
  assigned_agent_name: string | null;
  suggested_agent_name: string;
  ai_agent_id: string;
  ai_agent_name: string;
  lifecycle_stage: string;
  estimated_value: number;
  sentiment: Sentiment;
  last_message: string;
  last_message_at: string;
  created_at: string;
  resolved_at: string | null;
  related_history: string[];
  knowledge_gap_topic: string | null;
  ai_rule: string;
}

export interface SummaryCards {
  open_handoffs: number;
  critical_cases: number;
  average_wait_seconds: number;
  sla_breaches: number;
  ai_confidence_alerts: number;
  high_value_leads_waiting: number;
  high_value_potential_mxn: number;
  unassigned_cases: number;
}

export interface InsightCard {
  id: string;
  label: string;
  value: string;
  detail: string;
  trend: string;
  sparkline: number[];
  tone: InsightTone;
}

export interface RiskRadarItem {
  id: string;
  title: string;
  value: string;
  detail: string;
  trend: string;
  severity: RiskSeverity;
  sparkline: number[];
}

export interface TimelineEvent {
  id: string;
  handoff_id: string;
  event_type: string;
  actor_type: "ai" | "human" | "system";
  actor_id: string | null;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface HandoffCommandCenterResponse {
  items: HandoffCommandItem[];
  total: number;
  summary: SummaryCards;
  insights: InsightCard[];
  risk_radar: RiskRadarItem[];
  human_agents: HumanAgent[];
  ai_agents: AIAgent[];
  updated_at: string;
}

export interface HandoffDetailResponse {
  handoff: HandoffCommandItem;
  timeline: TimelineEvent[];
}

export interface TimelineResponse {
  items: TimelineEvent[];
}

export interface AssignmentRecommendation {
  suggested_agent: HumanAgent;
  reason: string;
  workload_info: string;
}

export interface DraftResponse {
  draft: string;
  safety_notes: string[];
  source: "mock" | "stored";
}

export interface CommandCenterFilters {
  urgency?: HandoffUrgency | "all";
  reason?: string;
  agent?: string;
  waiting_time?: string;
  sla_status?: SLAState | "all";
  lifecycle_stage?: string;
  ai_agent?: string;
  channel?: string;
  sentiment?: Sentiment | "all";
  high_value_only?: boolean;
  status?: HandoffStatus | "all";
  sort?: string;
  q?: string;
}

export interface ResolveCommandBody {
  resolution_outcome: string;
  note?: string | null;
}

export interface FeedbackBody {
  feedback_type:
    | "correct_escalation"
    | "ai_should_have_answered"
    | "knowledge_gap"
    | "routing_issue"
    | "wrong_answer"
    | "policy_risk_avoided";
  note?: string | null;
}

function cleanParams(params: CommandCenterFilters): Record<string, string | boolean> {
  const cleaned: Record<string, string | boolean> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === "all") continue;
    cleaned[key] = value;
  }
  return cleaned;
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
  commandCenter: async (
    params: CommandCenterFilters = {},
  ): Promise<HandoffCommandCenterResponse> => {
    const { data } = await api.get<HandoffCommandCenterResponse>("/handoffs/command-center", {
      params: cleanParams(params),
    });
    return data;
  },
  commandDetail: async (id: string): Promise<HandoffDetailResponse> => {
    const { data } = await api.get<HandoffDetailResponse>(`/handoffs/command-center/${id}`);
    return data;
  },
  commandTimeline: async (id: string): Promise<TimelineResponse> => {
    const { data } = await api.get<TimelineResponse>(`/handoffs/command-center/${id}/timeline`);
    return data;
  },
  takeCommand: async (id: string): Promise<HandoffCommandItem> => {
    const { data } = await api.post<HandoffCommandItem>(`/handoffs/command-center/${id}/take`, {});
    return data;
  },
  assignCommand: async (id: string, user_id: string): Promise<HandoffCommandItem> => {
    const { data } = await api.post<HandoffCommandItem>(`/handoffs/command-center/${id}/assign`, {
      user_id,
    });
    return data;
  },
  resolveCommand: async (id: string, body: ResolveCommandBody): Promise<HandoffCommandItem> => {
    const { data } = await api.post<HandoffCommandItem>(
      `/handoffs/command-center/${id}/resolve`,
      body,
    );
    return data;
  },
  feedbackCommand: async (id: string, body: FeedbackBody): Promise<HandoffCommandItem> => {
    const { data } = await api.post<HandoffCommandItem>(
      `/handoffs/command-center/${id}/feedback`,
      body,
    );
    return data;
  },
  generateReply: async (id: string, extra_context?: string): Promise<DraftResponse> => {
    const { data } = await api.post<DraftResponse>(
      `/handoffs/command-center/${id}/generate-reply`,
      { extra_context: extra_context ?? null },
    );
    return data;
  },
  replyDraft: async (id: string, extra_context?: string): Promise<DraftResponse> => {
    const { data } = await api.post<DraftResponse>(`/handoffs/command-center/${id}/reply-draft`, {
      extra_context: extra_context ?? null,
    });
    return data;
  },
  recommendAgent: async (id: string): Promise<AssignmentRecommendation> => {
    const { data } = await api.post<AssignmentRecommendation>(
      `/handoffs/command-center/${id}/recommend-agent`,
      {},
    );
    return data;
  },
};

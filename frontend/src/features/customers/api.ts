import { api } from "@/lib/api-client";

export type ClientStage =
  | "new"
  | "in_conversation"
  | "qualified"
  | "negotiation"
  | "documentation"
  | "pending_handoff"
  | "closed_won"
  | "closed_lost"
  | "lost_risk";

export type RiskLevel = "low" | "medium" | "high" | "critical";
export type SlaStatus = "on_track" | "attention_soon" | "breached";

export interface CustomerListItem {
  id: string;
  tenant_id: string;
  phone_e164: string;
  name: string | null;
  email: string | null;
  score: number;
  health_score: number;
  status: string;
  stage: ClientStage | string;
  effective_stage: string | null;
  source: string | null;
  tags: string[];
  assigned_user_id: string | null;
  assigned_user_email: string | null;
  last_activity_at: string | null;
  created_at: string;
  updated_at: string | null;
  conversation_count: number;
  risk_level: RiskLevel | string;
  sla_status: SlaStatus | string;
  next_best_action: string | null;
  ai_summary: string | null;
  ai_insight_reason: string | null;
  ai_confidence: number | null;
  documents_status: string;
}

export interface ConversationSummary {
  id: string;
  current_stage: string;
  status: string;
  last_activity_at: string;
  total_cost_usd: string;
}

export interface CustomerScore {
  id: string;
  customer_id: string;
  tenant_id: string;
  total_score: number;
  intent_score: number;
  activity_score: number;
  documentation_score: number;
  data_quality_score: number;
  conversation_engagement_score: number;
  stage_progress_score: number;
  abandonment_risk_score: number;
  explanation: Record<string, unknown>;
  calculated_at: string;
}

export interface CustomerRisk {
  id: string;
  tenant_id: string;
  customer_id: string;
  risk_type: string;
  severity: RiskLevel | string;
  reason: string;
  recommended_action: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

export interface NextBestAction {
  id: string;
  tenant_id: string;
  customer_id: string;
  action_type: string;
  priority: number;
  reason: string;
  confidence: number;
  suggested_message: string | null;
  status: string;
  expires_at: string | null;
  created_at: string;
  executed_at: string | null;
}

export interface TimelineEvent {
  id: string;
  tenant_id: string;
  customer_id: string;
  event_type: string;
  title: string;
  description: string | null;
  actor_type: string;
  actor_id: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface CustomerDocument {
  id: string;
  tenant_id: string;
  customer_id: string;
  document_type: string;
  label: string;
  status: "missing" | "received" | "rejected" | "approved" | string;
  file_url: string | null;
  uploaded_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  direction: string;
  sender_type: string;
  body: string;
  confidence_score: number | null;
  intent_detected: string | null;
  objection_detected: string | null;
  related_workflow: string | null;
  sent_at: string;
}

export interface AIReviewItem {
  id: string;
  tenant_id: string;
  customer_id: string;
  conversation_id: string | null;
  issue_type: string;
  severity: RiskLevel | string;
  title: string;
  description: string | null;
  ai_summary: string | null;
  confidence: number | null;
  risky_output_flag: boolean;
  human_review_required: boolean;
  status: string;
  feedback_status: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface CustomerDetail extends CustomerListItem {
  attrs: Record<string, unknown>;
  conversations: ConversationSummary[];
  last_extracted_data: Record<string, unknown>;
  total_cost_usd: string;
  latest_score: CustomerScore | null;
  open_risks: CustomerRisk[];
  next_best_actions: NextBestAction[];
  timeline: TimelineEvent[];
  documents: CustomerDocument[];
  messages: ConversationMessage[];
  ai_review_items: AIReviewItem[];
}

export interface CustomerPatch {
  name?: string;
  email?: string | null;
  attrs?: Record<string, unknown>;
  status?: string;
  stage?: ClientStage;
  source?: string | null;
  tags?: string[];
  assigned_user_id?: string | null;
}

export interface CustomerCreate {
  phone_e164: string;
  name?: string | null;
  email?: string | null;
  source?: string | null;
  tags?: string[];
  stage?: ClientStage;
  attrs?: Record<string, unknown>;
}

export interface CustomerKpis {
  total_clients: number;
  clients_needing_attention: number;
  high_score_without_followup: number;
  at_risk_clients: number;
  unassigned_clients: number;
  documentation_pending: number;
  active_negotiations: number;
  ai_review_open: number;
}

export interface RadarItem {
  title: string;
  count: number;
  severity: RiskLevel | string;
  affected_client_ids: string[];
  recommended_action: string;
  action_link: string;
}

export interface RiskRadarResponse {
  items: RadarItem[];
  updated_at: string;
}

export interface CustomerNote {
  id: string;
  customer_id: string;
  tenant_id: string;
  author_user_id: string | null;
  author_email: string | null;
  content: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface FieldDefinition {
  id: string;
  tenant_id: string;
  key: string;
  label: string;
  field_type: string;
  field_options: Record<string, unknown> | null;
  ordering: number;
  created_at: string;
}

export interface FieldValue {
  field_definition_id: string;
  key: string;
  value: string | null;
}

export interface CustomerImportPreviewRow {
  row: number;
  phone: string;
  name: string | null;
  email: string | null;
  score: number | null;
  will: "create" | "update";
}

export interface CustomerImportPreview {
  valid_rows: CustomerImportPreviewRow[];
  errors: string[];
  total: number;
}

export const customersApi = {
  list: async (params: {
    q?: string;
    limit?: number;
    stage?: string;
    assigned_user_id?: string;
    risk_level?: string;
    sla_status?: string;
    sort_by?: string;
    sort_dir?: string;
  } = {}) =>
    (await api.get<{ items: CustomerListItem[] }>("/customers", { params })).data,
  getOne: async (id: string) => (await api.get<CustomerDetail>(`/customers/${id}`)).data,
  create: async (body: CustomerCreate) =>
    (await api.post<CustomerDetail>("/customers", body)).data,
  patch: async (id: string, body: CustomerPatch) =>
    (await api.patch<CustomerDetail>(`/customers/${id}`, body)).data,
  delete: async (id: string) => api.delete(`/customers/${id}`),
  patchScore: async (id: string, score: number) =>
    (await api.patch<CustomerDetail>(`/customers/${id}/score`, { score })).data,
  assign: async (id: string, assigned_user_id: string | null) =>
    (await api.post<CustomerDetail>(`/customers/${id}/assign`, { assigned_user_id })).data,
  changeStage: async (id: string, stage: ClientStage) =>
    (await api.post<CustomerDetail>(`/customers/${id}/change-stage`, { stage })).data,
  recalculateScore: async (id: string) =>
    (await api.post<CustomerScore>(`/customers/${id}/recalculate-score`)).data,
  risks: async (id: string) =>
    (await api.get<CustomerRisk[]>(`/customers/${id}/risks`)).data,
  nextBestAction: async (id: string) =>
    (await api.get<NextBestAction[]>(`/customers/${id}/next-best-action`)).data,
  executeAction: async (customerId: string, actionId: string) =>
    (await api.post<CustomerDetail>(`/customers/${customerId}/actions/${actionId}/execute`)).data,
  timeline: async (id: string) =>
    (await api.get<TimelineEvent[]>(`/customers/${id}/timeline`)).data,
  documents: async (id: string) =>
    (await api.get<CustomerDocument[]>(`/customers/${id}/documents`)).data,
  patchDocument: async (id: string, body: Partial<CustomerDocument>) =>
    (await api.patch<CustomerDocument>(`/documents/${id}`, body)).data,
  messages: async (id: string) =>
    (await api.get<ConversationMessage[]>(`/customers/${id}/messages`)).data,
  createMessage: async (id: string, body: { body: string; sender_type?: string }) =>
    (await api.post<ConversationMessage>(`/customers/${id}/messages`, body)).data,
  audit: async (id: string) => (await api.get(`/customers/${id}/audit`)).data,
  kpis: async () => (await api.get<CustomerKpis>("/dashboard/kpis")).data,
  riskRadar: async () => (await api.get<RiskRadarResponse>("/dashboard/risk-radar")).data,
  listRisks: async () => (await api.get<CustomerRisk[]>("/risks")).data,
  resolveRisk: async (id: string) => (await api.post<CustomerRisk>(`/risks/${id}/resolve`)).data,
  aiReviewQueue: async () =>
    (await api.get<{ items: AIReviewItem[] }>("/ai/review-queue")).data,
  resolveAIReview: async (id: string) =>
    (await api.post<AIReviewItem>(`/ai/review-queue/${id}/resolve`)).data,
  importCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return (
      await api.post<{ created: number; updated: number; errors: string[] }>(
        "/customers/import",
        form,
      )
    ).data;
  },
  importPreview: async (file: File): Promise<CustomerImportPreview> => {
    const form = new FormData();
    form.append("file", file);
    return (
      await api.post<CustomerImportPreview>("/customers/import/preview", form)
    ).data;
  },
  exportCsvUrl: () => "/api/v1/customers/export",
};

export const notesApi = {
  list: async (customerId: string) =>
    (await api.get<CustomerNote[]>(`/customers/${customerId}/notes`)).data,
  create: async (customerId: string, body: { content: string; pinned?: boolean }) =>
    (await api.post<CustomerNote>(`/customers/${customerId}/notes`, body)).data,
  update: async (customerId: string, noteId: string, body: { content?: string; pinned?: boolean }) =>
    (await api.patch<CustomerNote>(`/customers/${customerId}/notes/${noteId}`, body)).data,
  delete: async (customerId: string, noteId: string) =>
    api.delete(`/customers/${customerId}/notes/${noteId}`),
};

export const fieldsApi = {
  listDefinitions: async () =>
    (await api.get<FieldDefinition[]>("/customer-fields/definitions")).data,
  getValues: async (customerId: string) =>
    (await api.get<FieldValue[]>(`/customers/${customerId}/field-values`)).data,
  putValues: async (customerId: string, values: Record<string, string | null>) =>
    (await api.put<{ updated: number }>(`/customers/${customerId}/field-values`, { values })).data,
};

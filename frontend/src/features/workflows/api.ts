import { api } from "@/lib/api-client";

export interface WorkflowNode {
  id: string;
  type: string;
  title?: string | null;
  enabled?: boolean;
  config: Record<string, unknown>;
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[];
  edges: Array<{ from: string; to: string; label?: string }>;
  ops?: Record<string, unknown>;
}

export interface WorkflowHealth {
  score: number;
  status: "healthy" | "warning" | "critical" | "inactive" | string;
  reasons: string[];
  suggested_actions: string[];
}

export interface WorkflowMetrics {
  executions_today: number;
  success_rate: number;
  failure_rate: number;
  avg_duration_seconds: number;
  dropoff_rate: number;
  leads_affected_today: number;
  failed_handoffs: number;
  documents_blocked: number;
  missed_followups: number;
  appointments_not_confirmed: number;
  blocked_opportunity_mxn: number;
  critical_failures_24h: number;
  ai_low_confidence_events: number;
  last_run_minutes_ago: number;
  sparkline: number[];
}

export interface WorkflowVariable {
  name: string;
  raw_name: string;
  created_in: string;
  used_in: number[];
  last_value: string | null;
  status: "ok" | "faltante" | "error" | "opcional" | string;
}

export interface WorkflowDependency {
  type: string;
  name: string;
  status: "ok" | "warning" | "error" | "deleted" | "inactive" | string;
  details: Record<string, unknown>;
}

export interface ValidationIssue {
  code: string;
  severity: "critical" | "warning" | "ok" | string;
  message: string;
  node_id: string | null;
  area: string;
}

export interface WorkflowValidation {
  status: "ready" | "warning" | "blocked" | string;
  summary: string;
  critical_count: number;
  warning_count: number;
  ok_count: number;
  issues: ValidationIssue[];
  checks: Array<{ label: string; status: "ok" | "warning" | "error" | string }>;
}

export interface WorkflowVersion {
  id: string;
  version: number;
  status: string;
  editor: string;
  summary: string;
  published_at: string | null;
}

export interface WorkflowItem {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  definition: WorkflowDefinition;
  active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  status: string;
  health: WorkflowHealth;
  metrics: WorkflowMetrics;
  published_version: number;
  draft_version: number;
  last_editor: string | null;
  last_published_at: string | null;
  validation: WorkflowValidation;
  variables: WorkflowVariable[];
  dependencies: WorkflowDependency[];
  safety_rules: Record<string, boolean>;
  version_history: WorkflowVersion[];
  webhook_url: string | null;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  conversation_id: string | null;
  customer_id: string | null;
  trigger_event_id: string | null;
  status: string;
  current_node_id: string | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  error_code: string | null;
  workflow_version: number;
  lead_name: string | null;
  lead_phone: string | null;
  duration_seconds: number | null;
  result: string;
  failed_node: string | null;
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown>;
  replay: Array<{
    time: string | null;
    node_id: string;
    label: string;
    status: string;
    detail: string;
  }>;
}

export interface SimulationResult {
  activated_nodes: string[];
  generated_response: string;
  variables_saved: Record<string, unknown>;
  assigned_advisor: string | null;
  created_tasks: string[];
  warnings: string[];
  errors: string[];
  comparison: Record<string, unknown>;
}

export interface WorkflowTemplate {
  id: string;
  tenant_id: string;
  name: string;
  category: string;
  status: string;
  language: string;
  body: string;
  variables: string[];
  created_at: string;
  updated_at: string;
}

export interface PipelineStageDef {
  id: string;
  label: string;
  color: string | null;
}

export const pipelineStagesApi = {
  list: async () => (await api.get<PipelineStageDef[]>("/pipeline/stages")).data,
};

export const workflowsApi = {
  list: async () => (await api.get<WorkflowItem[]>("/workflows")).data,
  get: async (id: string) => (await api.get<WorkflowItem>(`/workflows/${id}`)).data,
  create: async (body: Partial<WorkflowItem>) =>
    (await api.post<WorkflowItem>("/workflows", body)).data,
  patch: async (id: string, body: Partial<WorkflowItem>) =>
    (await api.patch<WorkflowItem>(`/workflows/${id}`, body)).data,
  delete: async (id: string) => api.delete(`/workflows/${id}`),
  toggle: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/toggle`)).data,
  activate: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/activate`)).data,
  deactivate: async (id: string) =>
    (await api.post<WorkflowItem>(`/workflows/${id}/deactivate`)).data,
  duplicate: async (id: string) =>
    (await api.post<WorkflowItem>(`/workflows/${id}/duplicate`)).data,
  archive: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/archive`)).data,
  pause: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/pause`)).data,
  safePause: async (id: string, mode: string) =>
    (await api.post<WorkflowItem>(`/workflows/${id}/safe-pause`, { mode })).data,
  saveDraft: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/draft`)).data,
  publish: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/publish`)).data,
  restore: async (id: string, versionId: string) =>
    (await api.post<WorkflowItem>(`/workflows/${id}/restore/${versionId}`)).data,
  compare: async (id: string, from = "v12", to = "v13") =>
    (await api.get<Record<string, unknown>>(`/workflows/${id}/compare`, { params: { from, to } }))
      .data,
  addNode: async (
    id: string,
    body: { type: string; title?: string; config: Record<string, unknown> },
  ) => (await api.post<WorkflowItem>(`/workflows/${id}/nodes`, body)).data,
  patchNode: async (id: string, nodeId: string, body: Partial<WorkflowNode>) =>
    (await api.patch<WorkflowItem>(`/workflows/${id}/nodes/${nodeId}`, body)).data,
  deleteNode: async (id: string, nodeId: string) =>
    (await api.delete<WorkflowItem>(`/workflows/${id}/nodes/${nodeId}`)).data,
  duplicateNode: async (id: string, nodeId: string) =>
    (await api.post<WorkflowItem>(`/workflows/${id}/nodes/${nodeId}/duplicate`)).data,
  reorderNodes: async (id: string, nodeIds: string[]) =>
    (await api.post<WorkflowItem>(`/workflows/${id}/nodes/reorder`, { node_ids: nodeIds })).data,
  validate: async (id: string) =>
    (await api.post<WorkflowValidation>(`/workflows/${id}/validate`)).data,
  simulate: async (
    id: string,
    body: { sample_lead_id?: string; incoming_message: string; version: string },
  ) => (await api.post<SimulationResult>(`/workflows/${id}/simulate`, body)).data,
  executions: async (id: string) =>
    (await api.get<WorkflowExecution[]>(`/workflows/${id}/executions`)).data,
  execution: async (id: string) => (await api.get<WorkflowExecution>(`/executions/${id}`)).data,
  retryExecution: async (id: string) =>
    (await api.post<WorkflowExecution>(`/executions/${id}/retry`)).data,
  retryExecutionFromNode: async (id: string, nodeId: string) =>
    (
      await api.post<WorkflowExecution>(`/executions/${id}/retry-from-node`, null, {
        params: { node_id: nodeId },
      })
    ).data,
  replay: async (id: string) =>
    (await api.get<WorkflowExecution["replay"]>(`/executions/${id}/replay`)).data,
  exportExecution: async (id: string) =>
    (await api.get<Record<string, unknown>>(`/executions/${id}/export-json`)).data,
  templates: async () => (await api.get<WorkflowTemplate[]>("/templates")).data,
};

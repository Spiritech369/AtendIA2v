import { api } from "@/lib/api-client";

export interface WorkflowItem {
  id: string;
  name: string;
  description: string | null;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  definition: { nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>> };
  active: boolean;
  created_at: string;
}

export interface WorkflowExecution {
  id: string;
  status: string;
  current_node_id: string | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export const workflowsApi = {
  list: async () => (await api.get<WorkflowItem[]>("/workflows")).data,
  create: async (body: Partial<WorkflowItem>) =>
    (await api.post<WorkflowItem>("/workflows", body)).data,
  patch: async (id: string, body: Partial<WorkflowItem>) =>
    (await api.patch<WorkflowItem>(`/workflows/${id}`, body)).data,
  delete: async (id: string) => api.delete(`/workflows/${id}`),
  toggle: async (id: string) => (await api.post<WorkflowItem>(`/workflows/${id}/toggle`)).data,
  executions: async (id: string) =>
    (await api.get<WorkflowExecution[]>(`/workflows/${id}/executions`)).data,
};

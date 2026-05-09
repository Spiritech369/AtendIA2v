import { api } from "@/lib/api-client";

export interface AgentItem {
  id: string;
  name: string;
  role: string;
  goal: string | null;
  style: string | null;
  tone: string | null;
  language: string | null;
  max_sentences: number | null;
  no_emoji: boolean;
  return_to_flow: boolean;
  is_default: boolean;
  system_prompt: string | null;
  active_intents: string[];
  extraction_config: Record<string, unknown>;
  auto_actions: Record<string, unknown>;
  knowledge_config: Record<string, unknown>;
  flow_mode_rules: Record<string, unknown> | null;
}

export type AgentPayload = Omit<AgentItem, "id">;

export const agentsApi = {
  list: async () => (await api.get<AgentItem[]>("/agents")).data,
  create: async (body: Partial<AgentPayload>) => (await api.post<AgentItem>("/agents", body)).data,
  patch: async (id: string, body: Partial<AgentPayload>) =>
    (await api.patch<AgentItem>(`/agents/${id}`, body)).data,
  delete: async (id: string) => api.delete(`/agents/${id}`),
  test: async (agent_config: Record<string, unknown>, message: string) =>
    (await api.post<{ response: string; flow_mode: string; intent: string }>("/agents/test", {
      agent_config,
      message,
    })).data,
};

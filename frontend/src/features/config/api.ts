import { type InboxConfig, normalizeInboxConfig } from "@/features/inbox-settings/types";
import { api } from "@/lib/api-client";

export interface PipelineResponse {
  version: number;
  definition: Record<string, unknown>;
  active: boolean;
  created_at: string;
}

export interface BrandFactsResponse {
  brand_facts: Record<string, string>;
}

export interface ToneResponse {
  voice: Record<string, unknown>;
}

export interface TimezoneResponse {
  timezone: string;
}

export interface WhatsAppDetails {
  phone_number: string | null;
  business_name: string | null;
  phone_number_id: string | null;
  business_id: string | null;
  verify_token: string | null;
  webhook_path: string;
  last_webhook_at: string | null;
  circuit_breaker_open: boolean;
}

export interface AIProviderInfo {
  nlu_provider: string;
  nlu_model: string;
  composer_provider: string;
  composer_model: string;
  has_openai_key: boolean;
}

export interface WorkflowReference {
  workflow_id: string;
  name: string;
  active: boolean;
  reference_kind: "trigger" | "move_stage_node";
  detail: string;
}

export interface StageImpactResponse {
  stage_id: string;
  conversation_count: number;
  workflow_references: WorkflowReference[];
}

export interface AuditLogEntry {
  id: string;
  type: string;
  occurred_at: string;
  actor_user_id: string | null;
  payload: Record<string, unknown>;
  conversation_id: string | null;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  has_more: boolean;
}

// P1 — pipeline version history. Each PUT snapshots the new definition
// into `tenant_pipelines.history` (capped at 10 by the backend). The
// list endpoint returns metadata only; the detail endpoint returns the
// full nested definition for diff/restore.

export interface PipelineVersionListItem {
  index: number;
  captured_at: string;
  captured_by: string | null;
  stage_count: number;
  is_current: boolean;
}

export interface PipelineVersionDetail extends PipelineVersionListItem {
  definition: Record<string, unknown>;
}

export const tenantsApi = {
  getPipeline: async () => (await api.get<PipelineResponse>("/tenants/pipeline")).data,
  putPipeline: async (definition: Record<string, unknown>) =>
    (await api.put<PipelineResponse>("/tenants/pipeline", { definition })).data,
  deletePipeline: async () => {
    await api.delete("/tenants/pipeline");
  },
  getStageImpact: async (stageId: string) =>
    (
      await api.get<StageImpactResponse>(
        `/tenants/pipeline/impacted-references/${encodeURIComponent(stageId)}`,
      )
    ).data,
  getPipelineAuditLog: async (params?: { limit?: number; before?: string }) =>
    (await api.get<AuditLogResponse>(`/tenants/pipeline/audit-log`, { params })).data,
  // P1 endpoints
  listPipelineVersions: async () =>
    (await api.get<PipelineVersionListItem[]>("/tenants/pipeline/versions")).data,
  getPipelineVersion: async (index: number) =>
    (await api.get<PipelineVersionDetail>(`/tenants/pipeline/versions/${index}`)).data,
  rollbackPipeline: async (index: number) =>
    (await api.post<PipelineResponse>("/tenants/pipeline/rollback", { index })).data,
  getBrandFacts: async () => (await api.get<BrandFactsResponse>("/tenants/brand-facts")).data,
  putBrandFacts: async (brand_facts: Record<string, string>) =>
    (await api.put<BrandFactsResponse>("/tenants/brand-facts", { brand_facts })).data,
  getTone: async () => (await api.get<ToneResponse>("/tenants/tone")).data,
  putTone: async (voice: Record<string, unknown>) =>
    (await api.put<ToneResponse>("/tenants/tone", { voice })).data,
  getTimezone: async () => (await api.get<TimezoneResponse>("/tenants/timezone")).data,
  putTimezone: async (timezone: string) =>
    (await api.put<TimezoneResponse>("/tenants/timezone", { timezone })).data,
};

export const inboxConfigApi = {
  get: async (): Promise<InboxConfig> => {
    const r = await api.get<{ inbox_config: unknown }>("/tenants/inbox-config");
    return normalizeInboxConfig(r.data.inbox_config);
  },
  put: async (inbox_config: InboxConfig): Promise<InboxConfig> => {
    const normalized = normalizeInboxConfig(inbox_config);
    const r = await api.put<{ inbox_config: unknown }>("/tenants/inbox-config", {
      inbox_config: normalized,
    });
    return normalizeInboxConfig(r.data.inbox_config);
  },
};

export const integrationsApi = {
  getWhatsAppDetails: async () =>
    (await api.get<WhatsAppDetails>("/integrations/whatsapp/details")).data,
  getAIProvider: async () => (await api.get<AIProviderInfo>("/integrations/ai-provider")).data,
};

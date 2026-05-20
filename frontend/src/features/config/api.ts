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

export interface ConfigValidationIssue {
  code: string;
  severity: string;
  message: string;
  path?: string | null;
}

export interface ConfigValidationResponse {
  status: string;
  summary: string;
  critical_count: number;
  warning_count: number;
  issues: ConfigValidationIssue[];
}

export interface QosConfig {
  enabled: boolean;
  debug_badges_enabled: boolean;
  fallback_on_timeout: boolean;
  pause_bot_on_budget_exceeded: boolean;
  response_slo_ms: number;
  nlu_timeout_ms: number;
  composer_timeout_ms: number;
  kb_timeout_ms: number;
  max_turn_cost_usd: number;
  daily_ai_budget_usd: number;
  max_messages_per_turn: number;
  inbound_rate_limit_per_min: number;
  outbound_rate_limit_per_min: number;
  workflow_rate_limit_per_min: number;
  dead_letter_after_attempts: number;
}

export interface QosConfigResponse {
  qos_config: QosConfig;
}

export interface NLUSubIntentConfig {
  key: string;
  label: string;
  description: string;
  examples: string[];
}

export interface NLUTopicConfig {
  key: string;
  label: string;
  description: string;
  examples: string[];
  sub_intents: NLUSubIntentConfig[];
}

export interface NLUTopicsResponse {
  topics: NLUTopicConfig[];
}

export interface NLUTestResponse {
  result: Record<string, unknown>;
  usage: Record<string, unknown> | null;
}

export interface FollowupScheduleItem {
  kind: string;
  delay_hours: number;
  body: string;
}

export interface RunnerRuleCondition {
  field: string;
  operator: string;
  value?: unknown;
}

export interface RunnerRuleThen {
  set_stage?: string | null;
  set_flow_mode?: string | null;
  set_action?: string | null;
  set_data?: Record<string, unknown>;
  pause_bot?: boolean | null;
}

export interface RunnerRule {
  name: string;
  category?: string;
  priority?: number;
  enabled: boolean;
  when: RunnerRuleCondition;
  then: RunnerRuleThen;
}

export interface RunnerRulesResponse {
  runner_rules: RunnerRule[];
}

export interface RunnerRulesTestResponse {
  matched_rules: string[];
  traces: Array<Record<string, unknown>>;
  set_data: Record<string, unknown>;
  set_stage: string | null;
  set_flow_mode: string | null;
  set_action: string | null;
  pause_bot: boolean | null;
}

export interface FollowupsConfig {
  enabled: boolean;
  schedule: FollowupScheduleItem[];
}

export interface FollowupsConfigResponse {
  followups_config: FollowupsConfig;
  stats: Record<string, number>;
  pending: Array<{
    id: string;
    kind: string;
    run_at: string;
    phone_e164: string;
    customer_name: string | null;
  }>;
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

export interface WhatsAppWebhookSandboxResponse {
  status: string;
  channel_message_id: string;
  conversation_id: string | null;
  message_id: string | null;
  trace_id: string | null;
  started_execution_ids: string[];
  last_webhook_at: string;
  request_preview: Record<string, unknown>;
  response_preview: Record<string, unknown>;
}

export interface AIProviderInfo {
  nlu_provider: string;
  nlu_model: string;
  nlu_fallback_provider: string;
  nlu_fallback_model: string;
  composer_provider: string;
  composer_model: string;
  has_openai_key: boolean;
  has_anthropic_key: boolean;
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
  validatePipeline: async (definition: Record<string, unknown>) =>
    (await api.post<ConfigValidationResponse>("/tenants/pipeline/validate", { definition })).data,
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
  getQosConfig: async () => (await api.get<QosConfigResponse>("/tenants/qos-config")).data,
  putQosConfig: async (qos_config: QosConfig) =>
    (await api.put<QosConfigResponse>("/tenants/qos-config", qos_config)).data,
  getNLUTopics: async () => (await api.get<NLUTopicsResponse>("/tenants/nlu-topics")).data,
  putNLUTopics: async (topics: NLUTopicConfig[]) =>
    (await api.put<NLUTopicsResponse>("/tenants/nlu-topics", { topics })).data,
  testNLU: async (text: string) =>
    (await api.post<NLUTestResponse>("/tenants/nlu-test", { text })).data,
  getRunnerRules: async () =>
    (await api.get<RunnerRulesResponse>("/tenants/runner-rules")).data,
  putRunnerRules: async (runner_rules: RunnerRule[]) =>
    (await api.put<RunnerRulesResponse>("/tenants/runner-rules", { runner_rules })).data,
  testRunnerRules: async (body: {
    runner_rules: RunnerRule[];
    extracted_before?: Record<string, unknown>;
    extracted_after?: Record<string, unknown>;
    nlu?: Record<string, unknown>;
    current_stage?: string;
    inbound_text?: string;
  }) => (await api.post<RunnerRulesTestResponse>("/tenants/runner-rules/test", body)).data,
  getFollowupsConfig: async () =>
    (await api.get<FollowupsConfigResponse>("/tenants/followups-config")).data,
  putFollowupsConfig: async (followups_config: FollowupsConfig) =>
    (await api.put<FollowupsConfigResponse>("/tenants/followups-config", followups_config)).data,
  cancelPendingFollowups: async () =>
    (await api.post<{ cancelled: number }>("/tenants/followups-config/cancel-pending", {})).data,
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
  testWhatsAppWebhook: async () =>
    (await api.post<WhatsAppWebhookSandboxResponse>("/integrations/whatsapp/test-webhook", {}))
      .data,
  getAIProvider: async () => (await api.get<AIProviderInfo>("/integrations/ai-provider")).data,
  putAIProvider: async (
    body: Pick<
      AIProviderInfo,
      "nlu_provider" | "nlu_model" | "composer_provider" | "composer_model"
    >,
  ) =>
    (await api.put<AIProviderInfo>("/integrations/ai-provider", body)).data,
};

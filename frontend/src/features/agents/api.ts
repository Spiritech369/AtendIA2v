import { api } from "@/lib/api-client";

export type AgentStatus = "draft" | "validation" | "testing" | "production" | "paused";
export type BehaviorMode = "normal" | "conservative" | "strict";
export type GuardrailSeverity = "critical" | "high" | "medium" | "low";
export type GuardrailAction = "block" | "rewrite" | "warn" | "handoff";
export type ExtractionFieldType =
  | "text"
  | "number"
  | "date"
  | "boolean"
  | "enum"
  | "phone"
  | "currency";

export interface Guardrail {
  id: string;
  severity: GuardrailSeverity;
  name: string;
  rule_text: string;
  allowed_examples: string[];
  forbidden_examples: string[];
  active: boolean;
  violation_count: number;
  enforcement_mode: GuardrailAction;
  created_by?: string;
  updated_by?: string;
  updated_at?: string;
}

export interface ExtractionField {
  id: string;
  field_key: string;
  label: string;
  description?: string | null;
  type: ExtractionFieldType;
  required: boolean;
  confidence_threshold: number;
  confidence?: number;
  auto_save: boolean;
  requires_confirmation: boolean;
  source_message_tracking: boolean;
  validation_regex?: string | null;
  enum_options: string[];
  source?: string;
  last_value?: string | null;
  status?: "confirmed" | "pending" | "optional" | string;
}

export interface AgentMetrics {
  response_accuracy: number;
  correct_handoff_rate: number;
  extraction_accuracy: number;
  lead_advancement_rate: number;
  guardrail_compliance: number;
  uptime_score: number;
  risk_score: number;
  active_conversations: number;
  blocked_responses: number;
  stuck_conversations: number;
  leads_waiting_human: number;
  failed_kb_searches: number;
  action_suggestions: number;
  conversations_today: number;
}

export interface AgentHealth {
  score: number;
  status: "healthy" | "warning" | "critical" | string;
  trend: number;
  last_checked: string;
}

export interface LiveMonitor {
  conversations_active: number;
  leads_at_risk: number;
  leads_waiting_human: number;
  failed_kb_searches: number;
  blocked_responses: number;
  action_suggestions: number;
  risky_leads: Array<Record<string, unknown>>;
}

export interface SupervisorSummary {
  hallucination_risk: string;
  guardrail_compliance: string;
  tone: string;
  handoff_correctness: number;
  extraction_reliability: number;
  last_decision: string;
  alert?: string;
}

export interface KnowledgeCoverage {
  coverage: number;
  faq_answered: number;
  catalog_connected: boolean;
  indexed_policies: number;
  missing_documents: number;
  unanswered_queries: number;
  weak_topics: string[];
}

export interface DecisionRule {
  id: string;
  name: string;
  intent: string;
  required_fields: string[];
  action: string;
  target?: string;
  priority: number;
  active: boolean;
}

export interface DecisionMap {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  rules?: DecisionRule[];
}

export interface AgentVersionSnapshot {
  role?: string;
  behavior_mode?: BehaviorMode;
  goal?: string | null;
  style?: string | null;
  tone?: string | null;
  language?: string | null;
  max_sentences?: number | null;
  no_emoji?: boolean;
  return_to_flow?: boolean;
  system_prompt?: string | null;
  active_intents?: string[];
  knowledge_config?: Record<string, unknown>;
  flow_mode_rules?: Record<string, unknown> | null;
}

export interface AgentVersion {
  id: string;
  version: string;
  status: AgentStatus | string;
  author: string;
  created_at: string;
  notes?: string;
  reason?: string;
  performance_impact?: string;
  // Migration A1 — full config snapshot at publish time. Optional so
  // versions published before snapshot persistence keep deserializing.
  snapshot?: AgentVersionSnapshot | null;
}

export interface ScenarioRun {
  id: string;
  name: string;
  status: "passed" | "warning" | "failed" | "risky" | string;
  score?: number;
  last_run?: string;
}

export interface AgentItem {
  id: string;
  tenant_id: string;
  name: string;
  role: string;
  status: AgentStatus;
  behavior_mode: BehaviorMode;
  version: string;
  dealership_id: string | null;
  branch_id: string | null;
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
  ops_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  health: AgentHealth;
  metrics: AgentMetrics;
  guardrails: Guardrail[];
  extraction_fields: ExtractionField[];
  live_monitor: LiveMonitor;
  supervisor: SupervisorSummary;
  knowledge_coverage: KnowledgeCoverage;
  decision_map: DecisionMap;
  versions: AgentVersion[];
  scenarios: ScenarioRun[];
}

export type AgentPayload = Omit<
  AgentItem,
  | "id"
  | "tenant_id"
  | "created_at"
  | "updated_at"
  | "health"
  | "metrics"
  | "guardrails"
  | "extraction_fields"
  | "live_monitor"
  | "supervisor"
  | "knowledge_coverage"
  | "decision_map"
  | "versions"
  | "scenarios"
>;

export interface ValidationIssue {
  code: string;
  severity: "ok" | "warning" | "error" | "critical" | string;
  message: string;
  area?: string;
}

export interface ValidationResult {
  status: "ok" | "warning" | "error" | string;
  summary: string;
  issues: ValidationIssue[];
  checks: Array<{ label: string; status: string }>;
}

export interface AgentMonitorMetrics {
  active_conversations_24h: number;
  turns_total: number;
  turns_24h: number;
  cost_usd_total: number;
  cost_usd_24h: number;
  avg_latency_ms: number;
  last_turn_at: string | null;
  covers_default_fallback: boolean;
}

export interface PreviewResult {
  rawResponse: string;
  finalResponse: string;
  confidence: number;
  retrievedFragments: Array<{ id: string; title: string; score: number }>;
  activatedGuardrails: Guardrail[];
  extractedFields: Array<{ field_key: string; value: string; confidence: number }>;
  supervisorDecision: Record<string, unknown>;
  trace: Array<{ step: string; status: string; detail: string }>;
  // The assembled system prompt the LLM actually saw. Surfaced in the
  // preview panel as a collapsible so the operator can verify what
  // their tono/estilo/objetivo/prompt_maestro combined into.
  systemPrompt?: string;
}

export const agentsApi = {
  list: async () => (await api.get<AgentItem[]>("/agents")).data,
  get: async (id: string) => (await api.get<AgentItem>(`/agents/${id}`)).data,
  create: async (body: Partial<AgentPayload>) => (await api.post<AgentItem>("/agents", body)).data,
  patch: async (id: string, body: Partial<AgentPayload>) =>
    (await api.patch<AgentItem>(`/agents/${id}`, body)).data,
  patchConfig: async (id: string, body: Partial<AgentPayload>) =>
    (await api.patch<AgentItem>(`/agents/${id}/config`, body)).data,
  delete: async (id: string) => api.delete(`/agents/${id}`),
  duplicate: async (id: string) => (await api.post<AgentItem>(`/agents/${id}/duplicate`)).data,
  disable: async (id: string) => (await api.post<AgentItem>(`/agents/${id}/disable`)).data,
  publish: async (id: string) => (await api.post<AgentItem>(`/agents/${id}/publish`)).data,
  rollback: async (id: string, version_id?: string) =>
    (await api.post<AgentItem>(`/agents/${id}/rollback`, version_id ? { version_id } : {})).data,
  exportJson: async (id: string) =>
    (await api.post<Record<string, unknown>>(`/agents/${id}/export`)).data,
  compare: async (agent_ids: string[]) =>
    (
      await api.post<{
        agents: AgentItem[];
        differences: Array<Record<string, unknown>>;
        performance: Array<Record<string, unknown>>;
      }>("/agents/compare", { agent_ids })
    ).data,
  validateConfig: async (id: string, draft?: Partial<AgentPayload>) =>
    (await api.post<ValidationResult>(`/agents/${id}/validate-config`, draft ?? {})).data,
  previewResponse: async (id: string, message: string, draftConfig?: Partial<AgentPayload>) =>
    (
      await api.post<PreviewResult>(`/agents/${id}/preview-response`, {
        message,
        draftConfig: draftConfig ?? {},
        conversationContext: {},
      })
    ).data,
  monitor: async (id: string) => (await api.get<AgentMonitorMetrics>(`/agents/${id}/monitor`)).data,
  createGuardrail: async (id: string, body: Omit<Guardrail, "id" | "violation_count">) =>
    (await api.post<Guardrail>(`/agents/${id}/guardrails`, body)).data,
  patchGuardrail: async (id: string, body: Omit<Guardrail, "id" | "violation_count">) =>
    (await api.patch<Guardrail>(`/guardrails/${id}`, body)).data,
  testGuardrail: async (id: string, text: string) =>
    (
      await api.post<{ guardrail_id: string; violated: boolean; action: string }>(
        `/guardrails/${id}/test`,
        { text },
      )
    ).data,
  createExtractionField: async (
    id: string,
    body: Omit<ExtractionField, "id" | "confidence" | "source" | "last_value" | "status">,
  ) => (await api.post<ExtractionField>(`/agents/${id}/extraction-fields`, body)).data,
  patchExtractionField: async (
    id: string,
    body: Omit<ExtractionField, "id" | "confidence" | "source" | "last_value" | "status">,
  ) => (await api.patch<ExtractionField>(`/extraction-fields/${id}`, body)).data,
  testExtractionField: async (id: string, text: string) =>
    (
      await api.post<{
        field_id: string;
        value: string;
        confidence: number;
        source_text: string;
        auto_saved: boolean;
      }>(`/extraction-fields/${id}/test`, { text })
    ).data,
  updateDecisionMap: async (id: string, body: DecisionMap) =>
    (await api.put<AgentItem>(`/agents/${id}/decision-map`, body)).data,
  validateDecisionMap: async (id: string, body: DecisionMap) =>
    (await api.post<ValidationResult>(`/agents/${id}/decision-map/validate`, body)).data,
  runScenario: async (id: string, scenario_id: string, message?: string) =>
    (
      await api.post<Record<string, unknown>>(`/agents/${id}/scenarios/run`, {
        scenario_id,
        message,
      })
    ).data,
  stressTest: async (id: string) =>
    (
      await api.post<{ queued: number; passed: number; failed: number }>(
        `/agents/${id}/scenarios/stress-test`,
      )
    ).data,
  test: async (agent_config: Record<string, unknown>, message: string) =>
    (
      await api.post<{ response: string; flow_mode: string; intent: string }>("/agents/test", {
        agent_config,
        message,
      })
    ).data,
};

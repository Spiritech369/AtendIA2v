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
  voice?: Record<string, unknown>;
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
  voice: Record<string, unknown>;
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
  template: string;
  instructions: string;
  language_policy: Record<string, unknown>;
  enabled_knowledge_source_ids: string[];
  enabled_action_ids: string[];
  visible_contact_field_keys: string[];
  allowed_lifecycle_stage_ids: string[];
  escalation_policy: Record<string, unknown>;
  metadata: Record<string, unknown>;
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
  path?: string;
}

export interface ValidationResult {
  status: "ok" | "ready" | "warning" | "error" | "blocked" | string;
  summary: string;
  issues: ValidationIssue[];
  checks: Array<{ label: string; status: string }>;
  critical_count?: number;
  warning_count?: number;
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

export interface AgentTestTurnHistoryItem {
  role: "customer" | "agent" | "system";
  text: string;
  sent_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentTestTurnContactField {
  key: string;
  label: string;
  field_type?: string;
  options?: Record<string, unknown> | null;
}

export interface AgentTestTurnV2Payload {
  test_message: string;
  conversation_history?: AgentTestTurnHistoryItem[];
  contact_fields?: AgentTestTurnContactField[];
  lifecycle_stage?: string | null;
  knowledge_source_ids?: string[] | null;
  save_readiness_evidence?: boolean;
  requires_knowledge_citation?: boolean;
  metadata?: Record<string, unknown>;
}

export interface AgentKnowledgeCitation {
  source_id?: string;
  title?: string | null;
  snippet?: string | null;
  score?: number | null;
  metadata?: Record<string, unknown>;
}

export interface AgentTestTurnV2Response {
  final_message: string;
  knowledge_citations: AgentKnowledgeCitation[];
  field_updates: Array<Record<string, unknown>>;
  lifecycle_update: Record<string, unknown> | null;
  actions: Array<Record<string, unknown>>;
  confidence: number;
  needs_human: boolean;
  risk_flags: string[];
  trace_metadata: Record<string, unknown>;
  debug: Record<string, unknown>;
}

export interface WorkflowRef {
  id: string;
  name: string;
  active: boolean;
  version: number;
  node_ids: string[];
}

export interface AgentStudioOption {
  id: string;
  label: string;
  type?: string | null;
  description?: string | null;
  metadata: Record<string, unknown>;
}

export interface OnboardingState {
  tenant_id: string;
  selected_blueprint_id: string | null;
  channel_connected: boolean;
  knowledge_uploaded: boolean;
  agent_configured: boolean;
  contact_fields_ready: boolean;
  lifecycle_ready: boolean;
  test_passed: boolean;
  published: boolean;
  current_step: string;
  checklist: Record<string, unknown>;
}

export interface OnboardingCheck {
  code: string;
  label: string;
  passed: boolean;
  severity: string;
  message: string;
  metadata: Record<string, unknown>;
}

export interface OnboardingValidation {
  ready: boolean;
  state: OnboardingState;
  checks: OnboardingCheck[];
  blocking_codes: string[];
  readiness: Record<string, unknown> | null;
}

export interface RuntimeV2ShadowReport {
  summary: Record<string, number>;
  legacy_vs_v2: Record<string, number>;
  top_risk_flags: Array<{ value: string; count: number }>;
  top_policy_issues: Array<{ value: string; count: number }>;
  top_knowledge_sources: Array<{ value: string; count: number }>;
  pilot_inputs?: Record<string, number | null>;
  examples: Array<Record<string, unknown>>;
}

export interface RuntimeV2PilotReport {
  tenant_id?: string;
  sends: number;
  policy_failures: number;
  average_confidence: number | null;
  needs_human_count: number;
  knowledge_gap_count: number;
  policy_blocked_count: number;
  actions_proposed: number;
  fields_suggested: number;
  fields_applied: number;
  lifecycle_suggested: number;
  lifecycle_applied: number;
  error_rate: number;
  trace_count: number;
}

export interface WhyAnswerReport {
  final_message: string;
  confidence: number | null;
  knowledge: {
    citations: Array<Record<string, unknown>>;
    source_cards: Array<Record<string, unknown>>;
  };
  field_updates: Array<Record<string, unknown>>;
  lifecycle_update: Record<string, unknown> | null;
  actions: {
    planned: Array<Record<string, unknown>>;
    executed: Array<Record<string, unknown>>;
    dry_run: Array<Record<string, unknown>>;
  };
  workflow_events: Array<Record<string, unknown>>;
  policy: Record<string, unknown>;
  rollout_policy: Record<string, unknown>;
  readiness: Record<string, unknown>;
  side_effects: Record<string, unknown>;
  human_summary: string;
}

export function normalizeValidationResult(raw: unknown): ValidationResult {
  const obj = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const checks = Array.isArray(obj.checks)
    ? obj.checks
    : Array.isArray(obj.checklist)
      ? obj.checklist
      : [];
  return {
    status: typeof obj.status === "string" ? obj.status : "error",
    summary: typeof obj.summary === "string" ? obj.summary : "Validacion no disponible",
    issues: Array.isArray(obj.issues) ? (obj.issues as ValidationIssue[]) : [],
    checks: checks as Array<{ label: string; status: string }>,
    critical_count: typeof obj.critical_count === "number" ? obj.critical_count : undefined,
    warning_count: typeof obj.warning_count === "number" ? obj.warning_count : undefined,
  };
}

export const agentsApi = {
  list: async () => (await api.get<AgentItem[]>("/agents")).data,
  get: async (id: string) => (await api.get<AgentItem>(`/agents/${id}`)).data,
  // W5 — reverse dependency: workflows whose assign_agent nodes point here.
  workflowsUsing: async (id: string) =>
    (await api.get<WorkflowRef[]>(`/agents/${id}/workflows`)).data,
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
    normalizeValidationResult(
      (await api.post<ValidationResult>(`/agents/${id}/validate-config`, draft ?? {})).data,
    ),
  previewResponse: async (id: string, message: string, draftConfig?: Partial<AgentPayload>) =>
    (
      await api.post<PreviewResult>(`/agents/${id}/preview-response`, {
        message,
        draftConfig: draftConfig ?? {},
        conversationContext: {},
      })
    ).data,
  testTurnV2: async (id: string, payload: AgentTestTurnV2Payload) =>
    (await api.post<AgentTestTurnV2Response>(`/agents/${id}/test-turn-v2`, payload)).data,
  studioActions: async () => (await api.get<AgentStudioOption[]>("/agents/studio/actions")).data,
  studioKnowledgeSources: async () =>
    (await api.get<AgentStudioOption[]>("/agents/studio/knowledge-sources")).data,
  studioContactFields: async () =>
    (await api.get<AgentStudioOption[]>("/agents/studio/contact-fields")).data,
  studioLifecycleStages: async () =>
    (await api.get<AgentStudioOption[]>("/agents/studio/lifecycle-stages")).data,
  onboardingState: async () => (await api.get<OnboardingState>("/onboarding/state")).data,
  validateOnboarding: async () =>
    (await api.post<OnboardingValidation>("/onboarding/validate")).data,
  publishReadiness: async () =>
    (await api.post<OnboardingValidation>("/onboarding/publish-readiness")).data,
  shadowReport: async (params?: {
    agent_id?: string;
    conversation_id?: string;
    channel?: string;
    min_confidence?: number;
    include_examples?: boolean;
    limit?: number;
  }) => (await api.get<RuntimeV2ShadowReport>("/agent-runtime-v2/shadow-report", { params })).data,
  pilotReport: async () =>
    (await api.get<RuntimeV2PilotReport>("/agent-runtime-v2/pilot-report")).data,
  whyAnswer: async (traceId: string, params?: { conversation_id?: string }) =>
    (await api.get<WhyAnswerReport>(`/turn-traces/${traceId}/why-answer-v2`, { params })).data,
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

import { api } from "@/lib/api-client";

export interface ProductAgent {
  id: string;
  tenant_id: string;
  name: string;
  role: string;
  status: string;
  tone: string | null;
  language: string | null;
  system_prompt: string | null;
  ops_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AgentVersion {
  id: string;
  tenant_id: string;
  agent_id: string;
  version_number: number;
  status: string;
  is_immutable: boolean;
  role: string | null;
  tone: string | null;
  language: string | null;
  instructions: string | null;
  prompt_blocks: Array<Record<string, unknown>>;
  snapshot: Record<string, unknown>;
  change_summary: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentDeployment {
  id: string;
  tenant_id: string;
  agent_id: string;
  active_version_id: string | null;
  rollback_version_id: string | null;
  name: string;
  channel: string;
  environment: string;
  publish_state: string;
  runtime_mode: string;
  send_scope: string;
  send_enabled: boolean;
  outbox_enabled: boolean;
  live_send_enabled: boolean;
  single_contact_smoke_enabled: boolean;
  actions_enabled: boolean;
  workflow_events_enabled: boolean;
  workflow_side_effects_enabled: boolean;
  canary_enabled: boolean;
  open_production_enabled: boolean;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuilderOption {
  id: string;
  label: string;
  type: string | null;
  status: string | null;
  metadata: Record<string, unknown>;
}

export interface BuilderOptions {
  knowledge_sources: BuilderOption[];
  tools: BuilderOption[];
  actions: BuilderOption[];
  workflows: BuilderOption[];
  registry_status: Record<string, string>;
}

export interface KnowledgeSourceOption {
  id: string;
  tenant_id: string;
  name: string;
  source_type: string;
  content_type: string;
  status: string;
  health: string;
  parser_status: string | null;
  index_status: string | null;
  checksum: string | null;
  version: string | null;
  last_indexed_at: string | null;
  error_message: string | null;
  bound_agent_ids: string[];
  blocker: boolean;
  blocker_reason: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentKnowledgeBinding {
  id: string;
  tenant_id: string;
  agent_id: string;
  agent_version_id: string;
  knowledge_source_id: string;
  source_name: string;
  source_type: string;
  status: string;
  health: string;
  required: boolean;
  binding_mode: string;
  priority: number;
  blocker: boolean;
  blocker_reason: string | null;
  checksum: string | null;
  version: string | null;
  last_indexed_at: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

export interface CapabilityOption {
  key: string;
  label: string;
  kind: "tool" | "action" | string;
  category: string;
  description: string;
  risk_level: string;
  side_effect_type: string;
  has_side_effects: boolean;
  default_mode: string;
  required_auth: boolean;
  required_permissions: string[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  publish_blockers: string[];
}

export interface AgentToolBinding {
  id: string;
  tenant_id: string;
  agent_id: string;
  agent_version_id: string;
  tool_name: string;
  label: string;
  category: string;
  enabled: boolean;
  required: boolean;
  risk_level: string;
  side_effect_type: string;
  has_side_effects: boolean;
  blocker: boolean;
  blocker_reason: string | null;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface AgentActionBinding {
  id: string;
  tenant_id: string;
  agent_id: string;
  agent_version_id: string;
  action_key: string;
  label: string;
  category: string;
  enabled: boolean;
  execution_mode: string;
  approval_required: boolean;
  risk_level: string;
  side_effect_type: string;
  has_side_effects: boolean;
  required_auth: boolean;
  required_permissions: string[];
  permissions: Record<string, unknown>;
  blocker: boolean;
  blocker_reason: string | null;
  publish_blockers: string[];
  metadata: Record<string, unknown>;
}

export interface AgentBuilderState {
  agent: ProductAgent;
  versions: AgentVersion[];
  deployments: AgentDeployment[];
  draft_version: AgentVersion | null;
  published_version: AgentVersion | null;
}

export interface BuilderReadinessCheck {
  code: string;
  label: string;
  status: "pass" | "warn" | "block" | string;
  message: string;
  metadata: Record<string, unknown>;
}

export interface BuilderReadiness {
  status: "ready" | "blocked" | string;
  version_id: string;
  agent_id: string | null;
  checks: BuilderReadinessCheck[];
  blocking_codes: string[];
  safety: Record<string, boolean>;
  test_lab_passed: boolean;
  live_publish_allowed: boolean;
}

export interface AgentTestSuite {
  id: string;
  tenant_id: string;
  agent_version_id: string;
  name: string;
  mode: string;
  status: string;
  last_run_id: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AgentTestScenario {
  id: string;
  tenant_id: string;
  test_suite_id: string;
  name: string;
  turns: Array<Record<string, unknown>>;
  expected: Record<string, unknown>;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface AgentTestRun {
  id: string;
  tenant_id: string;
  agent_version_id: string;
  test_suite_id: string;
  mode: string;
  status: string;
  decision: string;
  scenario_results: Array<Record<string, unknown>>;
  turn_results: Array<Record<string, unknown>>;
  pass_count: number;
  fail_count: number;
  blocked_count: number;
  trace_ids: unknown[];
  outbox_audit_result: Record<string, unknown>;
  side_effect_audit_result: Record<string, unknown>;
  coverage_summary: Record<string, unknown>;
  review_required: boolean;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentPublishRequest {
  id: string;
  tenant_id: string;
  agent_id: string;
  agent_version_id: string;
  deployment_id: string;
  requested_state: string;
  status: string;
  send_scope: string;
  channel_scope: string | null;
  audience_scope: Record<string, unknown>;
  test_run_ids: unknown[];
  readiness_snapshot: Record<string, unknown>;
  blockers: Array<Record<string, unknown>>;
  rollback_version_id: string | null;
  approval_text: string | null;
  decision_reason: string | null;
  requested_by_user_id: string | null;
  approved_by_user_id: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuilderConfigPayload {
  role?: string | null;
  tone?: string | null;
  language?: string | null;
  instructions?: string | null;
  prompt_blocks?: Array<Record<string, unknown>>;
  knowledge_policy?: Record<string, unknown>;
  tool_policy?: Record<string, unknown>;
  action_policy?: Record<string, unknown>;
  field_policy?: Record<string, unknown>;
  workflow_policy?: Record<string, unknown>;
  safety_policy?: Record<string, unknown>;
  test_policy?: Record<string, unknown>;
  snapshot?: Record<string, unknown>;
  change_summary?: string | null;
}

export const productAgentBuilderApi = {
  listAgents: async () => (await api.get<ProductAgent[]>("/product-agents/agents")).data,
  createAgent: async (body: { name: string; role: string; tone?: string; language?: string }) =>
    (await api.post<ProductAgent>("/product-agents/agents", body)).data,
  builderOptions: async () =>
    (await api.get<BuilderOptions>("/product-agents/builder/options")).data,
  knowledgeSourceOptions: async () =>
    (await api.get<KnowledgeSourceOption[]>("/product-agents/knowledge-sources/options")).data,
  toolOptions: async () =>
    (await api.get<CapabilityOption[]>("/product-agents/tools/options")).data,
  actionOptions: async () =>
    (await api.get<CapabilityOption[]>("/product-agents/actions/options")).data,
  builderState: async (agentId: string) =>
    (await api.get<AgentBuilderState>(`/product-agents/agents/${agentId}/builder-state`)).data,
  knowledgeBindings: async (agentId: string) =>
    (await api.get<AgentKnowledgeBinding[]>(`/product-agents/agents/${agentId}/knowledge-bindings`))
      .data,
  toolBindings: async (agentId: string) =>
    (await api.get<AgentToolBinding[]>(`/product-agents/agents/${agentId}/tool-bindings`)).data,
  actionBindings: async (agentId: string) =>
    (await api.get<AgentActionBinding[]>(`/product-agents/agents/${agentId}/action-bindings`)).data,
  bindKnowledgeSource: async (
    agentId: string,
    body: {
      knowledge_source_id: string;
      binding_mode?: string;
      required?: boolean;
      priority?: number;
    },
  ) =>
    (
      await api.post<AgentKnowledgeBinding>(
        `/product-agents/agents/${agentId}/knowledge-bindings`,
        body,
      )
    ).data,
  unbindKnowledgeSource: async (agentId: string, bindingId: string) =>
    await api.delete(`/product-agents/agents/${agentId}/knowledge-bindings/${bindingId}`),
  bindTool: async (
    agentId: string,
    body: {
      tool_name: string;
      enabled?: boolean;
      required?: boolean;
    },
  ) =>
    (await api.post<AgentToolBinding>(`/product-agents/agents/${agentId}/tool-bindings`, body))
      .data,
  unbindTool: async (agentId: string, bindingId: string) =>
    await api.delete(`/product-agents/agents/${agentId}/tool-bindings/${bindingId}`),
  bindAction: async (
    agentId: string,
    body: {
      action_key: string;
      enabled?: boolean;
      execution_mode?: string;
      permissions?: Record<string, unknown>;
    },
  ) =>
    (await api.post<AgentActionBinding>(`/product-agents/agents/${agentId}/action-bindings`, body))
      .data,
  unbindAction: async (agentId: string, bindingId: string) =>
    await api.delete(`/product-agents/agents/${agentId}/action-bindings/${bindingId}`),
  createDraftVersion: async (agentId: string, body: BuilderConfigPayload) =>
    (await api.post<AgentVersion>(`/product-agents/agents/${agentId}/draft-version`, body)).data,
  updateBuilderConfig: async (versionId: string, body: BuilderConfigPayload) =>
    (await api.patch<AgentVersion>(`/product-agents/versions/${versionId}/builder-config`, body))
      .data,
  agentReadiness: async (agentId: string) =>
    (await api.get<BuilderReadiness>(`/product-agents/agents/${agentId}/readiness`)).data,
  testSuites: async (versionId: string) =>
    (await api.get<AgentTestSuite[]>(`/product-agents/versions/${versionId}/test-suites`)).data,
  createTestSuite: async (
    versionId: string,
    body: { name: string; mode?: string; metadata?: Record<string, unknown> },
  ) =>
    (await api.post<AgentTestSuite>(`/product-agents/versions/${versionId}/test-suites`, body))
      .data,
  testScenarios: async (suiteId: string) =>
    (await api.get<AgentTestScenario[]>(`/product-agents/test-suites/${suiteId}/scenarios`)).data,
  createTestScenario: async (
    suiteId: string,
    body: {
      name: string;
      turns: Array<Record<string, unknown>>;
      expected?: Record<string, unknown>;
      metadata?: Record<string, unknown>;
    },
  ) =>
    (await api.post<AgentTestScenario>(`/product-agents/test-suites/${suiteId}/scenarios`, body))
      .data,
  runTestSuite: async (
    suiteId: string,
    body: { mode?: string; execution_mode?: string; review_required?: boolean },
  ) => (await api.post<AgentTestRun>(`/product-agents/test-suites/${suiteId}/runs`, body)).data,
  latestTestRun: async (suiteId: string) =>
    (await api.get<AgentTestRun | null>(`/product-agents/test-suites/${suiteId}/runs/latest`)).data,
  latestPublishRequest: async (deploymentId: string) =>
    (
      await api.get<AgentPublishRequest | null>(
        `/product-agents/deployments/${deploymentId}/publish-requests/latest`,
      )
    ).data,
  createPublishRequest: async (
    deploymentId: string,
    body: {
      agent_version_id: string;
      requested_state?: string;
      send_scope?: string;
      channel_scope?: string | null;
      audience_scope?: Record<string, unknown>;
      rollback_version_id?: string | null;
      approval_text?: string | null;
    },
  ) =>
    (
      await api.post<AgentPublishRequest>(
        `/product-agents/deployments/${deploymentId}/publish-requests`,
        body,
      )
    ).data,
  evaluatePublishRequest: async (requestId: string) =>
    (await api.post<AgentPublishRequest>(`/product-agents/publish-requests/${requestId}/evaluate`))
      .data,
  approvePublishRequestNoSend: async (requestId: string, body: { approval_text?: string | null }) =>
    (
      await api.post<AgentPublishRequest>(
        `/product-agents/publish-requests/${requestId}/approve-no-send`,
        body,
      )
    ).data,
  rejectPublishRequest: async (requestId: string, body: { reason?: string | null }) =>
    (
      await api.post<AgentPublishRequest>(
        `/product-agents/publish-requests/${requestId}/reject`,
        body,
      )
    ).data,
};

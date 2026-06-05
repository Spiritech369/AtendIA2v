/**
 * Sprint B.1 — AgentsPage smoke test. Mocks /api/v1/* to empty.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AgentsPage } from "@/features/agents/components/AgentsPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const server = setupServer(
  http.get("/api/v1/agents", () => HttpResponse.json([])),
  http.get("/api/v1/agents/:agentId/workflows", () => HttpResponse.json([])),
  http.get("/api/v1/agents/:agentId/audit-logs", () => HttpResponse.json([])),
  http.get("/api/v1/agents/:agentId/monitor", () =>
    HttpResponse.json({
      active_conversations_24h: 0,
      turns_total: 0,
      turns_24h: 0,
      cost_usd_total: 0,
      cost_usd_24h: 0,
      avg_latency_ms: 0,
      last_turn_at: null,
      covers_default_fallback: true,
    }),
  ),
  http.get("/api/v1/onboarding/state", () => HttpResponse.json(onboardingState())),
  http.get("/api/v1/*", () => HttpResponse.json({ items: [], total: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("AgentsPage", () => {
  it("renders without throwing for an empty tenant", async () => {
    const { container } = renderPage(<AgentsPage />);
    await waitFor(() => expect(container.firstChild).not.toBeNull());
  });

  it("renders Agent Studio v2 options and saves config", async () => {
    let patched: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/agents", () => HttpResponse.json([agentFixture()])),
      http.get("/api/v1/agents/studio/knowledge-sources", () =>
        HttpResponse.json([
          {
            id: "source-1",
            label: "Policy source",
            type: "manual",
            metadata: { badge: "native" },
          },
        ]),
      ),
      http.get("/api/v1/agents/studio/actions", () =>
        HttpResponse.json([
          {
            id: "add_tag",
            label: "Add Tag",
            type: "action",
            description: "Adds a tag",
            metadata: {},
          },
        ]),
      ),
      http.get("/api/v1/agents/studio/contact-fields", () =>
        HttpResponse.json([{ id: "email", label: "Email", type: "text", metadata: {} }]),
      ),
      http.get("/api/v1/agents/studio/lifecycle-stages", () =>
        HttpResponse.json([{ id: "qualified", label: "Qualified", type: "stage", metadata: {} }]),
      ),
      http.patch("/api/v1/agents/:agentId/config", async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...agentFixture(), ...patched });
      }),
    );

    const user = userEvent.setup();
    renderPage(<AgentsPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByText("Studio Agent"));
    await user.click(screen.getByRole("button", { name: "Agent Studio" }));
    await screen.findByText("Policy source");
    await user.clear(screen.getByLabelText("Instructions"));
    await user.type(screen.getByLabelText("Instructions"), "Use approved sources only.");
    await user.click(screen.getByText("Policy source"));
    await user.click(screen.getByText("Add Tag"));
    await user.click(screen.getByText("Email"));
    await user.click(screen.getByText("Qualified"));
    await user.click(screen.getByRole("button", { name: /save config/i }));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched).toMatchObject({
      instructions: "Use approved sources only.",
      enabled_knowledge_source_ids: ["source-1"],
      enabled_action_ids: ["add_tag"],
      visible_contact_field_keys: ["email"],
      allowed_lifecycle_stage_ids: ["qualified"],
    });
  });

  it("shows onboarding validation blockers", async () => {
    server.use(
      http.get("/api/v1/agents", () => HttpResponse.json([agentFixture()])),
      http.post("/api/v1/onboarding/validate", () =>
        HttpResponse.json({
          ready: false,
          state: onboardingState(),
          blocking_codes: ["knowledge_ready"],
          readiness: null,
          checks: [
            {
              code: "knowledge_ready",
              label: "Knowledge ready",
              passed: false,
              severity: "critical",
              message: "Upload at least one active source.",
              metadata: {},
            },
          ],
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage(<AgentsPage />, { auth: { role: "tenant_admin" } });

    await screen.findByText("Onboarding readiness");
    await user.click(screen.getByRole("button", { name: /validate/i }));

    expect(await screen.findByText("Upload at least one active source.")).toBeInTheDocument();
    expect(screen.getByText("knowledge_ready")).toBeInTheDocument();
  });

  it("renders runtime v2 operations reports and why-this-answer", async () => {
    server.use(
      http.get("/api/v1/agents", () => HttpResponse.json([agentFixture()])),
      http.get("/api/v1/agent-runtime-v2/shadow-report", () =>
        HttpResponse.json({
          summary: {
            shadow_turns: 3,
            avg_confidence: 0.82,
            needs_human_count: 1,
            policy_blocked_count: 1,
            knowledge_gap_count: 1,
            actions_proposed_count: 2,
            field_updates_proposed_count: 1,
            lifecycle_updates_proposed_count: 1,
            errors_count: 0,
          },
          legacy_vs_v2: {
            legacy_message_available_count: 3,
            v2_message_available_count: 3,
            same_or_similar_count: 2,
            v2_empty_count: 0,
            legacy_empty_count: 0,
            needs_human_when_legacy_answered_count: 1,
          },
          top_risk_flags: [{ value: "knowledge_gap", count: 1 }],
          top_policy_issues: [{ value: "missing_required_citations", count: 1 }],
          top_knowledge_sources: [{ value: "Policy source", count: 2 }],
          pilot_inputs: {
            shadow_sample_size: 3,
            avg_shadow_confidence: 0.82,
            policy_block_rate: 0.33,
            needs_human_rate: 0.33,
          },
          examples: [{ trace_id: "trace-1", v2_message: "Respuesta v2" }],
        }),
      ),
      http.get("/api/v1/agent-runtime-v2/pilot-report", () =>
        HttpResponse.json({
          sends: 1,
          policy_failures: 0,
          average_confidence: 0.91,
          needs_human_count: 0,
          knowledge_gap_count: 0,
          policy_blocked_count: 0,
          actions_proposed: 1,
          fields_suggested: 1,
          fields_applied: 0,
          lifecycle_suggested: 1,
          lifecycle_applied: 0,
          error_rate: 0,
          trace_count: 1,
        }),
      ),
      http.get("/api/v1/turn-traces/:traceId/why-answer-v2", () =>
        HttpResponse.json({
          final_message: "Use la fuente aprobada.",
          confidence: 0.88,
          knowledge: {
            citations: [{ source_id: "source-1", title: "Policy source" }],
            source_cards: [],
          },
          field_updates: [],
          lifecycle_update: null,
          actions: { planned: [], executed: [], dry_run: [{ name: "add_tag" }] },
          workflow_events: [],
          policy: { valid: true, issues: [] },
          rollout_policy: {},
          readiness: {},
          side_effects: {},
          human_summary: "Respondio con Knowledge OS y dry-run.",
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage(<AgentsPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByText("Studio Agent"));
    await user.click(screen.getByRole("button", { name: "Runtime v2" }));

    expect(await screen.findByText("Runtime v2 operations")).toBeInTheDocument();
    expect(await screen.findByText("Shadow turns")).toBeInTheDocument();
    expect(await screen.findByText("Pilot sends")).toBeInTheDocument();
    expect(await screen.findByText("Policy source 2")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Trace ID"), "trace-1");
    await user.click(screen.getByRole("button", { name: /explain/i }));

    expect(await screen.findByText("Use la fuente aprobada.")).toBeInTheDocument();
    expect(screen.getByText("Respondio con Knowledge OS y dry-run.")).toBeInTheDocument();
  });
});

function onboardingState() {
  return {
    tenant_id: "tenant-1",
    selected_blueprint_id: "automotive_real_estate",
    channel_connected: true,
    knowledge_uploaded: false,
    agent_configured: true,
    contact_fields_ready: true,
    lifecycle_ready: true,
    test_passed: false,
    published: false,
    current_step: "test_agent",
    checklist: { expected_knowledge_categories: ["catalog", "pricing"] },
  };
}

function agentFixture() {
  return {
    id: "agent-1",
    tenant_id: "tenant-1",
    name: "Studio Agent",
    role: "support",
    status: "testing",
    behavior_mode: "normal",
    version: "v2",
    dealership_id: null,
    branch_id: null,
    goal: null,
    style: null,
    tone: "neutral",
    voice: {},
    language: "es",
    max_sentences: 4,
    no_emoji: true,
    return_to_flow: true,
    is_default: true,
    system_prompt: "",
    active_intents: [],
    extraction_config: {},
    auto_actions: {},
    knowledge_config: {},
    flow_mode_rules: null,
    ops_config: {},
    template: "support",
    instructions: "",
    language_policy: { primary: "es", mode: "match_customer" },
    enabled_knowledge_source_ids: [],
    enabled_action_ids: [],
    visible_contact_field_keys: [],
    allowed_lifecycle_stage_ids: [],
    escalation_policy: {},
    metadata: {},
    created_at: "2026-05-31T00:00:00Z",
    updated_at: "2026-05-31T00:00:00Z",
    health: { score: 90, status: "healthy", trend: 0, last_checked: "now" },
    metrics: {
      response_accuracy: 90,
      correct_handoff_rate: 90,
      extraction_accuracy: 90,
      lead_advancement_rate: 70,
      guardrail_compliance: 98,
      uptime_score: 99,
      risk_score: 10,
      active_conversations: 1,
      blocked_responses: 0,
      stuck_conversations: 0,
      leads_waiting_human: 0,
      failed_kb_searches: 0,
      action_suggestions: 0,
      conversations_today: 1,
    },
    guardrails: [],
    extraction_fields: [],
    live_monitor: {
      conversations_active: 0,
      leads_at_risk: 0,
      leads_waiting_human: 0,
      failed_kb_searches: 0,
      blocked_responses: 0,
      action_suggestions: 0,
      risky_leads: [],
    },
    supervisor: {
      hallucination_risk: "low",
      guardrail_compliance: "ok",
      tone: "ok",
      handoff_correctness: 1,
      extraction_reliability: 1,
      last_decision: "none",
    },
    knowledge_coverage: {
      coverage: 20,
      faq_answered: 0,
      catalog_connected: false,
      indexed_policies: 0,
      missing_documents: 0,
      unanswered_queries: 0,
      weak_topics: [],
    },
    decision_map: { nodes: [], edges: [] },
    versions: [],
    scenarios: [],
  };
}

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { AgentItem } from "@/features/agents/api";
import { AgentTestChatV2 } from "@/features/agents/components/AgentTestChatV2";
import { resetAuth, withQueryClient } from "../../test-utils/renderPage";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("AgentTestChatV2", () => {
  it("renders the dry-run test harness", () => {
    render(withQueryClient(<AgentTestChatV2 agent={agentFixture()} />));

    expect(screen.getByText("Agent Test Chat v2")).toBeInTheDocument();
    expect(screen.getByText("Test mode / Dry run")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Escribe el mensaje del cliente...")).toBeInTheDocument();
  });

  it("submits and shows response, citations and actions", async () => {
    server.use(
      http.post("/api/v1/agents/:agentId/test-turn-v2", async ({ params, request }) => {
        expect(params.agentId).toBe("agent-1");
        const body = (await request.json()) as Record<string, unknown>;
        expect(body.test_message).toBe("Hola");
        return HttpResponse.json({
          final_message: "Hola, te puedo ayudar.",
          knowledge_citations: [
            {
              source_id: "source-1",
              title: "FAQ",
              snippet: "Horario de atencion",
              score: 0.91,
              metadata: {},
            },
          ],
          field_updates: [{ field_key: "priority", value: "high" }],
          lifecycle_update: { target_stage: "qualified", reason: "Test" },
          actions: [{ name: "add_tag", payload: { tag: "test" } }],
          confidence: 0.87,
          needs_human: false,
          risk_flags: [],
          trace_metadata: { trace_id: "trace-1" },
          debug: { policy: { valid: true }, actions: { dry_run: true } },
        });
      }),
    );

    const user = userEvent.setup();
    render(withQueryClient(<AgentTestChatV2 agent={agentFixture()} />));
    await user.type(screen.getByPlaceholderText("Escribe el mensaje del cliente..."), "Hola");
    await user.click(screen.getByRole("button", { name: /run test/i }));

    expect(await screen.findByText("Hola, te puedo ayudar.")).toBeInTheDocument();
    expect(screen.getByText("FAQ")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
    expect(screen.getByText(/add_tag/)).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
  });

  it("renders PolicyValidator errors legibly", async () => {
    server.use(
      http.post("/api/v1/agents/:agentId/test-turn-v2", () =>
        HttpResponse.json(
          {
            detail: {
              message: "agent_runtime_v2 output failed policy validation",
              issues: [
                {
                  code: "sensitive_action_missing_evidence",
                  message: "Action requires evidence.",
                },
              ],
            },
          },
          { status: 422 },
        ),
      ),
    );

    const user = userEvent.setup();
    render(withQueryClient(<AgentTestChatV2 agent={agentFixture()} />));
    await user.type(
      screen.getByPlaceholderText("Escribe el mensaje del cliente..."),
      "Marca prioridad",
    );
    await user.click(screen.getByRole("button", { name: /run test/i }));

    await waitFor(() => expect(screen.getByText("Policy/debug error")).toBeInTheDocument());
    expect(screen.getByText(/sensitive_action_missing_evidence/)).toBeInTheDocument();
    expect(screen.getByText(/Action requires evidence/)).toBeInTheDocument();
  });
});

function agentFixture(): AgentItem {
  return {
    id: "agent-1",
    tenant_id: "tenant-1",
    name: "Test Agent",
    role: "custom",
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
    is_default: false,
    system_prompt: null,
    active_intents: [],
    extraction_config: {},
    auto_actions: {},
    knowledge_config: {},
    flow_mode_rules: null,
    ops_config: {},
    template: "custom",
    instructions: "",
    language_policy: { primary: "es" },
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
      response_accuracy: 0,
      correct_handoff_rate: 0,
      extraction_accuracy: 0,
      lead_advancement_rate: 0,
      guardrail_compliance: 0,
      uptime_score: 0,
      risk_score: 0,
      active_conversations: 0,
      blocked_responses: 0,
      stuck_conversations: 0,
      leads_waiting_human: 0,
      failed_kb_searches: 0,
      action_suggestions: 0,
      conversations_today: 0,
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
      coverage: 0,
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

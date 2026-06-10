import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { productAgentBuilderApi } from "@/features/product-agent-builder/api";
import { AgentBuilderPage } from "@/features/product-agent-builder/components/AgentBuilderPage";
import { renderPage, resetAuth } from "../../test-utils/renderPage";

const agents = new Map<string, Record<string, unknown>>();
const draftAgents = new Set<string>();
const knowledgeBindings = new Map<string, Record<string, unknown>>();
const toolBindings = new Map<string, Record<string, unknown>>();
const actionBindings = new Map<string, Record<string, unknown>>();
const testSuites = new Map<string, Record<string, unknown>>();
const testScenarios = new Map<string, Record<string, unknown>>();
const latestRuns = new Map<string, Record<string, unknown>>();
const latestPublishRequests = new Map<string, Record<string, unknown>>();
let savedDraft: Record<string, unknown> | null = null;
let createdBody: Record<string, unknown> | null = null;
let runSuiteBody: Record<string, unknown> | null = null;
let legacyAgentsCalled = false;

const server = setupServer(
  http.get("/api/v1/product-agents/agents", () => HttpResponse.json([...agents.values()])),
  http.post("/api/v1/product-agents/agents", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    createdBody = body;
    const agent = agentFixture({
      id: "agent-created",
      name: String(body.name),
      role: String(body.role),
    });
    agents.set(String(agent.id), agent);
    return HttpResponse.json(agent, { status: 201 });
  }),
  http.get("/api/v1/product-agents/builder/options", () =>
    HttpResponse.json({
      knowledge_sources: [
        { id: "source-1", label: "Policies", type: "document", status: "active", metadata: {} },
      ],
      tools: [
        {
          id: "catalog.search",
          label: "Catalog search",
          type: "fact_lookup",
          status: "available",
          metadata: toolOptionFixture(),
        },
        {
          id: "quote.resolve",
          label: "Quote resolver",
          type: "fact_lookup",
          status: "available",
          metadata: toolOptionFixture({ key: "quote.resolve", label: "Quote resolver" }),
        },
      ],
      actions: [
        {
          id: "update_contact_field",
          label: "Update contact field",
          type: "state_write",
          status: "approval_required",
          metadata: actionOptionFixture(),
        },
        {
          id: "send_message",
          label: "Send message boundary",
          type: "send_boundary",
          status: "disabled",
          metadata: actionOptionFixture({
            key: "send_message",
            label: "Send message boundary",
            category: "send_boundary",
            risk_level: "critical",
            side_effect_type: "message_send_request",
            default_mode: "disabled",
            required_auth: true,
            required_permissions: ["send.message"],
            publish_blockers: ["send_adapter_boundary", "explicit_live_approval_required"],
          }),
        },
      ],
      workflows: [
        {
          id: "workflow-1",
          label: "Notify",
          type: "agent_event",
          status: "inactive",
          metadata: {},
        },
      ],
      registry_status: { send: "blocked_for_builder_mvp" },
    }),
  ),
  http.get("/api/v1/product-agents/knowledge-sources/options", () =>
    HttpResponse.json([
      sourceFixture(),
      sourceFixture({
        id: "source-2",
        name: "Broken FAQ",
        status: "failed",
        health: "unhealthy",
        checksum: null,
        version: "v2",
        last_indexed_at: null,
        blocker: true,
        blocker_reason: "source_unhealthy",
        error_message: "Parser failed",
      }),
    ]),
  ),
  http.get("/api/v1/product-agents/tools/options", () =>
    HttpResponse.json([
      toolOptionFixture(),
      toolOptionFixture({ key: "quote.resolve", label: "Quote resolver" }),
    ]),
  ),
  http.get("/api/v1/product-agents/actions/options", () =>
    HttpResponse.json([
      actionOptionFixture(),
      actionOptionFixture({
        key: "send_message",
        label: "Send message boundary",
        category: "send_boundary",
        risk_level: "critical",
        side_effect_type: "message_send_request",
        default_mode: "disabled",
        required_auth: true,
        required_permissions: ["send.message"],
        publish_blockers: ["send_adapter_boundary", "explicit_live_approval_required"],
      }),
    ]),
  ),
  http.get("/api/v1/product-agents/agents/:agentId/builder-state", ({ params }) =>
    HttpResponse.json(builderState(String(params.agentId))),
  ),
  http.get("/api/v1/product-agents/agents/:agentId/knowledge-bindings", ({ params }) =>
    HttpResponse.json(
      [...knowledgeBindings.values()].filter((binding) => binding.agent_id === params.agentId),
    ),
  ),
  http.post(
    "/api/v1/product-agents/agents/:agentId/knowledge-bindings",
    async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      const source = sourceFixture({ id: String(body.knowledge_source_id) });
      const binding = bindingFixture({
        id: "binding-1",
        agent_id: String(params.agentId),
        knowledge_source_id: source.id,
        source_name: source.name,
        source_type: source.source_type,
        status: source.status,
        health: source.health,
        blocker: source.blocker,
        blocker_reason: source.blocker_reason,
      });
      knowledgeBindings.set(String(binding.id), binding);
      return HttpResponse.json(binding, { status: 201 });
    },
  ),
  http.delete(
    "/api/v1/product-agents/agents/:agentId/knowledge-bindings/:bindingId",
    ({ params }) => {
      knowledgeBindings.delete(String(params.bindingId));
      return new HttpResponse(null, { status: 204 });
    },
  ),
  http.get("/api/v1/product-agents/agents/:agentId/tool-bindings", ({ params }) =>
    HttpResponse.json(
      [...toolBindings.values()].filter((binding) => binding.agent_id === params.agentId),
    ),
  ),
  http.post("/api/v1/product-agents/agents/:agentId/tool-bindings", async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    const binding = toolBindingFixture({
      id: "tool-binding-1",
      agent_id: String(params.agentId),
      tool_name: String(body.tool_name),
      enabled: Boolean(body.enabled ?? true),
      required: Boolean(body.required ?? false),
    });
    toolBindings.set(String(binding.id), binding);
    return HttpResponse.json(binding, { status: 201 });
  }),
  http.delete("/api/v1/product-agents/agents/:agentId/tool-bindings/:bindingId", ({ params }) => {
    toolBindings.delete(String(params.bindingId));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/product-agents/agents/:agentId/action-bindings", ({ params }) =>
    HttpResponse.json(
      [...actionBindings.values()].filter((binding) => binding.agent_id === params.agentId),
    ),
  ),
  http.post(
    "/api/v1/product-agents/agents/:agentId/action-bindings",
    async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      const binding = actionBindingFixture({
        id: "action-binding-1",
        agent_id: String(params.agentId),
        action_key: String(body.action_key),
        enabled: Boolean(body.enabled ?? false),
        execution_mode: String(body.execution_mode ?? "disabled"),
        permissions: (body.permissions as Record<string, unknown>) ?? {},
      });
      actionBindings.set(String(binding.id), binding);
      return HttpResponse.json(binding, { status: 201 });
    },
  ),
  http.delete("/api/v1/product-agents/agents/:agentId/action-bindings/:bindingId", ({ params }) => {
    actionBindings.delete(String(params.bindingId));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/product-agents/versions/:versionId/test-suites", ({ params }) =>
    HttpResponse.json(
      [...testSuites.values()].filter((suite) => suite.agent_version_id === params.versionId),
    ),
  ),
  http.post(
    "/api/v1/product-agents/versions/:versionId/test-suites",
    async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      const suite = testSuiteFixture({
        id: "suite-1",
        agent_version_id: String(params.versionId),
        name: String(body.name),
        mode: String(body.mode ?? "draft_validation"),
      });
      testSuites.set(String(suite.id), suite);
      return HttpResponse.json(suite, { status: 201 });
    },
  ),
  http.get("/api/v1/product-agents/test-suites/:suiteId/scenarios", ({ params }) =>
    HttpResponse.json(
      [...testScenarios.values()].filter((scenario) => scenario.test_suite_id === params.suiteId),
    ),
  ),
  http.post(
    "/api/v1/product-agents/test-suites/:suiteId/scenarios",
    async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      const scenario = testScenarioFixture({
        id: "scenario-1",
        test_suite_id: String(params.suiteId),
        name: String(body.name),
        turns: body.turns as Record<string, unknown>[],
        expected: (body.expected as Record<string, unknown>) ?? {},
      });
      testScenarios.set(String(scenario.id), scenario);
      return HttpResponse.json(scenario, { status: 201 });
    },
  ),
  http.post("/api/v1/product-agents/test-suites/:suiteId/runs", async ({ params, request }) => {
    runSuiteBody = (await request.json()) as Record<string, unknown>;
    const run = testRunFixture({ id: "run-1", test_suite_id: String(params.suiteId) });
    latestRuns.set(String(params.suiteId), run);
    return HttpResponse.json(run, { status: 201 });
  }),
  http.get("/api/v1/product-agents/test-suites/:suiteId/runs/latest", ({ params }) =>
    HttpResponse.json(latestRuns.get(String(params.suiteId)) ?? null),
  ),
  http.get(
    "/api/v1/product-agents/deployments/:deploymentId/publish-requests/latest",
    ({ params }) =>
      HttpResponse.json(latestPublishRequests.get(String(params.deploymentId)) ?? null),
  ),
  http.post(
    "/api/v1/product-agents/deployments/:deploymentId/publish-requests",
    async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      const hasRun = [...latestRuns.values()].some(
        (run) => run.agent_version_id === body.agent_version_id && run.status === "passed",
      );
      const publishRequest = publishRequestFixture({
        deployment_id: String(params.deploymentId),
        agent_version_id: String(body.agent_version_id),
        rollback_version_id: body.rollback_version_id ?? null,
        status: hasRun && body.rollback_version_id ? "ready_for_approval" : "blocked",
        blockers:
          hasRun && body.rollback_version_id
            ? []
            : [{ code: hasRun ? "rollback_target_missing" : "test_lab_run_missing" }],
      });
      latestPublishRequests.set(String(params.deploymentId), publishRequest);
      return HttpResponse.json(publishRequest, { status: 201 });
    },
  ),
  http.post("/api/v1/product-agents/publish-requests/:requestId/evaluate", ({ params }) => {
    const publishRequest = [...latestPublishRequests.values()].find(
      (item) => item.id === params.requestId,
    );
    return HttpResponse.json(publishRequest ?? publishRequestFixture({ id: params.requestId }));
  }),
  http.post("/api/v1/product-agents/publish-requests/:requestId/approve-no-send", ({ params }) => {
    const entry = [...latestPublishRequests.entries()].find(
      ([, item]) => item.id === params.requestId,
    );
    const approved = {
      ...(entry?.[1] ?? publishRequestFixture({ id: params.requestId })),
      status: "approved_no_send",
      decision_reason: "approved_no_send",
      blockers: [],
    };
    if (entry) latestPublishRequests.set(entry[0], approved);
    return HttpResponse.json(approved);
  }),
  http.post("/api/v1/product-agents/publish-requests/:requestId/reject", async ({ params }) => {
    const rejected = {
      ...publishRequestFixture({ id: params.requestId }),
      status: "rejected",
      decision_reason: "human rejected no-send publish",
    };
    return HttpResponse.json(rejected);
  }),
  http.post("/api/v1/product-agents/agents/:agentId/draft-version", ({ params }) => {
    draftAgents.add(String(params.agentId));
    return HttpResponse.json(versionFixture({ id: "draft-1", agent_id: params.agentId }), {
      status: 201,
    });
  }),
  http.patch("/api/v1/product-agents/versions/:versionId/builder-config", async ({ request }) => {
    savedDraft = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(versionFixture({ id: "draft-1", ...savedDraft }));
  }),
  http.get("/api/v1/product-agents/versions/:versionId/readiness", () =>
    HttpResponse.json({
      status: "blocked",
      version_id: "draft-1",
      blocking_codes: ["required_knowledge_missing"],
      safety: { send_enabled: false, outbox_enabled: false, live_send_enabled: false },
      checks: [
        {
          code: "required_knowledge_missing",
          label: "Knowledge sources",
          status: "block",
          message: "Required knowledge source binding is missing.",
          metadata: {},
        },
      ],
    }),
  ),
  http.get("/api/v1/product-agents/agents/:agentId/readiness", ({ params }) =>
    HttpResponse.json(agentReadiness(String(params.agentId))),
  ),
  http.all("/api/v1/agents", () => {
    legacyAgentsCalled = true;
    return HttpResponse.json([], { status: 500 });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  agents.clear();
  draftAgents.clear();
  knowledgeBindings.clear();
  toolBindings.clear();
  actionBindings.clear();
  testSuites.clear();
  testScenarios.clear();
  latestRuns.clear();
  latestPublishRequests.clear();
  savedDraft = null;
  createdBody = null;
  runSuiteBody = null;
  legacyAgentsCalled = false;
  server.resetHandlers();
  resetAuth();
});
afterAll(() => server.close());

describe("AgentBuilderPage", () => {
  it("renders an empty Product-First builder without touching legacy agents API", async () => {
    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    expect(await screen.findByText("Product Agent Builder")).toBeInTheDocument();
    expect(await screen.findByText("Sin agentes Product-First.")).toBeInTheDocument();
    expect(legacyAgentsCalled).toBe(false);
  }, 10_000);

  it("creates an agent, creates a draft, saves builder config, and shows readiness", async () => {
    const user = userEvent.setup();
    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.type(await screen.findByLabelText("Nombre del agente"), "Support Builder");
    await user.click(screen.getByLabelText("Crear agente"));

    expect(await screen.findAllByText("Support Builder")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: /crear draft/i }));
    expect(await screen.findByText("Draft v1")).toBeInTheDocument();
    expect(
      await screen.findByText("Required knowledge source binding is missing."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Prompt" }));
    await user.clear(screen.getByLabelText("Instrucciones"));
    await user.type(screen.getByLabelText("Instrucciones"), "Use tenant sources only.");
    await user.type(screen.getByLabelText("Prompt block"), "Escalate when policy is missing.");
    await user.click(screen.getByRole("tab", { name: "Identidad" }));
    await user.clear(screen.getByLabelText("Rol"));
    await user.type(screen.getByLabelText("Rol"), "advisor");
    await user.clear(screen.getByLabelText("Tono"));
    await user.type(screen.getByLabelText("Tono"), "direct");
    await user.clear(screen.getByLabelText("Idioma"));
    await user.type(screen.getByLabelText("Idioma"), "es-MX");
    await user.click(screen.getByLabelText("Guardar draft"));

    await waitFor(() => expect(savedDraft).not.toBeNull());
    expect(savedDraft).toMatchObject({
      role: "advisor",
      tone: "direct",
      language: "es-MX",
      instructions: "Use tenant sources only.",
      prompt_blocks: [{ type: "instruction", content: "Escalate when policy is missing." }],
      snapshot: { builder_surface: "product_first_agent_builder" },
    });
    expect(legacyAgentsCalled).toBe(false);
  }, 20_000);

  it("renders existing draft and binding counts from Product-First endpoints", async () => {
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Configured Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Configured Agent").length).toBeGreaterThan(0));
    expect(await screen.findByText("Draft v1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Bindings" }));
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("Workflows")).toBeInTheDocument();
    expect(screen.getAllByText("Tools").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Actions").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1")).toHaveLength(2);
    expect(screen.getAllByText("2")).toHaveLength(2);
    expect(screen.queryByText(/Published/i)).not.toBeInTheDocument();
  });

  it("renders Knowledge tab with available sources and missing source blocker", async () => {
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Knowledge Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await userEvent.click(await screen.findByRole("tab", { name: "Knowledge" }));
    expect(await screen.findByText("Policies")).toBeInTheDocument();
    expect(screen.getByText("Broken FAQ")).toBeInTheDocument();
    expect(
      screen.getAllByText("Este agente no tiene fuentes de conocimiento conectadas.").length,
    ).toBeGreaterThan(0);
  });

  it("shows unhealthy source blocker in Knowledge tab", async () => {
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Unhealthy Agent" }));
    knowledgeBindings.set(
      "binding-2",
      bindingFixture({
        id: "binding-2",
        agent_id: "agent-1",
        knowledge_source_id: "source-2",
        source_name: "Broken FAQ",
        source_type: "faq",
        status: "failed",
        health: "unhealthy",
        blocker: true,
        blocker_reason: "source_unhealthy",
        error_message: "Parser failed",
        checksum: null,
        version: null,
        last_indexed_at: null,
      }),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await userEvent.click(await screen.findByRole("tab", { name: "Knowledge" }));
    expect(
      (await screen.findAllByText("Esta fuente no esta lista para publicar.")).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Parser failed").length).toBeGreaterThan(0);
  });

  it("binds and unbinds a source in draft and keeps live disabled", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Draft Knowledge Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByRole("tab", { name: "Knowledge" }));
    await user.click(firstElement(await screen.findAllByRole("button", { name: /conectar/i })));
    expect((await screen.findAllByText("Knowledge connected.")).length).toBeGreaterThan(0);
    expect(await screen.findByRole("button", { name: /quitar/i })).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();
    expect(screen.getAllByText("off").length).toBeGreaterThan(0);
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /quitar/i }));
    expect(
      (await screen.findAllByText("Este agente no tiene fuentes de conocimiento conectadas."))
        .length,
    ).toBeGreaterThan(0);
  });

  it("renders Tools as fact capabilities and binds without action side effects", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Tool Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByRole("tab", { name: "Tools" }));
    expect(await screen.findByText("Tools resuelven hechos.")).toBeInTheDocument();
    expect(screen.getByText("catalog.search")).toBeInTheDocument();
    expect(screen.getAllByText("none").length).toBeGreaterThan(0);

    await user.click(firstElement(await screen.findAllByRole("button", { name: /conectar/i })));
    expect(await screen.findByRole("button", { name: /quitar/i })).toBeInTheDocument();
    expect(screen.getAllByText("fact").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /quitar/i }));
    expect(await screen.findByText("Este agente no tiene tools conectadas.")).toBeInTheDocument();
  });

  it("renders Actions as side-effect capabilities and keeps send boundary disabled", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Action Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByRole("tab", { name: "Actions" }));
    expect(await screen.findByText("Actions producen efectos.")).toBeInTheDocument();
    expect(screen.getByText("update_contact_field")).toBeInTheDocument();
    expect(screen.getByText("send_message")).toBeInTheDocument();
    expect(
      screen.getByText("send_adapter_boundary, explicit_live_approval_required"),
    ).toBeInTheDocument();

    await user.click(firstElement(await screen.findAllByRole("button", { name: /agregar/i })));
    expect(await screen.findByRole("button", { name: /quitar/i })).toBeInTheDocument();
    expect(screen.getAllByText("effect").length).toBeGreaterThan(0);
    expect(screen.getAllByText("disabled").length).toBeGreaterThan(0);
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /quitar/i }));
    expect(await screen.findByText("Este agente no tiene actions agregadas.")).toBeInTheDocument();
  });

  it("creates Test Lab suite, scenario, runs no-send, and shows durable evidence", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Test Lab Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Test Lab Agent")).toHaveLength(2));
    await user.click(await screen.findByRole("tab", { name: "Test Lab" }));
    expect(await screen.findByText("DB-backed no-send Test Lab.")).toBeInTheDocument();
    expect(screen.getByText("No WhatsApp will be sent.")).toBeInTheDocument();
    expect(screen.getByText("No live outbox will be written.")).toBeInTheDocument();
    expect(screen.getByText("Actions/workflows are disabled or dry-run.")).toBeInTheDocument();
    expect(screen.getByText("No hay suites de Test Lab.")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Nombre de suite"));
    await user.type(screen.getByLabelText("Nombre de suite"), "Readiness suite");
    await user.click(screen.getByRole("button", { name: /suite/i }));
    expect(await screen.findByText("Readiness suite")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Nombre de escenario"));
    await user.type(screen.getByLabelText("Nombre de escenario"), "Happy path");
    await user.clear(screen.getByLabelText("Texto inbound"));
    await user.type(screen.getByLabelText("Texto inbound"), "Hola test{enter}Necesito ayuda");
    await user.type(screen.getByLabelText("Final message contains"), "Respuesta validada");
    await user.type(screen.getByLabelText("Tool expected"), "catalog.search");
    await user.type(screen.getByLabelText("Field expected"), "customer_name");
    await user.click(screen.getByLabelText("Should block"));
    await user.selectOptions(screen.getByLabelText("Execution mode"), "openai_direct_provider");
    expect(
      screen.getByText("OpenAI direct provider, WhatsApp no-send. Diagnostic only, not readiness."),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Execution mode"), "runtime_v2_agent_service");
    expect(
      screen.getByText(
        "Runtime V2 AgentService, WhatsApp no-send. This is the readiness path and requires trace_id.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /escenario/i }));
    expect(await screen.findByText("Happy path")).toBeInTheDocument();
    expect(screen.getByText("2 turnos - draft")).toBeInTheDocument();
    expect(screen.getByText(/contains "Respuesta validada"/)).toBeInTheDocument();
    expect(screen.getByText(/should block/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /run no-send test/i }));
    await waitFor(() =>
      expect(runSuiteBody).toMatchObject({
        mode: "no_send",
        execution_mode: "runtime_v2_agent_service",
        review_required: true,
      }),
    );
    expect(await screen.findByText("TEST_LAB_PASSED")).toBeInTheDocument();
    expect(screen.getByText("Turn 1 passed")).toBeInTheDocument();
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Output exacto")).toBeInTheDocument();
    expect(screen.getAllByText("Tools").length).toBeGreaterThan(0);
    expect(screen.getByText("Policy")).toBeInTheDocument();
    expect(screen.getByText("Send decision")).toBeInTheDocument();
    expect(screen.getByText("Respuesta validada.")).toBeInTheDocument();
    expect(
      screen.getByText("required: catalog.search | executed: catalog.search"),
    ).toBeInTheDocument();
    expect(screen.getByText("customer_name")).toBeInTheDocument();
    expect(screen.getAllByText("no_send").length).toBeGreaterThan(0);
    expect(screen.getByText("execution runtime_v2_agent_service")).toBeInTheDocument();
    expect(screen.getByText("tokens in 120 / out 24 / total 144")).toBeInTheDocument();
    expect(screen.getByText("in 120 / out 24 / total 144")).toBeInTheDocument();
    expect(screen.getByText("cost_rate_not_configured")).toBeInTheDocument();
    expect(screen.getByText("outbox pass")).toBeInTheDocument();
    expect(screen.getByText("side effects pass")).toBeInTheDocument();
    expect(screen.getByText("No WhatsApp will be sent.")).toBeInTheDocument();
  }, 20_000);

  it("renders failed Test Lab turn evidence without touching live send", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Failed Evidence Agent" }));
    testSuites.set(
      "suite-1",
      testSuiteFixture({
        id: "suite-1",
        agent_version_id: "draft-1",
        name: "Failure suite",
        status: "failed",
      }),
    );
    testScenarios.set(
      "scenario-1",
      testScenarioFixture({
        test_suite_id: "suite-1",
        expected: { turns: ["not an object"] },
      }),
    );
    testScenarios.set(
      "scenario-2",
      testScenarioFixture({
        id: "scenario-2",
        test_suite_id: "suite-1",
        name: "Empty expectations",
        expected: { turns: [{}] },
      }),
    );
    latestRuns.set(
      "suite-1",
      testRunFixture({
        id: "run-failed-evidence",
        status: "failed",
        decision: "TEST_LAB_BLOCKED_BY_TOOL",
        pass_count: 0,
        fail_count: 1,
        blocked_count: 1,
        trace_ids: [],
        outbox_audit_result: {},
        side_effect_audit_result: {},
        coverage_summary: "invalid",
        turn_results: [
          {
            turn_number: null,
            status: "failed",
            failures: ["tool_failed:catalog.search"],
            inbound: "Hola",
            final_message: "",
            trace_id: null,
            required_tools: ["catalog.search"],
            tools_executed: [],
            tools_skipped: [{ tool_name: "faq.lookup", status: "skipped" }],
            tools_failed: [{ name: "catalog.search", status: "failed" }],
            state_writes: [],
            policy_result: {},
            send_decision: null,
          },
          {
            turn_number: 2,
            status: "blocked",
            tools_required: "quote.resolve",
            tools_executed: null,
            tools_skipped: [{}, "invalid"],
            tools_failed: "catalog.search",
            state_writes: [{ field: "fallback_field" }, {}],
            policy_result: "invalid",
            estimated_cost: { amount_usd: 0.000123 },
          },
          {
            turn_number: 3,
            state_writes: "invalid",
          },
        ],
      }),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Failed Evidence Agent")).toHaveLength(2));
    await user.click(await screen.findByRole("tab", { name: "Test Lab" }));
    expect(await screen.findByText("Failure suite")).toBeInTheDocument();
    expect(screen.getByText("Empty expectations")).toBeInTheDocument();
    expect(screen.getByText("Expected: should not block")).toBeInTheDocument();
    expect(screen.getByText("TEST_LAB_BLOCKED_BY_TOOL")).toBeInTheDocument();
    expect(screen.getByText("Turn ? failed")).toBeInTheDocument();
    expect(screen.getAllByText("Trace missing").length).toBeGreaterThan(0);
    expect(
      screen.getByText("required: catalog.search | skipped: faq.lookup | failed: catalog.search"),
    ).toBeInTheDocument();
    expect(screen.getByText("tool_failed:catalog.search")).toBeInTheDocument();
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
    expect(screen.getAllByText("none").length).toBeGreaterThan(0);
    expect(screen.getByText("Turn 2 blocked")).toBeInTheDocument();
    expect(screen.getByText("skipped: unknown")).toBeInTheDocument();
    expect(screen.getByText("fallback_field, unknown")).toBeInTheDocument();
    expect(screen.getByText("$0.000123 USD")).toBeInTheDocument();
    expect(screen.getByText("Turn 3 unknown")).toBeInTheDocument();
    expect(screen.getAllByText("not estimated").length).toBeGreaterThan(0);
    expect(screen.getByText("execution simulated_contract")).toBeInTheDocument();
    expect(screen.getByText("outbox unknown")).toBeInTheDocument();
    expect(screen.getByText("No WhatsApp will be sent.")).toBeInTheDocument();
  });

  it("switches between Test Lab suites without touching live send", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Suite Switch Agent" }));
    testSuites.set(
      "suite-1",
      testSuiteFixture({
        id: "suite-1",
        agent_version_id: "draft-1",
        name: "Draft suite",
        status: "draft",
      }),
    );
    testSuites.set(
      "suite-2",
      testSuiteFixture({
        id: "suite-2",
        agent_version_id: "draft-1",
        name: "Regression suite",
        mode: "regression",
        status: "passed",
      }),
    );
    latestRuns.set(
      "suite-1",
      testRunFixture({
        id: "run-failed",
        status: "failed",
        decision: "TEST_LAB_FAILED",
        turn_results: [],
        pass_count: 0,
        fail_count: 1,
        trace_ids: [],
        outbox_audit_result: {},
        side_effect_audit_result: {},
      }),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Suite Switch Agent")).toHaveLength(2));
    await user.click(await screen.findByRole("tab", { name: "Test Lab" }));
    expect(await screen.findByText("Draft suite")).toBeInTheDocument();
    expect(screen.getByText("regression - passed")).toBeInTheDocument();
    expect(await screen.findByText("TEST_LAB_FAILED")).toBeInTheDocument();
    expect(screen.getByText("outbox unknown")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /regression suite/i }));
    expect(screen.getByText("No hay escenarios para esta suite.")).toBeInTheDocument();
    testSuites.delete("suite-2");
    await user.click(screen.getByRole("button", { name: /refrescar/i }));
    expect(await screen.findByText("draft_validation - draft")).toBeInTheDocument();
    testSuites.clear();
    await user.click(screen.getByRole("button", { name: /refrescar/i }));
    expect(await screen.findByText("No hay suites de Test Lab.")).toBeInTheDocument();
    expect(screen.getByText("No WhatsApp will be sent.")).toBeInTheDocument();
  });

  it("keeps Test Lab tab stable when suite, scenario, and run requests fail", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Test Lab Error Agent" }));
    server.use(
      http.post("/api/v1/product-agents/versions/:versionId/test-suites", () =>
        HttpResponse.json({ detail: "suite failed" }, { status: 500 }),
      ),
      http.post("/api/v1/product-agents/test-suites/:suiteId/scenarios", () =>
        HttpResponse.json({ detail: "scenario failed" }, { status: 500 }),
      ),
      http.post("/api/v1/product-agents/test-suites/:suiteId/runs", () =>
        HttpResponse.json({ detail: "run failed" }, { status: 500 }),
      ),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByRole("tab", { name: "Test Lab" }));
    await user.click(screen.getByRole("button", { name: /suite/i }));
    expect(await screen.findByText("No hay suites de Test Lab.")).toBeInTheDocument();

    testSuites.set("suite-1", testSuiteFixture({ agent_version_id: "draft-1" }));
    testScenarios.set("scenario-1", testScenarioFixture({ test_suite_id: "suite-1" }));
    await user.click(screen.getByRole("button", { name: /refrescar/i }));
    await user.click(await screen.findByRole("tab", { name: "Test Lab" }));
    await user.click(screen.getByRole("button", { name: /escenario/i }));
    expect(screen.getByText("Happy path")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /run no-send test/i }));
    expect(screen.getByText("No hay ejecucion de Test Lab todavia.")).toBeInTheDocument();
  });

  it("prepares Publish Control and shows blockers without enabling send", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Publish Blocked Agent" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Publish Blocked Agent")).toHaveLength(2));
    await user.click(await screen.findByRole("tab", { name: "Publish" }));
    expect(await screen.findByText("Publish Control no-send only.")).toBeInTheDocument();
    expect(screen.getByText("Falta ejecutar Test Lab.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /preparar publish/i }));
    expect(await screen.findByText("test_lab_run_missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /aprobar no-send/i })).toBeDisabled();
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();
  });

  it("approves Publish Control as no-send when gates pass", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Publish Ready Agent" }));
    testSuites.set("suite-1", testSuiteFixture({ agent_version_id: "draft-1" }));
    latestRuns.set("suite-1", testRunFixture({ agent_version_id: "draft-1" }));

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Publish Ready Agent")).toHaveLength(2));
    await user.click(await screen.findByRole("tab", { name: "Publish" }));
    expect(await screen.findByText("Latest Test Lab")).toBeInTheDocument();
    expect(screen.getByText("TEST_LAB_PASSED")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /preparar publish/i }));
    expect(await screen.findByText("ready_for_approval")).toBeInTheDocument();
    expect(screen.getByText("no blockers")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /evaluar gates/i }));
    await user.click(screen.getByRole("button", { name: /aprobar no-send/i }));
    expect(await screen.findByText("approved_no_send")).toBeInTheDocument();
    expect(screen.getAllByText("none").length).toBeGreaterThan(0);
    expect(screen.queryByText(/production/i)).not.toBeInTheDocument();
  });

  it("keeps Publish Control stable when publish request actions fail", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Publish Error Agent" }));
    testSuites.set("suite-1", testSuiteFixture({ agent_version_id: "draft-1" }));
    latestRuns.set("suite-1", testRunFixture({ agent_version_id: "draft-1" }));
    server.use(
      http.post("/api/v1/product-agents/deployments/:deploymentId/publish-requests", () =>
        HttpResponse.json({ detail: "publish request failed" }, { status: 500 }),
      ),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Publish Error Agent")).toHaveLength(2));
    await user.click(await screen.findByRole("tab", { name: "Publish" }));
    await user.click(screen.getByRole("button", { name: /preparar publish/i }));
    expect(await screen.findByText("No hay solicitud publish preparada.")).toBeInTheDocument();

    latestPublishRequests.set(
      "deployment-1",
      publishRequestFixture({
        deployment_id: "deployment-1",
        status: "ready_for_approval",
        blockers: [],
      }),
    );
    server.use(
      http.post("/api/v1/product-agents/deployments/:deploymentId/publish-requests", async () =>
        HttpResponse.json(publishRequestFixture({ status: "ready_for_approval", blockers: [] }), {
          status: 201,
        }),
      ),
      http.post("/api/v1/product-agents/publish-requests/:requestId/evaluate", () =>
        HttpResponse.json({ detail: "evaluate failed" }, { status: 500 }),
      ),
      http.post("/api/v1/product-agents/publish-requests/:requestId/approve-no-send", () =>
        HttpResponse.json({ detail: "approve failed" }, { status: 500 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: /refrescar/i }));
    await user.click(await screen.findByRole("tab", { name: "Publish" }));
    expect(await screen.findByText("ready_for_approval")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /evaluar gates/i }));
    expect(await screen.findByText("ready_for_approval")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /aprobar no-send/i }));
    expect(await screen.findByText("ready_for_approval")).toBeInTheDocument();
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();
  });

  it("calls Publish Control reject API without using live send", async () => {
    const response = await productAgentBuilderApi.rejectPublishRequest("publish-request-1", {
      reason: "human rejected no-send publish",
    });

    expect(response).toMatchObject({
      id: "publish-request-1",
      status: "rejected",
    });
  });

  it("shows Publish Control missing rollback and unknown audits as blockers", async () => {
    agents.set("agent-2", agentFixture({ id: "agent-2", name: "Publish Missing Rollback" }));
    testSuites.set("suite-1", testSuiteFixture({ agent_version_id: "draft-1" }));
    latestRuns.set(
      "suite-1",
      testRunFixture({
        agent_version_id: "draft-1",
        outbox_audit_result: {},
        side_effect_audit_result: {},
      }),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Publish Missing Rollback")).toHaveLength(2));
    await userEvent.click(await screen.findByRole("tab", { name: "Publish" }));
    expect(await screen.findByText("missing")).toBeInTheDocument();
    expect(screen.getAllByText("unknown")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: /preparar publish/i }));
    expect(await screen.findByText("rollback_target_missing")).toBeInTheDocument();
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();
  });

  it("keeps Publish Control disabled when no draft exists", async () => {
    agents.set(
      "agent-created",
      agentFixture({ id: "agent-created", name: "Publish Draftless Agent" }),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("Publish Draftless Agent")).toHaveLength(2));
    await userEvent.click(await screen.findByRole("tab", { name: "Publish" }));
    expect((await screen.findAllByText("none")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /preparar publish/i })).toBeDisabled();
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();
  });

  it("keeps Publish Control disabled when no Product-First deployment exists", async () => {
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "No Deployment Agent" }));
    server.use(
      http.get("/api/v1/product-agents/agents/:agentId/builder-state", ({ params }) =>
        HttpResponse.json({
          ...builderState(String(params.agentId)),
          deployments: [],
        }),
      ),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await waitFor(() => expect(screen.getAllByText("No Deployment Agent")).toHaveLength(2));
    await userEvent.click(await screen.findByRole("tab", { name: "Publish" }));
    expect(await screen.findByText("No hay deployment Product-First.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /preparar publish/i })).toBeDisabled();
    expect(screen.queryByText(/WhatsApp/i)).not.toBeInTheDocument();
  });

  it("keeps Tool and Action tabs stable when bind and unbind requests fail", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Capability Error Agent" }));
    server.use(
      http.post("/api/v1/product-agents/agents/:agentId/tool-bindings", () =>
        HttpResponse.json({ detail: "tool bind failed" }, { status: 500 }),
      ),
      http.post("/api/v1/product-agents/agents/:agentId/action-bindings", () =>
        HttpResponse.json({ detail: "action bind failed" }, { status: 500 }),
      ),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByRole("tab", { name: "Tools" }));
    await user.click(firstElement(await screen.findAllByRole("button", { name: /conectar/i })));
    expect(await screen.findByText("Este agente no tiene tools conectadas.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Actions" }));
    await user.click(firstElement(await screen.findAllByRole("button", { name: /agregar/i })));
    expect(await screen.findByText("Este agente no tiene actions agregadas.")).toBeInTheDocument();

    toolBindings.set(
      "tool-binding-1",
      toolBindingFixture({
        agent_id: "agent-1",
        enabled: false,
        blocker: true,
        blocker_reason: "unknown_tool",
      }),
    );
    actionBindings.set(
      "action-binding-1",
      actionBindingFixture({
        agent_id: "agent-1",
        required_auth: true,
        required_permissions: [],
        blocker: true,
        blocker_reason: "auth_required",
      }),
    );
    server.use(
      http.post("/api/v1/product-agents/agents/:agentId/tool-bindings", async () =>
        HttpResponse.json(toolBindingFixture({ agent_id: "agent-1" }), { status: 201 }),
      ),
      http.post("/api/v1/product-agents/agents/:agentId/action-bindings", async () =>
        HttpResponse.json(actionBindingFixture({ agent_id: "agent-1" }), { status: 201 }),
      ),
      http.delete("/api/v1/product-agents/agents/:agentId/tool-bindings/:bindingId", () =>
        HttpResponse.json({ detail: "tool unbind failed" }, { status: 500 }),
      ),
      http.delete("/api/v1/product-agents/agents/:agentId/action-bindings/:bindingId", () =>
        HttpResponse.json({ detail: "action unbind failed" }, { status: 500 }),
      ),
    );

    await user.click(screen.getByRole("button", { name: /refrescar/i }));
    await user.click(screen.getByRole("tab", { name: "Tools" }));
    await user.click(await screen.findByRole("button", { name: /quitar/i }));
    expect(screen.getAllByText("catalog.search").length).toBeGreaterThan(0);
    expect(screen.getByText("unknown_tool")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Actions" }));
    await user.click(await screen.findByRole("button", { name: /quitar/i }));
    expect(screen.getAllByText("update_contact_field").length).toBeGreaterThan(0);
    expect(screen.getAllByText("auth required").length).toBeGreaterThan(0);
    expect(screen.getByText("auth_required")).toBeInTheDocument();
  });

  it("keeps Knowledge tab stable when bind and unbind requests fail", async () => {
    const user = userEvent.setup();
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Knowledge Error Agent" }));
    server.use(
      http.post("/api/v1/product-agents/agents/:agentId/knowledge-bindings", () =>
        HttpResponse.json({ detail: "bind failed" }, { status: 500 }),
      ),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByRole("tab", { name: "Knowledge" }));
    await user.click(firstElement(await screen.findAllByRole("button", { name: /conectar/i })));
    expect(
      (await screen.findAllByText("Este agente no tiene fuentes de conocimiento conectadas."))
        .length,
    ).toBeGreaterThan(0);

    knowledgeBindings.set("binding-1", bindingFixture({ agent_id: "agent-1" }));
    server.use(
      http.post("/api/v1/product-agents/agents/:agentId/knowledge-bindings", async () =>
        HttpResponse.json(bindingFixture({ agent_id: "agent-1" }), { status: 201 }),
      ),
      http.delete("/api/v1/product-agents/agents/:agentId/knowledge-bindings/:bindingId", () =>
        HttpResponse.json({ detail: "unbind failed" }, { status: 500 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: /refrescar/i }));
    await user.click(await screen.findByRole("button", { name: /quitar/i }));

    expect((await screen.findAllByText("Policies")).length).toBeGreaterThan(0);
  });

  it("keeps the Builder stable when create and save requests fail", async () => {
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Configured Agent" }));
    server.use(
      http.post("/api/v1/product-agents/agents", () =>
        HttpResponse.json({ detail: "create failed" }, { status: 500 }),
      ),
      http.patch("/api/v1/product-agents/versions/:versionId/builder-config", () =>
        HttpResponse.json({ detail: "save failed" }, { status: 500 }),
      ),
    );

    const user = userEvent.setup();
    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.type(await screen.findByLabelText("Nombre del agente"), "Broken Agent");
    await user.click(screen.getByLabelText("Crear agente"));
    await waitFor(() => expect(screen.getAllByText("Configured Agent")).toHaveLength(2));

    await user.click(screen.getByLabelText("Guardar draft"));
    await waitFor(() => expect(savedDraft).toBeNull());
    expect(screen.getByText("Draft v1")).toBeInTheDocument();
  }, 10_000);

  it("handles draft creation errors and agent selection without legacy calls", async () => {
    agents.set(
      "agent-created",
      agentFixture({
        id: "agent-created",
        name: "Draftless Agent",
        role: null,
        tone: null,
        language: null,
        system_prompt: null,
      }),
    );
    agents.set("agent-2", agentFixture({ id: "agent-2", name: "Second Agent" }));
    server.use(
      http.post("/api/v1/product-agents/agents/:agentId/draft-version", () =>
        HttpResponse.json({ detail: "draft failed" }, { status: 500 }),
      ),
    );

    const user = userEvent.setup();
    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await user.click(await screen.findByText("Second Agent"));
    expect(await screen.findByRole("heading", { name: "Second Agent" })).toBeInTheDocument();
    await user.click(screen.getByText("Draftless Agent"));
    expect(await screen.findByText("Sin draft")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /crear draft/i }));
    expect(await screen.findByText("Sin draft")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /refrescar/i }));

    expect(legacyAgentsCalled).toBe(false);
  });

  it("renders pass and warn readiness rows and saves empty canonical fields", async () => {
    agents.set("agent-2", agentFixture({ id: "agent-2", name: "Second Agent" }));
    server.use(
      http.get("/api/v1/product-agents/agents/:agentId/readiness", () =>
        HttpResponse.json({
          status: "ready",
          version_id: "draft-1",
          blocking_codes: [],
          safety: { send_enabled: false, outbox_enabled: false, live_send_enabled: false },
          checks: [
            {
              code: "identity_ready",
              label: "Identity",
              status: "pass",
              message: "Draft identity has required fields.",
              metadata: {},
            },
            {
              code: "tools_empty",
              label: "Tools",
              status: "warn",
              message: "No tool binding yet.",
              metadata: {},
            },
          ],
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    expect(await screen.findByText("identity_ready")).toBeInTheDocument();
    expect(await screen.findByText("tools_empty")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Rol"));
    await user.clear(screen.getByLabelText("Tono"));
    await user.clear(screen.getByLabelText("Idioma"));
    await user.click(screen.getByLabelText("Guardar draft"));

    await waitFor(() => expect(savedDraft).not.toBeNull());
    expect(savedDraft).toMatchObject({
      role: null,
      tone: null,
      language: null,
      prompt_blocks: [],
    });

    await user.clear(screen.getByLabelText("Rol"));
    await user.clear(screen.getByLabelText("Tono"));
    await user.clear(screen.getByLabelText("Idioma"));
    await user.type(screen.getByLabelText("Nombre del agente"), "Fallback Agent");
    await user.click(screen.getByLabelText("Crear agente"));
    await waitFor(() =>
      expect(createdBody).toMatchObject({ role: "support", tone: "natural", language: "es" }),
    );
  }, 10_000);

  it("renders zero binding counts when Builder options are unavailable", async () => {
    agents.set("agent-1", agentFixture({ id: "agent-1", name: "Options Missing" }));
    server.use(
      http.get("/api/v1/product-agents/builder/options", () =>
        HttpResponse.json({ detail: "options failed" }, { status: 500 }),
      ),
      http.get("/api/v1/product-agents/knowledge-sources/options", () =>
        HttpResponse.json({ detail: "knowledge options failed" }, { status: 500 }),
      ),
      http.get("/api/v1/product-agents/tools/options", () =>
        HttpResponse.json({ detail: "tool options failed" }, { status: 500 }),
      ),
      http.get("/api/v1/product-agents/actions/options", () =>
        HttpResponse.json({ detail: "action options failed" }, { status: 500 }),
      ),
    );

    renderPage(<AgentBuilderPage />, { auth: { role: "tenant_admin" } });

    await screen.findByText("Options Missing");
    await screen.findByText("Draft v1");
    await userEvent.click(screen.getByRole("tab", { name: "Bindings" }));
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("Workflows")).toBeInTheDocument();
    expect(screen.getAllByText("0")).toHaveLength(4);
    await userEvent.click(screen.getByRole("tab", { name: "Knowledge" }));
    expect(screen.getByText("No hay fuentes de conocimiento disponibles.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Tools" }));
    expect(screen.getByText("No hay tools disponibles.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Actions" }));
    expect(screen.getByText("No hay actions disponibles.")).toBeInTheDocument();
  });
});

function agentFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "agent-1",
    tenant_id: "tenant-1",
    name: "Builder Agent",
    role: "support",
    status: "draft",
    tone: "warm",
    language: "es",
    system_prompt: "Use approved sources.",
    ops_config: { product_first: true },
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function firstElement<T>(items: T[]): T {
  const [item] = items;
  if (!item) throw new Error("Expected at least one element");
  return item;
}

function versionFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "draft-1",
    tenant_id: "tenant-1",
    agent_id: "agent-1",
    version_number: 1,
    status: "draft",
    is_immutable: false,
    role: "support",
    tone: "warm",
    language: "es",
    instructions: "Use approved sources.",
    prompt_blocks: [],
    snapshot: {},
    change_summary: null,
    published_at: null,
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function sourceFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "source-1",
    tenant_id: "tenant-1",
    name: "Policies",
    source_type: "document",
    content_type: "text/plain",
    status: "active",
    health: "healthy",
    parser_status: null,
    index_status: null,
    checksum: "sha256:abc",
    version: null,
    last_indexed_at: "2026-06-07T00:00:00Z",
    error_message: null,
    bound_agent_ids: [],
    blocker: false,
    blocker_reason: null,
    metadata: {},
    ...overrides,
  };
}

function bindingFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "binding-1",
    tenant_id: "tenant-1",
    agent_id: "agent-1",
    agent_version_id: "draft-1",
    knowledge_source_id: "source-1",
    source_name: "Policies",
    source_type: "document",
    status: "active",
    health: "healthy",
    required: true,
    binding_mode: "answer_basis",
    priority: 0,
    blocker: false,
    blocker_reason: null,
    checksum: "sha256:abc",
    version: null,
    last_indexed_at: "2026-06-07T00:00:00Z",
    error_message: null,
    metadata: {},
    ...overrides,
  };
}

function toolOptionFixture(overrides: Record<string, unknown> = {}) {
  return {
    key: "catalog.search",
    label: "Catalog search",
    kind: "tool",
    category: "fact_lookup",
    description: "Finds tenant catalog records.",
    risk_level: "read_only",
    side_effect_type: "none",
    has_side_effects: false,
    default_mode: "dry_run_only",
    required_auth: false,
    required_permissions: [],
    input_schema: {},
    output_schema: {},
    publish_blockers: [],
    ...overrides,
  };
}

function actionOptionFixture(overrides: Record<string, unknown> = {}) {
  return {
    key: "update_contact_field",
    label: "Update contact field",
    kind: "action",
    category: "state_write",
    description: "Requests a governed contact field update.",
    risk_level: "internal_write",
    side_effect_type: "crm_write",
    has_side_effects: true,
    default_mode: "approval_required",
    required_auth: false,
    required_permissions: ["contact.write"],
    input_schema: {},
    output_schema: {},
    publish_blockers: ["field_policy_required", "approval_policy_required"],
    ...overrides,
  };
}

function toolBindingFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "tool-binding-1",
    tenant_id: "tenant-1",
    agent_id: "agent-1",
    agent_version_id: "draft-1",
    tool_name: "catalog.search",
    label: "Catalog search",
    category: "fact_lookup",
    enabled: true,
    required: false,
    risk_level: "read_only",
    side_effect_type: "none",
    has_side_effects: false,
    blocker: false,
    blocker_reason: null,
    input_schema: {},
    output_schema: {},
    metadata: {},
    ...overrides,
  };
}

function actionBindingFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "action-binding-1",
    tenant_id: "tenant-1",
    agent_id: "agent-1",
    agent_version_id: "draft-1",
    action_key: "update_contact_field",
    label: "Update contact field",
    category: "state_write",
    enabled: false,
    execution_mode: "disabled",
    approval_required: true,
    risk_level: "internal_write",
    side_effect_type: "crm_write",
    has_side_effects: true,
    required_auth: false,
    required_permissions: ["contact.write"],
    permissions: {},
    blocker: false,
    blocker_reason: null,
    publish_blockers: ["field_policy_required", "approval_policy_required"],
    metadata: {},
    ...overrides,
  };
}

function testSuiteFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "suite-1",
    tenant_id: "tenant-1",
    agent_version_id: "draft-1",
    name: "Readiness suite",
    mode: "draft_validation",
    status: "draft",
    last_run_id: null,
    metadata_json: {},
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function testScenarioFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "scenario-1",
    tenant_id: "tenant-1",
    test_suite_id: "suite-1",
    name: "Happy path",
    turns: [{ inbound_text: "Hola test" }],
    expected: { final_messages: ["Respuesta validada."] },
    status: "draft",
    metadata_json: {},
    created_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function testRunFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    tenant_id: "tenant-1",
    agent_version_id: "draft-1",
    test_suite_id: "suite-1",
    mode: "no_send",
    status: "passed",
    decision: "TEST_LAB_PASSED",
    scenario_results: [{ scenario_id: "scenario-1", status: "passed", failures: [] }],
    turn_results: [
      {
        turn_number: 1,
        status: "passed",
        failures: [],
        input: "Hola test",
        inbound: "Hola test",
        final_message: "Respuesta validada.",
        trace_id: "trace-1",
        tools_required: ["catalog.search"],
        required_tools: ["catalog.search"],
        tools_executed: [{ tool_name: "catalog.search", status: "succeeded" }],
        tools_skipped: [],
        tools_failed: [],
        state_writes: [{ field_key: "customer_name" }],
        policy_result: { status: "passed" },
        send_decision: "no_send",
        send_status: "no_send",
        execution_mode: "runtime_v2_agent_service",
        token_usage: { input_tokens: 120, output_tokens: 24, total_tokens: 144 },
        estimated_cost: {
          amount_usd: null,
          status: "cost_rate_not_configured",
          input_tokens: 120,
          output_tokens: 24,
          total_tokens: 144,
        },
      },
    ],
    pass_count: 1,
    fail_count: 0,
    blocked_count: 0,
    trace_ids: ["trace-1"],
    outbox_audit_result: { count: 0, status: "pass" },
    side_effect_audit_result: { count: 0, status: "pass" },
    coverage_summary: {
      scope: "product_first_test_lab_mvp",
      execution_mode: "runtime_v2_agent_service",
    },
    review_required: true,
    created_by_user_id: "user-1",
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function deploymentFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "deployment-1",
    tenant_id: "tenant-1",
    agent_id: "agent-1",
    active_version_id: null,
    rollback_version_id: "published-1",
    name: "No-send deployment",
    channel: "test_lab",
    environment: "no_send",
    publish_state: "draft",
    runtime_mode: "no_send",
    send_scope: "none",
    send_enabled: false,
    outbox_enabled: false,
    live_send_enabled: false,
    single_contact_smoke_enabled: false,
    actions_enabled: false,
    workflow_events_enabled: false,
    workflow_side_effects_enabled: false,
    canary_enabled: false,
    open_production_enabled: false,
    published_at: null,
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function publishRequestFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "publish-request-1",
    tenant_id: "tenant-1",
    agent_id: "agent-1",
    agent_version_id: "draft-1",
    deployment_id: "deployment-1",
    requested_state: "published_no_send",
    status: "blocked",
    send_scope: "none",
    channel_scope: null,
    audience_scope: {},
    test_run_ids: [],
    readiness_snapshot: {},
    blockers: [{ code: "test_lab_run_missing" }],
    rollback_version_id: "published-1",
    approval_text: null,
    decision_reason: "blocked",
    requested_by_user_id: "user-1",
    approved_by_user_id: null,
    decided_at: null,
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

function agentReadiness(agentId: string) {
  const bindings = [...knowledgeBindings.values()].filter(
    (binding) => binding.agent_id === agentId,
  );
  const unhealthy = bindings.some((binding) => Boolean(binding.blocker));
  if (!bindings.length) {
    return {
      status: "blocked",
      version_id: "draft-1",
      agent_id: agentId,
      blocking_codes: ["required_knowledge_missing"],
      safety: { send_enabled: false, outbox_enabled: false, live_send_enabled: false },
      test_lab_passed: false,
      live_publish_allowed: false,
      checks: [
        {
          code: "required_knowledge_missing",
          label: "Knowledge sources",
          status: "block",
          message: "Required knowledge source binding is missing.",
          metadata: {},
        },
      ],
    };
  }
  return {
    status: unhealthy ? "blocked" : "ready",
    version_id: "draft-1",
    agent_id: agentId,
    blocking_codes: unhealthy ? ["knowledge_sources_healthy"] : [],
    safety: { send_enabled: false, outbox_enabled: false, live_send_enabled: false },
    test_lab_passed: false,
    live_publish_allowed: false,
    checks: [
      {
        code: "knowledge_sources_healthy",
        label: "Knowledge sources",
        status: unhealthy ? "block" : "pass",
        message: unhealthy ? "Esta fuente no esta lista para publicar." : "Knowledge connected.",
        metadata: {},
      },
    ],
  };
}

function builderState(agentId: string) {
  const agent = agents.get(agentId) ?? agentFixture({ id: agentId });
  const hasDraft = draftAgents.has(agentId) || agentId !== "agent-created" || Boolean(savedDraft);
  const fallbackDraft =
    agentId === "agent-2"
      ? versionFixture({
          agent_id: agentId,
          role: null,
          tone: null,
          language: null,
          instructions: null,
          prompt_blocks: [{ type: "instruction", content: 123 }],
        })
      : versionFixture({ agent_id: agentId });
  const draft = hasDraft ? { ...fallbackDraft, ...savedDraft } : null;
  const published =
    agentId === "agent-1" ? versionFixture({ id: "published-1", status: "published" }) : null;
  return {
    agent,
    versions: draft ? [draft] : [],
    deployments: [deploymentFixture({ agent_id: agentId })],
    draft_version: draft,
    published_version: published,
  };
}

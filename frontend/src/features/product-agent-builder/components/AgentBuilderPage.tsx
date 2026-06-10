import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BotMessageSquare,
  CheckCircle2,
  Database,
  FileText,
  FlaskConical,
  Link,
  Lock,
  Plus,
  RefreshCw,
  Save,
  Unlink2,
  Wrench,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  type AgentActionBinding,
  type AgentBuilderState,
  type AgentKnowledgeBinding,
  type AgentPublishRequest,
  type AgentTestRun,
  type AgentTestScenario,
  type AgentTestSuite,
  type AgentToolBinding,
  type AgentVersion,
  type BuilderConfigPayload,
  type BuilderReadinessCheck,
  type CapabilityOption,
  type KnowledgeSourceOption,
  type ProductAgent,
  productAgentBuilderApi,
} from "@/features/product-agent-builder/api";
import { cn } from "@/lib/utils";

interface DraftForm {
  role: string;
  tone: string;
  language: string;
  instructions: string;
  promptBlock: string;
}

const emptyForm: DraftForm = {
  role: "support",
  tone: "natural",
  language: "es",
  instructions: "",
  promptBlock: "",
};

export function AgentBuilderPage() {
  const queryClient = useQueryClient();
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedSuiteId, setSelectedSuiteId] = useState<string | null>(null);
  const [newAgentName, setNewAgentName] = useState("");
  const [newSuiteName, setNewSuiteName] = useState("Readiness suite");
  const [newScenarioName, setNewScenarioName] = useState("Happy path");
  const [newScenarioText, setNewScenarioText] = useState("Hola");
  const [newScenarioExpected, setNewScenarioExpected] = useState("");
  const [newScenarioExpectedTool, setNewScenarioExpectedTool] = useState("");
  const [newScenarioExpectedField, setNewScenarioExpectedField] = useState("");
  const [newScenarioShouldBlock, setNewScenarioShouldBlock] = useState(false);
  const [testExecutionMode, setTestExecutionMode] = useState("simulated_contract");
  const [form, setForm] = useState<DraftForm>(emptyForm);

  const agentsQuery = useQuery({
    queryKey: ["product-agent-builder", "agents"],
    queryFn: productAgentBuilderApi.listAgents,
  });
  const optionsQuery = useQuery({
    queryKey: ["product-agent-builder", "options"],
    queryFn: productAgentBuilderApi.builderOptions,
  });
  const knowledgeOptionsQuery = useQuery({
    queryKey: ["product-agent-builder", "knowledge-options"],
    queryFn: productAgentBuilderApi.knowledgeSourceOptions,
  });
  const stateQuery = useQuery({
    queryKey: ["product-agent-builder", "state", selectedAgentId],
    queryFn: () => productAgentBuilderApi.builderState(selectedAgentId as string),
    enabled: Boolean(selectedAgentId),
  });
  const draftVersion = stateQuery.data?.draft_version ?? null;
  const readinessQuery = useQuery({
    queryKey: ["product-agent-builder", "readiness", selectedAgentId, draftVersion?.id],
    queryFn: () => productAgentBuilderApi.agentReadiness(selectedAgentId as string),
    enabled: Boolean(selectedAgentId && draftVersion?.id),
  });
  const knowledgeBindingsQuery = useQuery({
    queryKey: ["product-agent-builder", "knowledge-bindings", selectedAgentId, draftVersion?.id],
    queryFn: () => productAgentBuilderApi.knowledgeBindings(selectedAgentId as string),
    enabled: Boolean(selectedAgentId && draftVersion?.id),
  });
  const toolOptionsQuery = useQuery({
    queryKey: ["product-agent-builder", "tool-options"],
    queryFn: productAgentBuilderApi.toolOptions,
  });
  const actionOptionsQuery = useQuery({
    queryKey: ["product-agent-builder", "action-options"],
    queryFn: productAgentBuilderApi.actionOptions,
  });
  const toolBindingsQuery = useQuery({
    queryKey: ["product-agent-builder", "tool-bindings", selectedAgentId, draftVersion?.id],
    queryFn: () => productAgentBuilderApi.toolBindings(selectedAgentId as string),
    enabled: Boolean(selectedAgentId && draftVersion?.id),
  });
  const actionBindingsQuery = useQuery({
    queryKey: ["product-agent-builder", "action-bindings", selectedAgentId, draftVersion?.id],
    queryFn: () => productAgentBuilderApi.actionBindings(selectedAgentId as string),
    enabled: Boolean(selectedAgentId && draftVersion?.id),
  });
  const testSuitesQuery = useQuery({
    queryKey: ["product-agent-builder", "test-suites", draftVersion?.id],
    queryFn: () => productAgentBuilderApi.testSuites(draftVersion?.id as string),
    enabled: Boolean(draftVersion?.id),
  });
  const testScenariosQuery = useQuery({
    queryKey: ["product-agent-builder", "test-scenarios", selectedSuiteId],
    queryFn: () => productAgentBuilderApi.testScenarios(selectedSuiteId as string),
    enabled: Boolean(selectedSuiteId),
  });
  const latestTestRunQuery = useQuery({
    queryKey: ["product-agent-builder", "latest-test-run", selectedSuiteId],
    queryFn: () => productAgentBuilderApi.latestTestRun(selectedSuiteId as string),
    enabled: Boolean(selectedSuiteId),
  });
  const activeDeploymentId = stateQuery.data?.deployments[0]?.id ?? null;
  const latestPublishRequestQuery = useQuery({
    queryKey: ["product-agent-builder", "latest-publish-request", activeDeploymentId],
    queryFn: () => productAgentBuilderApi.latestPublishRequest(activeDeploymentId as string),
    enabled: Boolean(activeDeploymentId),
  });

  useEffect(() => {
    if (!selectedAgentId && agentsQuery.data?.[0]) {
      setSelectedAgentId(agentsQuery.data[0].id);
    }
  }, [agentsQuery.data, selectedAgentId]);

  useEffect(() => {
    if (draftVersion) {
      setForm(formFromVersion(draftVersion));
    } else if (stateQuery.data?.agent) {
      setForm(formFromAgent(stateQuery.data.agent));
    }
  }, [draftVersion, stateQuery.data?.agent]);

  useEffect(() => {
    if (!selectedSuiteId && testSuitesQuery.data?.[0]) {
      setSelectedSuiteId(testSuitesQuery.data[0].id);
    }
    if (selectedSuiteId && testSuitesQuery.data) {
      const stillExists = testSuitesQuery.data.some((suite) => suite.id === selectedSuiteId);
      if (!stillExists) setSelectedSuiteId(testSuitesQuery.data[0]?.id ?? null);
    }
  }, [selectedSuiteId, testSuitesQuery.data]);

  const createAgentMutation = useMutation({
    mutationFn: () =>
      productAgentBuilderApi.createAgent({
        name: newAgentName.trim(),
        role: form.role.trim() || "support",
        tone: form.tone.trim() || "natural",
        language: form.language.trim() || "es",
      }),
    onSuccess: (agent) => {
      setNewAgentName("");
      setSelectedAgentId(agent.id);
      toast.success("Agente creado");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "agents"] });
    },
    onError: (error: Error) => toast.error("No se pudo crear", { description: error.message }),
  });

  const createDraftMutation = useMutation({
    mutationFn: () => {
      /* v8 ignore next -- UI disables draft creation until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.createDraftVersion(selectedAgentId, payloadFromForm(form));
    },
    onSuccess: () => {
      toast.success("Draft creado");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "state"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo crear draft", { description: error.message }),
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      /* v8 ignore next -- UI disables save until a mutable draft exists. */
      if (!draftVersion) throw new Error("Crea un draft editable");
      return productAgentBuilderApi.updateBuilderConfig(draftVersion.id, payloadFromForm(form));
    },
    onSuccess: () => {
      toast.success("Draft guardado");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "state"] });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
    },
    onError: (error: Error) => toast.error("No se pudo guardar", { description: error.message }),
  });

  const bindKnowledgeMutation = useMutation({
    mutationFn: (sourceId: string) => {
      /* v8 ignore next -- UI disables binding until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.bindKnowledgeSource(selectedAgentId, {
        knowledge_source_id: sourceId,
        binding_mode: "answer_basis",
        required: true,
      });
    },
    onSuccess: () => {
      toast.success("Fuente conectada");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "knowledge"] });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "knowledge-options"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "knowledge-bindings"],
      });
    },
    onError: (error: Error) =>
      toast.error("No se pudo conectar la fuente", { description: error.message }),
  });

  const unbindKnowledgeMutation = useMutation({
    mutationFn: (bindingId: string) => {
      /* v8 ignore next -- UI disables unbinding until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.unbindKnowledgeSource(selectedAgentId, bindingId);
    },
    onSuccess: () => {
      toast.success("Fuente desconectada");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "knowledge-options"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "knowledge-bindings"],
      });
    },
    onError: (error: Error) =>
      toast.error("No se pudo desconectar la fuente", { description: error.message }),
  });

  const bindToolMutation = useMutation({
    mutationFn: (toolName: string) => {
      /* v8 ignore next -- UI disables binding until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.bindTool(selectedAgentId, {
        tool_name: toolName,
        enabled: true,
        required: false,
      });
    },
    onSuccess: () => {
      toast.success("Tool conectada");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "tool-bindings"] });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo conectar la tool", { description: error.message }),
  });

  const unbindToolMutation = useMutation({
    mutationFn: (bindingId: string) => {
      /* v8 ignore next -- UI disables unbinding until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.unbindTool(selectedAgentId, bindingId);
    },
    onSuccess: () => {
      toast.success("Tool desconectada");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "tool-bindings"] });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo desconectar la tool", { description: error.message }),
  });

  const bindActionMutation = useMutation({
    mutationFn: (actionKey: string) => {
      /* v8 ignore next -- UI disables binding until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.bindAction(selectedAgentId, {
        action_key: actionKey,
        enabled: false,
        execution_mode: "disabled",
        permissions: {},
      });
    },
    onSuccess: () => {
      toast.success("Action agregada en disabled");
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "action-bindings"],
      });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo agregar la action", { description: error.message }),
  });

  const unbindActionMutation = useMutation({
    mutationFn: (bindingId: string) => {
      /* v8 ignore next -- UI disables unbinding until an agent is selected. */
      if (!selectedAgentId) throw new Error("Selecciona un agente");
      return productAgentBuilderApi.unbindAction(selectedAgentId, bindingId);
    },
    onSuccess: () => {
      toast.success("Action removida");
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "action-bindings"],
      });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo remover la action", { description: error.message }),
  });

  const createTestSuiteMutation = useMutation({
    mutationFn: () => {
      /* v8 ignore next -- UI disables suite creation until a draft exists. */
      if (!draftVersion) throw new Error("Crea un draft editable");
      return productAgentBuilderApi.createTestSuite(draftVersion.id, {
        name: newSuiteName.trim(),
        mode: "draft_validation",
        metadata: { product_first_builder: true },
      });
    },
    onSuccess: (suite) => {
      setSelectedSuiteId(suite.id);
      toast.success("Suite creada");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "test-suites"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo crear suite", { description: error.message }),
  });

  const createTestScenarioMutation = useMutation({
    mutationFn: () => {
      /* v8 ignore next -- UI disables scenario creation until a suite exists. */
      if (!selectedSuiteId) throw new Error("Selecciona una suite");
      const turns = scenarioTurnsFromText(newScenarioText);
      const expectedTurn: Record<string, unknown> = {
        expected_send_decision: "no_send",
        should_block: newScenarioShouldBlock,
      };
      if (newScenarioExpected.trim()) {
        expectedTurn.final_message_contains = newScenarioExpected.trim();
      }
      if (newScenarioExpectedTool.trim()) {
        expectedTurn.expected_tools = [newScenarioExpectedTool.trim()];
      }
      if (newScenarioExpectedField.trim()) {
        expectedTurn.expected_state_writes = [newScenarioExpectedField.trim()];
      }
      return productAgentBuilderApi.createTestScenario(selectedSuiteId, {
        name: newScenarioName.trim(),
        turns,
        expected: {
          turns: turns.map(() => expectedTurn),
          expected_send_decision: "no_send",
          internal_text_forbidden: true,
        },
        metadata: { product_first_builder: true, behavior_validation: true },
      });
    },
    onSuccess: () => {
      toast.success("Escenario creado");
      setNewScenarioShouldBlock(false);
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "test-scenarios"],
      });
    },
    onError: (error: Error) =>
      toast.error("No se pudo crear escenario", { description: error.message }),
  });

  const runTestSuiteMutation = useMutation({
    mutationFn: () => {
      /* v8 ignore next -- UI disables run until a suite exists. */
      if (!selectedSuiteId) throw new Error("Selecciona una suite");
      return productAgentBuilderApi.runTestSuite(selectedSuiteId, {
        mode: "no_send",
        execution_mode: testExecutionMode,
        review_required: true,
      });
    },
    onSuccess: () => {
      toast.success("Test Lab ejecutado");
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "latest-test-run"],
      });
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "readiness"] });
    },
    onError: (error: Error) =>
      toast.error("No se pudo ejecutar Test Lab", { description: error.message }),
  });

  const createPublishRequestMutation = useMutation({
    mutationFn: () => {
      /* v8 ignore next -- UI disables publish request until deployment and draft exist. */
      if (!activeDeploymentId || !draftVersion) throw new Error("Falta deployment o version");
      return productAgentBuilderApi.createPublishRequest(activeDeploymentId, {
        agent_version_id: draftVersion.id,
        requested_state: "published_no_send",
        send_scope: "none",
        rollback_version_id: stateQuery.data?.published_version?.id ?? null,
        approval_text: "Prepare no-send publish approval.",
      });
    },
    onSuccess: () => {
      toast.success("Solicitud evaluada");
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "latest-publish-request"],
      });
    },
    onError: (error: Error) =>
      toast.error("No se pudo preparar publish", { description: error.message }),
  });

  const evaluatePublishRequestMutation = useMutation({
    mutationFn: () => {
      const requestId = latestPublishRequestQuery.data?.id;
      /* v8 ignore next -- UI disables evaluation until a request exists. */
      if (!requestId) throw new Error("No hay solicitud publish");
      return productAgentBuilderApi.evaluatePublishRequest(requestId);
    },
    onSuccess: () => {
      toast.success("Gates evaluados");
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "latest-publish-request"],
      });
    },
    onError: (error: Error) =>
      toast.error("No se pudieron evaluar gates", { description: error.message }),
  });

  const approvePublishRequestMutation = useMutation({
    mutationFn: () => {
      const requestId = latestPublishRequestQuery.data?.id;
      /* v8 ignore next -- UI disables approval until a request exists. */
      if (!requestId) throw new Error("No hay solicitud publish");
      return productAgentBuilderApi.approvePublishRequestNoSend(requestId, {
        approval_text: "Approved no-send publish only.",
      });
    },
    onSuccess: () => {
      toast.success("Publicado en no-send");
      void queryClient.invalidateQueries({ queryKey: ["product-agent-builder", "state"] });
      void queryClient.invalidateQueries({
        queryKey: ["product-agent-builder", "latest-publish-request"],
      });
    },
    onError: (error: Error) =>
      toast.error("No se pudo aprobar no-send", { description: error.message }),
  });

  const selectedAgent = useMemo(
    () => agentsQuery.data?.find((agent) => agent.id === selectedAgentId) ?? null,
    [agentsQuery.data, selectedAgentId],
  );

  return (
    <div className="-m-6 min-h-[calc(100vh-3.5rem)] bg-zinc-950 text-zinc-100">
      <header className="border-b border-white/10 bg-zinc-950 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <BotMessageSquare className="h-5 w-5 text-cyan-300" />
          <div>
            <h1 className="text-xl font-semibold">Product Agent Builder</h1>
            <p className="text-xs text-zinc-500">Draft control plane</p>
          </div>
          <Badge
            variant="outline"
            className="ml-auto border-cyan-400/30 bg-cyan-500/10 text-cyan-100"
          >
            No-send
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-white/10 bg-white/[0.035]"
            onClick={() => {
              void agentsQuery.refetch();
              void optionsQuery.refetch();
              void knowledgeOptionsQuery.refetch();
              void toolOptionsQuery.refetch();
              void actionOptionsQuery.refetch();
              void stateQuery.refetch();
              void readinessQuery.refetch();
              void knowledgeBindingsQuery.refetch();
              void toolBindingsQuery.refetch();
              void actionBindingsQuery.refetch();
              void testSuitesQuery.refetch();
              void testScenariosQuery.refetch();
              void latestTestRunQuery.refetch();
              void latestPublishRequestQuery.refetch();
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refrescar
          </Button>
        </div>
      </header>

      <main className="grid min-h-[calc(100vh-8.5rem)] gap-0 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="border-r border-white/10 bg-zinc-900/70 p-4">
          <div className="mb-3 flex gap-2">
            <Input
              aria-label="Nombre del agente"
              value={newAgentName}
              onChange={(event) => setNewAgentName(event.target.value)}
              placeholder="Nuevo agente"
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <Button
              type="button"
              size="icon"
              disabled={!newAgentName.trim() || createAgentMutation.isPending}
              onClick={() => createAgentMutation.mutate()}
              aria-label="Crear agente"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>

          <div className="space-y-2">
            {agentsQuery.isLoading ? (
              <>
                <Skeleton className="h-12 bg-white/10" />
                <Skeleton className="h-12 bg-white/10" />
              </>
            ) : agentsQuery.data?.length ? (
              agentsQuery.data.map((agent) => (
                <AgentListButton
                  key={agent.id}
                  agent={agent}
                  active={agent.id === selectedAgentId}
                  onClick={() => setSelectedAgentId(agent.id)}
                />
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-4 text-sm text-zinc-400">
                Sin agentes Product-First.
              </div>
            )}
          </div>
        </aside>

        <section className="min-w-0 p-4">
          {!selectedAgent ? (
            <div className="flex h-full min-h-96 items-center justify-center rounded-md border border-dashed border-white/10 text-zinc-500">
              Selecciona o crea un agente.
            </div>
          ) : (
            <BuilderWorkspace
              state={stateQuery.data}
              loading={stateQuery.isLoading}
              draftVersion={draftVersion}
              form={form}
              setForm={setForm}
              onCreateDraft={() => createDraftMutation.mutate()}
              creatingDraft={createDraftMutation.isPending}
              onSave={() => saveMutation.mutate()}
              saving={saveMutation.isPending}
              checks={readinessQuery.data?.checks ?? []}
              readinessStatus={readinessQuery.data?.status ?? "blocked"}
              knowledgeSources={knowledgeOptionsQuery.data ?? []}
              knowledgeBindings={knowledgeBindingsQuery.data ?? []}
              toolOptions={toolOptionsQuery.data ?? []}
              toolBindings={toolBindingsQuery.data ?? []}
              actionOptions={actionOptionsQuery.data ?? []}
              actionBindings={actionBindingsQuery.data ?? []}
              testSuites={testSuitesQuery.data ?? []}
              selectedSuiteId={selectedSuiteId}
              onSelectSuite={setSelectedSuiteId}
              testScenarios={testScenariosQuery.data ?? []}
              latestTestRun={latestTestRunQuery.data ?? null}
              latestPublishRequest={latestPublishRequestQuery.data ?? null}
              newSuiteName={newSuiteName}
              setNewSuiteName={setNewSuiteName}
              newScenarioName={newScenarioName}
              setNewScenarioName={setNewScenarioName}
              newScenarioText={newScenarioText}
              setNewScenarioText={setNewScenarioText}
              newScenarioExpected={newScenarioExpected}
              setNewScenarioExpected={setNewScenarioExpected}
              newScenarioExpectedTool={newScenarioExpectedTool}
              setNewScenarioExpectedTool={setNewScenarioExpectedTool}
              newScenarioExpectedField={newScenarioExpectedField}
              setNewScenarioExpectedField={setNewScenarioExpectedField}
              newScenarioShouldBlock={newScenarioShouldBlock}
              setNewScenarioShouldBlock={setNewScenarioShouldBlock}
              testExecutionMode={testExecutionMode}
              setTestExecutionMode={setTestExecutionMode}
              onCreateTestSuite={() => createTestSuiteMutation.mutate()}
              onCreateTestScenario={() => createTestScenarioMutation.mutate()}
              onRunTestSuite={() => runTestSuiteMutation.mutate()}
              onCreatePublishRequest={() => createPublishRequestMutation.mutate()}
              onEvaluatePublishRequest={() => evaluatePublishRequestMutation.mutate()}
              onApprovePublishNoSend={() => approvePublishRequestMutation.mutate()}
              creatingTestSuite={createTestSuiteMutation.isPending}
              creatingTestScenario={createTestScenarioMutation.isPending}
              runningTestSuite={runTestSuiteMutation.isPending}
              creatingPublishRequest={createPublishRequestMutation.isPending}
              evaluatingPublishRequest={evaluatePublishRequestMutation.isPending}
              approvingPublishRequest={approvePublishRequestMutation.isPending}
              onBindKnowledge={(sourceId) => bindKnowledgeMutation.mutate(sourceId)}
              onUnbindKnowledge={(bindingId) => unbindKnowledgeMutation.mutate(bindingId)}
              onBindTool={(toolName) => bindToolMutation.mutate(toolName)}
              onUnbindTool={(bindingId) => unbindToolMutation.mutate(bindingId)}
              onBindAction={(actionKey) => bindActionMutation.mutate(actionKey)}
              onUnbindAction={(bindingId) => unbindActionMutation.mutate(bindingId)}
              bindingKnowledge={bindKnowledgeMutation.isPending}
              unbindingKnowledge={unbindKnowledgeMutation.isPending}
              bindingTool={bindToolMutation.isPending}
              unbindingTool={unbindToolMutation.isPending}
              bindingAction={bindActionMutation.isPending}
              unbindingAction={unbindActionMutation.isPending}
              optionCounts={{
                sources: optionsQuery.data?.knowledge_sources.length ?? 0,
                tools: optionsQuery.data?.tools.length ?? 0,
                actions: optionsQuery.data?.actions.length ?? 0,
                workflows: optionsQuery.data?.workflows.length ?? 0,
              }}
            />
          )}
        </section>
      </main>
    </div>
  );
}

function AgentListButton({
  agent,
  active,
  onClick,
}: {
  agent: ProductAgent;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-left transition",
        active
          ? "border-cyan-300/50 bg-cyan-500/15 text-cyan-50"
          : "border-white/10 bg-black/20 text-zinc-300 hover:border-white/20 hover:bg-white/[0.04]",
      )}
    >
      <div className="truncate text-sm font-medium">{agent.name}</div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-zinc-500">
        <span>{agent.role}</span>
        <span>{agent.status}</span>
      </div>
    </button>
  );
}

function BuilderWorkspace({
  state,
  loading,
  draftVersion,
  form,
  setForm,
  onCreateDraft,
  creatingDraft,
  onSave,
  saving,
  checks,
  readinessStatus,
  knowledgeSources,
  knowledgeBindings,
  toolOptions,
  toolBindings,
  actionOptions,
  actionBindings,
  testSuites,
  selectedSuiteId,
  onSelectSuite,
  testScenarios,
  latestTestRun,
  latestPublishRequest,
  newSuiteName,
  setNewSuiteName,
  newScenarioName,
  setNewScenarioName,
  newScenarioText,
  setNewScenarioText,
  newScenarioExpected,
  setNewScenarioExpected,
  newScenarioExpectedTool,
  setNewScenarioExpectedTool,
  newScenarioExpectedField,
  setNewScenarioExpectedField,
  newScenarioShouldBlock,
  setNewScenarioShouldBlock,
  testExecutionMode,
  setTestExecutionMode,
  onBindKnowledge,
  onUnbindKnowledge,
  onBindTool,
  onUnbindTool,
  onBindAction,
  onUnbindAction,
  onCreateTestSuite,
  onCreateTestScenario,
  onRunTestSuite,
  onCreatePublishRequest,
  onEvaluatePublishRequest,
  onApprovePublishNoSend,
  bindingKnowledge,
  unbindingKnowledge,
  bindingTool,
  unbindingTool,
  bindingAction,
  unbindingAction,
  creatingTestSuite,
  creatingTestScenario,
  runningTestSuite,
  creatingPublishRequest,
  evaluatingPublishRequest,
  approvingPublishRequest,
  optionCounts,
}: {
  state: AgentBuilderState | undefined;
  loading: boolean;
  draftVersion: AgentVersion | null;
  form: DraftForm;
  setForm: (form: DraftForm) => void;
  onCreateDraft: () => void;
  creatingDraft: boolean;
  onSave: () => void;
  saving: boolean;
  checks: BuilderReadinessCheck[];
  readinessStatus: string;
  knowledgeSources: KnowledgeSourceOption[];
  knowledgeBindings: AgentKnowledgeBinding[];
  toolOptions: CapabilityOption[];
  toolBindings: AgentToolBinding[];
  actionOptions: CapabilityOption[];
  actionBindings: AgentActionBinding[];
  testSuites: AgentTestSuite[];
  selectedSuiteId: string | null;
  onSelectSuite: (suiteId: string | null) => void;
  testScenarios: AgentTestScenario[];
  latestTestRun: AgentTestRun | null;
  latestPublishRequest: AgentPublishRequest | null;
  newSuiteName: string;
  setNewSuiteName: (value: string) => void;
  newScenarioName: string;
  setNewScenarioName: (value: string) => void;
  newScenarioText: string;
  setNewScenarioText: (value: string) => void;
  newScenarioExpected: string;
  setNewScenarioExpected: (value: string) => void;
  newScenarioExpectedTool: string;
  setNewScenarioExpectedTool: (value: string) => void;
  newScenarioExpectedField: string;
  setNewScenarioExpectedField: (value: string) => void;
  newScenarioShouldBlock: boolean;
  setNewScenarioShouldBlock: (value: boolean) => void;
  testExecutionMode: string;
  setTestExecutionMode: (value: string) => void;
  onBindKnowledge: (sourceId: string) => void;
  onUnbindKnowledge: (bindingId: string) => void;
  onBindTool: (toolName: string) => void;
  onUnbindTool: (bindingId: string) => void;
  onBindAction: (actionKey: string) => void;
  onUnbindAction: (bindingId: string) => void;
  onCreateTestSuite: () => void;
  onCreateTestScenario: () => void;
  onRunTestSuite: () => void;
  onCreatePublishRequest: () => void;
  onEvaluatePublishRequest: () => void;
  onApprovePublishNoSend: () => void;
  bindingKnowledge: boolean;
  unbindingKnowledge: boolean;
  bindingTool: boolean;
  unbindingTool: boolean;
  bindingAction: boolean;
  unbindingAction: boolean;
  creatingTestSuite: boolean;
  creatingTestScenario: boolean;
  runningTestSuite: boolean;
  creatingPublishRequest: boolean;
  evaluatingPublishRequest: boolean;
  approvingPublishRequest: boolean;
  optionCounts: { sources: number; tools: number; actions: number; workflows: number };
}) {
  if (loading) return <Skeleton className="h-[680px] rounded-md bg-white/10" />;

  const draftLocked = !draftVersion || draftVersion.is_immutable;
  const boundSourceIds = new Set(knowledgeBindings.map((binding) => binding.knowledge_source_id));
  const boundToolNames = new Set(toolBindings.map((binding) => binding.tool_name));
  const boundActionKeys = new Set(actionBindings.map((binding) => binding.action_key));

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">{state?.agent.name}</h2>
          <Badge variant="outline" className="border-white/10 text-zinc-300">
            {draftVersion ? `Draft v${draftVersion.version_number}` : "Sin draft"}
          </Badge>
          <div className="ml-auto flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="border-white/10 bg-white/[0.035]"
              disabled={Boolean(draftVersion) || creatingDraft}
              onClick={onCreateDraft}
            >
              <FileText className="h-3.5 w-3.5" />
              Crear draft
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={draftLocked || saving}
              onClick={onSave}
              aria-label="Guardar draft"
            >
              <Save className="h-3.5 w-3.5" />
              Guardar
            </Button>
          </div>
        </div>

        <Tabs
          defaultValue="identity"
          className="rounded-md border border-white/10 bg-zinc-900/70 p-3"
        >
          <TabsList className="mb-3 bg-black/30">
            <TabsTrigger value="identity">Identidad</TabsTrigger>
            <TabsTrigger value="prompt">Prompt</TabsTrigger>
            <TabsTrigger value="knowledge">Knowledge</TabsTrigger>
            <TabsTrigger value="tools">Tools</TabsTrigger>
            <TabsTrigger value="actions">Actions</TabsTrigger>
            <TabsTrigger value="test-lab">Test Lab</TabsTrigger>
            <TabsTrigger value="publish">Publish</TabsTrigger>
            <TabsTrigger value="bindings">Bindings</TabsTrigger>
          </TabsList>
          <TabsContent value="identity" className="grid gap-3 md:grid-cols-3">
            <Field label="Rol" value={form.role} onChange={(role) => setForm({ ...form, role })} />
            <Field label="Tono" value={form.tone} onChange={(tone) => setForm({ ...form, tone })} />
            <Field
              label="Idioma"
              value={form.language}
              onChange={(language) => setForm({ ...form, language })}
            />
          </TabsContent>
          <TabsContent value="prompt" className="grid gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="builder-instructions">Instrucciones</Label>
              <Textarea
                id="builder-instructions"
                value={form.instructions}
                onChange={(event) => setForm({ ...form, instructions: event.target.value })}
                className="min-h-40 border-white/10 bg-black/20 text-zinc-100"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="builder-prompt-block">Prompt block</Label>
              <Textarea
                id="builder-prompt-block"
                value={form.promptBlock}
                onChange={(event) => setForm({ ...form, promptBlock: event.target.value })}
                className="min-h-32 border-white/10 bg-black/20 text-zinc-100"
              />
            </div>
          </TabsContent>
          <TabsContent value="knowledge">
            <KnowledgeTab
              sources={knowledgeSources}
              bindings={knowledgeBindings}
              boundSourceIds={boundSourceIds}
              draftLocked={draftLocked}
              bindingKnowledge={bindingKnowledge}
              unbindingKnowledge={unbindingKnowledge}
              onBind={onBindKnowledge}
              onUnbind={onUnbindKnowledge}
            />
          </TabsContent>
          <TabsContent value="tools">
            <ToolsTab
              options={toolOptions}
              bindings={toolBindings}
              boundToolNames={boundToolNames}
              draftLocked={draftLocked}
              bindingTool={bindingTool}
              unbindingTool={unbindingTool}
              onBind={onBindTool}
              onUnbind={onUnbindTool}
            />
          </TabsContent>
          <TabsContent value="actions">
            <ActionsTab
              options={actionOptions}
              bindings={actionBindings}
              boundActionKeys={boundActionKeys}
              draftLocked={draftLocked}
              bindingAction={bindingAction}
              unbindingAction={unbindingAction}
              onBind={onBindAction}
              onUnbind={onUnbindAction}
            />
          </TabsContent>
          <TabsContent value="test-lab">
            <TestLabTab
              draftLocked={draftLocked}
              suites={testSuites}
              selectedSuiteId={selectedSuiteId}
              onSelectSuite={onSelectSuite}
              scenarios={testScenarios}
              latestRun={latestTestRun}
              newSuiteName={newSuiteName}
              setNewSuiteName={setNewSuiteName}
              newScenarioName={newScenarioName}
              setNewScenarioName={setNewScenarioName}
              newScenarioText={newScenarioText}
              setNewScenarioText={setNewScenarioText}
              newScenarioExpected={newScenarioExpected}
              setNewScenarioExpected={setNewScenarioExpected}
              newScenarioExpectedTool={newScenarioExpectedTool}
              setNewScenarioExpectedTool={setNewScenarioExpectedTool}
              newScenarioExpectedField={newScenarioExpectedField}
              setNewScenarioExpectedField={setNewScenarioExpectedField}
              newScenarioShouldBlock={newScenarioShouldBlock}
              setNewScenarioShouldBlock={setNewScenarioShouldBlock}
              testExecutionMode={testExecutionMode}
              setTestExecutionMode={setTestExecutionMode}
              onCreateSuite={onCreateTestSuite}
              onCreateScenario={onCreateTestScenario}
              onRunSuite={onRunTestSuite}
              creatingSuite={creatingTestSuite}
              creatingScenario={creatingTestScenario}
              runningSuite={runningTestSuite}
            />
          </TabsContent>
          <TabsContent value="publish">
            <PublishTab
              deployment={state?.deployments[0] ?? null}
              draftVersion={draftVersion}
              publishedVersion={state?.published_version ?? null}
              latestRun={latestTestRun}
              latestRequest={latestPublishRequest}
              onCreateRequest={onCreatePublishRequest}
              onEvaluateRequest={onEvaluatePublishRequest}
              onApproveNoSend={onApprovePublishNoSend}
              creatingRequest={creatingPublishRequest}
              evaluatingRequest={evaluatingPublishRequest}
              approvingRequest={approvingPublishRequest}
            />
          </TabsContent>
          <TabsContent value="bindings" className="grid gap-3 md:grid-cols-2">
            <BindingStat label="Sources" value={optionCounts.sources} />
            <BindingStat label="Workflows" value={optionCounts.workflows} />
            <BindingStat label="Tools" value={optionCounts.tools} />
            <BindingStat label="Actions" value={optionCounts.actions} />
          </TabsContent>
        </Tabs>
      </div>

      <aside className="space-y-3">
        <div className="rounded-md border border-white/10 bg-zinc-900/70 p-3">
          <div className="mb-3 flex items-center gap-2">
            {readinessStatus === "ready" ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-300" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-300" />
            )}
            <div className="text-sm font-semibold">Readiness</div>
            <Badge variant="outline" className="ml-auto border-white/10 text-zinc-300">
              {readinessStatus}
            </Badge>
          </div>
          <div className="space-y-2">
            {checks.length ? (
              checks.map((check) => <ReadinessRow key={check.code} check={check} />)
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                Crea un draft para evaluar readiness.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-md border border-white/10 bg-zinc-900/70 p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Lock className="h-4 w-4 text-cyan-300" />
            Safety
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            {["send", "outbox", "live", "actions", "workflows", "canary"].map((item) => (
              <div key={item} className="rounded-md border border-white/10 bg-black/20 px-2 py-1.5">
                <span className="text-zinc-500">{item}</span>
                <span className="float-right text-emerald-300">off</span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = `builder-${label.toLowerCase()}`;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="border-white/10 bg-black/20 text-zinc-100"
      />
    </div>
  );
}

function BindingStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-white/10 bg-black/20 p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-zinc-100">{value}</div>
    </div>
  );
}

function KnowledgeTab({
  sources,
  bindings,
  boundSourceIds,
  draftLocked,
  bindingKnowledge,
  unbindingKnowledge,
  onBind,
  onUnbind,
}: {
  sources: KnowledgeSourceOption[];
  bindings: AgentKnowledgeBinding[];
  boundSourceIds: Set<string>;
  draftLocked: boolean;
  bindingKnowledge: boolean;
  unbindingKnowledge: boolean;
  onBind: (sourceId: string) => void;
  onUnbind: (bindingId: string) => void;
}) {
  const unhealthyBinding = bindings.find((binding) => binding.blocker);
  const statusCopy =
    bindings.length === 0
      ? "Este agente no tiene fuentes de conocimiento conectadas."
      : unhealthyBinding
        ? "Esta fuente no esta lista para publicar."
        : "Knowledge connected.";

  return (
    <div className="grid gap-3">
      <div
        className={cn(
          "rounded-md border p-3 text-sm",
          bindings.length === 0 || unhealthyBinding
            ? "border-amber-400/20 bg-amber-500/10 text-amber-100"
            : "border-emerald-400/20 bg-emerald-500/10 text-emerald-100",
        )}
      >
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4" />
          <span className="font-medium">{statusCopy}</span>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Fuentes disponibles</div>
          <div className="space-y-2">
            {sources.length ? (
              sources.map((source) => (
                <SourceRow
                  key={source.id}
                  source={source}
                  bound={boundSourceIds.has(source.id)}
                  disabled={draftLocked || bindingKnowledge || boundSourceIds.has(source.id)}
                  onBind={() => onBind(source.id)}
                />
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                No hay fuentes de conocimiento disponibles.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Fuentes conectadas</div>
          <div className="space-y-2">
            {bindings.length ? (
              bindings.map((binding) => (
                <BindingRow
                  key={binding.id}
                  binding={binding}
                  disabled={draftLocked || unbindingKnowledge}
                  onUnbind={() => onUnbind(binding.id)}
                />
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                Este agente no tiene fuentes de conocimiento conectadas.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function TestLabTab({
  draftLocked,
  suites,
  selectedSuiteId,
  onSelectSuite,
  scenarios,
  latestRun,
  newSuiteName,
  setNewSuiteName,
  newScenarioName,
  setNewScenarioName,
  newScenarioText,
  setNewScenarioText,
  newScenarioExpected,
  setNewScenarioExpected,
  newScenarioExpectedTool,
  setNewScenarioExpectedTool,
  newScenarioExpectedField,
  setNewScenarioExpectedField,
  newScenarioShouldBlock,
  setNewScenarioShouldBlock,
  testExecutionMode,
  setTestExecutionMode,
  onCreateSuite,
  onCreateScenario,
  onRunSuite,
  creatingSuite,
  creatingScenario,
  runningSuite,
}: {
  draftLocked: boolean;
  suites: AgentTestSuite[];
  selectedSuiteId: string | null;
  onSelectSuite: (suiteId: string | null) => void;
  scenarios: AgentTestScenario[];
  latestRun: AgentTestRun | null;
  newSuiteName: string;
  setNewSuiteName: (value: string) => void;
  newScenarioName: string;
  setNewScenarioName: (value: string) => void;
  newScenarioText: string;
  setNewScenarioText: (value: string) => void;
  newScenarioExpected: string;
  setNewScenarioExpected: (value: string) => void;
  newScenarioExpectedTool: string;
  setNewScenarioExpectedTool: (value: string) => void;
  newScenarioExpectedField: string;
  setNewScenarioExpectedField: (value: string) => void;
  newScenarioShouldBlock: boolean;
  setNewScenarioShouldBlock: (value: boolean) => void;
  testExecutionMode: string;
  setTestExecutionMode: (value: string) => void;
  onCreateSuite: () => void;
  onCreateScenario: () => void;
  onRunSuite: () => void;
  creatingSuite: boolean;
  creatingScenario: boolean;
  runningSuite: boolean;
}) {
  return (
    <div className="grid gap-3">
      <div className="rounded-md border border-cyan-400/20 bg-cyan-500/10 p-3 text-sm text-cyan-100">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4" />
          <span className="font-medium">DB-backed no-send Test Lab.</span>
        </div>
        <div className="mt-2 grid gap-1 text-xs text-cyan-50/80 md:grid-cols-3">
          <span>No WhatsApp will be sent.</span>
          <span>No live outbox will be written.</span>
          <span>Actions/workflows are disabled or dry-run.</span>
        </div>
        {testExecutionMode === "openai_direct_provider" ? (
          <div className="mt-2 rounded border border-amber-300/20 bg-amber-400/10 p-2 text-xs text-amber-50">
            OpenAI direct provider, WhatsApp no-send. Diagnostic only, not readiness.
          </div>
        ) : null}
        {testExecutionMode === "runtime_v2_agent_service" ? (
          <div className="mt-2 rounded border border-emerald-300/20 bg-emerald-400/10 p-2 text-xs text-emerald-50">
            Runtime V2 AgentService, WhatsApp no-send. This is the readiness path and requires
            trace_id.
          </div>
        ) : null}
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Suites</div>
          <div className="mb-3 flex gap-2">
            <Input
              aria-label="Nombre de suite"
              value={newSuiteName}
              onChange={(event) => setNewSuiteName(event.target.value)}
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <Button
              type="button"
              size="sm"
              disabled={draftLocked || creatingSuite || !newSuiteName.trim()}
              onClick={onCreateSuite}
            >
              <Plus className="h-3.5 w-3.5" />
              Suite
            </Button>
          </div>
          <div className="space-y-2">
            {suites.length ? (
              suites.map((suite) => (
                <button
                  key={suite.id}
                  type="button"
                  onClick={() => onSelectSuite(suite.id)}
                  className={cn(
                    "w-full rounded-md border px-3 py-2 text-left text-sm",
                    selectedSuiteId === suite.id
                      ? "border-cyan-300/50 bg-cyan-500/15 text-cyan-50"
                      : "border-white/10 bg-zinc-950/60 text-zinc-300",
                  )}
                >
                  <div className="font-medium">{suite.name}</div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    {suite.mode} - {suite.status}
                  </div>
                </button>
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                No hay suites de Test Lab.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Escenarios</div>
          <div className="grid gap-2">
            <Input
              aria-label="Nombre de escenario"
              value={newScenarioName}
              onChange={(event) => setNewScenarioName(event.target.value)}
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <Textarea
              aria-label="Texto inbound"
              value={newScenarioText}
              onChange={(event) => setNewScenarioText(event.target.value)}
              rows={4}
              placeholder="Un turno por linea"
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <Input
              aria-label="Final message contains"
              value={newScenarioExpected}
              onChange={(event) => setNewScenarioExpected(event.target.value)}
              placeholder="Texto que debe contener la respuesta"
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <Input
              aria-label="Tool expected"
              value={newScenarioExpectedTool}
              onChange={(event) => setNewScenarioExpectedTool(event.target.value)}
              placeholder="Tool esperada opcional"
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <Input
              aria-label="Field expected"
              value={newScenarioExpectedField}
              onChange={(event) => setNewScenarioExpectedField(event.target.value)}
              placeholder="Campo esperado opcional"
              className="border-white/10 bg-black/20 text-zinc-100"
            />
            <label className="flex items-center gap-2 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs text-zinc-300">
              <input
                type="checkbox"
                checked={newScenarioShouldBlock}
                onChange={(event) => setNewScenarioShouldBlock(event.target.checked)}
              />
              Should block
            </label>
            <label className="grid gap-1 text-xs text-zinc-400">
              Execution mode
              <select
                aria-label="Execution mode"
                value={testExecutionMode}
                onChange={(event) => setTestExecutionMode(event.target.value)}
                className="h-9 rounded-md border border-white/10 bg-black/20 px-3 text-sm text-zinc-100"
              >
                <option value="simulated_contract">simulated_contract</option>
                <option value="openai_direct_provider">openai_direct_provider</option>
                <option value="runtime_v2_agent_service">runtime_v2_agent_service</option>
              </select>
            </label>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="border-white/10 bg-white/[0.035]"
                disabled={
                  draftLocked ||
                  creatingScenario ||
                  !selectedSuiteId ||
                  !newScenarioName.trim() ||
                  !newScenarioText.trim()
                }
                onClick={onCreateScenario}
              >
                <Plus className="h-3.5 w-3.5" />
                Escenario
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!selectedSuiteId || runningSuite || scenarios.length === 0}
                onClick={onRunSuite}
              >
                <FlaskConical className="h-3.5 w-3.5" />
                Run no-send test
              </Button>
            </div>
          </div>
          <div className="mt-3 space-y-2">
            {scenarios.length ? (
              scenarios.map((scenario) => (
                <div
                  key={scenario.id}
                  className="rounded-md border border-white/10 bg-zinc-950/60 p-3"
                >
                  <div className="text-sm font-medium">{scenario.name}</div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    {scenario.turns.length} turnos - {scenario.status}
                  </div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    Expected: {scenarioExpectedSummary(scenario.expected)}
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                No hay escenarios para esta suite.
              </div>
            )}
          </div>
        </section>
      </div>

      <TestRunPanel run={latestRun} />
    </div>
  );
}

function TestRunPanel({ run }: { run: AgentTestRun | null }) {
  if (!run) {
    return (
      <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
        No hay ejecucion de Test Lab todavia.
      </div>
    );
  }
  return (
    <section className="rounded-md border border-white/10 bg-black/20 p-3">
      <div className="mb-2 flex items-center gap-2">
        <Badge
          variant="outline"
          className={cn(
            run.status === "passed"
              ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
              : "border-amber-400/30 bg-amber-500/10 text-amber-100",
          )}
        >
          {run.status}
        </Badge>
        <span className="text-sm font-semibold">{run.decision}</span>
      </div>
      <div className="grid gap-2 text-xs md:grid-cols-4">
        <BindingStat label="Passed" value={run.pass_count} />
        <BindingStat label="Failed" value={run.fail_count} />
        <BindingStat label="Blocked" value={run.blocked_count} />
        <BindingStat label="Traces" value={run.trace_ids.length} />
      </div>
      <div className="mt-3 space-y-2">
        {run.turn_results.length ? (
          run.turn_results.map((turn) => <TurnResultCard key={turnResultKey(turn)} turn={turn} />)
        ) : (
          <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
            No hay resultados por turno.
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500">
        <span>outbox {String(run.outbox_audit_result.status ?? "unknown")}</span>
        <span>side effects {String(run.side_effect_audit_result.status ?? "unknown")}</span>
        <span>{run.mode}</span>
        <span>{executionModeSummary(run)}</span>
        <span>{runCostSummary(run)}</span>
      </div>
    </section>
  );
}

function TurnResultCard({ turn }: { turn: Record<string, unknown> }) {
  const failures = arrayStrings(turn.failures);
  return (
    <article className="rounded-md border border-white/10 bg-zinc-950/60 p-3 text-xs">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={
            turn.status === "passed"
              ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
              : "border-amber-400/30 bg-amber-500/10 text-amber-100"
          }
        >
          Turn {String(turn.turn_number ?? "?")} {String(turn.status ?? "unknown")}
        </Badge>
        <span className="text-zinc-500">Trace {String(turn.trace_id ?? "missing")}</span>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <EvidenceBlock label="Input" value={String(turn.input ?? turn.inbound ?? "")} />
        <EvidenceBlock label="Output exacto" value={String(turn.final_message ?? "")} />
        <EvidenceBlock label="Tools" value={toolSummary(turn)} />
        <EvidenceBlock label="State writes" value={stateWriteSummary(turn)} />
        <EvidenceBlock label="Policy" value={policySummary(turn)} />
        <EvidenceBlock label="Send decision" value={String(turn.send_decision ?? "unknown")} />
        <EvidenceBlock label="Tokens" value={tokenSummary(turn)} />
        <EvidenceBlock label="Costo estimado" value={costSummary(turn)} />
      </div>
      {failures.length ? (
        <div className="mt-2 rounded bg-amber-500/10 p-2 text-amber-100">{failures.join(", ")}</div>
      ) : null}
    </article>
  );
}

function EvidenceBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-black/30 p-2">
      <div className="mb-1 text-[11px] uppercase text-zinc-500">{label}</div>
      <div className="break-words text-zinc-200">{value || "none"}</div>
    </div>
  );
}

function turnResultKey(turn: Record<string, unknown>) {
  return [
    String(turn.trace_id ?? "missing-trace"),
    String(turn.turn_number ?? "unknown-turn"),
    String(turn.input ?? turn.inbound ?? "unknown-input"),
  ].join(":");
}

function PublishTab({
  deployment,
  draftVersion,
  publishedVersion,
  latestRun,
  latestRequest,
  onCreateRequest,
  onEvaluateRequest,
  onApproveNoSend,
  creatingRequest,
  evaluatingRequest,
  approvingRequest,
}: {
  deployment: AgentBuilderState["deployments"][number] | null;
  draftVersion: AgentVersion | null;
  publishedVersion: AgentVersion | null;
  latestRun: AgentTestRun | null;
  latestRequest: AgentPublishRequest | null;
  onCreateRequest: () => void;
  onEvaluateRequest: () => void;
  onApproveNoSend: () => void;
  creatingRequest: boolean;
  evaluatingRequest: boolean;
  approvingRequest: boolean;
}) {
  const canPrepare = Boolean(deployment && draftVersion);
  const canApprove = latestRequest?.status === "ready_for_approval";
  return (
    <div className="grid gap-3">
      <section className="rounded-md border border-cyan-400/20 bg-cyan-500/10 p-3 text-sm text-cyan-100">
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4" />
          <span className="font-medium">Publish Control no-send only.</span>
        </div>
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Deployment</div>
          {deployment ? (
            <div className="space-y-2 text-sm text-zinc-300">
              <PublishKV label="Estado" value={deployment.publish_state} />
              <PublishKV label="Runtime" value={deployment.runtime_mode} />
              <PublishKV label="Send scope" value={deployment.send_scope} />
              <PublishKV
                label="Draft"
                value={draftVersion ? `v${draftVersion.version_number}` : "none"}
              />
              <PublishKV
                label="Rollback"
                value={publishedVersion ? `v${publishedVersion.version_number}` : "missing"}
              />
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
              No hay deployment Product-First.
            </div>
          )}
        </section>

        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Latest Test Lab</div>
          {latestRun ? (
            <div className="space-y-2 text-sm text-zinc-300">
              <PublishKV label="Status" value={latestRun.status} />
              <PublishKV label="Decision" value={latestRun.decision} />
              <PublishKV
                label="Outbox"
                value={String(latestRun.outbox_audit_result.status ?? "unknown")}
              />
              <PublishKV
                label="Side effects"
                value={String(latestRun.side_effect_audit_result.status ?? "unknown")}
              />
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
              Falta ejecutar Test Lab.
            </div>
          )}
        </section>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!canPrepare || creatingRequest}
          onClick={onCreateRequest}
        >
          <FileText className="h-3.5 w-3.5" />
          Preparar publish
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.035]"
          disabled={!latestRequest || evaluatingRequest}
          onClick={onEvaluateRequest}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Evaluar gates
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={!canApprove || approvingRequest}
          onClick={onApproveNoSend}
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          Aprobar no-send
        </Button>
      </div>

      <PublishRequestPanel request={latestRequest} />
    </div>
  );
}

function PublishRequestPanel({ request }: { request: AgentPublishRequest | null }) {
  if (!request) {
    return (
      <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
        No hay solicitud publish preparada.
      </div>
    );
  }
  return (
    <section className="rounded-md border border-white/10 bg-black/20 p-3">
      <div className="mb-2 flex items-center gap-2">
        <Badge
          variant="outline"
          className={cn(
            request.status === "ready_for_approval" || request.status === "approved_no_send"
              ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
              : "border-amber-400/30 bg-amber-500/10 text-amber-100",
          )}
        >
          {request.status}
        </Badge>
        <span className="text-sm font-semibold">{request.requested_state}</span>
      </div>
      <div className="grid gap-2 text-xs md:grid-cols-3">
        <BindingStat label="Blockers" value={request.blockers.length} />
        <BindingStat label="Test runs" value={request.test_run_ids.length} />
        <BindingStat label="Send scope" value={request.send_scope} />
      </div>
      <div className="mt-3 space-y-1 text-xs text-zinc-400">
        {request.blockers.length ? (
          request.blockers.map((blocker) => (
            <div
              key={`${String(blocker.code)}-${JSON.stringify(blocker.metadata ?? {})}`}
              className="rounded bg-zinc-950/70 p-2"
            >
              {String(blocker.code)}
            </div>
          ))
        ) : (
          <div className="rounded bg-zinc-950/70 p-2">no blockers</div>
        )}
      </div>
    </section>
  );
}

function PublishKV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded bg-zinc-950/60 px-2 py-1">
      <span className="text-zinc-500">{label}</span>
      <span className="font-medium text-zinc-100">{value}</span>
    </div>
  );
}

function ToolsTab({
  options,
  bindings,
  boundToolNames,
  draftLocked,
  bindingTool,
  unbindingTool,
  onBind,
  onUnbind,
}: {
  options: CapabilityOption[];
  bindings: AgentToolBinding[];
  boundToolNames: Set<string>;
  draftLocked: boolean;
  bindingTool: boolean;
  unbindingTool: boolean;
  onBind: (toolName: string) => void;
  onUnbind: (bindingId: string) => void;
}) {
  return (
    <div className="grid gap-3">
      <div className="rounded-md border border-cyan-400/20 bg-cyan-500/10 p-3 text-sm text-cyan-100">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4" />
          <span className="font-medium">Tools resuelven hechos.</span>
        </div>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <CapabilityList
          title="Tools disponibles"
          emptyCopy="No hay tools disponibles."
          items={options}
          boundKeys={boundToolNames}
          disabled={draftLocked || bindingTool}
          buttonCopy="Conectar"
          onBind={(capability) => onBind(capability.key)}
        />
        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Tools conectadas</div>
          <div className="space-y-2">
            {bindings.length ? (
              bindings.map((binding) => (
                <ToolBindingRow
                  key={binding.id}
                  binding={binding}
                  disabled={draftLocked || unbindingTool}
                  onUnbind={() => onUnbind(binding.id)}
                />
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                Este agente no tiene tools conectadas.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ActionsTab({
  options,
  bindings,
  boundActionKeys,
  draftLocked,
  bindingAction,
  unbindingAction,
  onBind,
  onUnbind,
}: {
  options: CapabilityOption[];
  bindings: AgentActionBinding[];
  boundActionKeys: Set<string>;
  draftLocked: boolean;
  bindingAction: boolean;
  unbindingAction: boolean;
  onBind: (actionKey: string) => void;
  onUnbind: (bindingId: string) => void;
}) {
  return (
    <div className="grid gap-3">
      <div className="rounded-md border border-amber-400/20 bg-amber-500/10 p-3 text-sm text-amber-100">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4" />
          <span className="font-medium">Actions producen efectos.</span>
        </div>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <CapabilityList
          title="Actions disponibles"
          emptyCopy="No hay actions disponibles."
          items={options}
          boundKeys={boundActionKeys}
          disabled={draftLocked || bindingAction}
          buttonCopy="Agregar disabled"
          onBind={(capability) => onBind(capability.key)}
        />
        <section className="rounded-md border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-sm font-semibold">Actions agregadas</div>
          <div className="space-y-2">
            {bindings.length ? (
              bindings.map((binding) => (
                <ActionBindingRow
                  key={binding.id}
                  binding={binding}
                  disabled={draftLocked || unbindingAction}
                  onUnbind={() => onUnbind(binding.id)}
                />
              ))
            ) : (
              <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
                Este agente no tiene actions agregadas.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function CapabilityList({
  title,
  emptyCopy,
  items,
  boundKeys,
  disabled,
  buttonCopy,
  onBind,
}: {
  title: string;
  emptyCopy: string;
  items: CapabilityOption[];
  boundKeys: Set<string>;
  disabled: boolean;
  buttonCopy: string;
  onBind: (capability: CapabilityOption) => void;
}) {
  return (
    <section className="rounded-md border border-white/10 bg-black/20 p-3">
      <div className="mb-2 text-sm font-semibold">{title}</div>
      <div className="space-y-2">
        {items.length ? (
          items.map((capability) => (
            <CapabilityRow
              key={capability.key}
              capability={capability}
              bound={boundKeys.has(capability.key)}
              disabled={disabled || boundKeys.has(capability.key)}
              buttonCopy={buttonCopy}
              onBind={() => onBind(capability)}
            />
          ))
        ) : (
          <div className="rounded-md border border-dashed border-white/10 p-3 text-sm text-zinc-500">
            {emptyCopy}
          </div>
        )}
      </div>
    </section>
  );
}

function CapabilityRow({
  capability,
  bound,
  disabled,
  buttonCopy,
  onBind,
}: {
  capability: CapabilityOption;
  bound: boolean;
  disabled: boolean;
  buttonCopy: string;
  onBind: () => void;
}) {
  return (
    <div className="rounded-md border border-white/10 bg-zinc-950/60 p-3">
      <div className="flex items-start gap-2">
        <CapabilityBadge capability={capability} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{capability.key}</div>
          <div className="mt-1 text-xs text-zinc-400">{capability.label}</div>
          <CapabilityMeta capability={capability} />
          {capability.publish_blockers.length ? (
            <div className="mt-1 text-[11px] text-amber-100">
              {capability.publish_blockers.join(", ")}
            </div>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.035]"
          disabled={disabled}
          onClick={onBind}
        >
          <Link className="h-3.5 w-3.5" />
          {bound ? "Agregada" : buttonCopy}
        </Button>
      </div>
    </div>
  );
}

function ToolBindingRow({
  binding,
  disabled,
  onUnbind,
}: {
  binding: AgentToolBinding;
  disabled: boolean;
  onUnbind: () => void;
}) {
  return (
    <div className="rounded-md border border-white/10 bg-zinc-950/60 p-3">
      <div className="flex items-start gap-2">
        <Badge
          variant="outline"
          className="border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
        >
          fact
        </Badge>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{binding.tool_name}</div>
          <div className="mt-1 text-xs text-zinc-400">{binding.label}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500">
            <span>{binding.category}</span>
            <span>{binding.risk_level}</span>
            <span>{binding.side_effect_type}</span>
            <span>{binding.enabled ? "enabled" : "disabled"}</span>
          </div>
          {binding.blocker ? (
            <div className="mt-1 text-xs text-amber-100">{binding.blocker_reason}</div>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.035]"
          disabled={disabled}
          onClick={onUnbind}
        >
          <Unlink2 className="h-3.5 w-3.5" />
          Quitar
        </Button>
      </div>
    </div>
  );
}

function ActionBindingRow({
  binding,
  disabled,
  onUnbind,
}: {
  binding: AgentActionBinding;
  disabled: boolean;
  onUnbind: () => void;
}) {
  return (
    <div className="rounded-md border border-white/10 bg-zinc-950/60 p-3">
      <div className="flex items-start gap-2">
        <Badge variant="outline" className="border-amber-400/30 bg-amber-500/10 text-amber-100">
          effect
        </Badge>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{binding.action_key}</div>
          <div className="mt-1 text-xs text-zinc-400">{binding.label}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500">
            <span>{binding.category}</span>
            <span>{binding.risk_level}</span>
            <span>{binding.side_effect_type}</span>
            <span>{binding.execution_mode}</span>
            <span>{binding.required_auth ? "auth required" : "no auth"}</span>
          </div>
          {binding.required_permissions.length ? (
            <div className="mt-1 text-[11px] text-zinc-500">
              {binding.required_permissions.join(", ")}
            </div>
          ) : null}
          {binding.blocker ? (
            <div className="mt-1 text-xs text-amber-100">{binding.blocker_reason}</div>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.035]"
          disabled={disabled}
          onClick={onUnbind}
        >
          <Unlink2 className="h-3.5 w-3.5" />
          Quitar
        </Button>
      </div>
    </div>
  );
}

function CapabilityBadge({ capability }: { capability: CapabilityOption }) {
  const tone = capability.has_side_effects
    ? "border-amber-400/30 bg-amber-500/10 text-amber-100"
    : "border-emerald-400/30 bg-emerald-500/10 text-emerald-100";
  return (
    <Badge variant="outline" className={cn("shrink-0", tone)}>
      {capability.has_side_effects ? "effect" : "fact"}
    </Badge>
  );
}

function CapabilityMeta({ capability }: { capability: CapabilityOption }) {
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500">
      <span>{capability.category}</span>
      <span>{capability.risk_level}</span>
      <span>{capability.side_effect_type}</span>
      <span>{capability.default_mode}</span>
      {capability.required_auth ? <span>auth required</span> : null}
      {capability.required_permissions.length ? (
        <span>{capability.required_permissions.join(", ")}</span>
      ) : null}
    </div>
  );
}

function SourceRow({
  source,
  bound,
  disabled,
  onBind,
}: {
  source: KnowledgeSourceOption;
  bound: boolean;
  disabled: boolean;
  onBind: () => void;
}) {
  return (
    <div className="rounded-md border border-white/10 bg-zinc-950/60 p-3">
      <div className="flex items-start gap-2">
        <SourceHealthBadge health={source.health} blocker={source.blocker} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{source.name}</div>
          <SourceMeta
            sourceType={source.source_type}
            status={source.status}
            checksum={source.checksum ?? source.version}
            lastIndexedAt={source.last_indexed_at}
          />
          {source.error_message ? (
            <div className="mt-1 text-xs text-red-200">{source.error_message}</div>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.035]"
          disabled={disabled}
          onClick={onBind}
        >
          <Link className="h-3.5 w-3.5" />
          {bound ? "Conectada" : "Conectar"}
        </Button>
      </div>
    </div>
  );
}

function BindingRow({
  binding,
  disabled,
  onUnbind,
}: {
  binding: AgentKnowledgeBinding;
  disabled: boolean;
  onUnbind: () => void;
}) {
  return (
    <div className="rounded-md border border-white/10 bg-zinc-950/60 p-3">
      <div className="flex items-start gap-2">
        <SourceHealthBadge health={binding.health} blocker={binding.blocker} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{binding.source_name}</div>
          <SourceMeta
            sourceType={binding.source_type}
            status={binding.status}
            checksum={binding.checksum ?? binding.version}
            lastIndexedAt={binding.last_indexed_at}
          />
          {binding.blocker ? (
            <div className="mt-1 text-xs text-amber-100">
              Esta fuente no esta lista para publicar.
            </div>
          ) : null}
          {binding.error_message ? (
            <div className="mt-1 text-xs text-red-200">{binding.error_message}</div>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.035]"
          disabled={disabled}
          onClick={onUnbind}
        >
          <Unlink2 className="h-3.5 w-3.5" />
          Quitar
        </Button>
      </div>
    </div>
  );
}

function SourceHealthBadge({ health, blocker }: { health: string; blocker: boolean }) {
  const tone = blocker
    ? "border-amber-400/30 bg-amber-500/10 text-amber-100"
    : "border-emerald-400/30 bg-emerald-500/10 text-emerald-100";
  return (
    <Badge variant="outline" className={cn("shrink-0", tone)}>
      {health}
    </Badge>
  );
}

function SourceMeta({
  sourceType,
  status,
  checksum,
  lastIndexedAt,
}: {
  sourceType: string;
  status: string;
  checksum: string | null;
  lastIndexedAt: string | null;
}) {
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500">
      <span>{sourceType}</span>
      <span>{status}</span>
      {checksum ? <span>{checksum}</span> : null}
      {lastIndexedAt ? <span>{lastIndexedAt}</span> : null}
    </div>
  );
}

function ReadinessRow({ check }: { check: BuilderReadinessCheck }) {
  const tone =
    check.status === "pass"
      ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
      : check.status === "block"
        ? "border-red-400/20 bg-red-500/10 text-red-100"
        : "border-amber-400/20 bg-amber-500/10 text-amber-100";
  return (
    <div className={cn("rounded-md border p-2", tone)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{check.label}</span>
        <span className="text-[11px] uppercase">{check.status}</span>
      </div>
      <div className="mt-1 text-xs opacity-80">{check.message}</div>
      <div className="mt-1 text-[11px] opacity-70">{check.code}</div>
    </div>
  );
}

function scenarioTurnsFromText(text: string): Record<string, unknown>[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => ({ inbound_text: line }));
}

function scenarioExpectedSummary(expected: Record<string, unknown>) {
  const expectedTurns = Array.isArray(expected.turns) ? expected.turns : [];
  if (!expectedTurns.length) return "no assertions";
  const first = expectedTurns.find((item): item is Record<string, unknown> => isRecord(item));
  if (!first) return "no assertions";
  const parts = [
    first.final_message_contains ? `contains "${String(first.final_message_contains)}"` : null,
    arrayStrings(first.expected_tools).length
      ? `tool ${arrayStrings(first.expected_tools).join(", ")}`
      : null,
    arrayStrings(first.expected_state_writes).length
      ? `field ${arrayStrings(first.expected_state_writes).join(", ")}`
      : null,
    first.should_block ? "should block" : "should not block",
  ].filter(Boolean);
  return parts.join(" / ");
}

function toolSummary(turn: Record<string, unknown>) {
  const required = arrayStrings(turn.tools_required ?? turn.required_tools);
  const executed = arrayToolNames(turn.tools_executed);
  const skipped = arrayToolNames(turn.tools_skipped);
  const failed = arrayToolNames(turn.tools_failed);
  return [
    required.length ? `required: ${required.join(", ")}` : null,
    executed.length ? `executed: ${executed.join(", ")}` : null,
    skipped.length ? `skipped: ${skipped.join(", ")}` : null,
    failed.length ? `failed: ${failed.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join(" | ");
}

function stateWriteSummary(turn: Record<string, unknown>) {
  const writes = Array.isArray(turn.state_writes) ? turn.state_writes : [];
  return writes
    .filter(isRecord)
    .map((write) => String(write.field_key ?? write.field ?? "unknown"))
    .join(", ");
}

function policySummary(turn: Record<string, unknown>) {
  const policy = isRecord(turn.policy_result) ? turn.policy_result : {};
  return String(policy.status ?? "unknown");
}

function tokenSummary(turn: Record<string, unknown>) {
  const usage = isRecord(turn.token_usage) ? turn.token_usage : {};
  const input = usage.input_tokens ?? 0;
  const output = usage.output_tokens ?? 0;
  const total = usage.total_tokens ?? 0;
  return `in ${String(input)} / out ${String(output)} / total ${String(total)}`;
}

function costSummary(turn: Record<string, unknown>) {
  const cost = isRecord(turn.estimated_cost) ? turn.estimated_cost : {};
  const amount = cost.amount_usd;
  if (typeof amount === "number") return `$${amount.toFixed(6)} USD`;
  return String(cost.status ?? "not estimated");
}

function executionModeSummary(run: AgentTestRun) {
  const coverage = isRecord(run.coverage_summary) ? run.coverage_summary : {};
  return `execution ${String(coverage.execution_mode ?? "simulated_contract")}`;
}

function runCostSummary(run: AgentTestRun) {
  const totals = run.turn_results.reduce(
    (acc, turn) => {
      const usage = isRecord(turn.token_usage) ? turn.token_usage : {};
      acc.input += Number(usage.input_tokens ?? 0);
      acc.output += Number(usage.output_tokens ?? 0);
      acc.total += Number(usage.total_tokens ?? 0);
      return acc;
    },
    { input: 0, output: 0, total: 0 },
  );
  return `tokens in ${totals.input} / out ${totals.output} / total ${totals.total}`;
}

function arrayToolNames(value: unknown) {
  return Array.isArray(value)
    ? value.filter(isRecord).map((item) => String(item.tool_name ?? item.name ?? "unknown"))
    : [];
}

function arrayStrings(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formFromAgent(agent: ProductAgent): DraftForm {
  return {
    role: agent.role || emptyForm.role,
    tone: agent.tone || emptyForm.tone,
    language: agent.language || emptyForm.language,
    instructions: agent.system_prompt || "",
    promptBlock: "",
  };
}

function formFromVersion(version: AgentVersion): DraftForm {
  const firstBlock = version.prompt_blocks[0];
  const promptBlock =
    firstBlock && typeof firstBlock.content === "string" ? firstBlock.content : "";
  return {
    role: version.role || emptyForm.role,
    tone: version.tone || emptyForm.tone,
    language: version.language || emptyForm.language,
    instructions: version.instructions || "",
    promptBlock,
  };
}

function payloadFromForm(form: DraftForm): BuilderConfigPayload {
  return {
    role: form.role.trim() || null,
    tone: form.tone.trim() || null,
    language: form.language.trim() || null,
    instructions: form.instructions,
    prompt_blocks: form.promptBlock.trim()
      ? [{ type: "instruction", content: form.promptBlock.trim() }]
      : [],
    snapshot: { builder_surface: "product_first_agent_builder" },
    change_summary: "Builder draft update",
  };
}

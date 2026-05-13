import { type UseQueryResult, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Archive,
  ArrowUpRight,
  BookOpen,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleGauge,
  Clock3,
  CopyCheck,
  Database,
  FileText,
  Filter,
  Gauge,
  GitCompareArrows,
  Info,
  Layers3,
  Loader2,
  Lock,
  MoreHorizontal,
  PackageCheck,
  PauseCircle,
  Pencil,
  Play,
  Plus,
  RefreshCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Split,
  SquareStack,
  Tag,
  Upload,
  XCircle,
} from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  type BottomActionCard,
  type ChunkImpact,
  type FunnelStage,
  type KnowledgeCommandItem,
  type KnowledgeHealth,
  type KnowledgeHealthMetric,
  knowledgeApi,
  type RiskFinding,
  type SimulationResponse,
  type UnansweredQuestion,
} from "@/features/knowledge/api";
import { extractErrorDetail } from "@/lib/error-detail";
import { cn } from "@/lib/utils";

type Status = "good" | "warning" | "critical";
type Severity = "low" | "medium" | "high" | "critical";
type SortKey = "title" | "retrieval_score" | "freshness_days" | "conflicts" | "last_used_at";
type ItemAction = "publish" | "archive" | "reindex";
type ChunkAction = "disable" | "split" | "merge" | "prioritize" | "reindex";
type QuestionAction = "create-faq" | "ignore" | "escalate";
type SimulationAction = "correct" | "incomplete" | "incorrect" | "create-faq" | "block";

const STATUS_STYLES: Record<
  Status,
  { label: string; text: string; bg: string; border: string; dot: string }
> = {
  good: {
    label: "Buena",
    text: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-400/30",
    dot: "bg-emerald-400",
  },
  warning: {
    label: "Media",
    text: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-400/30",
    dot: "bg-amber-400",
  },
  critical: {
    label: "Critica",
    text: "text-rose-300",
    bg: "bg-rose-500/10",
    border: "border-rose-400/30",
    dot: "bg-rose-400",
  },
};

const SEVERITY_STYLES: Record<Severity, { label: string; className: string; dot: string }> = {
  low: {
    label: "Baja",
    className: "border-emerald-400/30 bg-emerald-500/10 text-emerald-300",
    dot: "bg-emerald-400",
  },
  medium: {
    label: "Media",
    className: "border-amber-400/30 bg-amber-500/10 text-amber-300",
    dot: "bg-amber-400",
  },
  high: {
    label: "Alta",
    className: "border-orange-400/30 bg-orange-500/10 text-orange-300",
    dot: "bg-orange-400",
  },
  critical: {
    label: "Critica",
    className: "border-rose-400/30 bg-rose-500/10 text-rose-300",
    dot: "bg-rose-400",
  },
};

const TAB_DEFS = [
  { value: "faqs", label: "FAQs", count: 156, sourceTypes: ["FAQ"] },
  { value: "catalog", label: "Catalogo", count: 642, sourceTypes: ["Catalogo"] },
  { value: "documents", label: "Documentos", count: 412, sourceTypes: ["Documento"] },
  { value: "promos", label: "Promociones", count: 28, sourceTypes: ["Promocion"] },
  { value: "credit", label: "Reglas de credito", count: 24, sourceTypes: ["FAQ", "Documento"] },
  { value: "unanswered", label: "Preguntas sin respuesta", count: 118, sourceTypes: [] },
  { value: "conflicts", label: "Conflictos", count: 32, sourceTypes: [] },
  { value: "tests", label: "Pruebas", count: 30, sourceTypes: [] },
  { value: "metrics", label: "Metricas", count: 9, sourceTypes: [] },
] as const;

const QUERY_KEYS = {
  health: ["knowledge", "command-center", "health"] as const,
  risks: ["knowledge", "command-center", "risks"] as const,
  items: ["knowledge", "command-center", "items"] as const,
  unanswered: ["knowledge", "command-center", "unanswered"] as const,
  funnel: ["knowledge", "command-center", "funnel"] as const,
  cards: ["knowledge", "command-center", "cards"] as const,
  simulation: ["knowledge", "command-center", "simulation"] as const,
};

export function KnowledgeBasePage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<(typeof TAB_DEFS)[number]["value"]>("faqs");
  const [collection, setCollection] = useState("Todas");
  const [status, setStatus] = useState("Todos");
  const [risk, setRisk] = useState("Todos");
  const [freshness, setFreshness] = useState("Todas");
  const [sortKey, setSortKey] = useState<SortKey>("retrieval_score");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [selectedRows, setSelectedRows] = useState<Set<string>>(() => new Set());
  const [selectedChunkId, setSelectedChunkId] = useState("chunk-credit-policy-p5");
  const [chunkDrawerOpen, setChunkDrawerOpen] = useState(false);
  const [promptDrawerOpen, setPromptDrawerOpen] = useState(false);
  const [simulationMessage, setSimulationMessage] = useState("¿Aceptan INE de otro estado?");
  const [selectedAgent, setSelectedAgent] = useState("Sales Agent");
  const [selectedModel, setSelectedModel] = useState("gpt-4o-mini");

  const healthQuery = useQuery({
    queryKey: QUERY_KEYS.health,
    queryFn: knowledgeApi.getHealth,
  });
  const risksQuery = useQuery({
    queryKey: QUERY_KEYS.risks,
    queryFn: knowledgeApi.listRisks,
  });
  const itemsQuery = useQuery({
    queryKey: [...QUERY_KEYS.items, search, collection, status, risk],
    queryFn: () =>
      knowledgeApi.listItems({
        q: search || undefined,
        collection,
        status,
        risk,
        page_size: 30,
      }),
  });
  const unansweredQuery = useQuery({
    queryKey: QUERY_KEYS.unanswered,
    queryFn: knowledgeApi.listUnansweredQuestions,
  });
  const funnelQuery = useQuery({
    queryKey: QUERY_KEYS.funnel,
    queryFn: knowledgeApi.getFunnelCoverage,
  });
  const cardsQuery = useQuery({
    queryKey: QUERY_KEYS.cards,
    queryFn: knowledgeApi.getDashboardCards,
  });
  const defaultSimulationQuery = useQuery({
    queryKey: QUERY_KEYS.simulation,
    queryFn: () =>
      knowledgeApi.simulate({
        message: "¿Aceptan INE de otro estado?",
        agent: selectedAgent,
        model: selectedModel,
      }),
  });
  const chunkImpactQuery = useQuery({
    queryKey: ["knowledge", "command-center", "chunk-impact", selectedChunkId],
    queryFn: () => knowledgeApi.getChunkImpact(selectedChunkId),
    enabled: Boolean(selectedChunkId),
  });

  const reindexAll = useMutation({
    mutationFn: knowledgeApi.reindex,
    onSuccess: (data) => {
      toast.success(`Reindexado encolado: ${data.queued} documentos`);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.items });
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo reindexar.")),
  });

  const itemAction = useMutation({
    mutationFn: ({ id, action }: { id: string; action: ItemAction }) => {
      if (action === "publish") return knowledgeApi.publishItem(id);
      if (action === "archive") return knowledgeApi.archiveItem(id);
      return knowledgeApi.reindexItem(id);
    },
    onSuccess: (_data, vars) => {
      const label =
        vars.action === "publish"
          ? "Publicado"
          : vars.action === "archive"
            ? "Archivado"
            : "Reindexado";
      toast.success(`${label}: ${vars.id}`);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.items });
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo completar la accion.")),
  });

  const riskAction = useMutation({
    mutationFn: knowledgeApi.resolveRisk,
    onSuccess: () => {
      toast.success("Riesgo marcado para resolucion");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.risks });
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo resolver el riesgo.")),
  });

  const questionAction = useMutation({
    mutationFn: ({ id, action }: { id: string; action: QuestionAction }) => {
      if (action === "create-faq") return knowledgeApi.createFaqFromQuestion(id);
      if (action === "ignore") return knowledgeApi.ignoreQuestion(id);
      return knowledgeApi.escalateQuestion(id);
    },
    onSuccess: (_data, vars) => {
      const labels: Record<QuestionAction, string> = {
        "create-faq": "FAQ borrador creada",
        ignore: "Pregunta ignorada",
        escalate: "Pregunta escalada",
      };
      toast.success(labels[vars.action]);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.unanswered });
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo procesar la pregunta.")),
  });

  const runSimulation = useMutation({
    mutationFn: knowledgeApi.simulate,
    onSuccess: (result) => {
      toast.success("Simulacion ejecutada");
      const firstChunk = result.retrieved_chunks[0];
      if (firstChunk) setSelectedChunkId(firstChunk.id);
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo ejecutar la simulacion.")),
  });

  const markSimulation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: SimulationAction }) => {
      if (action === "correct") return knowledgeApi.markSimulationCorrect(id);
      if (action === "incomplete") return knowledgeApi.markSimulationIncomplete(id);
      if (action === "incorrect") return knowledgeApi.markSimulationIncorrect(id);
      if (action === "create-faq") return knowledgeApi.createFaqFromSimulation(id);
      return knowledgeApi.blockSimulationAnswer(id);
    },
    onSuccess: (_data, vars) => {
      const labels: Record<SimulationAction, string> = {
        correct: "Marcada como correcta",
        incomplete: "Marcada como incompleta",
        incorrect: "Marcada como incorrecta",
        "create-faq": "FAQ creada desde simulacion",
        block: "Respuesta bloqueada",
      };
      toast.success(labels[vars.action]);
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo actualizar la simulacion.")),
  });

  const chunkAction = useMutation({
    mutationFn: ({ id, action }: { id: string; action: ChunkAction }) => {
      if (action === "disable") return knowledgeApi.disableChunk(id);
      if (action === "split") return knowledgeApi.splitChunk(id);
      if (action === "merge") return knowledgeApi.mergeChunk(id);
      if (action === "prioritize") return knowledgeApi.prioritizeChunk(id);
      return knowledgeApi.reindexChunk(id);
    },
    onSuccess: (_data, vars) => {
      const labels: Record<ChunkAction, string> = {
        disable: "Chunk desactivado",
        split: "Division encolada",
        merge: "Fusion encolada",
        prioritize: "Chunk priorizado",
        reindex: "Reindexado encolado",
      };
      toast.success(labels[vars.action]);
      void queryClient.invalidateQueries({
        queryKey: ["knowledge", "command-center", "chunk-impact", vars.id],
      });
    },
    onError: (err) => toast.error(extractErrorDetail(err, "No se pudo actualizar el chunk.")),
  });

  const visibleItems = useMemo(() => {
    const rows = itemsQuery.data?.items ?? [];
    const tab = TAB_DEFS.find((item) => item.value === activeTab);
    const tabSourceTypes: readonly string[] = tab?.sourceTypes ?? [];
    const tabRows =
      tabSourceTypes.length > 0
        ? rows.filter((item) => tabSourceTypes.includes(item.source_type))
        : rows;
    const freshRows =
      freshness === "Todas" ? tabRows : tabRows.filter((item) => item.freshness === freshness);
    return [...freshRows].sort((a, b) => {
      const aValue = a[sortKey];
      const bValue = b[sortKey];
      const modifier = sortDirection === "asc" ? 1 : -1;
      if (typeof aValue === "number" && typeof bValue === "number")
        return (aValue - bValue) * modifier;
      return String(aValue).localeCompare(String(bValue)) * modifier;
    });
  }, [activeTab, freshness, itemsQuery.data?.items, sortDirection, sortKey]);

  const simulation = runSimulation.data ?? defaultSimulationQuery.data;

  function toggleRow(id: string) {
    setSelectedRows((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleCurrentPage(checked: boolean) {
    setSelectedRows((current) => {
      const next = new Set(current);
      for (const item of visibleItems) {
        if (checked) next.add(item.id);
        else next.delete(item.id);
      }
      return next;
    });
  }

  function openChunk(id: string) {
    setSelectedChunkId(id);
    setChunkDrawerOpen(true);
  }

  return (
    <TooltipProvider>
      <div className="-m-6 min-h-[calc(100vh-3.5rem)] bg-[#07101b] text-slate-100">
        <TopCommandBar
          search={search}
          setSearch={setSearch}
          selectedModel={selectedModel}
          setSelectedModel={setSelectedModel}
          reindexing={reindexAll.isPending}
          onReindex={() => reindexAll.mutate()}
          onRunSimulation={() =>
            runSimulation.mutate({
              message: simulationMessage,
              agent: selectedAgent,
              model: selectedModel,
            })
          }
        />

        <div className="grid gap-3 p-3 xl:grid-cols-[minmax(0,1fr)_370px]">
          <div className="min-w-0 space-y-3">
            <KnowledgeHealthCockpit query={healthQuery} />

            <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_390px]">
              <div className="min-w-0 space-y-3">
                <KnowledgeTabs
                  activeTab={activeTab}
                  onTabChange={(value) => setActiveTab(value as (typeof TAB_DEFS)[number]["value"])}
                />
                <KnowledgeTableFilters
                  collection={collection}
                  status={status}
                  risk={risk}
                  freshness={freshness}
                  onCollectionChange={setCollection}
                  onStatusChange={setStatus}
                  onRiskChange={setRisk}
                  onFreshnessChange={setFreshness}
                />
                <BulkActionsBar
                  count={selectedRows.size}
                  onArchive={() => {
                    for (const id of selectedRows) itemAction.mutate({ id, action: "archive" });
                  }}
                  onReindex={() => {
                    for (const id of selectedRows) itemAction.mutate({ id, action: "reindex" });
                  }}
                  onClear={() => setSelectedRows(new Set())}
                />
                <KnowledgeTable
                  query={itemsQuery}
                  items={visibleItems}
                  selectedRows={selectedRows}
                  sortKey={sortKey}
                  sortDirection={sortDirection}
                  onSort={(key) => {
                    setSortDirection((current) =>
                      sortKey === key && current === "desc" ? "asc" : "desc",
                    );
                    setSortKey(key);
                  }}
                  onToggleRow={toggleRow}
                  onTogglePage={toggleCurrentPage}
                  onAction={(id, action) => itemAction.mutate({ id, action })}
                  onOpenChunk={openChunk}
                />
              </div>

              <div className="space-y-3">
                <RiskRadarPanel
                  query={risksQuery}
                  onResolve={(id) => riskAction.mutate(id)}
                  resolvingId={riskAction.variables}
                />
                <WhatsAppGapsPanel
                  query={unansweredQuery}
                  onAction={(id, action) => questionAction.mutate({ id, action })}
                />
              </div>
            </div>

            <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_410px]">
              <FunnelKnowledgeCoverage query={funnelQuery} />
              <ChunkImpactSummaryPanel
                query={chunkImpactQuery}
                onOpen={() => setChunkDrawerOpen(true)}
              />
            </div>

            <BottomActionCards query={cardsQuery} />
          </div>

          <RagSimulationPanel
            initialQuery={defaultSimulationQuery}
            simulation={simulation}
            message={simulationMessage}
            setMessage={setSimulationMessage}
            selectedAgent={selectedAgent}
            setSelectedAgent={setSelectedAgent}
            selectedModel={selectedModel}
            running={runSimulation.isPending || defaultSimulationQuery.isFetching}
            onRun={() =>
              runSimulation.mutate({
                message: simulationMessage,
                agent: selectedAgent,
                model: selectedModel,
              })
            }
            onOpenPrompt={() => setPromptDrawerOpen(true)}
            onOpenChunk={openChunk}
            onMark={(id, action) => markSimulation.mutate({ id, action })}
          />
        </div>

        <ChunkImpactDrawer
          open={chunkDrawerOpen}
          onOpenChange={setChunkDrawerOpen}
          query={chunkImpactQuery}
          onAction={(id, action) => chunkAction.mutate({ id, action })}
        />
        <PromptPreviewDrawer
          open={promptDrawerOpen}
          onOpenChange={setPromptDrawerOpen}
          simulation={simulation}
        />
      </div>
    </TooltipProvider>
  );
}

function TopCommandBar({
  search,
  setSearch,
  selectedModel,
  setSelectedModel,
  reindexing,
  onReindex,
  onRunSimulation,
}: {
  search: string;
  setSearch: (value: string) => void;
  selectedModel: string;
  setSelectedModel: (value: string) => void;
  reindexing: boolean;
  onReindex: () => void;
  onRunSimulation: () => void;
}) {
  return (
    <div className="sticky top-0 z-30 border-b border-slate-800 bg-[#07101b]/95 px-3 py-2 backdrop-blur">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-64 flex-1">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="h-9 border-slate-700 bg-slate-950/80 pl-9 pr-20 text-sm text-slate-100 placeholder:text-slate-500"
              placeholder="Buscar en FAQs, catalogo, articulos, documentos y preguntas reales..."
            />
            <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400">
              Ctrl K
            </kbd>
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          className="border-slate-700 bg-slate-950/80 text-slate-200"
          asChild
        >
          <label>
            <Upload className="h-4 w-4" />
            Importar
            <input className="hidden" type="file" accept=".pdf,.docx,.xlsx,.csv,.json,.txt" />
          </label>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" className="bg-violet-600 text-white hover:bg-violet-500">
              <Plus className="h-4 w-4" />
              Nuevo
              <ChevronDown className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="border-slate-800 bg-slate-950 text-slate-100">
            <DropdownMenuLabel className="text-xs text-slate-400">Crear fuente</DropdownMenuLabel>
            <DropdownMenuItem>FAQ manual</DropdownMenuItem>
            <DropdownMenuItem>Regla de credito</DropdownMenuItem>
            <DropdownMenuItem>Promocion</DropdownMenuItem>
            <DropdownMenuItem>Documento interno</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          variant="outline"
          size="sm"
          className="border-slate-700 bg-slate-950/80 text-slate-200"
          disabled={reindexing}
          onClick={onReindex}
        >
          {reindexing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCcw className="h-4 w-4" />
          )}
          Reindexar
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="border-slate-700 bg-slate-950/80 text-slate-200"
          onClick={onRunSimulation}
        >
          <Play className="h-4 w-4" />
          Ejecutar simulacion
        </Button>

        <div className="flex h-9 items-center gap-2 rounded-md border border-emerald-400/20 bg-emerald-500/10 px-3 text-xs text-emerald-300">
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
          Sincronizado en vivo
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="border-slate-700 bg-slate-950/80 text-slate-200"
            >
              <SlidersHorizontal className="h-4 w-4" />
              Filtros guardados
              <ChevronDown className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="border-slate-800 bg-slate-950 text-slate-100">
            <DropdownMenuItem>Riesgo alto</DropdownMenuItem>
            <DropdownMenuItem>Credito sin validar</DropdownMenuItem>
            <DropdownMenuItem>Promociones por vencer</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Select value={selectedModel} onValueChange={setSelectedModel}>
          <SelectTrigger className="h-9 w-44 border-slate-700 bg-slate-950/80 text-slate-200">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="border-slate-800 bg-slate-950 text-slate-100">
            <SelectItem value="gpt-4o-mini">gpt-4o-mini</SelectItem>
            <SelectItem value="gpt-4.1-mini">gpt-4.1-mini</SelectItem>
            <SelectItem value="mock-local">mock-local</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

function KnowledgeHealthCockpit({ query }: { query: UseQueryResult<KnowledgeHealth> }) {
  return (
    <Panel className="p-3">
      <QueryBoundary
        query={query}
        loadingLabel="Cargando salud de conocimiento"
        empty={(data) => data.metrics.length === 0}
      >
        {(health) => (
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase text-slate-400">Knowledge Health</p>
                <div className="mt-1 flex items-end gap-2">
                  <span className="text-4xl font-semibold text-emerald-300">
                    {health.overall_score}
                  </span>
                  <span className="pb-1 text-sm text-slate-400">/100</span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs">
                  <StatusBadge status={health.status} label={health.label} />
                  <span className="text-emerald-300">
                    +{health.change_vs_yesterday} pts vs ayer
                  </span>
                </div>
              </div>
              <CircleGauge className="h-8 w-8 text-cyan-300" />
            </div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
              {health.metrics.map((metric) => (
                <HealthScoreCard key={metric.key} metric={metric} />
              ))}
            </div>
          </div>
        )}
      </QueryBoundary>
    </Panel>
  );
}

function HealthScoreCard({ metric }: { metric: KnowledgeHealthMetric }) {
  const style = STATUS_STYLES[metric.status];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={cn("min-h-24 rounded-md border p-3", style.bg, style.border)}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-slate-300">{metric.label}</span>
            <Info className="h-3.5 w-3.5 text-slate-500" />
          </div>
          <div className={cn("mt-3 text-2xl font-semibold", style.text)}>
            {metric.score}
            <span className="ml-1 text-xs text-slate-500">/100</span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <StatusBadge status={metric.status} />
            <span
              className={cn(
                "text-[11px]",
                metric.trend >= 0 ? "text-emerald-300" : "text-rose-300",
              )}
            >
              {metric.trend >= 0 ? "+" : ""}
              {metric.trend}
            </span>
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{metric.tooltip}</TooltipContent>
    </Tooltip>
  );
}

function KnowledgeTabs({
  activeTab,
  onTabChange,
}: {
  activeTab: string;
  onTabChange: (value: string) => void;
}) {
  return (
    <Tabs value={activeTab} onValueChange={onTabChange}>
      <TabsList className="h-auto w-full justify-start overflow-x-auto rounded-md border border-slate-800 bg-slate-950/80 p-1">
        {TAB_DEFS.map((tab) => (
          <TabsTrigger
            key={tab.value}
            value={tab.value}
            className="h-8 flex-none gap-2 px-3 text-xs text-slate-400 data-[state=active]:border-violet-400/30 data-[state=active]:bg-violet-500/15 data-[state=active]:text-violet-200"
          >
            {tab.label}
            <span className="rounded-sm border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400">
              {tab.count}
            </span>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

function KnowledgeTableFilters({
  collection,
  status,
  risk,
  freshness,
  onCollectionChange,
  onStatusChange,
  onRiskChange,
  onFreshnessChange,
}: {
  collection: string;
  status: string;
  risk: string;
  freshness: string;
  onCollectionChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onRiskChange: (value: string) => void;
  onFreshnessChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/70 p-2">
      <Filter className="h-4 w-4 text-slate-500" />
      <CompactSelect
        value={collection}
        onValueChange={onCollectionChange}
        values={["Todas", "Credito", "Motos", "Promociones", "Legal", "Interno"]}
      />
      <CompactSelect
        value={status}
        onValueChange={onStatusChange}
        values={["Todos", "Publicado", "Borrador", "Archivado"]}
      />
      <CompactSelect
        value={risk}
        onValueChange={onRiskChange}
        values={["Todos", "low", "medium", "high", "critical"]}
        labelMap={{ low: "Bajo", medium: "Medio", high: "Alto", critical: "Critico" }}
      />
      <CompactSelect
        value={freshness}
        onValueChange={onFreshnessChange}
        values={["Todas", "Buena", "Media", "Critica"]}
      />
      <Button
        variant="ghost"
        size="xs"
        className="text-violet-300 hover:bg-violet-500/10 hover:text-violet-200"
        onClick={() => {
          onCollectionChange("Todas");
          onStatusChange("Todos");
          onRiskChange("Todos");
          onFreshnessChange("Todas");
        }}
      >
        Limpiar filtros
      </Button>
    </div>
  );
}

function CompactSelect({
  value,
  onValueChange,
  values,
  labelMap = {},
}: {
  value: string;
  onValueChange: (value: string) => void;
  values: string[];
  labelMap?: Record<string, string>;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger className="h-8 min-w-36 border-slate-700 bg-slate-950/80 text-xs text-slate-200">
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="border-slate-800 bg-slate-950 text-slate-100">
        {values.map((item) => (
          <SelectItem key={item} value={item}>
            {labelMap[item] ?? item}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function BulkActionsBar({
  count,
  onArchive,
  onReindex,
  onClear,
}: {
  count: number;
  onArchive: () => void;
  onReindex: () => void;
  onClear: () => void;
}) {
  if (count === 0) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-100">
      <span>{count} fuentes seleccionadas</span>
      <div className="flex items-center gap-2">
        <Button
          size="xs"
          variant="outline"
          className="border-cyan-400/30 bg-cyan-500/10 text-cyan-100"
          onClick={onReindex}
        >
          <RefreshCcw className="h-3 w-3" />
          Reindexar
        </Button>
        <Button
          size="xs"
          variant="outline"
          className="border-slate-700 bg-slate-950/70 text-slate-200"
          onClick={onArchive}
        >
          <Archive className="h-3 w-3" />
          Archivar
        </Button>
        <Button
          size="icon-xs"
          variant="ghost"
          className="text-slate-300"
          onClick={onClear}
          aria-label="Limpiar seleccion"
        >
          <XCircle className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

function KnowledgeTable({
  query,
  items,
  selectedRows,
  sortKey,
  sortDirection,
  onSort,
  onToggleRow,
  onTogglePage,
  onAction,
  onOpenChunk,
}: {
  query: UseQueryResult<{
    items: KnowledgeCommandItem[];
    total: number;
    page: number;
    page_size: number;
  }>;
  items: KnowledgeCommandItem[];
  selectedRows: Set<string>;
  sortKey: SortKey;
  sortDirection: "asc" | "desc";
  onSort: (key: SortKey) => void;
  onToggleRow: (id: string) => void;
  onTogglePage: (checked: boolean) => void;
  onAction: (id: string, action: ItemAction) => void;
  onOpenChunk: (id: string) => void;
}) {
  const allSelected = items.length > 0 && items.every((item) => selectedRows.has(item.id));

  return (
    <Panel className="overflow-hidden">
      <QueryBoundary
        query={query}
        loadingLabel="Cargando fuentes de conocimiento"
        empty={() => items.length === 0}
      >
        {() => (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-left text-xs">
                <thead className="border-b border-slate-800 bg-slate-950/80 text-slate-400">
                  <tr>
                    <th className="w-9 px-3 py-2">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={(event) => onTogglePage(event.target.checked)}
                        aria-label="Seleccionar pagina"
                        className="h-4 w-4 rounded border-slate-700 bg-slate-950"
                      />
                    </th>
                    <SortableHead
                      label="Titulo"
                      active={sortKey === "title"}
                      direction={sortDirection}
                      onClick={() => onSort("title")}
                    />
                    <th className="px-3 py-2 font-medium">Tipo de fuente</th>
                    <th className="px-3 py-2 font-medium">Coleccion</th>
                    <SortableHead
                      label="Score recuperacion"
                      active={sortKey === "retrieval_score"}
                      direction={sortDirection}
                      onClick={() => onSort("retrieval_score")}
                    />
                    <th className="px-3 py-2 font-medium">Estado</th>
                    <SortableHead
                      label="Frescura"
                      active={sortKey === "freshness_days"}
                      direction={sortDirection}
                      onClick={() => onSort("freshness_days")}
                    />
                    <SortableHead
                      label="Conflictos"
                      active={sortKey === "conflicts"}
                      direction={sortDirection}
                      onClick={() => onSort("conflicts")}
                    />
                    <SortableHead
                      label="Ultimo uso"
                      active={sortKey === "last_used_at"}
                      direction={sortDirection}
                      onClick={() => onSort("last_used_at")}
                    />
                    <th className="px-3 py-2 text-right font-medium">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-slate-900 bg-slate-950/40 hover:bg-slate-900/70"
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selectedRows.has(item.id)}
                          onChange={() => onToggleRow(item.id)}
                          aria-label={`Seleccionar ${item.title}`}
                          className="h-4 w-4 rounded border-slate-700 bg-slate-950"
                        />
                      </td>
                      <td className="max-w-72 px-3 py-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <SourceIcon sourceType={item.source_type} />
                          <span className="truncate text-slate-100" title={item.title}>
                            {item.title}
                          </span>
                        </div>
                        <div className="mt-0.5 text-[10px] text-slate-500">{item.owner}</div>
                      </td>
                      <td className="px-3 py-2 text-slate-300">{item.source_type}</td>
                      <td className="px-3 py-2 text-slate-300">{item.collection}</td>
                      <td className="px-3 py-2">
                        <ScoreBadge score={item.retrieval_score} />
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot label={item.status} active={item.status === "Publicado"} />
                      </td>
                      <td className="px-3 py-2">
                        <FreshnessBadge freshness={item.freshness} days={item.freshness_days} />
                      </td>
                      <td className="px-3 py-2">
                        <ConflictBadge count={item.conflicts} risk={item.risk_level} />
                      </td>
                      <td className="px-3 py-2 text-slate-400">{item.last_used_at}</td>
                      <td className="px-3 py-2">
                        <KnowledgeTableRowActions
                          item={item}
                          onAction={onAction}
                          onOpenChunk={() =>
                            onOpenChunk(
                              item.id === "doc-credit-policy" ? "chunk-credit-policy-p5" : item.id,
                            )
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 px-3 py-2 text-xs text-slate-400">
              <span>
                1-{items.length} de {query.data?.total ?? items.length} resultados
              </span>
              <div className="flex items-center gap-2">
                <Button
                  size="icon-xs"
                  variant="outline"
                  className="border-violet-400/30 bg-violet-500/10 text-violet-200"
                >
                  1
                </Button>
                <Button size="icon-xs" variant="ghost" className="text-slate-400">
                  2
                </Button>
                <Button size="icon-xs" variant="ghost" className="text-slate-400">
                  3
                </Button>
                <span>...</span>
                <Button size="icon-xs" variant="ghost" className="text-slate-400">
                  20
                </Button>
                <Select defaultValue="20">
                  <SelectTrigger className="h-8 w-32 border-slate-700 bg-slate-950/80 text-xs text-slate-300">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="border-slate-800 bg-slate-950 text-slate-100">
                    <SelectItem value="20">20 por pagina</SelectItem>
                    <SelectItem value="50">50 por pagina</SelectItem>
                    <SelectItem value="100">100 por pagina</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </>
        )}
      </QueryBoundary>
    </Panel>
  );
}

function SortableHead({
  label,
  active,
  direction,
  onClick,
}: {
  label: string;
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
}) {
  return (
    <th className="px-3 py-2">
      <button
        type="button"
        className="flex items-center gap-1 font-medium text-slate-400 hover:text-slate-200"
        onClick={onClick}
      >
        {label}
        <ArrowUpRight
          className={cn(
            "h-3 w-3",
            active ? "text-violet-300" : "text-slate-600",
            direction === "asc" && "-rotate-90",
          )}
        />
      </button>
    </th>
  );
}

function KnowledgeTableRowActions({
  item,
  onAction,
  onOpenChunk,
}: {
  item: KnowledgeCommandItem;
  onAction: (id: string, action: ItemAction) => void;
  onOpenChunk: () => void;
}) {
  return (
    <div className="flex justify-end gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            size="icon-xs"
            variant="ghost"
            className="text-slate-300 hover:bg-cyan-500/10 hover:text-cyan-200"
            aria-label="Probar fuente"
          >
            <Play className="h-3 w-3" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Probar</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            size="icon-xs"
            variant="ghost"
            className="text-slate-300 hover:bg-violet-500/10 hover:text-violet-200"
            aria-label="Editar fuente"
          >
            <Pencil className="h-3 w-3" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Editar</TooltipContent>
      </Tooltip>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="icon-xs"
            variant="ghost"
            className="text-slate-300"
            aria-label={`Mas acciones para ${item.title}`}
          >
            <MoreHorizontal className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="border-slate-800 bg-slate-950 text-slate-100">
          <DropdownMenuItem onClick={() => onAction(item.id, "publish")}>
            <CheckCircle2 className="h-4 w-4" />
            Publicar
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onAction(item.id, "reindex")}>
            <RefreshCcw className="h-4 w-4" />
            Reindexar
          </DropdownMenuItem>
          <DropdownMenuItem onClick={onOpenChunk}>
            <SquareStack className="h-4 w-4" />
            Ver chunks
          </DropdownMenuItem>
          <DropdownMenuItem onClick={onOpenChunk}>
            <Gauge className="h-4 w-4" />
            Ver impacto
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => onAction(item.id, "archive")} variant="destructive">
            <Archive className="h-4 w-4" />
            Archivar
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function RiskRadarPanel({
  query,
  onResolve,
  resolvingId,
}: {
  query: UseQueryResult<{ items: RiskFinding[]; updated_at: string }>;
  onResolve: (id: string) => void;
  resolvingId?: string;
}) {
  return (
    <Panel className="p-3">
      <PanelTitle
        icon={<ShieldAlert className="h-4 w-4 text-rose-300" />}
        title="Risk Radar"
        action="Ver todo"
      />
      <QueryBoundary
        query={query}
        loadingLabel="Calculando riesgos"
        empty={(data) => data.items.length === 0}
      >
        {(data) => (
          <div className="space-y-2">
            {data.items.map((risk) => (
              <RiskFindingRow
                key={risk.id}
                risk={risk}
                resolving={resolvingId === risk.id}
                onResolve={() => onResolve(risk.id)}
              />
            ))}
          </div>
        )}
      </QueryBoundary>
    </Panel>
  );
}

function RiskFindingRow({
  risk,
  resolving,
  onResolve,
}: {
  risk: RiskFinding;
  resolving: boolean;
  onResolve: () => void;
}) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/70 p-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <RiskBadge severity={risk.severity} />
            <span className="truncate text-xs font-medium text-slate-100" title={risk.title}>
              {risk.title}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">{risk.description}</p>
        </div>
        <Button
          size="xs"
          variant="ghost"
          className="text-violet-300 hover:bg-violet-500/10"
          disabled={resolving}
          onClick={onResolve}
        >
          {resolving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          Resolver
        </Button>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-slate-400">
        <span>{risk.affected_sources} fuentes</span>
        <span>{risk.affected_conversations} conv.</span>
        <span className="truncate text-cyan-300" title={risk.quick_action_type}>
          {risk.quick_action_type}
        </span>
      </div>
    </div>
  );
}

function WhatsAppGapsPanel({
  query,
  onAction,
}: {
  query: UseQueryResult<{ items: UnansweredQuestion[]; total: number }>;
  onAction: (id: string, action: QuestionAction) => void;
}) {
  return (
    <Panel className="p-3">
      <PanelTitle
        icon={<CopyCheck className="h-4 w-4 text-amber-300" />}
        title="Preguntas reales sin respuesta"
        action="Ver todas"
      />
      <QueryBoundary
        query={query}
        loadingLabel="Agrupando preguntas de WhatsApp"
        empty={(data) => data.items.length === 0}
      >
        {(data) => (
          <>
            <div className="space-y-2">
              {data.items.map((question) => (
                <UnansweredQuestionRow key={question.id} question={question} onAction={onAction} />
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500">
              <span>Mostrando 5 de {data.total} preguntas</span>
              <Button size="xs" variant="ghost" className="text-violet-300">
                Ver todas
              </Button>
            </div>
          </>
        )}
      </QueryBoundary>
    </Panel>
  );
}

function UnansweredQuestionRow({
  question,
  onAction,
}: {
  question: UnansweredQuestion;
  onAction: (id: string, action: QuestionAction) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_54px_74px] items-center gap-2 rounded-md border border-slate-800 bg-slate-950/70 p-2 text-xs">
      <div className="min-w-0">
        <p className="truncate text-slate-100" title={question.question}>
          {question.question}
        </p>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
          <span>{question.last_seen_at}</span>
          <Badge className="rounded-sm border-violet-400/20 bg-violet-500/10 px-1.5 py-0 text-[10px] text-violet-200">
            {question.funnel_stage}
          </Badge>
        </div>
      </div>
      <div>
        <div className="text-slate-100">{question.frequency}</div>
        <div
          className={cn(
            "text-[11px]",
            question.trend_percent > 0 ? "text-emerald-300" : "text-amber-300",
          )}
        >
          {question.trend_percent > 0 ? "+" : ""}
          {question.trend_percent}%
        </div>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="xs"
            variant="outline"
            className="border-violet-400/30 bg-violet-500/10 text-violet-200"
          >
            Crear FAQ
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="border-slate-800 bg-slate-950 text-slate-100">
          <DropdownMenuItem onClick={() => onAction(question.id, "create-faq")}>
            Crear FAQ
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onAction(question.id, "escalate")}>
            Escalar
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onAction(question.id, "ignore")}>
            Ignorar
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function RagSimulationPanel({
  initialQuery,
  simulation,
  message,
  setMessage,
  selectedAgent,
  setSelectedAgent,
  selectedModel,
  running,
  onRun,
  onOpenPrompt,
  onOpenChunk,
  onMark,
}: {
  initialQuery: UseQueryResult<SimulationResponse>;
  simulation?: SimulationResponse;
  message: string;
  setMessage: (value: string) => void;
  selectedAgent: string;
  setSelectedAgent: (value: string) => void;
  selectedModel: string;
  running: boolean;
  onRun: () => void;
  onOpenPrompt: () => void;
  onOpenChunk: (id: string) => void;
  onMark: (id: string, action: SimulationAction) => void;
}) {
  return (
    <aside className="sticky top-14 h-fit space-y-3 xl:max-h-[calc(100vh-5rem)] xl:overflow-y-auto">
      <Panel className="p-3">
        <div className="mb-3 flex items-center justify-between">
          <PanelTitle
            icon={<Sparkles className="h-4 w-4 text-violet-300" />}
            title="RAG Simulation"
          />
          <Button
            size="icon-xs"
            variant="ghost"
            className="text-slate-400"
            aria-label="Cerrar simulador"
          >
            <XCircle className="h-3 w-3" />
          </Button>
        </div>
        <QueryBoundary
          query={initialQuery}
          loadingLabel="Preparando simulador"
          empty={(data) => data.retrieved_chunks.length === 0}
        >
          {() => (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <Select value={selectedAgent} onValueChange={setSelectedAgent}>
                  <SelectTrigger className="h-8 border-slate-700 bg-slate-950/80 text-xs text-slate-200">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="border-slate-800 bg-slate-950 text-slate-100">
                    <SelectItem value="Sales Agent">Sales Agent</SelectItem>
                    <SelectItem value="Duda General Agent">Duda General Agent</SelectItem>
                    <SelectItem value="AI Supervisor">AI Supervisor</SelectItem>
                  </SelectContent>
                </Select>
                <div className="flex h-8 items-center rounded-md border border-slate-800 bg-slate-950/70 px-2 text-xs text-slate-400">
                  Modelo: {selectedModel}
                </div>
              </div>

              <div className="rounded-md border border-slate-800 bg-slate-950/70 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-300">
                    Vista previa del prompt del agente
                  </span>
                  <Button
                    size="xs"
                    variant="ghost"
                    className="text-violet-300"
                    onClick={onOpenPrompt}
                  >
                    Ver completo
                  </Button>
                </div>
                <p className="line-clamp-4 text-xs text-slate-400">{simulation?.prompt_preview}</p>
              </div>

              <div className="space-y-2">
                <label
                  className="text-xs font-medium text-slate-300"
                  htmlFor="kb-simulation-message"
                >
                  Mensaje de prueba
                </label>
                <Textarea
                  id="kb-simulation-message"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  className="min-h-20 border-slate-700 bg-slate-950/80 text-sm text-slate-100 placeholder:text-slate-500"
                />
                <Button
                  className="w-full bg-cyan-600 text-white hover:bg-cyan-500"
                  disabled={running || !message.trim()}
                  onClick={onRun}
                >
                  {running ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  Ejecutar prueba
                </Button>
              </div>

              {simulation && (
                <>
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-slate-300">
                      Chunks recuperados (Top {simulation.retrieved_chunks.length})
                    </div>
                    {simulation.retrieved_chunks.map((chunk, index) => (
                      <RetrievedChunkCard
                        key={chunk.id}
                        chunk={chunk}
                        index={index + 1}
                        onOpen={() => onOpenChunk(chunk.id)}
                      />
                    ))}
                  </div>

                  <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-2">
                    <ConfidenceScore
                      score={simulation.confidence_score}
                      coverage={simulation.coverage_score}
                    />
                    <RiskFlags flags={simulation.risk_flags} />
                  </div>

                  <SafeAnswerModeCard />

                  <div className="rounded-md border border-slate-800 bg-slate-950/70 p-3">
                    <div className="mb-2 text-xs font-medium text-slate-300">
                      Respuesta simulada del agente
                    </div>
                    <p className="text-sm leading-6 text-slate-100">{simulation.answer}</p>
                    <p className="mt-2 text-[11px] text-slate-500">
                      Fuente: {simulation.source_summary}
                    </p>
                  </div>

                  <div className="grid grid-cols-3 gap-2">
                    <Button
                      size="xs"
                      className="bg-emerald-600 text-white hover:bg-emerald-500"
                      onClick={() => onMark(simulation.id, "correct")}
                    >
                      <Check className="h-3 w-3" />
                      Correcta
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      className="border-amber-400/30 bg-amber-500/10 text-amber-200"
                      onClick={() => onMark(simulation.id, "incomplete")}
                    >
                      Incompleta
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      className="border-rose-400/30 bg-rose-500/10 text-rose-200"
                      onClick={() => onMark(simulation.id, "incorrect")}
                    >
                      Incorrecta
                    </Button>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <Button
                      size="xs"
                      variant="outline"
                      className="border-slate-700 bg-slate-950/80 text-slate-200"
                      onClick={() => onMark(simulation.id, "create-faq")}
                    >
                      Crear FAQ
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      className="border-slate-700 bg-slate-950/80 text-slate-200"
                    >
                      Escalar
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      className="border-slate-700 bg-slate-950/80 text-slate-200"
                      onClick={() => onMark(simulation.id, "block")}
                    >
                      Bloquear
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
        </QueryBoundary>
      </Panel>
    </aside>
  );
}

function RetrievedChunkCard({
  chunk,
  index,
  onOpen,
}: {
  chunk: SimulationResponse["retrieved_chunks"][number];
  index: number;
  onOpen: () => void;
}) {
  const hasWarnings = chunk.warnings.length > 0;
  return (
    <button
      type="button"
      className="w-full rounded-md border border-slate-800 bg-slate-950/70 p-2 text-left hover:border-cyan-400/40 hover:bg-slate-900/70"
      onClick={onOpen}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 grid h-5 w-5 place-items-center rounded-sm bg-slate-900 text-[11px] text-slate-400">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-xs font-medium text-slate-100">
              {chunk.source_name} · p. {chunk.page_number}
            </span>
            <span className="text-xs text-slate-300">{chunk.retrieval_score.toFixed(2)}</span>
          </div>
          <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">{chunk.preview}</p>
          <div className="mt-2 flex items-center gap-2">
            <FreshnessBadge freshness={chunk.freshness_status === "vigente" ? "Buena" : "Media"} />
            {hasWarnings ? (
              <AlertCircle className="h-3.5 w-3.5 text-amber-300" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

function ConfidenceScore({ score, coverage }: { score: number; coverage: number }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/70 p-3 text-center">
      <div
        className="mx-auto grid h-20 w-20 place-items-center rounded-full"
        style={{
          background: `conic-gradient(#7c3aed ${score * 3.6}deg, rgba(51,65,85,0.55) 0deg)`,
        }}
      >
        <div className="grid h-14 w-14 place-items-center rounded-full bg-slate-950">
          <span className="text-lg font-semibold text-violet-200">{score}</span>
        </div>
      </div>
      <div className="mt-2 text-xs text-slate-300">Confianza media-alta</div>
      <div className="text-[11px] text-slate-500">Cobertura {coverage}%</div>
    </div>
  );
}

function RiskFlags({ flags }: { flags: string[] }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/70 p-3">
      <div className="mb-2 text-xs font-medium text-slate-300">Riesgos detectados</div>
      <div className="space-y-2">
        {flags.map((flag) => (
          <div key={flag} className="flex items-start gap-2 text-[11px] text-amber-200">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-300" />
            <span>{flag}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SafeAnswerModeCard() {
  return (
    <div className="rounded-md border border-emerald-400/20 bg-emerald-500/10 p-3 text-xs text-emerald-100">
      <div className="flex items-center gap-2 font-medium">
        <Lock className="h-3.5 w-3.5" />
        Modo respuesta segura activo
      </div>
      <p className="mt-1 text-[11px] text-emerald-200/80">
        Si falta catalogo, precio, stock, promocion o plan_credito, la respuesta pide confirmacion
        de asesor.
      </p>
    </div>
  );
}

function FunnelKnowledgeCoverage({ query }: { query: UseQueryResult<{ stages: FunnelStage[] }> }) {
  return (
    <Panel className="p-3">
      <PanelTitle
        icon={<Layers3 className="h-4 w-4 text-cyan-300" />}
        title="Funnel Knowledge Coverage"
        action="Ver mapa completo"
      />
      <QueryBoundary
        query={query}
        loadingLabel="Calculando cobertura por etapa"
        empty={(data) => data.stages.length === 0}
      >
        {(data) => (
          <div className="overflow-x-auto">
            <div className="grid min-w-[860px] grid-cols-8 gap-2">
              {data.stages.map((stage) => (
                <FunnelStageNode key={stage.id} stage={stage} />
              ))}
            </div>
          </div>
        )}
      </QueryBoundary>
    </Panel>
  );
}

function FunnelStageNode({ stage }: { stage: FunnelStage }) {
  const style = STATUS_STYLES[stage.status];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="relative rounded-md border border-slate-800 bg-slate-950/70 p-2 text-center">
          <div
            className={cn(
              "mx-auto mb-2 grid h-8 w-8 place-items-center rounded-md border",
              style.bg,
              style.border,
              style.text,
            )}
          >
            <PackageCheck className="h-4 w-4" />
          </div>
          <div className="truncate text-xs text-slate-200">{stage.label}</div>
          <div className={cn("mt-1 text-lg font-semibold", style.text)}>
            {stage.coverage_percent}%
          </div>
          <StatusBadge status={stage.status} />
        </div>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <div className="space-y-1">
          <p>Confianza promedio: {stage.confidence_average}%</p>
          <p>Preguntas sin respuesta: {stage.unanswered_count}</p>
          <p>Conflictos: {stage.conflict_count}</p>
          <p>Fuente de mayor riesgo: {stage.highest_risk_source}</p>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function ChunkImpactSummaryPanel({
  query,
  onOpen,
}: {
  query: UseQueryResult<ChunkImpact>;
  onOpen: () => void;
}) {
  return (
    <Panel className="p-3">
      <PanelTitle
        icon={<SquareStack className="h-4 w-4 text-violet-300" />}
        title="Chunk Impact"
        action="Abrir editor"
        onAction={onOpen}
      />
      <QueryBoundary
        query={query}
        loadingLabel="Cargando impacto del chunk"
        empty={(data) => !data.chunk_id}
      >
        {(impact) => (
          <div className="space-y-3">
            <div className="rounded-md border border-violet-400/20 bg-violet-500/10 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {impact.source_document} · Pagina {impact.page_number}
                  </p>
                  <p className="mt-1 text-xs text-violet-200">
                    Usado en {impact.used_in_answers_week} respuestas esta semana
                  </p>
                </div>
                <StatusBadge
                  status={impact.embedding_status === "publicada" ? "good" : "warning"}
                  label={impact.embedding_status}
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <MetricPill
                label="Conversaciones activas"
                value={String(impact.affected_active_conversations)}
              />
              <MetricPill
                label="Etapas afectadas"
                value={String(impact.affected_funnel_stages.length)}
              />
              <MetricPill
                label="Nivel de riesgo"
                value={SEVERITY_STYLES[impact.risk_level].label}
                tone={impact.risk_level}
              />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Button
                size="xs"
                variant="outline"
                className="border-slate-700 bg-slate-950/80 text-slate-200"
              >
                <Pencil className="h-3 w-3" />
                Editar
              </Button>
              <Button
                size="xs"
                variant="outline"
                className="border-slate-700 bg-slate-950/80 text-slate-200"
              >
                <Split className="h-3 w-3" />
                Dividir
              </Button>
              <Button
                size="xs"
                variant="outline"
                className="border-slate-700 bg-slate-950/80 text-slate-200"
              >
                Fusionar
              </Button>
            </div>
          </div>
        )}
      </QueryBoundary>
    </Panel>
  );
}

function BottomActionCards({ query }: { query: UseQueryResult<{ items: BottomActionCard[] }> }) {
  return (
    <QueryBoundary
      query={query}
      loadingLabel="Cargando acciones priorizadas"
      empty={(data) => data.items.length === 0}
    >
      {(data) => (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
          {data.items.map((card) => (
            <ActionCard key={card.id} card={card} />
          ))}
        </div>
      )}
    </QueryBoundary>
  );
}

function ActionCard({ card }: { card: BottomActionCard }) {
  const style = STATUS_STYLES[card.status];
  return (
    <Panel className="p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs text-slate-400">{card.title}</div>
          <div className={cn("mt-1 text-2xl font-semibold", style.text)}>{card.value}</div>
          <div className="mt-1 text-[11px] text-slate-500">{card.trend}</div>
        </div>
        <MiniIcon status={card.status} />
      </div>
      <div className="mt-2 h-8">
        <TinyLine
          data={card.sparkline}
          color={
            card.status === "critical"
              ? "#fb7185"
              : card.status === "warning"
                ? "#fbbf24"
                : "#34d399"
          }
        />
      </div>
      <Button
        size="xs"
        variant="outline"
        className="mt-2 w-full border-slate-700 bg-slate-950/80 text-slate-200"
      >
        {card.cta}
      </Button>
    </Panel>
  );
}

function ChunkImpactDrawer({
  open,
  onOpenChange,
  query,
  onAction,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: UseQueryResult<ChunkImpact>;
  onAction: (id: string, action: ChunkAction) => void;
}) {
  const impact = query.data;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full border-slate-800 bg-slate-950 text-slate-100 sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="text-slate-100">Chunk Impact Drawer</SheetTitle>
          <SheetDescription className="text-slate-400">
            Trazabilidad operativa del fragmento usado por RAG.
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
          <QueryBoundary
            query={query}
            loadingLabel="Cargando chunk"
            empty={(data) => !data.chunk_id}
          >
            {(data) => (
              <>
                <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
                  <div className="text-sm font-medium text-slate-100">{data.source_document}</div>
                  <div className="mt-1 text-xs text-slate-400">
                    Pagina {data.page_number} · Chunk ID {data.chunk_id}
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-200">{data.chunk_text}</p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <MetricPill label="Embedding" value={data.embedding_status} />
                  <MetricPill label="Retrieval score" value={data.retrieval_score.toFixed(2)} />
                  <MetricPill label="Usos esta semana" value={String(data.used_in_answers_week)} />
                  <MetricPill
                    label="Conversaciones activas"
                    value={String(data.affected_active_conversations)}
                  />
                </div>
                <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
                  <div className="mb-2 text-xs font-medium text-slate-300">Etapas afectadas</div>
                  <div className="flex flex-wrap gap-2">
                    {data.affected_funnel_stages.map((stage) => (
                      <Badge
                        key={stage}
                        className="rounded-sm border-cyan-400/20 bg-cyan-500/10 text-cyan-200"
                      >
                        {stage}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-slate-300">
                      Conflictos relacionados
                    </span>
                    <RiskBadge severity={data.risk_level} />
                  </div>
                  <div className="space-y-2">
                    {data.related_conflicts.map((conflict) => (
                      <div
                        key={conflict}
                        className="flex items-center gap-2 text-xs text-slate-300"
                      >
                        <GitCompareArrows className="h-3.5 w-3.5 text-amber-300" />
                        {conflict}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
                  <span>Ultima edicion: {data.last_edited_by}</span>
                  <span>Indexado: {data.last_indexed_at}</span>
                </div>
              </>
            )}
          </QueryBoundary>
        </div>
        {impact && (
          <div className="grid grid-cols-3 gap-2 border-t border-slate-800 p-4">
            <Button
              size="xs"
              variant="outline"
              className="border-slate-700 bg-slate-950/80 text-slate-200"
            >
              <Pencil className="h-3 w-3" />
              Editar
            </Button>
            <Button
              size="xs"
              variant="outline"
              className="border-slate-700 bg-slate-950/80 text-slate-200"
              onClick={() => onAction(impact.chunk_id, "split")}
            >
              Dividir
            </Button>
            <Button
              size="xs"
              variant="outline"
              className="border-slate-700 bg-slate-950/80 text-slate-200"
              onClick={() => onAction(impact.chunk_id, "merge")}
            >
              Fusionar
            </Button>
            <Button
              size="xs"
              variant="outline"
              className="border-rose-400/30 bg-rose-500/10 text-rose-200"
              onClick={() => onAction(impact.chunk_id, "disable")}
            >
              Desactivar
            </Button>
            <Button
              size="xs"
              variant="outline"
              className="border-violet-400/30 bg-violet-500/10 text-violet-200"
              onClick={() => onAction(impact.chunk_id, "prioritize")}
            >
              Priorizar
            </Button>
            <Button
              size="xs"
              variant="outline"
              className="border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
              onClick={() => onAction(impact.chunk_id, "reindex")}
            >
              Reindexar
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function PromptPreviewDrawer({
  open,
  onOpenChange,
  simulation,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  simulation?: SimulationResponse;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full border-slate-800 bg-slate-950 text-slate-100 sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="text-slate-100">PromptPreviewDrawer</SheetTitle>
          <SheetDescription className="text-slate-400">
            Bloque de seguridad y contexto enviado al agente para esta simulacion.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-3 overflow-y-auto px-4 pb-4">
          <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
            <div className="mb-2 text-xs font-medium text-slate-300">Sistema del agente</div>
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-200">
              {simulation?.prompt_preview}
            </p>
          </div>
          <div className="rounded-md border border-emerald-400/20 bg-emerald-500/10 p-3 text-sm text-emerald-100">
            No inventar precios, modelos, stock, promociones, aprobaciones, fechas de entrega ni
            terminos de credito.
          </div>
          <div className="rounded-md border border-amber-400/20 bg-amber-500/10 p-3 text-sm text-amber-100">
            Si catalogo o credito no tienen datos suficientes, responder: "Un asesor debe confirmar
            disponibilidad y precio actualizado."
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function QueryBoundary<T>({
  query,
  loadingLabel,
  empty,
  children,
}: {
  query: UseQueryResult<T>;
  loadingLabel: string;
  empty: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState label={loadingLabel} />;
  if (query.isError) return <ErrorState error={query.error} />;
  if (!query.data || empty(query.data)) return <EmptyState />;
  return <>{children(query.data)}</>;
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="space-y-2 p-3">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {label}
      </div>
      <Skeleton className="h-8 bg-slate-800" />
      <Skeleton className="h-8 bg-slate-800" />
      <Skeleton className="h-8 bg-slate-800" />
    </div>
  );
}

function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="rounded-md border border-rose-400/30 bg-rose-500/10 p-3 text-sm text-rose-100">
      <div className="flex items-center gap-2 font-medium">
        <AlertCircle className="h-4 w-4" />
        No se pudo cargar esta seccion.
      </div>
      <p className="mt-1 text-xs text-rose-200/80">
        {extractErrorDetail(error, "Intenta de nuevo en un momento.")}
      </p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/70 p-6 text-center text-sm text-slate-400">
      Sin datos para los filtros actuales.
    </div>
  );
}

function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <section
      className={cn("rounded-md border border-slate-800 bg-[#0a1424]/92 shadow-sm", className)}
    >
      {children}
    </section>
  );
}

function PanelTitle({
  icon,
  title,
  action,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="text-xs font-semibold uppercase text-slate-300">{title}</h2>
      </div>
      {action && (
        <Button size="xs" variant="ghost" className="text-violet-300" onClick={onAction}>
          {action}
        </Button>
      )}
    </div>
  );
}

function StatusBadge({ status, label }: { status: Status; label?: string }) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px]",
        style.bg,
        style.border,
        style.text,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
      {label ?? style.label}
    </span>
  );
}

function RiskBadge({ severity }: { severity: Severity }) {
  const style = SEVERITY_STYLES[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[10px]",
        style.className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
      {style.label}
    </span>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const tone =
    score >= 0.85
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-300"
      : score >= 0.75
        ? "border-amber-400/30 bg-amber-500/10 text-amber-300"
        : "border-rose-400/30 bg-rose-500/10 text-rose-300";
  return (
    <span className={cn("rounded-sm border px-2 py-1 font-mono text-xs", tone)}>
      {score.toFixed(2)}
    </span>
  );
}

function FreshnessBadge({ freshness, days }: { freshness: string; days?: number }) {
  const status: Status =
    freshness === "Critica" ? "critical" : freshness === "Media" ? "warning" : "good";
  const style = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px]",
        style.bg,
        style.border,
        style.text,
      )}
    >
      <Clock3 className="h-3 w-3" />
      {typeof days === "number" ? `${days} dias` : freshness}
    </span>
  );
}

function StatusDot({ label, active }: { label: string; active: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-300">
      <span className={cn("h-2 w-2 rounded-full", active ? "bg-emerald-400" : "bg-amber-400")} />
      {label}
    </span>
  );
}

function ConflictBadge({ count, risk }: { count: number; risk: Severity }) {
  if (count === 0) return <span className="text-emerald-300">0</span>;
  const style = SEVERITY_STYLES[risk];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs",
        style.className,
        "rounded-sm border px-1.5 py-0.5",
      )}
    >
      {count}
      <AlertCircle className="h-3 w-3" />
    </span>
  );
}

function SourceIcon({ sourceType }: { sourceType: string }) {
  const className = "h-4 w-4 shrink-0";
  if (sourceType === "FAQ") return <BookOpen className={cn(className, "text-violet-300")} />;
  if (sourceType === "Catalogo") return <Boxes className={cn(className, "text-cyan-300")} />;
  if (sourceType === "Promocion") return <Tag className={cn(className, "text-amber-300")} />;
  return <FileText className={cn(className, "text-slate-300")} />;
}

function MetricPill({
  label,
  value,
  tone = "low",
}: {
  label: string;
  value: string;
  tone?: Severity;
}) {
  const toneClass =
    tone === "high" || tone === "critical"
      ? "text-rose-300"
      : tone === "medium"
        ? "text-amber-300"
        : "text-slate-100";
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/70 p-2">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className={cn("mt-1 truncate text-sm font-medium", toneClass)}>{value}</div>
    </div>
  );
}

function MiniIcon({ status }: { status: Status }) {
  const className = "h-6 w-6";
  if (status === "critical") return <AlertCircle className={cn(className, "text-rose-300")} />;
  if (status === "warning") return <PauseCircle className={cn(className, "text-amber-300")} />;
  return <Database className={cn(className, "text-cyan-300")} />;
}

function TinyLine({ data, color }: { data: number[]; color: string }) {
  const chartData = data.map((value, index) => ({ index, value }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData}>
        <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Filter,
  Headphones,
  MessageCircle,
  PauseCircle,
  Radar,
  RefreshCw,
  SendHorizonal,
  ShieldAlert,
  Sparkles,
  UserCheck,
  Users,
  Zap,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  Tooltip as ChartTooltip,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  RadarChart,
  Radar as RadarShape,
  ResponsiveContainer,
} from "recharts";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useTenantStream } from "@/features/conversations/hooks/useTenantStream";
import {
  type CommandCenterFilters,
  type DraftResponse,
  type FeedbackBody,
  type HandoffCommandCenterResponse,
  type HandoffCommandItem,
  type HumanAgent,
  handoffsApi,
  type InsightCard,
  type RiskRadarItem,
  type TimelineEvent,
} from "@/features/handoffs/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

const DEFAULT_FILTERS: CommandCenterFilters = {
  urgency: "all",
  reason: "all",
  agent: "all",
  waiting_time: "all",
  sla_status: "all",
  lifecycle_stage: "all",
  ai_agent: "all",
  channel: "all",
  sentiment: "all",
  high_value_only: false,
  status: "all",
  sort: "priority_score_desc",
  q: "",
};

const HANDOFF_REASONS = [
  "Factura fiscal / Datos incorrectos",
  "Negociacion de precio",
  "Disponibilidad / Agenda",
  "Error de sistema / Pago",
  "Documentos incompletos",
  "Cliente pidio humano",
  "Baja confianza IA",
  "Fuera de horario",
  "Queja o frustracion",
  "Pregunta no encontrada en KB",
];

const LIFECYCLE_STAGES = [
  "Nuevo",
  "Calificacion",
  "Documentos",
  "Negociacion",
  "Cita",
  "Sistema",
  "Enganche listo",
  "Cerrado",
];

const RESOLUTION_OUTCOMES = [
  "Sale opportunity continued",
  "Appointment confirmed",
  "Customer not interested",
  "Wrong intent",
  "AI mistake",
  "Knowledge base missing data",
  "Human exception",
  "Duplicate",
  "Spam",
  "Other",
];

const DEFAULT_RESOLUTION_OUTCOME = "Sale opportunity continued";
const SUMMARY_SKELETON_KEYS = ["open", "critical", "wait", "sla", "ai", "value"];
const ROW_SKELETON_KEYS = ["alpha", "bravo", "charlie", "delta", "echo"];

const FEEDBACK_OPTIONS: {
  type: FeedbackBody["feedback_type"];
  label: string;
  icon: typeof CheckCircle2;
  tone: string;
}[] = [
  {
    type: "correct_escalation",
    label: "Correcta",
    icon: CheckCircle2,
    tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  },
  {
    type: "ai_should_have_answered",
    label: "Debio responder IA",
    icon: Bot,
    tone: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  },
  {
    type: "knowledge_gap",
    label: "Brecha de conocimiento",
    icon: BrainCircuit,
    tone: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  },
  {
    type: "routing_issue",
    label: "Problema de ruteo",
    icon: ArrowUpRight,
    tone: "border-violet-500/30 bg-violet-500/10 text-violet-200",
  },
];

const currency = new Intl.NumberFormat("es-MX", {
  style: "currency",
  currency: "MXN",
  maximumFractionDigits: 0,
});

function updateCachedItem(queryClient: QueryClient, updated: HandoffCommandItem) {
  queryClient.setQueriesData<HandoffCommandCenterResponse>(
    { queryKey: ["handoffs", "command-center"] },
    (old) =>
      old
        ? {
            ...old,
            items: old.items.map((item) => (item.id === updated.id ? updated : item)),
          }
        : old,
  );
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes < 60) return `${minutes}m ${secs.toString().padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${(minutes % 60).toString().padStart(2, "0")}m`;
}

function formatCountdown(deadline: string, now: number): string {
  const delta = new Date(deadline).getTime() - now;
  if (delta < 0) return `Vencido ${formatDuration(Math.abs(delta) / 1000)}`;
  return formatDuration(delta / 1000);
}

function confidenceLabel(confidence: number): string {
  if (confidence < 0.35) return "Muy baja";
  if (confidence < 0.55) return "Media";
  if (confidence < 0.75) return "Media alta";
  return "Alta";
}

function roleLabel(role: string): string {
  if (role === "tenant_admin" || role === "manager") return "Manager";
  if (role === "superadmin" || role === "ai_supervisor") return "AI Supervisor";
  return "Operator";
}

export function HandoffQueue() {
  useTenantStream();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [filters, setFilters] = useState<CommandCenterFilters>(DEFAULT_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [roleView, setRoleView] = useState(roleLabel(user?.role ?? "operator"));
  const [now, setNow] = useState(Date.now());
  const [assignTarget, setAssignTarget] = useState<HandoffCommandItem | null>(null);
  const [assignUserId, setAssignUserId] = useState<string>("");
  const [resolveTarget, setResolveTarget] = useState<HandoffCommandItem | null>(null);
  const [resolutionOutcome, setResolutionOutcome] = useState(DEFAULT_RESOLUTION_OUTCOME);
  const [resolutionNote, setResolutionNote] = useState("");
  const [draftTarget, setDraftTarget] = useState<HandoffCommandItem | null>(null);
  const [draftResponse, setDraftResponse] = useState<DraftResponse | null>(null);
  const [draftContext, setDraftContext] = useState("");

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setRoleView(roleLabel(user?.role ?? "operator"));
  }, [user?.role]);

  const commandQuery = useQuery({
    queryKey: ["handoffs", "command-center", filters],
    queryFn: () => handoffsApi.commandCenter(filters),
    refetchInterval: 30_000,
  });

  const items = commandQuery.data?.items ?? [];
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const snapshot = commandQuery.data;

  useEffect(() => {
    if (!selectedId && items[0]) setSelectedId(items[0].id);
    if (selectedId && items.length > 0 && !items.some((item) => item.id === selectedId)) {
      const first = items[0];
      if (first) setSelectedId(first.id);
    }
  }, [items, selectedId]);

  const timelineQuery = useQuery({
    queryKey: ["handoffs", "command-center", selected?.id, "timeline"],
    queryFn: () => handoffsApi.commandTimeline(selected?.id ?? ""),
    enabled: Boolean(selected?.id),
  });

  const takeMutation = useMutation({
    mutationFn: handoffsApi.takeCommand,
    onSuccess: (item) => {
      updateCachedItem(queryClient, item);
      setSelectedId(item.id);
      toast.success("Handoff tomado");
    },
    onError: (error: Error) =>
      toast.error("No se pudo tomar el handoff", { description: error.message }),
  });

  const assignMutation = useMutation({
    mutationFn: ({ id, userId }: { id: string; userId: string }) =>
      handoffsApi.assignCommand(id, userId),
    onSuccess: (item) => {
      updateCachedItem(queryClient, item);
      setAssignTarget(null);
      setAssignUserId("");
      setSelectedId(item.id);
      toast.success("Agente asignado");
    },
    onError: (error: Error) => toast.error("No se pudo asignar", { description: error.message }),
  });

  const resolveMutation = useMutation({
    mutationFn: ({
      id,
      resolution_outcome,
      note,
    }: {
      id: string;
      resolution_outcome: string;
      note?: string | null;
    }) => handoffsApi.resolveCommand(id, { resolution_outcome, note }),
    onSuccess: (item) => {
      updateCachedItem(queryClient, item);
      setResolveTarget(null);
      setResolutionNote("");
      setResolutionOutcome(DEFAULT_RESOLUTION_OUTCOME);
      setSelectedId(item.id);
      toast.success("Handoff resuelto");
    },
    onError: (error: Error) => toast.error("No se pudo resolver", { description: error.message }),
  });

  const feedbackMutation = useMutation({
    mutationFn: ({
      id,
      feedback_type,
    }: {
      id: string;
      feedback_type: FeedbackBody["feedback_type"];
    }) => handoffsApi.feedbackCommand(id, { feedback_type }),
    onSuccess: (item) => {
      updateCachedItem(queryClient, item);
      void queryClient.invalidateQueries({
        queryKey: ["handoffs", "command-center", item.id, "timeline"],
      });
      toast.success("Feedback registrado");
    },
    onError: (error: Error) =>
      toast.error("No se pudo registrar feedback", { description: error.message }),
  });

  const draftMutation = useMutation({
    mutationFn: ({ id, context }: { id: string; context?: string }) =>
      handoffsApi.generateReply(id, context),
    onSuccess: (response) => {
      setDraftResponse(response);
      toast.success("Borrador generado para revision humana");
    },
    onError: (error: Error) =>
      toast.error("No se pudo generar el borrador", { description: error.message }),
  });

  const openAssign = (item: HandoffCommandItem) => {
    const suggested = commandQuery.data?.human_agents.find(
      (agent) => agent.name === item.suggested_agent_name,
    );
    setAssignTarget(item);
    setAssignUserId(suggested?.id ?? commandQuery.data?.human_agents[0]?.id ?? "");
  };

  const openDraft = (item: HandoffCommandItem) => {
    setDraftTarget(item);
    setDraftResponse(null);
    setDraftContext("");
    draftMutation.mutate({ id: item.id });
  };

  const updateFilter = <K extends keyof CommandCenterFilters>(
    key: K,
    value: CommandCenterFilters[K],
  ) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const activeFilters = useMemo(
    () =>
      Object.entries(filters).filter(
        ([key, value]) =>
          key !== "sort" &&
          value !== undefined &&
          value !== "" &&
          value !== "all" &&
          value !== false,
      ).length,
    [filters],
  );

  return (
    <div className="-m-6 min-h-[calc(100vh-3.5rem)] bg-[#050b14] text-slate-100">
      <div className="border-b border-slate-800/80 bg-[#07101b]/95 px-5 py-3 shadow-2xl shadow-black/20">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-4">
            <div className="grid h-11 w-11 place-items-center rounded-lg border border-cyan-400/30 bg-cyan-500/10 text-cyan-200 shadow-lg shadow-cyan-950/40">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <div className="text-xs text-slate-400">
                Tenant: {user?.tenant_id ?? "demo"} · Actividad del sistema:{" "}
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-300">
                  Normal
                </span>
              </div>
              <h1 className="mt-1 text-2xl font-semibold text-white">Handoff Command Center</h1>
              <p className="text-sm text-slate-400">Real-time AI-to-human escalation control</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {["Operator", "Manager", "AI Supervisor"].map((role) => (
              <Button
                key={role}
                size="sm"
                variant={roleView === role ? "default" : "outline"}
                className={cn(
                  "border-slate-700 bg-slate-950/80 text-slate-200 hover:bg-slate-800",
                  roleView === role && "border-blue-500 bg-blue-600 text-white hover:bg-blue-500",
                )}
                onClick={() => setRoleView(role)}
              >
                {role}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <main className="space-y-4 p-5">
        {commandQuery.isLoading ? (
          <LoadingSkeleton />
        ) : commandQuery.isError ? (
          <EmptyState
            title="No se pudo cargar Handoffs"
            detail={commandQuery.error.message}
            action={
              <Button
                onClick={() => commandQuery.refetch()}
                className="bg-blue-600 hover:bg-blue-500"
              >
                <RefreshCw className="h-4 w-4" />
                Reintentar
              </Button>
            }
          />
        ) : !snapshot ? (
          <EmptyState
            title="Sin datos de command center"
            detail="El snapshot operativo todavia no esta disponible."
          />
        ) : (
          <>
            <SummaryCards data={snapshot.summary} />
            <HandoffFilters
              filters={filters}
              activeFilters={activeFilters}
              aiAgents={snapshot.ai_agents}
              humanAgents={snapshot.human_agents}
              onChange={updateFilter}
              onClear={() => setFilters(DEFAULT_FILTERS)}
            />

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px] 2xl:grid-cols-[minmax(0,1fr)_420px]">
              <section className="rounded-lg border border-slate-800/90 bg-[#07111f]/90 shadow-2xl shadow-black/20">
                <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-white">
                      <Headphones className="h-4 w-4 text-cyan-300" />
                      Prioritized Handoff Queue
                    </div>
                    <p className="text-xs text-slate-500">
                      {snapshot.total} casos ordenados por riesgo, SLA y valor comercial
                    </p>
                  </div>
                  <Select
                    value={filters.sort ?? "priority_score_desc"}
                    onValueChange={(value) => updateFilter("sort", value)}
                  >
                    <SelectTrigger className="h-8 w-[210px] border-slate-700 bg-slate-950 text-xs text-slate-200">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="border-slate-700 bg-slate-950 text-slate-100">
                      <SelectItem value="priority_score_desc">Prioridad desc</SelectItem>
                      <SelectItem value="wait_time_desc">Espera desc</SelectItem>
                      <SelectItem value="estimated_value_desc">Valor desc</SelectItem>
                      <SelectItem value="ai_confidence_asc">Confianza IA asc</SelectItem>
                      <SelectItem value="sla_deadline_asc">SLA vence primero</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {items.length === 0 ? (
                  <EmptyState
                    title="Sin handoffs en esta vista"
                    detail="Ajusta filtros o limpia la busqueda para volver a la cola operativa."
                  />
                ) : (
                  <div className="divide-y divide-slate-800/80">
                    {items.map((item) => (
                      <HandoffCard
                        key={item.id}
                        item={item}
                        selected={item.id === selected?.id}
                        now={now}
                        onSelect={() => setSelectedId(item.id)}
                        onTake={() => takeMutation.mutate(item.id)}
                        onAssign={() => openAssign(item)}
                        onDraft={() => openDraft(item)}
                        onResolve={() => setResolveTarget(item)}
                        busy={
                          takeMutation.isPending ||
                          assignMutation.isPending ||
                          resolveMutation.isPending ||
                          draftMutation.isPending
                        }
                      />
                    ))}
                  </div>
                )}
              </section>

              <IntelligencePanel
                item={selected}
                roleView={roleView}
                now={now}
                timeline={timelineQuery.data?.items ?? []}
                timelineLoading={timelineQuery.isLoading}
                onDraft={() => selected && openDraft(selected)}
                onFeedback={(feedback_type) => {
                  if (selected) feedbackMutation.mutate({ id: selected.id, feedback_type });
                }}
                feedbackBusy={feedbackMutation.isPending}
              />
            </div>

            <AnalyticsStrip insights={snapshot.insights} />
            <RiskRadar items={snapshot.risk_radar} />
          </>
        )}
      </main>

      <AssignModal
        open={Boolean(assignTarget)}
        item={assignTarget}
        agents={commandQuery.data?.human_agents ?? []}
        selectedUserId={assignUserId}
        onSelectedUserId={setAssignUserId}
        onOpenChange={(open) => {
          if (!open) setAssignTarget(null);
        }}
        onConfirm={() => {
          if (assignTarget && assignUserId) {
            assignMutation.mutate({ id: assignTarget.id, userId: assignUserId });
          }
        }}
        busy={assignMutation.isPending}
      />

      <ResolveModal
        open={Boolean(resolveTarget)}
        item={resolveTarget}
        outcome={resolutionOutcome}
        note={resolutionNote}
        onOutcome={setResolutionOutcome}
        onNote={setResolutionNote}
        onOpenChange={(open) => {
          if (!open) setResolveTarget(null);
        }}
        onConfirm={() => {
          if (resolveTarget) {
            resolveMutation.mutate({
              id: resolveTarget.id,
              resolution_outcome: resolutionOutcome,
              note: resolutionNote || null,
            });
          }
        }}
        busy={resolveMutation.isPending}
      />

      <ReplyDraftModal
        open={Boolean(draftTarget)}
        item={draftTarget}
        draft={draftResponse}
        context={draftContext}
        busy={draftMutation.isPending}
        onContext={setDraftContext}
        onRegenerate={() => {
          if (draftTarget) draftMutation.mutate({ id: draftTarget.id, context: draftContext });
        }}
        onOpenChange={(open) => {
          if (!open) setDraftTarget(null);
        }}
      />
    </div>
  );
}

function SummaryCards({ data }: { data: HandoffCommandCenterResponse["summary"] }) {
  const cards = [
    {
      label: "Open Handoffs",
      value: data.open_handoffs,
      detail: `${data.unassigned_cases} sin asignar`,
      icon: Users,
      tone: "text-blue-300 bg-blue-500/10 border-blue-500/20",
    },
    {
      label: "Critical Cases",
      value: data.critical_cases,
      detail: "SLA y frustracion",
      icon: AlertTriangle,
      tone: "text-red-300 bg-red-500/10 border-red-500/20",
    },
    {
      label: "Average Wait Time",
      value: formatDuration(data.average_wait_seconds),
      detail: "Promedio de cola",
      icon: Clock3,
      tone: "text-cyan-300 bg-cyan-500/10 border-cyan-500/20",
    },
    {
      label: "SLA Breaches",
      value: data.sla_breaches,
      detail: "Requieren accion",
      icon: ShieldAlert,
      tone: "text-orange-300 bg-orange-500/10 border-orange-500/20",
    },
    {
      label: "AI Confidence Alerts",
      value: data.ai_confidence_alerts,
      detail: "Confianza menor a 40%",
      icon: BrainCircuit,
      tone: "text-violet-300 bg-violet-500/10 border-violet-500/20",
    },
    {
      label: "High-Value Leads Waiting",
      value: data.high_value_leads_waiting,
      detail: currency.format(data.high_value_potential_mxn),
      icon: CircleDollarSign,
      tone: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
    },
  ];

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.label}
            className="rounded-lg border border-slate-800 bg-[#0b1422]/90 p-4 shadow-lg shadow-black/15"
          >
            <div className="flex items-start gap-3">
              <div className={cn("rounded-lg border p-2", card.tone)}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs text-slate-400">{card.label}</div>
                <div className="mt-1 text-2xl font-semibold text-white">{card.value}</div>
                <div className="mt-1 text-xs text-slate-500">{card.detail}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function HandoffFilters({
  filters,
  activeFilters,
  aiAgents,
  humanAgents,
  onChange,
  onClear,
}: {
  filters: CommandCenterFilters;
  activeFilters: number;
  aiAgents: HandoffCommandCenterResponse["ai_agents"];
  humanAgents: HumanAgent[];
  onChange: <K extends keyof CommandCenterFilters>(key: K, value: CommandCenterFilters[K]) => void;
  onClear: () => void;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-[#07111f]/90 p-3">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
        <div className="relative min-w-[260px] flex-1">
          <MessageCircle className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <Input
            value={filters.q ?? ""}
            onChange={(event) => onChange("q", event.target.value)}
            placeholder="Buscar cliente, motivo, mensaje o accion..."
            className="h-9 border-slate-700 bg-slate-950/80 pl-9 text-sm text-slate-100 placeholder:text-slate-500"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FilterSelect
            label="Urgencia"
            value={filters.urgency ?? "all"}
            options={[
              ["all", "Todas"],
              ["critical", "Critica"],
              ["high", "Alta"],
              ["medium", "Media"],
              ["low", "Baja"],
            ]}
            onValueChange={(value) => onChange("urgency", value as CommandCenterFilters["urgency"])}
          />
          <FilterSelect
            label="Razon"
            value={filters.reason ?? "all"}
            options={[
              ["all", "Todas"],
              ...HANDOFF_REASONS.map((reason) => [reason, reason] as const),
            ]}
            onValueChange={(value) => onChange("reason", value)}
          />
          <FilterSelect
            label="Agente"
            value={filters.agent ?? "all"}
            options={[
              ["all", "Todos"],
              ["unassigned", "Sin asignar"],
              ...humanAgents.map((agent) => [agent.name, agent.name] as const),
            ]}
            onValueChange={(value) => onChange("agent", value)}
          />
          <FilterSelect
            label="Espera"
            value={filters.waiting_time ?? "all"}
            options={[
              ["all", "Todas"],
              ["5", "+5 min"],
              ["15", "+15 min"],
              ["30", "+30 min"],
            ]}
            onValueChange={(value) => onChange("waiting_time", value)}
          />
          <FilterSelect
            label="SLA"
            value={filters.sla_status ?? "all"}
            options={[
              ["all", "Todos"],
              ["healthy", "Healthy"],
              ["warning", "Warning"],
              ["breached", "Breached"],
            ]}
            onValueChange={(value) =>
              onChange("sla_status", value as CommandCenterFilters["sla_status"])
            }
          />
          <FilterSelect
            label="Etapa"
            value={filters.lifecycle_stage ?? "all"}
            options={[
              ["all", "Todas"],
              ...LIFECYCLE_STAGES.map((stage) => [stage, stage] as const),
            ]}
            onValueChange={(value) => onChange("lifecycle_stage", value)}
          />
          <FilterSelect
            label="Agente IA"
            value={filters.ai_agent ?? "all"}
            options={[
              ["all", "Todos"],
              ...aiAgents.map((agent) => [agent.id, agent.name] as const),
            ]}
            onValueChange={(value) => onChange("ai_agent", value)}
          />
          <FilterSelect
            label="Canal"
            value={filters.channel ?? "all"}
            options={[
              ["all", "Todos"],
              ["WhatsApp", "WhatsApp"],
              ["web", "Web"],
            ]}
            onValueChange={(value) => onChange("channel", value)}
          />
          <FilterSelect
            label="Sentimiento"
            value={filters.sentiment ?? "all"}
            options={[
              ["all", "Todos"],
              ["positive", "Positivo"],
              ["neutral", "Neutral"],
              ["negative", "Negativo"],
            ]}
            onValueChange={(value) =>
              onChange("sentiment", value as CommandCenterFilters["sentiment"])
            }
          />
          <label className="flex h-9 items-center gap-2 rounded-md border border-slate-700 bg-slate-950/80 px-3 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={Boolean(filters.high_value_only)}
              onChange={(event) => onChange("high_value_only", event.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-950"
            />
            Solo alto valor
          </label>
          <Button
            variant="outline"
            size="sm"
            className="h-9 border-slate-700 bg-slate-950/80 text-slate-300 hover:bg-slate-800"
            onClick={onClear}
          >
            <Filter className="h-4 w-4" />
            Limpiar filtros
            {activeFilters > 0 && (
              <span className="rounded-full bg-blue-500/20 px-1.5 py-0.5 text-[10px] text-blue-200">
                {activeFilters}
              </span>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onValueChange,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string])[];
  onValueChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger className="h-9 min-w-[126px] border-slate-700 bg-slate-950/80 text-xs text-slate-200">
        <Filter className="h-3.5 w-3.5 text-slate-500" />
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent className="max-h-80 border-slate-700 bg-slate-950 text-slate-100">
        {options.map(([optionValue, optionLabel]) => (
          <SelectItem key={`${label}-${optionValue}`} value={optionValue}>
            {optionLabel}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function HandoffCard({
  item,
  selected,
  now,
  busy,
  onSelect,
  onTake,
  onAssign,
  onDraft,
  onResolve,
}: {
  item: HandoffCommandItem;
  selected: boolean;
  now: number;
  busy: boolean;
  onSelect: () => void;
  onTake: () => void;
  onAssign: () => void;
  onDraft: () => void;
  onResolve: () => void;
}) {
  return (
    <article
      className={cn(
        "bg-[#081322]/70 px-4 py-3 transition hover:bg-[#0b1828]",
        selected && "bg-[#0d1e33] shadow-[inset_3px_0_0_0_rgba(14,165,233,0.95)]",
      )}
    >
      <div className="grid gap-3 2xl:grid-cols-[90px_minmax(250px,1.35fr)_minmax(210px,1fr)_150px_170px_160px_190px]">
        <div className="flex items-center gap-3 2xl:block">
          <PriorityBadge score={item.priority_score} urgency={item.urgency} />
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-emerald-500/15 text-xs font-semibold text-emerald-200">
              {item.customer_name
                .split(" ")
                .slice(0, 2)
                .map((part) => part[0])
                .join("")}
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-white">{item.customer_name}</div>
              <div className="text-xs text-slate-400">{item.phone}</div>
            </div>
            <Badge className="border-emerald-500/20 bg-emerald-500/10 text-emerald-200">
              {item.channel}
            </Badge>
            <Button
              size="xs"
              variant="ghost"
              className="h-6 px-2 text-xs text-cyan-300 hover:bg-cyan-500/10 hover:text-cyan-200"
              onClick={onSelect}
            >
              Ver
            </Button>
          </div>
          <p className="mt-2 line-clamp-2 text-sm text-slate-300">"{item.last_message}"</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{item.detected_intent}</span>
            <span>·</span>
            <span>
              {item.last_message_at
                ? new Date(item.last_message_at).toLocaleTimeString("es-MX", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : ""}
            </span>
          </div>
        </div>

        <div>
          <div className="text-xs text-slate-500">Motivo del handoff</div>
          <div className="mt-1 text-sm font-medium text-slate-100">{item.handoff_reason}</div>
          <p className="mt-1 line-clamp-2 text-xs text-slate-400">{item.why_triggered}</p>
          <button
            type="button"
            className="mt-1 flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200"
            onClick={(event) => {
              event.stopPropagation();
              onSelect();
            }}
          >
            ¿Por que se activo?
            <ChevronDown className="h-3 w-3" />
          </button>
        </div>

        <ConfidenceMeter confidence={item.ai_confidence} />

        <div className="space-y-2">
          <div>
            <div className="text-xs text-slate-500">Espera / SLA</div>
            <div className="mt-1 text-sm text-slate-200">
              {formatDuration(item.wait_time_seconds)}
            </div>
          </div>
          <SLAStatus item={item} now={now} />
        </div>

        <div>
          <div className="text-xs text-slate-500">Agente</div>
          <div className="mt-1 text-sm text-slate-200">
            {item.assigned_agent_name ?? "Sin asignar"}
          </div>
          {!item.assigned_agent_name && (
            <div className="mt-1 text-xs text-slate-500">
              Sugerido: <span className="text-cyan-300">{item.suggested_agent_name}</span>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <div className="text-sm font-semibold text-emerald-300">
            {currency.format(item.estimated_value)}
          </div>
          <div className="text-xs text-slate-400">{item.lifecycle_stage}</div>
          <SentimentBadge sentiment={item.sentiment} />
          <ActionButtons
            item={item}
            busy={busy}
            onTake={onTake}
            onAssign={onAssign}
            onDraft={onDraft}
            onResolve={onResolve}
          />
        </div>
      </div>
      <div className="mt-3 rounded-md border border-slate-800/80 bg-black/20 px-3 py-2 text-xs text-slate-400">
        <span className="font-medium text-slate-300">Siguiente accion:</span>{" "}
        {item.recommended_action}
      </div>
    </article>
  );
}

function PriorityBadge({
  score,
  urgency,
}: {
  score: number;
  urgency: HandoffCommandItem["urgency"];
}) {
  const tone =
    urgency === "critical"
      ? "border-red-400 text-red-200 shadow-red-950/50"
      : urgency === "high"
        ? "border-orange-400 text-orange-200 shadow-orange-950/50"
        : urgency === "medium"
          ? "border-yellow-400 text-yellow-100 shadow-yellow-950/40"
          : "border-cyan-400 text-cyan-100 shadow-cyan-950/40";
  return (
    <div className="flex items-center gap-3 2xl:block">
      <div
        className={cn(
          "grid h-14 w-14 place-items-center rounded-full border-2 bg-slate-950 text-lg font-semibold shadow-lg",
          tone,
        )}
      >
        {score}
      </div>
      <div className="mt-1 text-xs font-medium capitalize text-slate-300">{urgency}</div>
    </div>
  );
}

function SLAStatus({ item, now }: { item: HandoffCommandItem; now: number }) {
  const remaining = new Date(item.sla_deadline).getTime() - now;
  const pct =
    item.sla_status === "breached" ? 100 : Math.min(100, Math.max(8, 100 - remaining / 600));
  const badgeTone =
    item.sla_status === "breached"
      ? "bg-red-500/15 text-red-200"
      : item.sla_status === "warning"
        ? "bg-amber-500/15 text-amber-200"
        : "bg-emerald-500/15 text-emerald-200";
  const barTone =
    item.sla_status === "breached"
      ? "bg-red-500"
      : item.sla_status === "warning"
        ? "bg-amber-500"
        : "bg-emerald-500";
  return (
    <div>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-500">SLA</span>
        <span className={cn("rounded-full px-2 py-0.5", badgeTone)}>{item.sla_status}</span>
      </div>
      <div className="mt-1 text-xs text-slate-300">{formatCountdown(item.sla_deadline, now)}</div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className={cn("h-full rounded-full", barTone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ConfidenceMeter({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color = pct < 35 ? "#ef4444" : pct < 60 ? "#f59e0b" : "#22c55e";
  return (
    <div className="flex items-center gap-3">
      <div
        className="grid h-14 w-14 place-items-center rounded-full text-sm font-semibold text-white"
        style={{
          background: `conic-gradient(${color} ${pct * 3.6}deg, rgba(30,41,59,0.95) 0deg)`,
        }}
      >
        <div className="grid h-10 w-10 place-items-center rounded-full bg-[#07111f]">{pct}%</div>
      </div>
      <div>
        <div className="text-xs text-slate-500">Confianza IA</div>
        <div className="text-sm text-slate-200">{confidenceLabel(confidence)}</div>
      </div>
    </div>
  );
}

function ActionButtons({
  item,
  busy,
  onTake,
  onAssign,
  onDraft,
  onResolve,
}: {
  item: HandoffCommandItem;
  busy: boolean;
  onTake: () => void;
  onAssign: () => void;
  onDraft: () => void;
  onResolve: () => void;
}) {
  const resolved = item.status === "resolved";
  return (
    <div className="grid grid-cols-2 gap-2 pt-1">
      <Button
        size="xs"
        className="bg-blue-600 text-white hover:bg-blue-500"
        disabled={busy || resolved}
        onClick={(event) => {
          event.stopPropagation();
          onTake();
        }}
      >
        <UserCheck className="h-3.5 w-3.5" />
        Tomar
      </Button>
      <Button
        size="xs"
        variant="outline"
        className="border-slate-700 bg-slate-950 text-slate-200 hover:bg-slate-800"
        disabled={busy || resolved}
        onClick={(event) => {
          event.stopPropagation();
          onAssign();
        }}
      >
        <Users className="h-3.5 w-3.5" />
        Asignar
      </Button>
      <Button
        size="xs"
        variant="outline"
        className="border-violet-500/30 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20"
        disabled={busy || resolved}
        onClick={(event) => {
          event.stopPropagation();
          onDraft();
        }}
      >
        <Sparkles className="h-3.5 w-3.5" />
        Borrador IA
      </Button>
      <Button
        size="xs"
        variant="outline"
        className="border-emerald-500/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
        disabled={busy || resolved}
        onClick={(event) => {
          event.stopPropagation();
          onResolve();
        }}
      >
        <CheckCircle2 className="h-3.5 w-3.5" />
        Resolver
      </Button>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment: HandoffCommandItem["sentiment"] }) {
  const tone =
    sentiment === "negative"
      ? "border-red-500/30 bg-red-500/10 text-red-200"
      : sentiment === "positive"
        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
        : "border-amber-500/30 bg-amber-500/10 text-amber-200";
  const label =
    sentiment === "negative" ? "Negativo" : sentiment === "positive" ? "Positivo" : "Neutral";
  return <Badge className={tone}>{label}</Badge>;
}

function IntelligencePanel({
  item,
  roleView,
  now,
  timeline,
  timelineLoading,
  onDraft,
  onFeedback,
  feedbackBusy,
}: {
  item: HandoffCommandItem | null;
  roleView: string;
  now: number;
  timeline: TimelineEvent[];
  timelineLoading: boolean;
  onDraft: () => void;
  onFeedback: (feedbackType: FeedbackBody["feedback_type"]) => void;
  feedbackBusy: boolean;
}) {
  if (!item) {
    return (
      <aside className="rounded-lg border border-slate-800 bg-[#07111f]/90 p-5">
        <EmptyState
          title="Selecciona un handoff"
          detail="El panel mostrara contexto, riesgo y acciones."
        />
      </aside>
    );
  }

  return (
    <aside className="space-y-3 rounded-lg border border-slate-800/90 bg-[#07111f]/95 p-4 shadow-2xl shadow-black/20">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Bot className="h-4 w-4 text-cyan-300" />
          Analista IA · Copiloto
        </div>
        <Badge className="border-slate-700 bg-slate-950 text-slate-300">{roleView}</Badge>
      </div>

      <section className="space-y-2">
        <PanelTitle icon={MessageCircle} label={`Context Snapshot - ${item.customer_name}`} />
        <FactRow label="Canal" value={item.channel} />
        <FactRow label="Inicio" value={new Date(item.created_at).toLocaleString("es-MX")} />
        <FactRow label="Etapa" value={item.lifecycle_stage} />
        <FactRow label="Valor estimado" value={currency.format(item.estimated_value)} />
        <FactRow label="Agente IA" value={item.ai_agent_name} />
        <FactRow label="SLA" value={formatCountdown(item.sla_deadline, now)} />
      </section>

      <SuggestedReplyBox item={item} onDraft={onDraft} />

      <section className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
        <PanelTitle icon={Zap} label="Siguiente mejor accion" />
        <p className="mt-2 text-sm text-slate-300">{item.recommended_action}</p>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <PanelTitle icon={PauseCircle} label="Datos faltantes / No resueltos" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {item.missing_fields.map((field) => (
              <Badge key={field} className="border-orange-500/30 bg-orange-500/10 text-orange-200">
                {field}
              </Badge>
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <PanelTitle icon={ShieldAlert} label="Riesgo" />
          <div className="mt-2 flex items-center gap-2">
            <Badge className="border-red-500/30 bg-red-500/10 text-red-200">
              {item.risk_level}
            </Badge>
            <span className="text-sm text-slate-300">{item.risk_explanation}</span>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
        <PanelTitle icon={BrainCircuit} label="Regla IA que activo el handoff" />
        <p className="mt-2 text-sm text-slate-300">{item.ai_rule}</p>
        <div className="mt-2 text-xs text-slate-500">{item.why_triggered}</div>
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
        <PanelTitle icon={Clock3} label="Historial relacionado" />
        <div className="mt-2 space-y-2">
          {item.related_history.map((entry) => (
            <div
              key={entry}
              className="rounded-md bg-slate-900/80 px-2 py-1.5 text-xs text-slate-300"
            >
              {entry}
            </div>
          ))}
        </div>
      </section>

      <FeedbackButtons onFeedback={onFeedback} busy={feedbackBusy} />
      <TimelinePanel timeline={timeline} loading={timelineLoading} />
    </aside>
  );
}

function PanelTitle({ icon: Icon, label }: { icon: typeof MessageCircle; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
      <Icon className="h-4 w-4 text-cyan-300" />
      {label}
    </div>
  );
}

function FactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  );
}

function SuggestedReplyBox({ item, onDraft }: { item: HandoffCommandItem; onDraft: () => void }) {
  return (
    <section className="rounded-lg border border-violet-500/20 bg-violet-500/10 p-3">
      <div className="flex items-center justify-between">
        <PanelTitle icon={Sparkles} label="Borrador de respuesta sugerido" />
        <Button
          size="xs"
          variant="outline"
          className="border-violet-400/40 bg-violet-500/10 text-violet-100 hover:bg-violet-500/20"
          onClick={onDraft}
        >
          <SendHorizonal className="h-3.5 w-3.5" />
          Usar borrador
        </Button>
      </div>
      <p className="mt-3 rounded-md border border-violet-400/10 bg-slate-950/60 p-3 text-sm text-slate-200">
        {item.suggested_reply}
      </p>
      <p className="mt-2 text-xs text-violet-200/70">No se envia automaticamente.</p>
    </section>
  );
}

function FeedbackButtons({
  onFeedback,
  busy,
}: {
  onFeedback: (feedbackType: FeedbackBody["feedback_type"]) => void;
  busy: boolean;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <PanelTitle icon={BrainCircuit} label="Fue correcta la escalacion?" />
      <div className="mt-3 grid grid-cols-2 gap-2">
        {FEEDBACK_OPTIONS.map((option) => {
          const Icon = option.icon;
          return (
            <Button
              key={option.type}
              size="sm"
              variant="outline"
              className={cn("justify-start whitespace-normal text-left text-xs", option.tone)}
              disabled={busy}
              onClick={() => onFeedback(option.type)}
            >
              <Icon className="h-3.5 w-3.5" />
              {option.label}
            </Button>
          );
        })}
      </div>
    </section>
  );
}

function TimelinePanel({ timeline, loading }: { timeline: TimelineEvent[]; loading: boolean }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <PanelTitle icon={Activity} label="Audit timeline" />
      <div className="mt-3 space-y-2">
        {loading ? (
          <>
            <Skeleton className="h-10 bg-slate-800" />
            <Skeleton className="h-10 bg-slate-800" />
          </>
        ) : (
          timeline.slice(-5).map((event) => (
            <div key={event.id} className="border-l border-cyan-500/40 pl-3">
              <div className="text-xs text-slate-300">{event.description}</div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                {event.actor_type} · {new Date(event.created_at).toLocaleString("es-MX")}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function AnalyticsStrip({ insights }: { insights: InsightCard[] }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-[#07111f]/90 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
        <Activity className="h-4 w-4 text-cyan-300" />
        Insights del dia
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        {insights.map((insight) => (
          <div key={insight.id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-xs text-slate-500">{insight.label}</div>
                <div className="mt-1 text-sm font-semibold text-slate-100">{insight.value}</div>
                <div className="text-xs text-slate-400">{insight.detail}</div>
              </div>
              <Badge className={insightTone(insight.tone)}>{insight.trend}</Badge>
            </div>
            <MiniSparkline data={insight.sparkline} tone={insight.tone} />
          </div>
        ))}
      </div>
    </section>
  );
}

function RiskRadar({ items }: { items: RiskRadarItem[] }) {
  const radarData = items.slice(0, 6).map((item) => ({
    metric: item.title.split(" ").slice(0, 2).join(" "),
    value: Math.max(8, Number.parseInt(item.value.replace(/\D/g, ""), 10) || 12),
  }));

  return (
    <section className="rounded-lg border border-slate-800 bg-[#07111f]/90 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Radar className="h-4 w-4 text-cyan-300" />
          Handoff Risk Radar
        </div>
        <span className="text-xs text-slate-500">Monitoreo en tiempo real</span>
      </div>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_240px]">
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-6">
          {items.map((item) => (
            <div key={item.id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs text-slate-400">{item.title}</div>
                <Badge className={severityTone(item.severity)}>{item.severity}</Badge>
              </div>
              <div className="mt-2 text-2xl font-semibold text-white">{item.value}</div>
              <div className="text-xs text-slate-500">{item.detail}</div>
              <div className="mt-1 text-xs text-red-300">{item.trend}</div>
              <MiniSparkline
                data={item.sparkline}
                tone={item.severity === "critical" ? "critical" : "warning"}
              />
            </div>
          ))}
        </div>
        <div className="h-64 rounded-lg border border-slate-800 bg-slate-950/50 p-2">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={radarData}>
              <PolarGrid stroke="#334155" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: "#94a3b8", fontSize: 10 }} />
              <RadarShape
                dataKey="value"
                fill="#2563eb"
                fillOpacity={0.35}
                stroke="#38bdf8"
                strokeWidth={2}
              />
              <ChartTooltip
                contentStyle={{
                  background: "#020617",
                  border: "1px solid #1e293b",
                  color: "#e2e8f0",
                }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

function MiniSparkline({
  data,
  tone,
}: {
  data: number[];
  tone: InsightCard["tone"] | "medium" | "high";
}) {
  const color =
    tone === "critical" || tone === "high"
      ? "#ef4444"
      : tone === "warning" || tone === "medium"
        ? "#f59e0b"
        : tone === "good"
          ? "#22c55e"
          : "#38bdf8";
  const points = data.map((value, index) => ({ index, value }));
  return (
    <div className="mt-2 h-10">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function AssignModal({
  open,
  item,
  agents,
  selectedUserId,
  busy,
  onSelectedUserId,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  item: HandoffCommandItem | null;
  agents: HumanAgent[];
  selectedUserId: string;
  busy: boolean;
  onSelectedUserId: (id: string) => void;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-slate-800 bg-[#07111f] text-slate-100 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Asignar handoff</DialogTitle>
          <DialogDescription>
            {item ? `${item.customer_name} · ${item.handoff_reason}` : "Selecciona un agente"}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 md:grid-cols-2">
          {agents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              className={cn(
                "rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-left transition hover:border-cyan-500/40",
                selectedUserId === agent.id && "border-cyan-400 bg-cyan-500/10",
              )}
              onClick={() => onSelectedUserId(agent.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-medium text-slate-100">{agent.name}</div>
                <Badge
                  className={
                    agent.status === "online"
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-200"
                  }
                >
                  {agent.status}
                </Badge>
              </div>
              <div className="mt-1 text-xs text-slate-500">{agent.role}</div>
              <div className="mt-2 text-xs text-slate-300">
                Carga: {agent.current_workload}/{agent.max_active_cases}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {agent.skills.slice(0, 3).map((skill) => (
                  <span
                    key={skill}
                    className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-300"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </button>
          ))}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            className="border-slate-700 bg-slate-950"
            onClick={() => onOpenChange(false)}
          >
            Cancelar
          </Button>
          <Button
            className="bg-blue-600 hover:bg-blue-500"
            disabled={!selectedUserId || busy}
            onClick={onConfirm}
          >
            <UserCheck className="h-4 w-4" />
            Asignar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResolveModal({
  open,
  item,
  outcome,
  note,
  busy,
  onOutcome,
  onNote,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  item: HandoffCommandItem | null;
  outcome: string;
  note: string;
  busy: boolean;
  onOutcome: (value: string) => void;
  onNote: (value: string) => void;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-slate-800 bg-[#07111f] text-slate-100">
        <DialogHeader>
          <DialogTitle>Resolver handoff</DialogTitle>
          <DialogDescription>
            {item ? `${item.customer_name} · requiere outcome operativo` : "Cierra el caso"}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Select value={outcome} onValueChange={onOutcome}>
            <SelectTrigger className="border-slate-700 bg-slate-950 text-slate-100">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="border-slate-700 bg-slate-950 text-slate-100">
              {RESOLUTION_OUTCOMES.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Textarea
            value={note}
            onChange={(event) => onNote(event.target.value)}
            placeholder="Nota del agente..."
            className="min-h-28 border-slate-700 bg-slate-950 text-slate-100"
          />
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            className="border-slate-700 bg-slate-950"
            onClick={() => onOpenChange(false)}
          >
            Cancelar
          </Button>
          <Button
            className="bg-emerald-600 hover:bg-emerald-500"
            disabled={busy || !outcome}
            onClick={onConfirm}
          >
            <CheckCircle2 className="h-4 w-4" />
            Resolver
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReplyDraftModal({
  open,
  item,
  draft,
  context,
  busy,
  onContext,
  onRegenerate,
  onOpenChange,
}: {
  open: boolean;
  item: HandoffCommandItem | null;
  draft: DraftResponse | null;
  context: string;
  busy: boolean;
  onContext: (value: string) => void;
  onRegenerate: () => void;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-slate-800 bg-[#07111f] text-slate-100 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Borrador de respuesta</DialogTitle>
          <DialogDescription>
            {item ? `${item.customer_name} · revisar antes de enviar` : "Draft seguro"}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Textarea
            value={draft?.draft ?? item?.suggested_reply ?? ""}
            readOnly
            className="min-h-36 border-violet-500/30 bg-violet-500/10 text-slate-100"
          />
          <Textarea
            value={context}
            onChange={(event) => onContext(event.target.value)}
            placeholder="Contexto adicional para regenerar..."
            className="min-h-20 border-slate-700 bg-slate-950 text-slate-100"
          />
          {draft?.safety_notes && (
            <div className="rounded-md border border-slate-800 bg-slate-950/70 p-3 text-xs text-slate-400">
              {draft.safety_notes.map((note) => (
                <div key={note}>• {note}</div>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            className="border-slate-700 bg-slate-950"
            disabled={busy}
            onClick={onRegenerate}
          >
            <RefreshCw className="h-4 w-4" />
            Regenerar
          </Button>
          <Button
            className="bg-violet-600 hover:bg-violet-500"
            onClick={() => {
              toast.success("Borrador listo para copiar al composer humano");
              onOpenChange(false);
            }}
          >
            <SendHorizonal className="h-4 w-4" />
            Usar borrador
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="grid min-h-48 place-items-center p-8 text-center">
      <div>
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-lg border border-slate-800 bg-slate-950 text-slate-400">
          <PauseCircle className="h-5 w-5" />
        </div>
        <div className="mt-3 text-sm font-semibold text-slate-100">{title}</div>
        <div className="mt-1 max-w-md text-sm text-slate-500">{detail}</div>
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        {SUMMARY_SKELETON_KEYS.map((key) => (
          <Skeleton key={key} className="h-24 rounded-lg bg-slate-800" />
        ))}
      </div>
      <Skeleton className="h-14 rounded-lg bg-slate-800" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-2">
          {ROW_SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-36 rounded-lg bg-slate-800" />
          ))}
        </div>
        <Skeleton className="h-[620px] rounded-lg bg-slate-800" />
      </div>
    </div>
  );
}

function insightTone(tone: InsightCard["tone"]) {
  if (tone === "critical") return "border-red-500/30 bg-red-500/10 text-red-200";
  if (tone === "warning") return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  if (tone === "good") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
  return "border-cyan-500/30 bg-cyan-500/10 text-cyan-200";
}

function severityTone(severity: RiskRadarItem["severity"]) {
  if (severity === "critical") return "border-red-500/30 bg-red-500/10 text-red-200";
  if (severity === "high") return "border-orange-500/30 bg-orange-500/10 text-orange-200";
  if (severity === "medium") return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  return "border-cyan-500/30 bg-cyan-500/10 text-cyan-200";
}

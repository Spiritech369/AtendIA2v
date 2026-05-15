import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Archive,
  Bell,
  Bookmark,
  Bot,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  FileWarning,
  FolderOpen,
  Gauge,
  GitBranch,
  HeartPulse,
  Import,
  LayoutGrid,
  ListFilter,
  MessageCircle,
  MoreVertical,
  PauseCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Trash2,
  UserRoundCog,
  Workflow,
  X,
  Zap,
  ZapOff,
} from "lucide-react";
import { type ChangeEvent, type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  type SimulationResult,
  type WorkflowExecution,
  type WorkflowItem,
  type WorkflowMetrics,
  type WorkflowNode,
  workflowsApi,
} from "@/features/workflows/api";
import { cn } from "@/lib/utils";
import { NextBestFixPanel } from "./NextBestFixPanel";
import { WorkflowEditor } from "./WorkflowEditor";

type ContextAction = { label: string; action: () => void; danger?: boolean };

type ContextState = {
  x: number;
  y: number;
  actions: ContextAction[];
} | null;

const STATUS_STYLES: Record<string, { label: string; border: string; text: string; bg: string }> = {
  healthy: {
    label: "Saludable",
    border: "border-emerald-400/60",
    text: "text-emerald-300",
    bg: "bg-emerald-500/10",
  },
  warning: {
    label: "Revisión",
    border: "border-amber-400/60",
    text: "text-amber-300",
    bg: "bg-amber-500/10",
  },
  critical: {
    label: "Crítico",
    border: "border-red-400/60",
    text: "text-red-300",
    bg: "bg-red-500/10",
  },
  inactive: {
    label: "Pausado",
    border: "border-slate-500/50",
    text: "text-slate-400",
    bg: "bg-white/5",
  },
  archived: {
    label: "Archivado",
    border: "border-slate-500/50",
    text: "text-slate-400",
    bg: "bg-white/5",
  },
};

const DEFAULT_STATUS_STYLE = {
  label: "Pausado",
  border: "border-slate-500/50",
  text: "text-slate-400",
  bg: "bg-white/5",
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-MX").format(value);
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency: "MXN",
    maximumFractionDigits: 0,
  }).format(value);
}

function duration(seconds: number | null) {
  if (!seconds) return "—";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function Sparkline({ values, color = "#60a5fa" }: { values: number[]; color?: string }) {
  const hasData = values.some((value) => value > 0);
  if (!hasData) {
    return (
      <svg width="78" height="28" viewBox="0 0 78 28" aria-hidden>
        <line
          x1="2"
          x2="76"
          y1="22"
          y2="22"
          stroke="rgba(148,163,184,0.35)"
          strokeWidth="1.2"
          strokeDasharray="3 3"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  const max = Math.max(...values, 1);
  const points = values
    .map(
      (value, index) =>
        `${(index / Math.max(1, values.length - 1)) * 78},${26 - (value / max) * 22}`,
    )
    .join(" ");
  return (
    <svg width="78" height="28" viewBox="0 0 78 28" aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ContextMenu({ menu, onClose }: { menu: ContextState; onClose: () => void }) {
  if (!menu) return null;
  return (
    <div
      className="fixed z-[80] w-56 rounded-md border border-white/10 bg-[#101b27] p-1 text-xs text-slate-200 shadow-2xl"
      style={{ left: menu.x, top: menu.y }}
      onMouseLeave={onClose}
    >
      {menu.actions.map((item) => (
        <button
          key={item.label}
          type="button"
          className={cn(
            "flex w-full items-center rounded px-2 py-1.5 text-left hover:bg-white/10",
            item.danger && "text-red-300 hover:bg-red-500/10",
          )}
          onClick={() => {
            item.action();
            onClose();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function KpiCard({
  label,
  value,
  delta,
  status,
  values,
  onClick,
}: {
  label: string;
  value: string;
  delta: string;
  status: "ok" | "warn" | "critical" | "info";
  values: number[];
  onClick: () => void;
}) {
  const color =
    status === "ok"
      ? "#34d399"
      : status === "warn"
        ? "#fbbf24"
        : status === "critical"
          ? "#f87171"
          : "#60a5fa";
  return (
    <button
      type="button"
      onClick={onClick}
      className="min-w-[150px] flex-1 rounded-md border border-white/10 bg-[#101b27] px-3 py-2 text-left hover:border-blue-400/40"
    >
      <div className="flex items-center justify-between text-[11px] text-slate-400">
        <span>{label}</span>
        <Gauge className="h-3.5 w-3.5" style={{ color }} />
      </div>
      <div className="mt-1 flex items-end justify-between">
        <span className="text-xl font-semibold text-slate-100">{value}</span>
        <Sparkline values={values} color={color} />
      </div>
      <p className="mt-1 text-[10px]" style={{ color }}>
        {delta}
      </p>
    </button>
  );
}

function WorkflowCard({
  workflow,
  selected,
  onSelect,
  onAction,
  onContextMenu,
}: {
  workflow: WorkflowItem;
  selected: boolean;
  onSelect: () => void;
  onAction: (action: string, workflow: WorkflowItem) => void;
  onContextMenu: (event: MouseEvent, actions: ContextAction[]) => void;
}) {
  const style = STATUS_STYLES[workflow.health.status] ?? DEFAULT_STATUS_STYLE;
  const actions: ContextAction[] = [
    { label: "Editar", action: onSelect },
    { label: "Probar", action: () => onAction("simulate", workflow) },
    { label: "Ver ejecuciones", action: () => onAction("executions", workflow) },
    { label: "Duplicar", action: () => onAction("duplicate", workflow) },
    { label: "Comparar versiones", action: () => onAction("compare", workflow) },
    { label: "Restaurar versión", action: () => onAction("restore", workflow) },
    { label: "Pausar seguro", action: () => onAction("safePause", workflow) },
    { label: "Exportar JSON", action: () => onAction("export", workflow) },
    { label: "Archivar", action: () => onAction("archive", workflow) },
    {
      label: workflow.active ? "Desactivar" : "Activar",
      action: () => onAction("toggle", workflow),
    },
    { label: "Eliminar", action: () => onAction("delete", workflow), danger: true },
  ];
  return (
    <article
      className={cn(
        "rounded-md border bg-[#101b27] p-2 transition hover:bg-[#132333]",
        style.border,
        selected && "ring-1 ring-blue-400/70",
      )}
      onClick={onSelect}
      onContextMenu={(event) => onContextMenu(event, actions)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("grid h-7 w-7 place-items-center rounded", style.bg)}>
              <Zap className={cn("h-4 w-4", style.text)} />
            </span>
            <div className="min-w-0">
              <h3 className="truncate text-xs font-semibold text-slate-100">{workflow.name}</h3>
              <p className="text-[10px] text-slate-400">
                {workflow.description ?? "Mensaje entrante"}
              </p>
            </div>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-slate-300"
              onClick={(event) => event.stopPropagation()}
            >
              <MoreVertical className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {actions.map((item, index) => (
              <div key={item.label}>
                {index === 8 && <DropdownMenuSeparator />}
                <DropdownMenuItem
                  className={item.danger ? "text-destructive focus:text-destructive" : undefined}
                  onClick={item.action}
                >
                  {item.label}
                </DropdownMenuItem>
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="mt-3 grid grid-cols-[1fr_auto] items-end gap-2">
        <div>
          <p className="text-[10px] text-slate-400">Health Score</p>
          <p className={cn("text-3xl font-semibold", style.text)}>{workflow.health.score}</p>
        </div>
        <Sparkline
          values={workflow.metrics.sparkline}
          color={
            workflow.health.status === "critical"
              ? "#f87171"
              : workflow.health.status === "warning"
                ? "#fbbf24"
                : "#34d399"
          }
        />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
        <span>
          <b className="block text-slate-200">{workflow.metrics.executions_today}</b>
          <span className="text-slate-500">Ejec. hoy</span>
        </span>
        <span>
          <b className="block text-slate-200">{workflow.metrics.success_rate}%</b>
          <span className="text-slate-500">Éxito</span>
        </span>
        <span>
          <b
            className={cn(
              "block",
              workflow.metrics.failure_rate > 15 ? "text-red-300" : "text-slate-200",
            )}
          >
            {workflow.metrics.failure_rate}%
          </b>
          <span className="text-slate-500">Fallo</span>
        </span>
      </div>
      <p className="mt-2 truncate text-[10px] text-slate-500">{workflow.health.reasons[0]}</p>
    </article>
  );
}

function ExecutionsPanel({
  workflow,
  executions,
  selectedExecution,
  onSelectExecution,
  onContextMenu,
  nodeFilter,
  onClearNodeFilter,
}: {
  workflow: WorkflowItem | null;
  executions: WorkflowExecution[];
  selectedExecution: WorkflowExecution | null;
  onSelectExecution: (execution: WorkflowExecution | null) => void;
  onContextMenu: (event: MouseEvent, actions: ContextAction[]) => void;
  nodeFilter?: string | null;
  onClearNodeFilter?: () => void;
}) {
  const nodeFilterLabel = nodeFilter
    ? (workflow?.definition.nodes.find((n) => n.id === nodeFilter)?.title ?? nodeFilter)
    : null;
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: (execution: WorkflowExecution) =>
      workflowsApi.retryExecutionFromNode(
        execution.id,
        execution.failed_node ?? execution.current_node_id ?? "trigger_1",
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflows", workflow?.id, "executions"] });
      toast.success("Ejecución reintentada");
    },
    onError: (error) => toast.error("No se pudo reintentar", { description: error.message }),
  });

  const copyJson = async (execution: WorkflowExecution) => {
    await navigator.clipboard.writeText(JSON.stringify(execution, null, 2));
    toast.success("JSON copiado");
  };

  const rowActions = (execution: WorkflowExecution): ContextAction[] => [
    { label: "Reproducir ejecución", action: () => onSelectExecution(execution) },
    { label: "Reintentar desde fallo", action: () => retry.mutate(execution) },
    {
      label: "Abrir lead",
      action: () => toast.info(`Abriendo lead ${execution.lead_name ?? "sin nombre"}`),
    },
    { label: "Copiar JSON", action: () => void copyJson(execution) },
    {
      label: "Copiar execution ID",
      action: () => void navigator.clipboard.writeText(execution.id),
    },
    { label: "Exportar JSON", action: () => void copyJson(execution) },
  ];

  return (
    <aside className="flex min-h-0 w-[330px] flex-col border border-white/10 bg-[#0d1822]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Ejecuciones recientes</h2>
          <p className="text-[10px] text-slate-400">
            {workflow ? workflow.name : "Sin workflow seleccionado"}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-slate-400"
          onClick={() => onSelectExecution(null)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      {nodeFilterLabel && (
        <div className="flex items-center gap-1 border-b border-white/10 bg-blue-500/10 px-3 py-1 text-[10px] text-blue-200">
          <span className="truncate">Filtrando por nodo: {nodeFilterLabel}</span>
          <button
            type="button"
            className="ml-auto rounded px-1 text-[10px] text-blue-100 underline-offset-2 hover:underline"
            onClick={onClearNodeFilter}
          >
            limpiar
          </button>
        </div>
      )}
      <div className="grid grid-cols-[18px_1fr_54px_48px] border-b border-white/10 px-3 py-1.5 text-[10px] text-slate-500">
        <span />
        <span>Lead</span>
        <span>Inicio</span>
        <span>Resultado</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {executions.map((execution) => {
          const failed = execution.status === "failed";
          return (
            <button
              key={execution.id}
              type="button"
              onClick={() => onSelectExecution(execution)}
              onContextMenu={(event) => onContextMenu(event, rowActions(execution))}
              className={cn(
                "grid w-full grid-cols-[18px_1fr_54px_48px] items-center border-b border-white/5 px-3 py-2 text-left text-[11px] hover:bg-white/5",
                selectedExecution?.id === execution.id && "bg-blue-500/10",
              )}
            >
              <span
                className={cn("h-2 w-2 rounded-full", failed ? "bg-red-400" : "bg-emerald-400")}
              />
              <span className="min-w-0">
                <span className="block truncate text-slate-200">{execution.lead_name}</span>
                <span className="block truncate text-[10px] text-slate-500">
                  {execution.failed_node ?? "—"}
                </span>
              </span>
              <span className="text-slate-400">
                {new Date(execution.started_at).toLocaleTimeString("es-MX", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className={failed ? "text-red-300" : "text-emerald-300"}>
                {execution.result}
              </span>
            </button>
          );
        })}
      </div>
      {selectedExecution && (
        <div className="border-t border-white/10 p-3">
          <Tabs defaultValue="detalles">
            <TabsList className="h-8 bg-white/5">
              <TabsTrigger value="detalles" className="text-[10px]">
                Detalles
              </TabsTrigger>
              <TabsTrigger value="entrada" className="text-[10px]">
                Entrada JSON
              </TabsTrigger>
              <TabsTrigger value="salida" className="text-[10px]">
                Salida JSON
              </TabsTrigger>
              <TabsTrigger value="replay" className="text-[10px]">
                Replay
              </TabsTrigger>
            </TabsList>
            <TabsContent value="detalles" className="mt-2 space-y-1 text-[11px] text-slate-300">
              <p>
                <span className="text-slate-500">ID:</span>{" "}
                <span className="font-mono text-[10px]">{selectedExecution.id.slice(0, 18)}…</span>
              </p>
              <p>
                <span className="text-slate-500">Lead:</span> {selectedExecution.lead_name} |{" "}
                {selectedExecution.lead_phone}
              </p>
              <p>
                <span className="text-slate-500">Duración:</span>{" "}
                {duration(selectedExecution.duration_seconds)}
              </p>
              {selectedExecution.error && (
                <p className="rounded border border-red-400/30 bg-red-500/10 p-2 text-red-200">
                  {selectedExecution.error}
                </p>
              )}
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Button
                  size="sm"
                  className="h-7 text-[11px]"
                  onClick={() => onSelectExecution(selectedExecution)}
                >
                  <Play className="mr-1 h-3 w-3" /> Reproducir
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 border-red-400/40 bg-red-500/10 text-[11px] text-red-200"
                  onClick={() => retry.mutate(selectedExecution)}
                >
                  <RotateCcw className="mr-1 h-3 w-3" /> Reintentar
                </Button>
              </div>
            </TabsContent>
            <TabsContent value="entrada" className="mt-2">
              <pre className="max-h-40 overflow-auto rounded bg-black/25 p-2 text-[10px] text-slate-300">
                {JSON.stringify(selectedExecution.input_json, null, 2)}
              </pre>
            </TabsContent>
            <TabsContent value="salida" className="mt-2">
              <pre className="max-h-40 overflow-auto rounded bg-black/25 p-2 text-[10px] text-slate-300">
                {JSON.stringify(selectedExecution.output_json, null, 2)}
              </pre>
            </TabsContent>
            <TabsContent value="replay" className="mt-2 space-y-2">
              {selectedExecution.replay.map((step) => (
                <div key={`${step.node_id}-${step.time}`} className="flex gap-2 text-[11px]">
                  <span
                    className={cn(
                      "mt-1 h-2 w-2 rounded-full",
                      step.status === "error" ? "bg-red-400" : "bg-emerald-400",
                    )}
                  />
                  <span>
                    <span className="block text-slate-200">{step.label}</span>
                    <span className="text-slate-500">{step.detail}</span>
                  </span>
                </div>
              ))}
            </TabsContent>
          </Tabs>
        </div>
      )}
    </aside>
  );
}

function SimulatorPanel({ workflow }: { workflow: WorkflowItem | null }) {
  const [message, setMessage] = useState("Quiero una moto, gano por nómina");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const simulate = useMutation({
    mutationFn: () =>
      workflow
        ? workflowsApi.simulate(workflow.id, { incoming_message: message, version: "draft" })
        : Promise.reject(new Error("Selecciona un workflow")),
    onSuccess: (data) => {
      setResult(data);
      toast.success("Simulación ejecutada");
    },
    onError: (error) => toast.error("No se pudo simular", { description: error.message }),
  });
  return (
    <section className="flex min-h-0 flex-col rounded-md border border-blue-400/40 bg-[#0d1822]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <h3 className="text-xs font-semibold text-slate-100">Probar workflow antes de publicar</h3>
        <Play className="h-3.5 w-3.5 text-blue-300" />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[210px_1fr] gap-3 p-3">
        <div className="space-y-2">
          <select
            className="h-8 w-full rounded border border-white/10 bg-white/5 px-2 text-xs text-slate-200"
            defaultValue="juan"
          >
            <option value="juan">Juan Pérez | 5512345678</option>
            <option value="maria">María López | 5587654321</option>
          </select>
          <Textarea
            className="h-20 resize-none border-white/10 bg-black/20 text-xs text-slate-100"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
          />
          <Button
            className="h-8 w-full text-xs"
            onClick={() => simulate.mutate()}
            disabled={!workflow || simulate.isPending}
          >
            Ejecutar simulación
          </Button>
        </div>
        <div className="min-h-0 overflow-auto text-[11px]">
          {result ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                {result.activated_nodes.map((node) => (
                  <p key={node} className="text-emerald-300">
                    ✓ Nodo activado: {node}
                  </p>
                ))}
                {result.warnings.map((warning) => (
                  <p key={warning} className="text-amber-300">
                    ⚠ {warning}
                  </p>
                ))}
                {result.errors.map((error) => (
                  <p key={error} className="text-red-300">
                    ✕ {error}
                  </p>
                ))}
              </div>
              <div className="rounded bg-white/5 p-2 text-slate-200">
                <p className="mb-1 text-slate-500">Respuesta generada</p>
                <p>{result.generated_response}</p>
                <pre className="mt-2 overflow-auto text-[10px] text-slate-400">
                  {JSON.stringify(result.variables_saved, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-slate-500">
              Ejecuta una simulación para ver nodos, variables y diferencias draft vs publicado.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function VariablesPanel({ workflow }: { workflow: WorkflowItem | null }) {
  return (
    <section className="min-h-0 rounded-md border border-white/10 bg-[#0d1822]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <h3 className="text-xs font-semibold text-slate-100">Variables y dependencias</h3>
        <GitBranch className="h-3.5 w-3.5 text-blue-300" />
      </div>
      <Tabs defaultValue="variables" className="h-[calc(100%-37px)]">
        <TabsList className="mx-3 mt-2 h-7 bg-white/5">
          <TabsTrigger value="variables" className="text-[10px]">
            Variables
          </TabsTrigger>
          <TabsTrigger value="dependencias" className="text-[10px]">
            Dependencias
          </TabsTrigger>
        </TabsList>
        <TabsContent value="variables" className="mt-2 max-h-52 overflow-auto px-3">
          <table className="w-full text-left text-[11px]">
            <thead className="text-slate-500">
              <tr>
                <th>Variable</th>
                <th>Usada en</th>
                <th>Último valor</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {(workflow?.variables ?? []).map((variable) => (
                <tr key={variable.name} className="border-t border-white/5">
                  <td className="py-1 text-slate-200">{variable.name}</td>
                  <td className="text-slate-400">{variable.used_in.join(", ")}</td>
                  <td className="text-slate-400">{variable.last_value ?? "—"}</td>
                  <td
                    className={
                      variable.status === "ok"
                        ? "text-emerald-300"
                        : variable.status === "faltante"
                          ? "text-amber-300"
                          : "text-red-300"
                    }
                  >
                    {variable.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TabsContent>
        <TabsContent value="dependencias" className="mt-2 max-h-52 overflow-auto px-3">
          {(workflow?.dependencies ?? []).map((dependency) => (
            <div
              key={`${dependency.type}-${dependency.name}`}
              className="flex items-center justify-between border-t border-white/5 py-1.5 text-[11px]"
            >
              <span>
                <span className="text-slate-500">{dependency.type}</span>{" "}
                <span className="text-slate-200">{dependency.name}</span>
              </span>
              <span
                className={
                  dependency.status === "ok"
                    ? "text-emerald-300"
                    : dependency.status === "warning"
                      ? "text-amber-300"
                      : "text-red-300"
                }
              >
                {dependency.status}
              </span>
            </div>
          ))}
        </TabsContent>
      </Tabs>
    </section>
  );
}

function ValidationPanel({ workflow }: { workflow: WorkflowItem | null }) {
  const validation = workflow?.validation;
  const blocked = validation?.status === "blocked";
  return (
    <section className="min-h-0 rounded-md border border-white/10 bg-[#0d1822]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <h3 className="text-xs font-semibold text-slate-100">Validación antes de publicar</h3>
        <FileWarning className={cn("h-3.5 w-3.5", blocked ? "text-red-300" : "text-emerald-300")} />
      </div>
      <div className="max-h-64 overflow-auto p-3 text-[11px]">
        {(validation?.checks ?? []).map((check) => (
          <div key={check.label} className="mb-1 flex items-center justify-between">
            <span className="text-slate-300">{check.label}</span>
            <span
              className={
                check.status === "ok"
                  ? "text-emerald-300"
                  : check.status === "warning"
                    ? "text-amber-300"
                    : "text-red-300"
              }
            >
              {check.status}
            </span>
          </div>
        ))}
        <div
          className={cn(
            "mt-3 rounded-md border p-3 text-center",
            blocked
              ? "border-red-400/40 bg-red-500/10 text-red-200"
              : "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
          )}
        >
          <AlertCircle className="mx-auto mb-1 h-5 w-5" />
          <p className="font-semibold">{validation?.summary ?? "Sin validación"}</p>
          {validation && (
            <p className="text-[10px]">
              {validation.critical_count} críticos | {validation.warning_count} advertencias
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

type PauseMode = "immediate" | "new_leads" | "after_active" | "handoff_human";

function SafetyPanel({
  workflow,
  onToggle,
  onPause,
  pausing,
}: {
  workflow: WorkflowItem | null;
  onToggle: (key: string) => void;
  onPause: (mode: PauseMode) => void;
  pausing: boolean;
}) {
  const labels: Record<string, string> = {
    business_hours: "Respetar horario laboral",
    max_3_messages_24h: "Máximo 3 mensajes automáticos en 24h",
    dedupe_template: "No repetir misma plantilla",
    stop_on_no: 'Detener si el cliente dice "no"',
    stop_on_human: "Detener si pide humano",
    stop_on_frustration: "Detener si se detecta frustración",
    pause_on_critical: "Pausar si hay error crítico",
  };
  // The 4 modes map 1:1 to backend endpoints: /pause (immediate) and
  // /safe-pause with mode in {new_leads, after_active, handoff_human}.
  const pauseModes: Array<{
    mode: PauseMode;
    label: string;
    icon: typeof PauseCircle;
    tone: string;
  }> = [
    {
      mode: "immediate",
      label: "Pausar inmediatamente",
      icon: ZapOff,
      tone: "text-red-200 hover:bg-red-500/10 border-red-500/20",
    },
    {
      mode: "new_leads",
      label: "Pausar solo nuevos leads",
      icon: PauseCircle,
      tone: "text-amber-200 hover:bg-amber-500/10 border-amber-500/20",
    },
    {
      mode: "after_active",
      label: "Pausar después de ejecuciones activas",
      icon: PauseCircle,
      tone: "text-slate-200 hover:bg-white/10 border-white/15",
    },
    {
      mode: "handoff_human",
      label: "Pausar y enviar a humano",
      icon: UserRoundCog,
      tone: "text-violet-200 hover:bg-violet-500/10 border-violet-500/20",
    },
  ];
  const disabled = !workflow || pausing;
  return (
    <section className="rounded-md border border-white/10 bg-[#0d1822]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <h3 className="text-xs font-semibold text-slate-100">Seguridad y anti-spam</h3>
        <ShieldCheck className="h-3.5 w-3.5 text-blue-300" />
      </div>
      <div className="space-y-2 p-3 text-[11px] text-slate-300">
        {Object.entries(labels).map(([key, label]) => {
          const enabled = Boolean(workflow?.safety_rules[key]);
          return (
            <button
              key={key}
              type="button"
              className="flex w-full items-center justify-between"
              onClick={() => onToggle(key)}
            >
              <span>{label}</span>
              <span
                className={cn(
                  "h-4 w-8 rounded-full p-0.5 transition",
                  enabled ? "bg-blue-500" : "bg-white/15",
                )}
              >
                <span
                  className={cn(
                    "block h-3 w-3 rounded-full bg-white transition",
                    enabled && "translate-x-4",
                  )}
                />
              </span>
            </button>
          );
        })}
        <div className="mt-2 flex flex-col gap-1.5">
          {pauseModes.map(({ mode, label, icon: Icon, tone }) => (
            <button
              key={mode}
              type="button"
              disabled={disabled}
              onClick={() => onPause(mode)}
              className={cn(
                "flex items-center gap-1.5 rounded-md border bg-[#0d1822] px-2 py-1.5 text-left text-[11px] transition",
                tone,
                disabled && "cursor-not-allowed opacity-50",
              )}
              title={!workflow ? "Selecciona un workflow primero" : `Modo: ${mode}`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="flex-1">{label}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

// Saved-view persistence key. Keeps the operator's last search + selection
// so refreshing the page or coming back later doesn't make them re-find
// the workflow they were working on. Only stores trivial UI state — no
// secrets, no PII, no remote sync.
const SAVED_VIEW_KEY = "workflows:saved-view-v1";

type SavedView = { search: string; selectedId: string | null };

export function WorkflowsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [savedView, setSavedView] = useState<SavedView | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem(SAVED_VIEW_KEY);
      return raw ? (JSON.parse(raw) as SavedView) : null;
    } catch {
      // Corrupt JSON — discard silently, the user can re-save.
      return null;
    }
  });
  const [selectedExecution, setSelectedExecution] = useState<WorkflowExecution | null>(null);
  const [menu, setMenu] = useState<ContextState>(null);
  const [simOpen, setSimOpen] = useState(false);
  const [executionNodeFilter, setExecutionNodeFilter] = useState<string | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);

  const workflowsQuery = useQuery({
    queryKey: ["workflows"],
    queryFn: workflowsApi.list,
    refetchInterval: 15_000,
  });
  const workflows = workflowsQuery.data ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return workflows;
    return workflows.filter((workflow) =>
      `${workflow.name} ${workflow.description ?? ""}`.toLowerCase().includes(q),
    );
  }, [search, workflows]);
  const selected = filtered.find((workflow) => workflow.id === selectedId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!selectedId && workflows[0]) setSelectedId(workflows[0].id);
  }, [selectedId, workflows]);

  const executionsQuery = useQuery({
    queryKey: ["workflows", selected?.id, "executions"],
    queryFn: () => (selected ? workflowsApi.executions(selected.id) : Promise.resolve([])),
    refetchInterval: 10_000,
  });
  const allExecutions = executionsQuery.data ?? [];
  const executions = useMemo(() => {
    if (!executionNodeFilter) return allExecutions;
    return allExecutions.filter(
      (execution) =>
        execution.replay?.some((step) => step.node_id === executionNodeFilter) ||
        execution.current_node_id === executionNodeFilter ||
        execution.failed_node === executionNodeFilter,
    );
  }, [allExecutions, executionNodeFilter]);

  // Drop the node filter the moment the operator switches workflows so the
  // filter doesn't quietly hide every execution under a different graph.
  useEffect(() => {
    setExecutionNodeFilter(null);
  }, [selected?.id]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["workflows"] });

  const create = useMutation({
    mutationFn: () =>
      workflowsApi.create({
        name: "Nuevo workflow",
        description: "Mensaje entrante",
        trigger_type: "message_received",
        trigger_config: {},
        definition: {
          nodes: [
            {
              id: "trigger_1",
              type: "trigger",
              title: "Disparador: Mensaje entrante",
              config: { event: "message_received" },
            },
            {
              id: "n1",
              type: "template_message",
              title: "Enviar mensaje WhatsApp",
              config: { template: "bienvenida_v3", text: "Hola {{nombre}}, ¿cómo te ayudo?" },
            },
            { id: "n2", type: "end", title: "Finalizar workflow", config: { result: "nuevo" } },
          ],
          edges: [
            { from: "trigger_1", to: "n1" },
            { from: "n1", to: "n2" },
          ],
        },
        active: false,
      }),
    onSuccess: (workflow) => {
      void invalidate();
      setSelectedId(workflow.id);
      toast.success("Workflow creado");
    },
  });

  const duplicate = useMutation({
    mutationFn: (id: string) => workflowsApi.duplicate(id),
    onSuccess: (workflow) => {
      void invalidate();
      setSelectedId(workflow.id);
      toast.success("Workflow duplicado");
    },
  });
  const archive = useMutation({
    mutationFn: (id: string) => workflowsApi.archive(id),
    onSuccess: () => {
      void invalidate();
      toast.success("Workflow archivado");
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => workflowsApi.delete(id),
    onSuccess: () => {
      void invalidate();
      setSelectedId(null);
      toast.success("Workflow eliminado");
    },
  });
  const toggle = useMutation({
    mutationFn: (workflow: WorkflowItem) =>
      workflow.active ? workflowsApi.deactivate(workflow.id) : workflowsApi.activate(workflow.id),
    onSuccess: () => {
      void invalidate();
      toast.success("Estado actualizado");
    },
    onError: (error) => toast.error("No se pudo activar", { description: error.message }),
  });
  const safePause = useMutation({
    mutationFn: (id: string) => workflowsApi.safePause(id, "new_leads"),
    onSuccess: () => {
      void invalidate();
      toast.success("Pausa segura activada");
    },
  });
  // Generic pause mutation used by SafetyPanel's 4 mode buttons. `mode="immediate"`
  // hits /pause (no body); the other 3 modes hit /safe-pause with mode in the body.
  const pauseControl = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: PauseMode }) =>
      mode === "immediate" ? workflowsApi.pause(id) : workflowsApi.safePause(id, mode),
    onSuccess: (_data, vars) => {
      void invalidate();
      const friendly: Record<PauseMode, string> = {
        immediate: "Pausa inmediata aplicada",
        new_leads: "Sólo nuevos leads en pausa",
        after_active: "Pausará al terminar ejecuciones activas",
        handoff_human: "Pausa con derivación a humano activada",
      };
      toast.success(friendly[vars.mode]);
    },
    onError: (error) => toast.error("No se pudo pausar", { description: error.message }),
  });

  const patchWorkflow = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<WorkflowItem> }) =>
      workflowsApi.patch(id, body),
    onSuccess: () => {
      void invalidate();
      toast.success("Configuración actualizada");
    },
    onError: (error) => toast.error("No se pudo guardar", { description: error.message }),
  });

  const openContextMenu = (event: MouseEvent, actions: ContextAction[]) => {
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, actions });
  };

  const saveCurrentView = () => {
    const view: SavedView = { search, selectedId };
    try {
      window.localStorage.setItem(SAVED_VIEW_KEY, JSON.stringify(view));
      setSavedView(view);
      toast.success("Vista guardada", {
        description: search ? `Búsqueda: "${search}"` : "Sin filtro de búsqueda",
      });
    } catch {
      toast.error("No se pudo guardar la vista (almacenamiento bloqueado)");
    }
  };

  const restoreSavedView = () => {
    if (!savedView) {
      toast.info("Aún no hay vista guardada", {
        description: "Guarda una primero para poder restaurarla.",
      });
      return;
    }
    setSearch(savedView.search);
    if (savedView.selectedId) setSelectedId(savedView.selectedId);
    toast.success("Vista restaurada");
  };

  const clearSavedView = () => {
    try {
      window.localStorage.removeItem(SAVED_VIEW_KEY);
    } catch {
      // best effort
    }
    setSavedView(null);
    toast.success("Vista borrada");
  };

  // JSON import. Caps and strip rules mirror the respond.io contract:
  //   - File must be JSON, ≤ 400 KB, ≤ 100 nodes / 150 edges.
  //   - Must have name + trigger_type.
  //   - `id`, `tenant_id`, timestamps, metrics, validation are NEVER trusted
  //     from the file — server-assigned.
  //   - Name collisions get auto-numbered: "Foo" → "Foo (2)" → "Foo (3)".
  //   - We strip references the current workspace can't resolve (agent_id /
  //     pool / stage_id / workflow_id / user_id) and tell the operator what
  //     was dropped via a validation toast.
  const onPickJsonFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 400 * 1024) {
      toast.error("Archivo demasiado grande", { description: "Máximo 400 KB." });
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => toast.error("No se pudo leer el archivo");
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result ?? "")) as Partial<WorkflowItem>;
        if (!parsed.name || !parsed.trigger_type) {
          toast.error("JSON inválido", { description: "Falta `name` o `trigger_type`." });
          return;
        }
        const definition = parsed.definition ?? { nodes: [], edges: [] };
        const nodes = Array.isArray(definition.nodes) ? definition.nodes : [];
        const edges = Array.isArray(definition.edges) ? definition.edges : [];
        if (nodes.length > 100) {
          toast.error("Workflow excede el límite", {
            description: `${nodes.length} nodos (máx 100).`,
          });
          return;
        }
        if (edges.length > 150) {
          toast.error("Workflow excede el límite", {
            description: `${edges.length} aristas (máx 150).`,
          });
          return;
        }
        if (!nodes.length) {
          toast.error("JSON inválido", { description: "El workflow no tiene nodos." });
          return;
        }

        const stripped: string[] = [];
        const knownAgentIds = new Set<string>();
        // We don't have a tenant-scoped agent/pool/stage list here; the
        // backend will validate references when the operator activates the
        // workflow. What we *can* do now is wipe foreign IDs (UUID-looking
        // strings) and let the operator re-select via the typed pickers,
        // because importing across tenants almost always means the IDs are
        // stale. The heuristic is: strip any `agent_id`/`user_id`/`pool`/
        // `workflow_id`/`stage_id` whose value doesn't appear in this
        // tenant's known list. For now, with no known list, we just blank
        // them and report.
        const sanitizedNodes = nodes.map((node) => {
          if (!node || typeof node !== "object") return node;
          const cfg = (node as { config?: Record<string, unknown> }).config ?? {};
          const out: Record<string, unknown> = { ...cfg };
          for (const key of ["agent_id", "user_id", "pool", "stage_id", "workflow_id"]) {
            if (typeof out[key] === "string" && (out[key] as string).length > 0) {
              stripped.push(`${(node as { id?: string }).id ?? "?"}.${key}`);
              out[key] = "";
            }
          }
          if (
            knownAgentIds.size &&
            typeof out.agent_id === "string" &&
            knownAgentIds.has(out.agent_id)
          ) {
            // (placeholder — currently unreachable; kept so the audit branch
            // works once we wire a tenant agent list into this page).
          }
          return { ...(node as object), config: out };
        });

        // Name-collision numbering. We only see workflows the current tenant
        // can list, so this is safe to dedupe locally before the POST.
        const existingNames = new Set(workflows.map((w) => w.name));
        let candidate = parsed.name;
        if (existingNames.has(candidate)) {
          let n = 2;
          while (existingNames.has(`${parsed.name} (${n})`)) n++;
          candidate = `${parsed.name} (${n})`;
        }

        const body: Partial<WorkflowItem> = {
          name: candidate,
          description: parsed.description,
          trigger_type: parsed.trigger_type,
          trigger_config: parsed.trigger_config ?? {},
          definition: { nodes: sanitizedNodes as WorkflowNode[], edges, ops: definition.ops },
          active: false,
        };
        workflowsApi
          .create(body)
          .then((workflow) => {
            void invalidate();
            setSelectedId(workflow.id);
            const renamed = candidate !== parsed.name;
            const lines = [
              `"${workflow.name}" creado en borrador.`,
              renamed ? `Renombrado para evitar colisión.` : null,
              stripped.length
                ? `${stripped.length} referencias limpiadas — vuelve a seleccionarlas.`
                : null,
            ].filter(Boolean) as string[];
            toast.success("Workflow importado", { description: lines.join(" ") });
          })
          .catch((error) =>
            toast.error("Importación rechazada", { description: error?.message ?? String(error) }),
          );
      } catch (error) {
        toast.error("JSON malformado", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    };
    reader.readAsText(file);
  };

  const workflowAction = (action: string, workflow: WorkflowItem) => {
    if (action === "simulate") {
      setSelectedId(workflow.id);
      setSimOpen(true);
    } else if (action === "executions") {
      setSelectedId(workflow.id);
      toast.info("Mostrando ejecuciones recientes");
    } else if (action === "duplicate") duplicate.mutate(workflow.id);
    else if (action === "archive") archive.mutate(workflow.id);
    else if (action === "safePause") safePause.mutate(workflow.id);
    else if (action === "delete") remove.mutate(workflow.id);
    else if (action === "toggle") toggle.mutate(workflow);
    else if (action === "export") {
      // We export a clean, importable shape — no metrics, validation, health,
      // version_history, ids, or timestamps. The importer will refuse those
      // anyway, but a small file is more useful for diffing and sharing.
      const exportable = {
        name: workflow.name,
        description: workflow.description,
        trigger_type: workflow.trigger_type,
        trigger_config: workflow.trigger_config,
        definition: workflow.definition,
      };
      const json = JSON.stringify(exportable, null, 2);
      try {
        const blob = new Blob([json], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${workflow.name.replace(/[^a-z0-9-_]+/gi, "_")}.workflow.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        void navigator.clipboard.writeText(json).catch(() => undefined);
        toast.success("Workflow exportado", {
          description: "Archivo descargado y copiado al portapapeles.",
        });
      } catch (error) {
        toast.error("No se pudo exportar", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    } else if (action === "compare") {
      void workflowsApi.compare(workflow.id).then(() => toast.success("Comparación generada"));
    } else if (action === "restore") {
      void workflowsApi.restore(workflow.id, "v12").then(() => {
        void invalidate();
        toast.success("Versión restaurada");
      });
    }
  };

  const toggleSafety = (key: string) => {
    if (!selected) return;
    const definition = structuredClone(selected.definition);
    const ops = { ...(definition.ops ?? {}) };
    const currentRules = selected.safety_rules;
    ops.safety_rules = { ...currentRules, [key]: !currentRules[key] };
    definition.ops = ops;
    patchWorkflow.mutate({ id: selected.id, body: { definition } });
  };

  const kpis = useMemo(() => {
    const metrics = workflows.map((workflow) => workflow.metrics);
    const total = (key: keyof WorkflowMetrics) =>
      metrics.reduce((sum, item) => sum + Number(item[key] ?? 0), 0);
    const averageSuccess = metrics.length
      ? Math.round(metrics.reduce((sum, item) => sum + item.success_rate, 0) / metrics.length)
      : 0;
    const spark = workflows[0]?.metrics.sparkline ?? [];
    // We don't yet store a real "vs ayer" comparison; show em-dash instead of inventing one.
    const noDelta = "— vs ayer";
    return [
      {
        label: "Flujos activos",
        value: String(workflows.filter((workflow) => workflow.active).length),
        delta: noDelta,
        status: "ok" as const,
        values: spark,
      },
      {
        label: "Flujos críticos",
        value: String(workflows.filter((workflow) => workflow.health.status === "critical").length),
        delta: noDelta,
        status: "critical" as const,
        values: spark,
      },
      {
        label: "Ejecuciones hoy",
        value: formatNumber(total("executions_today")),
        delta: noDelta,
        status: "info" as const,
        values: spark,
      },
      {
        label: "Tasa de éxito",
        value: `${averageSuccess}%`,
        delta: noDelta,
        status: "ok" as const,
        values: spark,
      },
      {
        label: "Leads afectados",
        value: formatNumber(total("leads_affected_today")),
        delta: noDelta,
        status: "warn" as const,
        values: spark,
      },
      {
        label: "Handoffs fallidos",
        value: formatNumber(total("failed_handoffs")),
        delta: noDelta,
        status: "critical" as const,
        values: spark,
      },
      {
        label: "Documentos detenidos",
        value: formatNumber(total("documents_blocked")),
        delta: noDelta,
        status: "warn" as const,
        values: spark,
      },
      {
        label: "Errores últimas 24h",
        value: formatNumber(total("critical_failures_24h")),
        delta: noDelta,
        status: "critical" as const,
        values: spark,
      },
    ];
  }, [workflows]);

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden bg-[#07111a] text-slate-100">
      <ContextMenu menu={menu} onClose={() => setMenu(null)} />
      <header className="flex h-13 shrink-0 items-center gap-3 border-b border-white/10 bg-[#08131d] px-4">
        <div className="relative w-[360px]">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <Input
            className="h-8 border-white/10 bg-black/20 pl-8 text-xs text-slate-100"
            placeholder="Buscar flujo, lead, ejecución..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <Badge className="ml-auto border-emerald-400/30 bg-emerald-500/10 text-emerald-200">
          ● Sincronizado en vivo
        </Badge>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-8 border-white/10 bg-white/5 text-xs text-slate-200 hover:bg-white/10"
            >
              <Bookmark className="mr-1.5 h-3.5 w-3.5" />
              Vista guardada
              {savedView && (
                <span
                  className="ml-1 h-1.5 w-1.5 rounded-full bg-emerald-400"
                  aria-label="Tienes una vista guardada"
                />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onSelect={saveCurrentView}>
              <Save className="mr-2 h-3.5 w-3.5" />
              Guardar vista actual
            </DropdownMenuItem>
            <DropdownMenuItem disabled={!savedView} onSelect={restoreSavedView}>
              <FolderOpen className="mr-2 h-3.5 w-3.5" />
              Restaurar última vista
            </DropdownMenuItem>
            {savedView && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={clearSavedView}
                  className="text-rose-300 focus:bg-rose-500/10 focus:text-rose-200"
                >
                  <Trash2 className="mr-2 h-3.5 w-3.5" />
                  Borrar vista guardada
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={onPickJsonFile}
        />
        <Button
          variant="outline"
          size="sm"
          className="h-8 border-white/10 bg-white/5 text-xs text-slate-200 hover:bg-white/10"
          onClick={() => fileInputRef.current?.click()}
        >
          <Import className="mr-1.5 h-3.5 w-3.5" />
          Importar JSON
        </Button>
        <Button
          className="h-8 bg-blue-600 text-xs hover:bg-blue-500"
          onClick={() => create.mutate()}
        >
          <Plus className="mr-1 h-3.5 w-3.5" /> Nuevo workflow
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-slate-300"
          onClick={() => toast.info("12 alertas activas")}
        >
          <Bell className="h-4 w-4" />
        </Button>
        <Badge className="border-white/10 bg-white/5 text-slate-300">
          <Bot className="mr-1 h-3.5 w-3.5" /> Salud IA: 98/100
        </Badge>
      </header>

      <div className="flex gap-2 overflow-x-auto border-b border-white/10 bg-[#08131d] p-2">
        {kpis.map((kpi) => (
          <KpiCard
            key={kpi.label}
            {...kpi}
            onClick={() => toast.info(`Filtro aplicado: ${kpi.label}`)}
          />
        ))}
      </div>

      <main className="grid min-h-0 flex-1 grid-cols-[360px_minmax(640px,1fr)_330px] gap-2 p-2">
        <section className="flex min-h-0 flex-col rounded-md border border-white/10 bg-[#0d1822]">
          <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
            <div>
              <h2 className="text-sm font-semibold">Salud de workflows</h2>
              <p className="text-[10px] text-slate-500">{filtered.length} workflows</p>
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-slate-300"
                onClick={() => void workflowsQuery.refetch()}
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", workflowsQuery.isFetching && "animate-spin")}
                />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-slate-300"
                onClick={() => toast.info("Ordenado por salud")}
              >
                <ListFilter className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-slate-300"
                onClick={() => toast.info("Vista de grid")}
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {workflowsQuery.isLoading ? (
              <div className="grid grid-cols-2 gap-2">
                {Array.from({ length: 8 }).map((_, index) => (
                  <Skeleton key={index} className="h-40 bg-white/10" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {filtered.map((workflow) => (
                  <WorkflowCard
                    key={workflow.id}
                    workflow={workflow}
                    selected={selected?.id === workflow.id}
                    onSelect={() => setSelectedId(workflow.id)}
                    onAction={workflowAction}
                    onContextMenu={openContextMenu}
                  />
                ))}
              </div>
            )}
          </div>
          <Button
            variant="outline"
            className="m-2 h-9 border-dashed border-white/15 bg-white/5 text-xs text-blue-200"
            onClick={() => create.mutate()}
          >
            <Plus className="mr-1 h-3.5 w-3.5" /> Crear nuevo workflow
          </Button>
        </section>

        <div className="flex min-h-0 flex-col gap-2">
          {selected ? (
            <WorkflowEditor
              workflow={selected}
              focusNodeId={focusNodeId}
              onRunSimulation={() => setSimOpen(true)}
              onContextMenu={openContextMenu}
              onShowExecutions={(nodeId) => {
                setExecutionNodeFilter(nodeId);
                const node = selected.definition.nodes.find((n) => n.id === nodeId);
                toast.success("Filtrando ejecuciones", {
                  description: node?.title ? `Nodo: ${node.title}` : `Nodo ${nodeId}`,
                });
              }}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center rounded-md border border-white/10 bg-[#0d1822] text-sm text-slate-500">
              Selecciona un workflow para editarlo.
            </div>
          )}
          <div className="grid h-[250px] shrink-0 grid-cols-[minmax(320px,1.1fr)_minmax(320px,1fr)] gap-2">
            <SimulatorPanel workflow={simOpen ? selected : selected} />
            <VariablesPanel workflow={selected} />
          </div>
        </div>

        <div className="flex min-h-0 flex-col gap-2">
          <ExecutionsPanel
            workflow={selected}
            executions={executions}
            selectedExecution={selectedExecution}
            onSelectExecution={setSelectedExecution}
            onContextMenu={openContextMenu}
            nodeFilter={executionNodeFilter}
            onClearNodeFilter={() => setExecutionNodeFilter(null)}
          />
          <div className="grid min-h-0 flex-1 grid-rows-[auto_1fr_auto] gap-2">
            <NextBestFixPanel
              workflow={selected}
              onOpenNode={(nodeId) => {
                setFocusNodeId(nodeId);
                // Clear after a tick so the same nodeId can be re-focused later.
                setTimeout(() => setFocusNodeId(null), 100);
              }}
            />
            <ValidationPanel workflow={selected} />
            <SafetyPanel
              workflow={selected}
              onToggle={toggleSafety}
              onPause={(mode) => selected && pauseControl.mutate({ id: selected.id, mode })}
              pausing={pauseControl.isPending}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

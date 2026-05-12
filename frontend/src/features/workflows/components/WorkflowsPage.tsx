import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Archive,
  Bell,
  Bot,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  FileWarning,
  Gauge,
  GitBranch,
  HeartPulse,
  Import,
  LayoutGrid,
  ListFilter,
  MessageCircle,
  MoreVertical,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
  UserRoundCog,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState, type MouseEvent } from "react";
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
  workflowsApi,
  type SimulationResult,
  type WorkflowExecution,
  type WorkflowItem,
  type WorkflowMetrics,
} from "@/features/workflows/api";
import { NYIButton } from "@/components/NYIButton";
import { cn } from "@/lib/utils";
import { WorkflowEditor } from "./WorkflowEditor";

type ContextAction = { label: string; action: () => void; danger?: boolean };

type ContextState = {
  x: number;
  y: number;
  actions: ContextAction[];
} | null;

const STATUS_STYLES: Record<string, { label: string; border: string; text: string; bg: string }> = {
  healthy: { label: "Saludable", border: "border-emerald-400/60", text: "text-emerald-300", bg: "bg-emerald-500/10" },
  warning: { label: "Revisión", border: "border-amber-400/60", text: "text-amber-300", bg: "bg-amber-500/10" },
  critical: { label: "Crítico", border: "border-red-400/60", text: "text-red-300", bg: "bg-red-500/10" },
  inactive: { label: "Pausado", border: "border-slate-500/50", text: "text-slate-400", bg: "bg-white/5" },
  archived: { label: "Archivado", border: "border-slate-500/50", text: "text-slate-400", bg: "bg-white/5" },
};

const DEFAULT_STATUS_STYLE = { label: "Pausado", border: "border-slate-500/50", text: "text-slate-400", bg: "bg-white/5" };

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-MX").format(value);
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 }).format(value);
}

function duration(seconds: number | null) {
  if (!seconds) return "—";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function Sparkline({ values, color = "#60a5fa" }: { values: number[]; color?: string }) {
  const safe = values.length ? values : [20, 30, 25, 36, 44, 40, 52];
  const max = Math.max(...safe, 1);
  const points = safe
    .map((value, index) => `${(index / Math.max(1, safe.length - 1)) * 78},${26 - (value / max) * 22}`)
    .join(" ");
  return (
    <svg width="78" height="28" viewBox="0 0 78 28" aria-hidden>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
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
  const color = status === "ok" ? "#34d399" : status === "warn" ? "#fbbf24" : status === "critical" ? "#f87171" : "#60a5fa";
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
      <p className="mt-1 text-[10px]" style={{ color }}>{delta}</p>
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
    { label: workflow.active ? "Desactivar" : "Activar", action: () => onAction("toggle", workflow) },
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
              <p className="text-[10px] text-slate-400">{workflow.description ?? "Mensaje entrante"}</p>
            </div>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300" onClick={(event) => event.stopPropagation()}>
              <MoreVertical className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {actions.map((item, index) => (
              <div key={item.label}>
                {index === 8 && <DropdownMenuSeparator />}
                <DropdownMenuItem className={item.danger ? "text-destructive focus:text-destructive" : undefined} onClick={item.action}>
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
        <Sparkline values={workflow.metrics.sparkline} color={workflow.health.status === "critical" ? "#f87171" : workflow.health.status === "warning" ? "#fbbf24" : "#34d399"} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
        <span><b className="block text-slate-200">{workflow.metrics.executions_today}</b><span className="text-slate-500">Ejec. hoy</span></span>
        <span><b className="block text-slate-200">{workflow.metrics.success_rate}%</b><span className="text-slate-500">Éxito</span></span>
        <span><b className={cn("block", workflow.metrics.failure_rate > 15 ? "text-red-300" : "text-slate-200")}>{workflow.metrics.failure_rate}%</b><span className="text-slate-500">Fallo</span></span>
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
}: {
  workflow: WorkflowItem | null;
  executions: WorkflowExecution[];
  selectedExecution: WorkflowExecution | null;
  onSelectExecution: (execution: WorkflowExecution | null) => void;
  onContextMenu: (event: MouseEvent, actions: ContextAction[]) => void;
}) {
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: (execution: WorkflowExecution) =>
      workflowsApi.retryExecutionFromNode(execution.id, execution.failed_node ?? execution.current_node_id ?? "trigger_1"),
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
    { label: "Abrir lead", action: () => toast.info(`Abriendo lead ${execution.lead_name ?? "sin nombre"}`) },
    { label: "Copiar JSON", action: () => void copyJson(execution) },
    { label: "Copiar execution ID", action: () => void navigator.clipboard.writeText(execution.id) },
    { label: "Exportar JSON", action: () => void copyJson(execution) },
  ];

  return (
    <aside className="flex min-h-0 w-[330px] flex-col border border-white/10 bg-[#0d1822]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Ejecuciones recientes</h2>
          <p className="text-[10px] text-slate-400">{workflow ? workflow.name : "Sin workflow seleccionado"}</p>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-400" onClick={() => onSelectExecution(null)}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
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
              <span className={cn("h-2 w-2 rounded-full", failed ? "bg-red-400" : "bg-emerald-400")} />
              <span className="min-w-0">
                <span className="block truncate text-slate-200">{execution.lead_name}</span>
                <span className="block truncate text-[10px] text-slate-500">{execution.failed_node ?? "—"}</span>
              </span>
              <span className="text-slate-400">
                {new Date(execution.started_at).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}
              </span>
              <span className={failed ? "text-red-300" : "text-emerald-300"}>{execution.result}</span>
            </button>
          );
        })}
      </div>
      {selectedExecution && (
        <div className="border-t border-white/10 p-3">
          <Tabs defaultValue="detalles">
            <TabsList className="h-8 bg-white/5">
              <TabsTrigger value="detalles" className="text-[10px]">Detalles</TabsTrigger>
              <TabsTrigger value="entrada" className="text-[10px]">Entrada JSON</TabsTrigger>
              <TabsTrigger value="salida" className="text-[10px]">Salida JSON</TabsTrigger>
              <TabsTrigger value="replay" className="text-[10px]">Replay</TabsTrigger>
            </TabsList>
            <TabsContent value="detalles" className="mt-2 space-y-1 text-[11px] text-slate-300">
              <p><span className="text-slate-500">ID:</span> <span className="font-mono text-[10px]">{selectedExecution.id.slice(0, 18)}…</span></p>
              <p><span className="text-slate-500">Lead:</span> {selectedExecution.lead_name} | {selectedExecution.lead_phone}</p>
              <p><span className="text-slate-500">Duración:</span> {duration(selectedExecution.duration_seconds)}</p>
              {selectedExecution.error && <p className="rounded border border-red-400/30 bg-red-500/10 p-2 text-red-200">{selectedExecution.error}</p>}
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Button size="sm" className="h-7 text-[11px]" onClick={() => onSelectExecution(selectedExecution)}>
                  <Play className="mr-1 h-3 w-3" /> Reproducir
                </Button>
                <Button variant="outline" size="sm" className="h-7 border-red-400/40 bg-red-500/10 text-[11px] text-red-200" onClick={() => retry.mutate(selectedExecution)}>
                  <RotateCcw className="mr-1 h-3 w-3" /> Reintentar
                </Button>
              </div>
            </TabsContent>
            <TabsContent value="entrada" className="mt-2">
              <pre className="max-h-40 overflow-auto rounded bg-black/25 p-2 text-[10px] text-slate-300">{JSON.stringify(selectedExecution.input_json, null, 2)}</pre>
            </TabsContent>
            <TabsContent value="salida" className="mt-2">
              <pre className="max-h-40 overflow-auto rounded bg-black/25 p-2 text-[10px] text-slate-300">{JSON.stringify(selectedExecution.output_json, null, 2)}</pre>
            </TabsContent>
            <TabsContent value="replay" className="mt-2 space-y-2">
              {selectedExecution.replay.map((step) => (
                <div key={`${step.node_id}-${step.time}`} className="flex gap-2 text-[11px]">
                  <span className={cn("mt-1 h-2 w-2 rounded-full", step.status === "error" ? "bg-red-400" : "bg-emerald-400")} />
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
    mutationFn: () => workflow ? workflowsApi.simulate(workflow.id, { incoming_message: message, version: "draft" }) : Promise.reject(new Error("Selecciona un workflow")),
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
          <select className="h-8 w-full rounded border border-white/10 bg-white/5 px-2 text-xs text-slate-200" defaultValue="juan">
            <option value="juan">Juan Pérez | 5512345678</option>
            <option value="maria">María López | 5587654321</option>
          </select>
          <Textarea className="h-20 resize-none border-white/10 bg-black/20 text-xs text-slate-100" value={message} onChange={(event) => setMessage(event.target.value)} />
          <Button className="h-8 w-full text-xs" onClick={() => simulate.mutate()} disabled={!workflow || simulate.isPending}>Ejecutar simulación</Button>
        </div>
        <div className="min-h-0 overflow-auto text-[11px]">
          {result ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                {result.activated_nodes.map((node) => <p key={node} className="text-emerald-300">✓ Nodo activado: {node}</p>)}
                {result.warnings.map((warning) => <p key={warning} className="text-amber-300">⚠ {warning}</p>)}
                {result.errors.map((error) => <p key={error} className="text-red-300">✕ {error}</p>)}
              </div>
              <div className="rounded bg-white/5 p-2 text-slate-200">
                <p className="mb-1 text-slate-500">Respuesta generada</p>
                <p>{result.generated_response}</p>
                <pre className="mt-2 overflow-auto text-[10px] text-slate-400">{JSON.stringify(result.variables_saved, null, 2)}</pre>
              </div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-slate-500">Ejecuta una simulación para ver nodos, variables y diferencias draft vs publicado.</div>
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
          <TabsTrigger value="variables" className="text-[10px]">Variables</TabsTrigger>
          <TabsTrigger value="dependencias" className="text-[10px]">Dependencias</TabsTrigger>
        </TabsList>
        <TabsContent value="variables" className="mt-2 max-h-52 overflow-auto px-3">
          <table className="w-full text-left text-[11px]">
            <thead className="text-slate-500"><tr><th>Variable</th><th>Usada en</th><th>Último valor</th><th>Estado</th></tr></thead>
            <tbody>
              {(workflow?.variables ?? []).map((variable) => (
                <tr key={variable.name} className="border-t border-white/5">
                  <td className="py-1 text-slate-200">{variable.name}</td>
                  <td className="text-slate-400">{variable.used_in.join(", ")}</td>
                  <td className="text-slate-400">{variable.last_value ?? "—"}</td>
                  <td className={variable.status === "ok" ? "text-emerald-300" : variable.status === "faltante" ? "text-amber-300" : "text-red-300"}>{variable.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TabsContent>
        <TabsContent value="dependencias" className="mt-2 max-h-52 overflow-auto px-3">
          {(workflow?.dependencies ?? []).map((dependency) => (
            <div key={`${dependency.type}-${dependency.name}`} className="flex items-center justify-between border-t border-white/5 py-1.5 text-[11px]">
              <span><span className="text-slate-500">{dependency.type}</span> <span className="text-slate-200">{dependency.name}</span></span>
              <span className={dependency.status === "ok" ? "text-emerald-300" : dependency.status === "warning" ? "text-amber-300" : "text-red-300"}>{dependency.status}</span>
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
            <span className={check.status === "ok" ? "text-emerald-300" : check.status === "warning" ? "text-amber-300" : "text-red-300"}>{check.status}</span>
          </div>
        ))}
        <div className={cn("mt-3 rounded-md border p-3 text-center", blocked ? "border-red-400/40 bg-red-500/10 text-red-200" : "border-emerald-400/40 bg-emerald-500/10 text-emerald-200")}>
          <AlertCircle className="mx-auto mb-1 h-5 w-5" />
          <p className="font-semibold">{validation?.summary ?? "Sin validación"}</p>
          {validation && <p className="text-[10px]">{validation.critical_count} críticos | {validation.warning_count} advertencias</p>}
        </div>
      </div>
    </section>
  );
}

function SafetyPanel({ workflow, onToggle }: { workflow: WorkflowItem | null; onToggle: (key: string) => void }) {
  const labels: Record<string, string> = {
    business_hours: "Respetar horario laboral",
    max_3_messages_24h: "Máximo 3 mensajes automáticos en 24h",
    dedupe_template: "No repetir misma plantilla",
    stop_on_no: "Detener si el cliente dice \"no\"",
    stop_on_human: "Detener si pide humano",
    stop_on_frustration: "Detener si se detecta frustración",
    pause_on_critical: "Pausar si hay error crítico",
  };
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
            <button key={key} type="button" className="flex w-full items-center justify-between" onClick={() => onToggle(key)}>
              <span>{label}</span>
              <span className={cn("h-4 w-8 rounded-full p-0.5 transition", enabled ? "bg-blue-500" : "bg-white/15")}>
                <span className={cn("block h-3 w-3 rounded-full bg-white transition", enabled && "translate-x-4")} />
              </span>
            </button>
          );
        })}
        <div className="mt-2 flex flex-col gap-1.5">
          <NYIButton label="Pausar inmediatamente" />
          <NYIButton label="Pausar solo nuevos leads" />
          <NYIButton label="Pausar después de ejecuciones activas" />
          <NYIButton label="Pausar y enviar a humano" />
        </div>
      </div>
    </section>
  );
}

export function WorkflowsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedExecution, setSelectedExecution] = useState<WorkflowExecution | null>(null);
  const [menu, setMenu] = useState<ContextState>(null);
  const [simOpen, setSimOpen] = useState(false);

  const workflowsQuery = useQuery({
    queryKey: ["workflows"],
    queryFn: workflowsApi.list,
    refetchInterval: 15_000,
  });
  const workflows = workflowsQuery.data ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return workflows;
    return workflows.filter((workflow) => `${workflow.name} ${workflow.description ?? ""}`.toLowerCase().includes(q));
  }, [search, workflows]);
  const selected = filtered.find((workflow) => workflow.id === selectedId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!selectedId && workflows[0]) setSelectedId(workflows[0].id);
  }, [selectedId, workflows]);

  const executionsQuery = useQuery({
    queryKey: ["workflows", selected?.id, "executions"],
    queryFn: () => selected ? workflowsApi.executions(selected.id) : Promise.resolve([]),
    refetchInterval: 10_000,
  });
  const executions = executionsQuery.data ?? [];

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
            { id: "trigger_1", type: "trigger", title: "Disparador: Mensaje entrante", config: { event: "message_received" } },
            { id: "n1", type: "template_message", title: "Enviar mensaje WhatsApp", config: { template: "bienvenida_v3", text: "Hola {{nombre}}, ¿cómo te ayudo?" } },
            { id: "n2", type: "end", title: "Finalizar workflow", config: { result: "nuevo" } },
          ],
          edges: [{ from: "trigger_1", to: "n1" }, { from: "n1", to: "n2" }],
        },
        active: false,
      }),
    onSuccess: (workflow) => {
      void invalidate();
      setSelectedId(workflow.id);
      toast.success("Workflow creado");
    },
  });

  const duplicate = useMutation({ mutationFn: (id: string) => workflowsApi.duplicate(id), onSuccess: (workflow) => { void invalidate(); setSelectedId(workflow.id); toast.success("Workflow duplicado"); } });
  const archive = useMutation({ mutationFn: (id: string) => workflowsApi.archive(id), onSuccess: () => { void invalidate(); toast.success("Workflow archivado"); } });
  const remove = useMutation({ mutationFn: (id: string) => workflowsApi.delete(id), onSuccess: () => { void invalidate(); setSelectedId(null); toast.success("Workflow eliminado"); } });
  const toggle = useMutation({
    mutationFn: (workflow: WorkflowItem) => workflow.active ? workflowsApi.deactivate(workflow.id) : workflowsApi.activate(workflow.id),
    onSuccess: () => { void invalidate(); toast.success("Estado actualizado"); },
    onError: (error) => toast.error("No se pudo activar", { description: error.message }),
  });
  const safePause = useMutation({ mutationFn: (id: string) => workflowsApi.safePause(id, "new_leads"), onSuccess: () => { void invalidate(); toast.success("Pausa segura activada"); } });

  const patchWorkflow = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<WorkflowItem> }) => workflowsApi.patch(id, body),
    onSuccess: () => { void invalidate(); toast.success("Configuración actualizada"); },
    onError: (error) => toast.error("No se pudo guardar", { description: error.message }),
  });

  const openContextMenu = (event: MouseEvent, actions: ContextAction[]) => {
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, actions });
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
      void navigator.clipboard.writeText(JSON.stringify(workflow, null, 2));
      toast.success("Workflow copiado como JSON");
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
    const total = (key: keyof WorkflowMetrics) => metrics.reduce((sum, item) => sum + Number(item[key] ?? 0), 0);
    const averageSuccess = metrics.length ? Math.round(metrics.reduce((sum, item) => sum + item.success_rate, 0) / metrics.length) : 0;
    const spark = workflows[0]?.metrics.sparkline ?? [20, 30, 42, 36, 50, 48, 62];
    return [
      { label: "Flujos activos", value: String(workflows.filter((workflow) => workflow.active).length), delta: "↑ 5 vs ayer", status: "ok" as const, values: spark },
      { label: "Flujos críticos", value: String(workflows.filter((workflow) => workflow.health.status === "critical").length), delta: "↑ 1 vs ayer", status: "critical" as const, values: spark.map((value) => 100 - value) },
      { label: "Ejecuciones hoy", value: formatNumber(total("executions_today")), delta: "↑ 12.6% vs ayer", status: "info" as const, values: spark },
      { label: "Tasa de éxito", value: `${averageSuccess}%`, delta: "↑ 2.8 pp vs ayer", status: "ok" as const, values: spark },
      { label: "Leads afectados", value: formatNumber(total("leads_affected_today")), delta: "↑ 18 vs ayer", status: "warn" as const, values: spark },
      { label: "Handoffs fallidos", value: formatNumber(total("failed_handoffs")), delta: "↓ 5 vs ayer", status: "critical" as const, values: spark.map((value) => value / 2) },
      { label: "Documentos detenidos", value: formatNumber(total("documents_blocked")), delta: "↑ 6 vs ayer", status: "warn" as const, values: spark },
      { label: "Errores últimas 24h", value: formatNumber(total("critical_failures_24h")), delta: "↑ 14 vs ayer", status: "critical" as const, values: spark.map((value) => 100 - value) },
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
        <Badge className="ml-auto border-emerald-400/30 bg-emerald-500/10 text-emerald-200">● Sincronizado en vivo</Badge>
        <NYIButton label="Vista guardada" />
        <NYIButton label="Importar JSON" icon={Import} />
        <Button className="h-8 bg-blue-600 text-xs hover:bg-blue-500" onClick={() => create.mutate()}>
          <Plus className="mr-1 h-3.5 w-3.5" /> Nuevo workflow
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-300" onClick={() => toast.info("12 alertas activas")}>
          <Bell className="h-4 w-4" />
        </Button>
        <Badge className="border-white/10 bg-white/5 text-slate-300"><Bot className="mr-1 h-3.5 w-3.5" /> Salud IA: 98/100</Badge>
      </header>

      <div className="flex gap-2 overflow-x-auto border-b border-white/10 bg-[#08131d] p-2">
        {kpis.map((kpi) => (
          <KpiCard key={kpi.label} {...kpi} onClick={() => toast.info(`Filtro aplicado: ${kpi.label}`)} />
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
              <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300" onClick={() => void workflowsQuery.refetch()}>
                <RefreshCw className={cn("h-3.5 w-3.5", workflowsQuery.isFetching && "animate-spin")} />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300" onClick={() => toast.info("Ordenado por salud")}>
                <ListFilter className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300" onClick={() => toast.info("Vista de grid")}>
                <LayoutGrid className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {workflowsQuery.isLoading ? (
              <div className="grid grid-cols-2 gap-2">
                {Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} className="h-40 bg-white/10" />)}
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
          <Button variant="outline" className="m-2 h-9 border-dashed border-white/15 bg-white/5 text-xs text-blue-200" onClick={() => create.mutate()}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Crear nuevo workflow
          </Button>
        </section>

        <div className="flex min-h-0 flex-col gap-2">
          {selected ? (
            <WorkflowEditor workflow={selected} onRunSimulation={() => setSimOpen(true)} onContextMenu={openContextMenu} />
          ) : (
            <div className="flex flex-1 items-center justify-center rounded-md border border-white/10 bg-[#0d1822] text-sm text-slate-500">Selecciona un workflow para editarlo.</div>
          )}
          <div className="grid h-[250px] shrink-0 grid-cols-[minmax(320px,1.1fr)_minmax(320px,1fr)] gap-2">
            <SimulatorPanel workflow={simOpen ? selected : selected} />
            <VariablesPanel workflow={selected} />
          </div>
        </div>

        <div className="flex min-h-0 flex-col gap-2">
          <ExecutionsPanel workflow={selected} executions={executions} selectedExecution={selectedExecution} onSelectExecution={setSelectedExecution} onContextMenu={openContextMenu} />
          <div className="grid min-h-0 flex-1 grid-rows-[1fr_auto] gap-2">
            <ValidationPanel workflow={selected} />
            <SafetyPanel workflow={selected} onToggle={toggleSafety} />
          </div>
        </div>
      </main>
    </div>
  );
}

import "@xyflow/react/dist/style.css";

import { Background, Controls, ReactFlow } from "@xyflow/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Calendar,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Copy,
  GitBranch,
  MessageSquare,
  MoreHorizontal,
  Play,
  Plus,
  Save,
  Trash2,
  UserCheck,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
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
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { workflowsApi, type WorkflowExecution, type WorkflowItem } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

interface WFNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  [key: string]: unknown;
}

// ── Node metadata ─────────────────────────────────────────────────────────────

interface NodeMeta {
  label: string;
  icon: typeof Zap;
  iconColor: string;
  bgColor: string;
}

const NODE_META: Record<string, NodeMeta> = {
  trigger: { label: "Disparador", icon: Zap, iconColor: "text-amber-500", bgColor: "bg-amber-500/10" },
  message: { label: "Enviar mensaje", icon: MessageSquare, iconColor: "text-blue-500", bgColor: "bg-blue-500/10" },
  condition: { label: "Condición", icon: GitBranch, iconColor: "text-purple-500", bgColor: "bg-purple-500/10" },
  assign_agent: { label: "Asignar a asesor", icon: UserCheck, iconColor: "text-emerald-500", bgColor: "bg-emerald-500/10" },
  task: { label: "Crear tarea", icon: CheckSquare, iconColor: "text-indigo-500", bgColor: "bg-indigo-500/10" },
  delay: { label: "Esperar", icon: Clock, iconColor: "text-orange-500", bgColor: "bg-orange-500/10" },
  notify_agent: { label: "Notificar al asesor", icon: Bell, iconColor: "text-pink-500", bgColor: "bg-pink-500/10" },
  move_stage: { label: "Cambiar etapa", icon: Calendar, iconColor: "text-cyan-500", bgColor: "bg-cyan-500/10" },
};

const DEFAULT_META: NodeMeta = {
  label: "Acción",
  icon: Zap,
  iconColor: "text-muted-foreground",
  bgColor: "bg-muted",
};

const TRIGGER_LABELS: Record<string, string> = {
  message_received: "Mensaje entrante",
  field_updated: "Campo actualizado",
  stage_changed: "Etapa cambiada",
  appointment_created: "Cita creada",
  bot_paused: "Bot pausado",
};

const ACTION_TYPES = [
  "message", "condition", "assign_agent", "task",
  "delay", "notify_agent", "move_stage",
];

function nodeDescription(node: WFNode): string {
  const cfg = node.config;
  switch (node.type) {
    case "trigger":
      return TRIGGER_LABELS[String(cfg.event ?? "")] ?? String(cfg.event ?? "Configura el disparador");
    case "message":
      return String(cfg.text ?? "Sin texto definido").slice(0, 60);
    case "condition":
      return `Palabras clave: ${String(cfg.keywords ?? "—")}`;
    case "assign_agent":
      return `Asignar a: ${String(cfg.assignment ?? "Asesor disponible (Round Robin)")}`;
    case "task":
      return String(cfg.title ?? "Sin título");
    case "delay":
      return `Esperar ${String(cfg.hours ?? 1)} hora(s)`;
    case "notify_agent":
      return `Canal: ${String(cfg.channel ?? "WhatsApp")}`;
    case "move_stage":
      return `Mover a: ${String(cfg.stage ?? "—")}`;
    default:
      return node.type;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.round(diffMs / 60_000);
  if (m < 1) return "ahora";
  if (m < 60) return `hace ${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h}h`;
  return `hace ${Math.round(h / 24)}d`;
}

function execDuration(exec: WorkflowExecution): string {
  if (!exec.finished_at) return "—";
  const ms = new Date(exec.finished_at).getTime() - new Date(exec.started_at).getTime();
  return `${(ms / 1000).toFixed(1)}s`;
}

function execSuccess(exec: WorkflowExecution): boolean {
  return exec.status === "success" || exec.status === "completed";
}

// ── Node form ─────────────────────────────────────────────────────────────────

function NodeForm({ node, onChange }: { node: WFNode; onChange: (n: WFNode) => void }) {
  const patch = (key: string, val: unknown) =>
    onChange({ ...node, config: { ...node.config, [key]: val } });

  switch (node.type) {
    case "message":
      return (
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Mensaje</Label>
            <Textarea
              rows={3}
              className="mt-1 text-xs"
              placeholder="¡Hola {{contact.name}}! ¿En qué podemos ayudarte hoy?"
              value={String(node.config.text ?? "")}
              onChange={(e) => patch("text", e.target.value)}
            />
            <p className="mt-1 text-[10px] text-muted-foreground">
              Variables: <code>{"{{contact.name}}"}</code> <code>{"{{agent.name}}"}</code>
            </p>
          </div>
        </div>
      );

    case "condition":
      return (
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Si el mensaje contiene alguna palabra clave
            </Label>
            <Input
              className="mt-1 h-7 text-xs"
              placeholder="precio, cotización, costos"
              value={String(node.config.keywords ?? "")}
              onChange={(e) => patch("keywords", e.target.value)}
            />
          </div>
          <div className="flex gap-4">
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-sm bg-emerald-500" />
              <span className="text-xs">Sí → continúa</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-sm bg-muted-foreground/40" />
              <span className="text-xs">No → termina flujo</span>
            </div>
          </div>
        </div>
      );

    case "assign_agent":
      return (
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Tipo de asignación</Label>
            <select
              className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs"
              value={String(node.config.assignment ?? "round_robin")}
              onChange={(e) => patch("assignment", e.target.value)}
            >
              <option value="round_robin">Asesor disponible (Round Robin)</option>
              <option value="specific">Asesor específico</option>
              <option value="load_balanced">Balance de carga</option>
            </select>
          </div>
        </div>
      );

    case "task":
      return (
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Título</Label>
            <Input
              className="mt-1 h-7 text-xs"
              placeholder="Dar seguimiento al lead"
              value={String(node.config.title ?? "")}
              onChange={(e) => patch("title", e.target.value)}
            />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Vence en (días)</Label>
            <Input
              type="number"
              min={1}
              className="mt-1 h-7 w-24 text-xs"
              value={String(node.config.due_days ?? 1)}
              onChange={(e) => patch("due_days", Number(e.target.value))}
            />
          </div>
        </div>
      );

    case "delay":
      return (
        <div className="space-y-2">
          <div className="flex items-end gap-2">
            <div>
              <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Esperar</Label>
              <Input
                type="number"
                min={1}
                className="mt-1 h-7 w-20 text-xs"
                value={String(node.config.hours ?? 1)}
                onChange={(e) => patch("hours", Number(e.target.value))}
              />
            </div>
            <span className="mb-1.5 text-xs text-muted-foreground">hora(s)</span>
          </div>
        </div>
      );

    default:
      return (
        <div>
          <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Config (JSON)</Label>
          <Textarea
            rows={4}
            className="mt-1 font-mono text-[11px]"
            value={JSON.stringify(node.config, null, 2)}
            onChange={(e) => {
              try {
                onChange({ ...node, config: JSON.parse(e.target.value) });
              } catch {
                /* keep typing */
              }
            }}
          />
        </div>
      );
  }
}

// ── NodeCard ──────────────────────────────────────────────────────────────────

function NodeCard({
  node,
  index,
  isLast,
  expanded,
  onToggle,
  onChange,
  onDelete,
}: {
  node: WFNode;
  index: number;
  isLast: boolean;
  expanded: boolean;
  onToggle: () => void;
  onChange: (n: WFNode) => void;
  onDelete: () => void;
}) {
  const meta = NODE_META[node.type] ?? DEFAULT_META;
  const Icon = meta.icon;
  const isTrigger = node.type === "trigger";

  return (
    <div className="flex gap-2.5">
      {/* Step connector */}
      <div className="flex flex-col items-center pt-2.5">
        <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[9px] font-bold text-muted-foreground">
          {index + 1}
        </div>
        {!isLast && <div className="mt-1 flex-1 w-px bg-border" />}
      </div>

      {/* Card */}
      <div className={cn("mb-2 flex-1 overflow-hidden rounded-lg border bg-card", expanded && "shadow-sm")}>
        <button
          type="button"
          className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-muted/40"
          onClick={onToggle}
        >
          <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md", meta.bgColor)}>
            <Icon className={cn("h-3.5 w-3.5", meta.iconColor)} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold">{meta.label}</p>
            <p className="truncate text-[10px] text-muted-foreground">{nodeDescription(node)}</p>
          </div>
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
        </button>

        {expanded && (
          <div className="border-t px-3 py-3">
            <NodeForm node={node} onChange={onChange} />
            {!isTrigger && (
              <div className="mt-3 flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-[11px] text-destructive hover:text-destructive"
                  onClick={onDelete}
                >
                  <Trash2 className="mr-1 h-3 w-3" /> Eliminar paso
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Execution panel ───────────────────────────────────────────────────────────

function ExecutionPanel({
  workflowId,
  onClose,
}: {
  workflowId: string;
  onClose: () => void;
}) {
  const executions = useQuery({
    queryKey: ["workflows", workflowId, "executions"],
    queryFn: () => workflowsApi.executions(workflowId),
    refetchInterval: 15_000,
  });
  const [selectedExec, setSelectedExec] = useState<WorkflowExecution | null>(null);
  const [detailTab, setDetailTab] = useState<"detalles" | "entrada" | "salida">("detalles");

  const items = executions.data ?? [];
  const total = items.length;
  const success = items.filter(execSuccess).length;
  const failed = total - success;
  const avgMs = useMemo(() => {
    const durations = items
      .filter((e) => e.finished_at)
      .map((e) => new Date(e.finished_at!).getTime() - new Date(e.started_at).getTime());
    if (!durations.length) return 0;
    return durations.reduce((a, b) => a + b, 0) / durations.length;
  }, [items]);

  return (
    <div className="flex w-72 shrink-0 flex-col overflow-hidden border-l bg-background">
      {/* Header */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b px-3">
        <div>
          <span className="text-xs font-semibold">Ejecuciones</span>
          <span className="ml-1.5 text-[10px] text-muted-foreground">Últimas 50 ejecuciones</span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose} title="Cerrar panel">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Stats */}
      <div className="shrink-0 border-b px-3 py-2.5">
        <div className="grid grid-cols-4 gap-1 text-center">
          <div>
            <p className="text-base font-semibold tabular-nums">{total}</p>
            <p className="text-[9px] text-muted-foreground">Total</p>
          </div>
          <div>
            <p className="text-base font-semibold tabular-nums text-emerald-500">{success}</p>
            <p className="text-[9px] text-muted-foreground">
              Exitosas
              {total > 0 && <span className="block text-[8px]">({Math.round((success / total) * 100)}%)</span>}
            </p>
          </div>
          <div>
            <p className="text-base font-semibold tabular-nums text-destructive">{failed}</p>
            <p className="text-[9px] text-muted-foreground">
              Fallidas
              {total > 0 && <span className="block text-[8px]">({Math.round((failed / total) * 100)}%)</span>}
            </p>
          </div>
          <div>
            <p className="text-base font-semibold tabular-nums">
              {avgMs > 0 ? `${(avgMs / 1000).toFixed(1)}s` : "—"}
            </p>
            <p className="text-[9px] text-muted-foreground">Tiempo prom.</p>
          </div>
        </div>
      </div>

      {/* Execution list */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {executions.isLoading ? (
          <div className="space-y-1 p-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <Play className="h-6 w-6 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">Sin ejecuciones aún</p>
          </div>
        ) : (
          <div>
            <div className="grid grid-cols-4 border-b px-3 py-1.5 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
              <span>Estado</span>
              <span>Inicio</span>
              <span>Duración</span>
              <span>Resultado</span>
            </div>
            {items.slice(0, 50).map((exec) => {
              const ok = execSuccess(exec);
              const isSelected = selectedExec?.id === exec.id;
              return (
                <button
                  key={exec.id}
                  type="button"
                  onClick={() => setSelectedExec(isSelected ? null : exec)}
                  className={cn(
                    "grid w-full grid-cols-4 items-center border-b px-3 py-2 text-left text-[10px] hover:bg-muted/40",
                    isSelected && "bg-muted/60",
                  )}
                >
                  <span>
                    {ok ? (
                      <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                    ) : (
                      <XCircle className="h-3 w-3 text-destructive" />
                    )}
                  </span>
                  <span className="truncate text-muted-foreground">
                    {new Date(exec.started_at).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <span className="text-muted-foreground">{execDuration(exec)}</span>
                  <span className={ok ? "text-emerald-600" : "text-destructive"}>
                    {ok ? "Éxito" : "Fallo"}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Execution detail */}
      {selectedExec && (
        <div className="shrink-0 border-t">
          {/* Detail tabs */}
          <div className="flex border-b">
            {(["detalles", "entrada", "salida"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setDetailTab(t)}
                className={cn(
                  "flex-1 py-1.5 text-[10px] font-medium capitalize transition-colors",
                  detailTab === t
                    ? "border-b-2 border-primary text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t === "detalles" ? "Detalles" : t === "entrada" ? "Entrada (JSON)" : "Salida (JSON)"}
              </button>
            ))}
          </div>
          <div className="p-3 text-[11px]">
            {detailTab === "detalles" && (
              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">ID</span>
                  <span className="max-w-[140px] truncate font-mono text-[9px]">{selectedExec.id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Inicio</span>
                  <span>{new Date(selectedExec.started_at).toLocaleString("es-MX")}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Duración</span>
                  <span>{execDuration(selectedExec)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Resultado</span>
                  <span className={execSuccess(selectedExec) ? "text-emerald-600" : "text-destructive"}>
                    {execSuccess(selectedExec) ? "Éxito" : "Fallo"}
                  </span>
                </div>
                {selectedExec.error && (
                  <div className="mt-2 rounded-md bg-destructive/10 px-2 py-1.5 text-[10px] text-destructive">
                    {selectedExec.error}
                  </div>
                )}
              </div>
            )}
            {(detailTab === "entrada" || detailTab === "salida") && (
              <pre className="overflow-x-auto rounded-md bg-muted p-2 font-mono text-[10px] text-muted-foreground">
                {"{}"}{/* API doesn't expose input/output yet */}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── WorkflowEditor ────────────────────────────────────────────────────────────

export function WorkflowEditor({
  workflow,
  onClose,
  onDeleted,
}: {
  workflow: WorkflowItem;
  onClose?: () => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<WorkflowItem>({ ...workflow });
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set(["trigger_1"]));
  const [showExec, setShowExec] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const nodes = useMemo<WFNode[]>(
    () =>
      (draft.definition.nodes ?? []).map((n) => ({
        id: String(n.id ?? ""),
        type: String(n.type ?? ""),
        config: (n.config as Record<string, unknown>) ?? {},
      })),
    [draft.definition.nodes],
  );

  const save = useMutation({
    mutationFn: () => workflowsApi.patch(workflow.id, draft),
    onSuccess: (updated) => {
      setDraft(updated);
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      toast.success("Flujo guardado");
    },
    onError: () => toast.error("No se pudo guardar el flujo"),
  });

  const toggle = useMutation({
    mutationFn: () => workflowsApi.toggle(workflow.id),
    onSuccess: (updated) => {
      setDraft(updated);
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });

  const remove = useMutation({
    mutationFn: () => workflowsApi.delete(workflow.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      onDeleted();
    },
  });

  const toggleNode = (id: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const updateNode = (idx: number, updated: WFNode) => {
    const nextNodes = nodes.map((n, i) => (i === idx ? updated : n));
    setDraft((prev) => ({ ...prev, definition: { ...prev.definition, nodes: nextNodes } }));
  };

  const deleteNode = (idx: number) => {
    const nextNodes = nodes.filter((_, i) => i !== idx);
    const nextEdges = nextNodes.slice(1).map((n, i) => ({
      from: i === 0 ? "trigger_1" : `action_${i}`,
      to: n.id,
    }));
    setDraft((prev) => ({ ...prev, definition: { nodes: nextNodes, edges: nextEdges } }));
  };

  const addAction = () => {
    const nextId = `action_${nodes.length}`;
    const newNode: WFNode = { id: nextId, type: "message", config: { text: "" } };
    const nextNodes = [...nodes, newNode];
    const nextEdges = nextNodes.slice(1).map((n, i) => ({
      from: i === 0 ? "trigger_1" : `action_${i}`,
      to: n.id,
    }));
    setDraft((prev) => ({ ...prev, definition: { nodes: nextNodes, edges: nextEdges } }));
    setExpandedNodes((prev) => new Set([...prev, nextId]));
  };

  const isDirty = JSON.stringify(draft) !== JSON.stringify(workflow);

  return (
    <>
      {/* Editor panel */}
      <div className="flex w-[390px] shrink-0 flex-col overflow-hidden border-l bg-background">
        {/* Editor header */}
        <div className="flex h-10 shrink-0 items-center gap-2 border-b px-3">
          <div className="min-w-0 flex-1">
            <span className="truncate text-xs font-semibold">Editor: {draft.name}</span>
          </div>
          <Badge
            variant="outline"
            className={cn(
              "shrink-0 text-[10px]",
              draft.active ? "border-emerald-500/50 text-emerald-600" : "text-muted-foreground",
            )}
          >
            {draft.active ? "● Activo" : "○ Inactivo"}
          </Badge>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" title="Opciones">
                <MoreHorizontal className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => toggle.mutate()}>
                {draft.active ? "Desactivar flujo" : "Activar flujo"}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setShowExec((v) => !v)}>
                {showExec ? "Ocultar ejecuciones" : "Ver ejecuciones"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onClick={() => setShowDeleteConfirm(true)}
              >
                <Trash2 className="mr-2 h-3.5 w-3.5" /> Eliminar flujo
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          {onClose && (
            <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onClose} title="Cerrar editor">
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>

        {/* Delete confirm */}
        {showDeleteConfirm && (
          <div className="shrink-0 border-b bg-destructive/5 px-4 py-3">
            <p className="mb-2 text-xs font-medium text-destructive">
              ¿Eliminar "{draft.name}"? Esta acción no se puede deshacer.
            </p>
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                className="h-7 text-xs"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
              >
                {remove.isPending ? "Eliminando…" : "Eliminar"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => setShowDeleteConfirm(false)}
              >
                Cancelar
              </Button>
            </div>
          </div>
        )}

        {/* Tabs */}
        <Tabs defaultValue="editor" className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="shrink-0 border-b px-3">
            <TabsList className="h-8 bg-transparent p-0">
              {(["editor", "configuracion", "historial"] as const).map((tab) => (
                <TabsTrigger
                  key={tab}
                  value={tab}
                  className="h-8 rounded-none border-b-2 border-transparent px-3 text-xs data-[state=active]:border-primary data-[state=active]:shadow-none"
                >
                  {tab === "editor" ? "Editor" : tab === "configuracion" ? "Configuración" : "Historial"}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          {/* Editor tab: timeline */}
          <TabsContent value="editor" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
            <ScrollArea className="flex-1">
              <div className="p-3">
                {nodes.map((node, idx) => (
                  <NodeCard
                    key={node.id}
                    node={node}
                    index={idx}
                    isLast={idx === nodes.length - 1}
                    expanded={expandedNodes.has(node.id)}
                    onToggle={() => toggleNode(node.id)}
                    onChange={(updated) => updateNode(idx, updated)}
                    onDelete={() => deleteNode(idx)}
                  />
                ))}
                <div className="pl-8">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 w-full text-xs"
                    onClick={addAction}
                  >
                    <Plus className="mr-1.5 h-3 w-3" /> Agregar acción
                  </Button>
                </div>
              </div>
            </ScrollArea>

            {/* Save bar */}
            <div className="flex shrink-0 items-center justify-between border-t bg-background px-3 py-2">
              {isDirty ? (
                <span className="text-[10px] text-amber-600">Cambios sin guardar</span>
              ) : (
                <span className="text-[10px] text-muted-foreground">Sin cambios</span>
              )}
              <div className="flex gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => setShowExec((v) => !v)}
                  title={showExec ? "Ocultar ejecuciones" : "Ver ejecuciones"}
                >
                  <Play className="mr-1 h-3 w-3" />
                  Ejecuciones
                </Button>
                <Button
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => save.mutate()}
                  disabled={save.isPending || !isDirty}
                >
                  <Save className="mr-1 h-3 w-3" />
                  {save.isPending ? "Guardando…" : "Guardar"}
                </Button>
              </div>
            </div>
          </TabsContent>

          {/* Configuración tab */}
          <TabsContent value="configuracion" className="mt-0 flex-1 overflow-y-auto p-4">
            <div className="space-y-4">
              <div>
                <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Nombre del flujo</Label>
                <Input
                  className="mt-1 h-8 text-sm"
                  value={draft.name}
                  onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Descripción</Label>
                <Textarea
                  rows={3}
                  className="mt-1 text-xs"
                  placeholder="¿Qué hace este flujo y cuándo se activa?"
                  value={draft.description ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, description: e.target.value }))}
                />
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Tipo de disparador</Label>
                <select
                  className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                  value={draft.trigger_type}
                  onChange={(e) => setDraft((p) => ({ ...p, trigger_type: e.target.value }))}
                >
                  <option value="message_received">Mensaje entrante</option>
                  <option value="field_updated">Campo actualizado</option>
                  <option value="stage_changed">Etapa cambiada</option>
                  <option value="appointment_created">Cita creada</option>
                  <option value="bot_paused">Bot pausado</option>
                </select>
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Estado</Label>
                <div className="mt-2 flex items-center gap-3">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={draft.active}
                    onClick={() => toggle.mutate()}
                    className={cn(
                      "relative inline-flex h-5 w-9 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                      draft.active ? "bg-primary" : "bg-muted",
                    )}
                  >
                    <span
                      className={cn(
                        "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
                        draft.active ? "translate-x-4" : "translate-x-0",
                      )}
                    />
                  </button>
                  <span className="text-xs text-muted-foreground">
                    {draft.active ? "Activo — recibiendo eventos" : "Inactivo — no procesa eventos"}
                  </span>
                </div>
              </div>

              {/* Danger zone */}
              <div className="rounded-lg border border-destructive/30 p-3">
                <p className="mb-2 text-xs font-semibold text-destructive">Zona de peligro</p>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 border-destructive/50 text-xs text-destructive hover:bg-destructive/10"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <Trash2 className="mr-1.5 h-3 w-3" /> Eliminar flujo permanentemente
                </Button>
              </div>
            </div>
          </TabsContent>

          {/* Historial tab */}
          <TabsContent value="historial" className="mt-0 flex-1 overflow-y-auto">
            <ExecutionPanel workflowId={workflow.id} onClose={() => {}} />
          </TabsContent>
        </Tabs>
      </div>

      {/* Executions side panel (shown in Editor tab) */}
      {showExec && (
        <ExecutionPanel workflowId={workflow.id} onClose={() => setShowExec(false)} />
      )}
    </>
  );
}

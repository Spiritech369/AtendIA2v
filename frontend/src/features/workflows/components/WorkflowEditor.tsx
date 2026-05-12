import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Bot,
  CheckCircle2,
  Copy,
  FileCheck2,
  GitBranch,
  MessageSquare,
  MoreVertical,
  Play,
  Plus,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
  Trash2,
  UserCheck,
  Workflow,
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
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { workflowsApi, type WorkflowItem, type WorkflowNode } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

type ContextAction = { label: string; action: () => void; danger?: boolean };

interface WorkflowEditorProps {
  workflow: WorkflowItem;
  onRunSimulation: () => void;
  onContextMenu?: (event: MouseEvent, actions: ContextAction[]) => void;
}

const DEFAULT_NODE_META = { label: "Acción", icon: Zap, color: "text-slate-300", bg: "bg-white/10" };

const NODE_META: Record<string, { label: string; icon: typeof Zap; color: string; bg: string }> = {
  trigger: { label: "Disparador", icon: Zap, color: "text-emerald-300", bg: "bg-emerald-500/15" },
  template_message: { label: "Acción", icon: MessageSquare, color: "text-emerald-300", bg: "bg-emerald-500/15" },
  message: { label: "Acción", icon: MessageSquare, color: "text-emerald-300", bg: "bg-emerald-500/15" },
  detect_intent: { label: "Condición", icon: GitBranch, color: "text-amber-300", bg: "bg-amber-500/15" },
  condition: { label: "Condición", icon: GitBranch, color: "text-amber-300", bg: "bg-amber-500/15" },
  classify_credit: { label: "Acción", icon: Bot, color: "text-blue-300", bg: "bg-blue-500/15" },
  request_documents: { label: "Acción", icon: FileCheck2, color: "text-blue-300", bg: "bg-blue-500/15" },
  advisor_pool: { label: "Acción", icon: UserCheck, color: "text-blue-300", bg: "bg-blue-500/15" },
  create_task: { label: "Acción", icon: CheckCircle2, color: "text-blue-300", bg: "bg-blue-500/15" },
  followup: { label: "Acción", icon: Send, color: "text-blue-300", bg: "bg-blue-500/15" },
  escalate_manager: { label: "Escalar", icon: ShieldCheck, color: "text-red-300", bg: "bg-red-500/15" },
  end: { label: "Final", icon: Workflow, color: "text-violet-300", bg: "bg-violet-500/15" },
};

function titleFor(node: WorkflowNode) {
  return node.title || NODE_META[node.type]?.label || node.type;
}

function summaryFor(node: WorkflowNode) {
  const cfg = node.config;
  if (node.type === "trigger") return String(cfg.event ?? "Mensaje entrante");
  if (node.type === "template_message") return `Plantilla: ${String(cfg.template ?? "sin plantilla")}`;
  if (node.type === "condition") return `Regla: ${String(cfg.field ?? "sin campo")} ${String(cfg.operator ?? "eq")}`;
  if (node.type === "advisor_pool") return `Pool: ${String(cfg.pool ?? "sin pool")}`;
  if (node.type === "request_documents") return "INE, comprobante, ingresos";
  if (node.type === "end") return String(cfg.result ?? "finaliza");
  return String(cfg.intent ?? cfg.field ?? cfg.title ?? cfg.reason ?? "configuración lista");
}

function nodeMetrics(workflow: WorkflowItem, nodeId: string) {
  const ops = workflow.definition.ops as { node_metrics?: Record<string, Record<string, unknown>> } | undefined;
  return ops?.node_metrics?.[nodeId] ?? {};
}

function pct(value: unknown, fallback = 0) {
  return typeof value === "number" ? `${value}%` : `${fallback}%`;
}

export function WorkflowEditor({ workflow, onRunSimulation, onContextMenu }: WorkflowEditorProps) {
  const qc = useQueryClient();
  const nodes = workflow.definition.nodes;
  const [selectedNodeId, setSelectedNodeId] = useState(nodes[0]?.id ?? "");
  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) ?? nodes[0],
    [nodes, selectedNodeId],
  );
  const [titleDraft, setTitleDraft] = useState("");
  const [configDraft, setConfigDraft] = useState("{}");

  useEffect(() => {
    if (!selectedNode) return;
    setSelectedNodeId(selectedNode.id);
    setTitleDraft(selectedNode.title ?? "");
    setConfigDraft(JSON.stringify(selectedNode.config ?? {}, null, 2));
  }, [selectedNode?.id]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["workflows"] });

  const patchNode = useMutation({
    mutationFn: ({ nodeId, body }: { nodeId: string; body: Partial<WorkflowNode> }) =>
      workflowsApi.patchNode(workflow.id, nodeId, body),
    onSuccess: () => {
      void invalidate();
      toast.success("Nodo actualizado");
    },
    onError: (error) => toast.error("No se pudo actualizar el nodo", { description: error.message }),
  });

  const addNode = useMutation({
    mutationFn: () =>
      workflowsApi.addNode(workflow.id, {
        type: "template_message",
        title: "Enviar mensaje WhatsApp",
        config: { template: "seguimiento_v2", text: "Hola {{nombre}}, seguimos atentos a tu solicitud." },
      }),
    onSuccess: (updated) => {
      void invalidate();
      const last = updated.definition.nodes.at(-1);
      if (last) setSelectedNodeId(last.id);
      toast.success("Nodo agregado");
    },
  });

  const deleteNode = useMutation({
    mutationFn: (nodeId: string) => workflowsApi.deleteNode(workflow.id, nodeId),
    onSuccess: () => {
      void invalidate();
      toast.success("Nodo eliminado");
    },
  });

  const duplicateNode = useMutation({
    mutationFn: (nodeId: string) => workflowsApi.duplicateNode(workflow.id, nodeId),
    onSuccess: () => {
      void invalidate();
      toast.success("Nodo duplicado");
    },
  });

  const reorder = useMutation({
    mutationFn: (nodeIds: string[]) => workflowsApi.reorderNodes(workflow.id, nodeIds),
    onSuccess: () => {
      void invalidate();
      toast.success("Orden actualizado");
    },
  });

  const publish = useMutation({
    mutationFn: () => workflowsApi.publish(workflow.id),
    onSuccess: () => {
      void invalidate();
      toast.success("Cambios publicados");
    },
    onError: (error) => toast.error("Publicación bloqueada", { description: error.message }),
  });

  const saveDraft = useMutation({
    mutationFn: () => workflowsApi.saveDraft(workflow.id),
    onSuccess: () => {
      void invalidate();
      toast.success("Borrador guardado");
    },
  });

  const compare = useMutation({
    mutationFn: () => workflowsApi.compare(workflow.id),
    onSuccess: (data) => {
      const changed = Array.isArray(data.changed) ? data.changed.length : 0;
      toast.success("Comparación lista", { description: `${changed} cambios detectados` });
    },
  });

  const restore = useMutation({
    mutationFn: () => workflowsApi.restore(workflow.id, "v12"),
    onSuccess: () => {
      void invalidate();
      toast.success("Versión restaurada a borrador");
    },
  });

  const moveNode = (nodeId: string, delta: -1 | 1) => {
    const index = nodes.findIndex((node) => node.id === nodeId);
    const target = index + delta;
    if (index <= 0 || target <= 0 || target >= nodes.length) return;
    const next = [...nodes];
    const current = next[index];
    const targetNode = next[target];
    if (!current || !targetNode) return;
    next[index] = targetNode;
    next[target] = current;
    reorder.mutate(next.map((node) => node.id));
  };

  const saveSelectedNode = () => {
    if (!selectedNode) return;
    try {
      const config = JSON.parse(configDraft) as Record<string, unknown>;
      patchNode.mutate({ nodeId: selectedNode.id, body: { title: titleDraft, config } });
    } catch {
      toast.error("Config JSON inválido");
    }
  };

  const nodeActions = (node: WorkflowNode): ContextAction[] => [
    { label: "Editar configuración", action: () => setSelectedNodeId(node.id) },
    { label: "Duplicar nodo", action: () => duplicateNode.mutate(node.id) },
    { label: "Desactivar nodo", action: () => patchNode.mutate({ nodeId: node.id, body: { enabled: node.enabled === false } }) },
    { label: "Mover arriba", action: () => moveNode(node.id, -1) },
    { label: "Mover abajo", action: () => moveNode(node.id, 1) },
    { label: "Ver métricas", action: () => toast.info("Feature en construcción", { description: '"Ver métricas" estará disponible próximamente.' }) },
    { label: "Ver ejecuciones relacionadas", action: () => toast.info("Feature en construcción", { description: '"Ver ejecuciones" estará disponible próximamente.' }) },
    { label: "Eliminar", action: () => deleteNode.mutate(node.id), danger: true },
  ];

  return (
    <section className="flex min-w-0 flex-1 flex-col overflow-hidden border border-white/10 bg-[#0d1822]">
      <div className="flex flex-col gap-2 border-b border-white/10 px-3 py-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-sm font-semibold text-slate-100">Editor: {workflow.name}</h2>
            <Badge className="h-5 border-emerald-400/40 bg-emerald-500/10 px-1.5 text-[10px] text-emerald-200">
              {workflow.active ? "Publicado" : "Borrador"}
            </Badge>
          </div>
          <div className="mt-1 flex gap-6 text-[10px] text-slate-400">
            <span>Versión publicada v{workflow.published_version}</span>
            <span>Borrador v{workflow.draft_version}</span>
            <span>Último editor {workflow.last_editor ?? "Sistema"}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <Button variant="outline" size="sm" className="h-7 border-white/10 bg-white/5 text-[11px] text-slate-200" onClick={() => compare.mutate()}>
            <GitBranch className="mr-1 h-3 w-3" /> Comparar
          </Button>
          <Button variant="outline" size="sm" className="h-7 border-white/10 bg-white/5 text-[11px] text-slate-200" onClick={() => restore.mutate()}>
            <RotateCcw className="mr-1 h-3 w-3" /> Restaurar
          </Button>
          <Button variant="outline" size="sm" className="h-7 border-white/10 bg-white/5 text-[11px] text-slate-200" onClick={onRunSimulation}>
            <Play className="mr-1 h-3 w-3" /> Probar
          </Button>
          <Button size="sm" className="h-7 text-[11px]" onClick={() => saveDraft.mutate()}>
            <Save className="mr-1 h-3 w-3" /> Guardar draft
          </Button>
          <Button size="sm" className="h-7 bg-blue-600 text-[11px] hover:bg-blue-500" onClick={() => publish.mutate()}>
            Publicar cambios
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(430px,1fr)_300px]">
        <ScrollArea className="min-h-0 border-r border-white/10">
          <div className="p-3">
            {nodes.map((node, index) => {
              const meta = NODE_META[node.type] ?? DEFAULT_NODE_META;
              const Icon = meta.icon;
              const metrics = nodeMetrics(workflow, node.id);
              const selected = selectedNode?.id === node.id;
              const issue = workflow.validation.issues.find((item) => item.node_id === node.id);
              return (
                <div key={node.id} className="flex gap-2">
                  <div className="flex w-7 flex-col items-center pt-3">
                    <button
                      type="button"
                      className={cn(
                        "grid h-6 w-6 place-items-center rounded-full border text-[10px]",
                        selected ? "border-blue-400 bg-blue-500/20 text-blue-100" : "border-white/15 bg-white/5 text-slate-400",
                      )}
                      onClick={() => setSelectedNodeId(node.id)}
                      aria-label={`Seleccionar nodo ${index + 1}`}
                    >
                      {index + 1}
                    </button>
                    {index < nodes.length - 1 && <div className="h-8 w-px bg-white/15" />}
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedNodeId(node.id)}
                    onContextMenu={(event) => onContextMenu?.(event, nodeActions(node))}
                    className={cn(
                      "mb-2 grid min-h-14 flex-1 grid-cols-[1fr_54px_54px_54px_52px_1fr] items-center gap-2 rounded-md border px-2 py-2 text-left text-[11px]",
                      selected ? "border-blue-400/60 bg-blue-500/10" : "border-white/10 bg-[#101f2c] hover:bg-[#142637]",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md", meta.bg)}>
                        <Icon className={cn("h-3.5 w-3.5", meta.color)} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-slate-100">{meta.label}: {titleFor(node)}</span>
                        <span className="block truncate text-[10px] text-slate-400">{summaryFor(node)}</span>
                      </span>
                    </span>
                    <span className="text-slate-200">{pct(metrics.conversion_rate, 100)}</span>
                    <span className="text-slate-300">{String(metrics.entered ?? "0")}</span>
                    <span className="text-slate-300">{String(metrics.completed ?? "0")}</span>
                    <span className={Number(metrics.dropoff ?? 0) > 20 ? "text-red-300" : "text-slate-400"}>
                      {pct(metrics.dropoff)}
                    </span>
                    <span className="truncate text-right text-[10px] text-red-300">
                      {issue?.message ?? String(metrics.last_error ?? "—")}
                    </span>
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="mt-3 h-7 w-7 text-slate-300">
                        <MoreVertical className="h-3.5 w-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {nodeActions(node).map((action) => (
                        <DropdownMenuItem
                          key={action.label}
                          className={action.danger ? "text-destructive focus:text-destructive" : undefined}
                          onClick={action.action}
                        >
                          {action.label}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            })}
            <Button
              variant="outline"
              className="ml-9 mt-1 h-8 w-[calc(100%-2.25rem)] border-dashed border-white/15 bg-white/5 text-xs text-slate-300"
              onClick={() => addNode.mutate()}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" /> Agregar nodo aquí
            </Button>
          </div>
        </ScrollArea>

        <div className="flex min-h-0 flex-col">
          <div className="border-b border-white/10 p-3">
            <p className="text-xs font-semibold text-slate-100">Formulario de nodo</p>
            <p className="mt-1 text-[10px] text-slate-400">Edita la configuración del paso seleccionado.</p>
          </div>
          {selectedNode ? (
            <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
              <div>
                <Label className="text-[10px] uppercase text-slate-400">Título</Label>
                <Input
                  className="mt-1 h-8 border-white/10 bg-white/5 text-xs text-slate-100"
                  value={titleDraft}
                  onChange={(event) => setTitleDraft(event.target.value)}
                />
              </div>
              <div className="min-h-0 flex-1">
                <Label className="text-[10px] uppercase text-slate-400">Config JSON</Label>
                <Textarea
                  className="mt-1 h-[calc(100%-1.25rem)] resize-none border-white/10 bg-[#08131d] font-mono text-[11px] text-slate-200"
                  value={configDraft}
                  onChange={(event) => setConfigDraft(event.target.value)}
                />
              </div>
              {workflow.validation.issues.some((issue) => issue.node_id === selectedNode.id) && (
                <div className="rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
                  <AlertTriangle className="mr-1 inline h-3 w-3" />
                  {workflow.validation.issues.find((issue) => issue.node_id === selectedNode.id)?.message}
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" className="h-8 border-white/10 bg-white/5 text-xs text-slate-200" onClick={() => duplicateNode.mutate(selectedNode.id)}>
                  <Copy className="mr-1 h-3 w-3" /> Duplicar
                </Button>
                <Button className="h-8 text-xs" onClick={saveSelectedNode}>
                  <Save className="mr-1 h-3 w-3" /> Guardar nodo
                </Button>
                <Button variant="outline" className="h-8 border-white/10 bg-white/5 text-xs text-slate-200" onClick={() => moveNode(selectedNode.id, -1)}>
                  <ArrowUp className="mr-1 h-3 w-3" /> Subir
                </Button>
                <Button variant="outline" className="h-8 border-white/10 bg-white/5 text-xs text-slate-200" onClick={() => moveNode(selectedNode.id, 1)}>
                  <ArrowDown className="mr-1 h-3 w-3" /> Bajar
                </Button>
                <Button
                  variant="destructive"
                  className="col-span-2 h-8 text-xs"
                  disabled={selectedNode.type === "trigger"}
                  onClick={() => deleteNode.mutate(selectedNode.id)}
                >
                  <Trash2 className="mr-1 h-3 w-3" /> Eliminar nodo
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center text-xs text-slate-500">Selecciona un nodo</div>
          )}
        </div>
      </div>
    </section>
  );
}

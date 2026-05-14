import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { agentsApi } from "@/features/agents/api";
import { pipelineStagesApi, workflowsApi, type WorkflowItem, type WorkflowNode } from "@/features/workflows/api";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkflowCanvas } from "./WorkflowCanvas";
import { PublishDialog } from "./PublishDialog";
import { VersionCompareDialog } from "./VersionCompareDialog";
import { cn } from "@/lib/utils";

type ContextAction = { label: string; action: () => void; danger?: boolean };

type EditorMode = "design" | "simulation" | "production";

interface WorkflowEditorProps {
  workflow: WorkflowItem;
  onRunSimulation: () => void;
  onContextMenu?: (event: MouseEvent, actions: ContextAction[]) => void;
  onShowExecutions?: (nodeId: string) => void;
  focusNodeId?: string | null;
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
  assign_agent: { label: "Agente IA", icon: Bot, color: "text-blue-300", bg: "bg-blue-500/15" },
  move_stage: { label: "Mover etapa", icon: ArrowDown, color: "text-blue-300", bg: "bg-blue-500/15" },
  delay: { label: "Esperar", icon: RotateCcw, color: "text-slate-300", bg: "bg-white/10" },
  jump_to: { label: "Saltar a", icon: ArrowUp, color: "text-amber-300", bg: "bg-amber-500/15" },
  http_request: { label: "HTTP Request", icon: Send, color: "text-purple-300", bg: "bg-purple-500/15" },
  branch: { label: "Bifurcación", icon: GitBranch, color: "text-amber-300", bg: "bg-amber-500/15" },
  create_task: { label: "Acción", icon: CheckCircle2, color: "text-blue-300", bg: "bg-blue-500/15" },
  followup: { label: "Acción", icon: Send, color: "text-blue-300", bg: "bg-blue-500/15" },
  escalate_manager: { label: "Escalar", icon: ShieldCheck, color: "text-red-300", bg: "bg-red-500/15" },
  end: { label: "Final", icon: Workflow, color: "text-violet-300", bg: "bg-violet-500/15" },
};

type AddNodeTemplate = {
  key: string;
  label: string;
  description: string;
  body: { type: string; title: string; config: Record<string, unknown> };
};

const ADD_NODE_TEMPLATES: AddNodeTemplate[] = [
  {
    key: "message",
    label: "Enviar mensaje WhatsApp",
    description: "Envía un mensaje al lead en la conversación activa.",
    body: {
      type: "template_message",
      title: "Enviar mensaje WhatsApp",
      config: { template: "seguimiento_v2", text: "Hola {{nombre}}, seguimos atentos a tu solicitud." },
    },
  },
  {
    key: "assign_agent",
    label: "Asignar Agente IA",
    description: "Entrega la conversación a uno de tus Agentes IA.",
    body: {
      type: "assign_agent",
      title: "Asignar Agente IA",
      config: { agent_id: "" },
    },
  },
  {
    key: "move_stage",
    label: "Mover de etapa",
    description: "Mueve al lead a una etapa del pipeline.",
    body: {
      type: "move_stage",
      title: "Mover de etapa",
      config: { stage_id: "" },
    },
  },
  {
    key: "delay",
    label: "Esperar",
    description: "Pausa la ejecución antes del siguiente paso.",
    body: {
      type: "delay",
      title: "Esperar",
      config: { seconds: 3600 },
    },
  },
  {
    key: "condition",
    label: "Condición",
    description: "Bifurca el flujo según un campo del lead.",
    body: {
      type: "condition",
      title: "Condición",
      config: { field: "extracted.tipo_credito", operator: "eq", value: "nomina" },
    },
  },
  {
    key: "branch",
    label: "Bifurcación AND/OR",
    description: "Múltiples ramas con grupos de condiciones (AND/OR) y rama 'else'.",
    body: {
      type: "branch",
      title: "Bifurcación",
      config: {
        branches: [
          {
            label: "califica",
            group: {
              op: "and",
              rules: [
                { field: "extracted.tipo_credito", operator: "eq", value: "nomina" },
              ],
            },
          },
        ],
      },
    },
  },
  {
    key: "http_request",
    label: "HTTP Request",
    description: "Llama a un servicio externo (REST). Guarda la respuesta en variables.",
    body: {
      type: "http_request",
      title: "Llamar a servicio externo",
      config: { method: "POST", url: "https://api.example.com", timeout_seconds: 10, headers: {}, body: {} },
    },
  },
  {
    key: "jump_to",
    label: "Saltar a otro nodo",
    description: "Reintenta un paso anterior o crea un loop con tope de 100 pasos.",
    body: {
      type: "jump_to",
      title: "Saltar a",
      config: { target_node_id: "" },
    },
  },
  {
    key: "end",
    label: "Finalizar",
    description: "Marca el final del workflow.",
    body: {
      type: "end",
      title: "Finalizar workflow",
      config: { result: "completed" },
    },
  },
];

function titleFor(node: WorkflowNode) {
  return node.title || NODE_META[node.type]?.label || node.type;
}

function summaryFor(
  node: WorkflowNode,
  agentNameById?: Map<string, string>,
  triggerType?: string,
) {
  const cfg = node.config;
  if (node.type === "trigger") {
    return triggerLabel(triggerType ?? String(cfg.event ?? "message_received"));
  }
  if (node.type === "template_message") return `Plantilla: ${String(cfg.template ?? "sin plantilla")}`;
  if (node.type === "message") {
    const text = String(cfg.text ?? "").slice(0, 60);
    return text ? `“${text}${text.length === 60 ? "…" : ""}”` : "Mensaje sin texto";
  }
  if (node.type === "condition") return `Regla: ${String(cfg.field ?? "sin campo")} ${String(cfg.operator ?? "eq")}`;
  if (node.type === "advisor_pool") return `Pool: ${String(cfg.pool ?? "sin pool")}`;
  if (node.type === "assign_agent") {
    const id = String(cfg.agent_id ?? "");
    if (!id) return "Agente sin asignar";
    return `Agente: ${agentNameById?.get(id) ?? id.slice(0, 8)}`;
  }
  if (node.type === "move_stage") {
    const stage = String(cfg.stage_id ?? "");
    return stage ? `Etapa: ${stage}` : "Etapa sin definir";
  }
  if (node.type === "delay") {
    const seconds = Number(cfg.seconds ?? 0);
    if (!seconds) return "Duración sin definir";
    if (seconds < 60) return `Espera ${seconds}s`;
    if (seconds < 3600) return `Espera ${Math.round(seconds / 60)} min`;
    if (seconds < 86400) return `Espera ${Math.round(seconds / 3600)} h`;
    return `Espera ${Math.round(seconds / 86400)} d`;
  }
  if (node.type === "branch") {
    const branches = Array.isArray(cfg.branches) ? cfg.branches : [];
    if (branches.length === 0) return "Sin ramas";
    const first = (branches[0] as { label?: unknown } | undefined)?.label;
    return `${branches.length} rama${branches.length === 1 ? "" : "s"}${first ? ` · ${first}` : ""}`;
  }
  if (node.type === "jump_to") {
    const target = String(cfg.target_node_id ?? "");
    return target ? `Salta a ${target}` : "Destino sin definir";
  }
  if (node.type === "http_request") {
    const method = String(cfg.method ?? "GET");
    const url = String(cfg.url ?? "");
    return url ? `${method} ${url}` : `${method} sin URL`;
  }
  if (node.type === "request_documents") return "INE, comprobante, ingresos";
  if (node.type === "end") return String(cfg.result ?? "finaliza");
  return String(cfg.intent ?? cfg.field ?? cfg.title ?? cfg.reason ?? "configuración lista");
}

function readConfigString(configDraft: string, key: string): string {
  try {
    const parsed = JSON.parse(configDraft) as Record<string, unknown>;
    const value = parsed[key];
    return value == null ? "" : String(value);
  } catch {
    return "";
  }
}

function writeConfigValue(configDraft: string, key: string, value: string | number): string {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(configDraft) as Record<string, unknown>;
  } catch {
    parsed = {};
  }
  if (value === "" || value === null) delete parsed[key];
  else parsed[key] = value;
  return JSON.stringify(parsed, null, 2);
}

type DelayUnit = "seconds" | "minutes" | "hours" | "days";
const DELAY_UNIT_SECONDS: Record<DelayUnit, number> = {
  seconds: 1,
  minutes: 60,
  hours: 3600,
  days: 86400,
};

function readDelayParts(configDraft: string): { amount: number; unit: DelayUnit } {
  const seconds = Math.max(0, Number(readConfigString(configDraft, "seconds") || 0));
  if (seconds === 0) return { amount: 1, unit: "hours" };
  if (seconds % 86400 === 0) return { amount: seconds / 86400, unit: "days" };
  if (seconds % 3600 === 0) return { amount: seconds / 3600, unit: "hours" };
  if (seconds % 60 === 0) return { amount: seconds / 60, unit: "minutes" };
  return { amount: seconds, unit: "seconds" };
}

function writeDelayParts(configDraft: string, amount: number, unit: DelayUnit): string {
  const safeAmount = Math.max(1, Math.floor(amount));
  return writeConfigValue(configDraft, "seconds", safeAmount * DELAY_UNIT_SECONDS[unit]);
}

function readSelectedAgentId(configDraft: string): string {
  try {
    const parsed = JSON.parse(configDraft) as Record<string, unknown>;
    return typeof parsed.agent_id === "string" ? parsed.agent_id : "";
  } catch {
    return "";
  }
}

function writeSelectedAgentId(configDraft: string, agentId: string): string {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(configDraft) as Record<string, unknown>;
  } catch {
    parsed = {};
  }
  parsed.agent_id = agentId;
  return JSON.stringify(parsed, null, 2);
}

// Trigger catalog — must stay in sync with TRIGGERS in core/atendia/workflows/engine.py.
// Each trigger declares a label, a one-liner, and the shape of its config form.
type TriggerConfigField =
  | { key: string; label: string; kind: "text"; placeholder?: string; description?: string }
  | { key: string; label: string; kind: "csv"; placeholder?: string; description?: string }
  | { key: string; label: string; kind: "select"; options: Array<{ value: string; label: string }>; description?: string }
  | { key: string; label: string; kind: "stage"; description?: string };

interface TriggerDef {
  value: string;
  label: string;
  description: string;
  fields: TriggerConfigField[];
}

const TRIGGER_CATALOG: TriggerDef[] = [
  {
    value: "message_received",
    label: "Mensaje entrante",
    description: "Cualquier mensaje que envíe el lead a la conversación.",
    fields: [],
  },
  {
    value: "conversation_created",
    label: "Conversación iniciada",
    description: "Se inicia una nueva conversación con el contacto.",
    fields: [],
  },
  {
    value: "conversation_closed",
    label: "Conversación cerrada",
    description: "La conversación pasó a resuelta/cerrada/archivada.",
    fields: [
      {
        key: "category",
        label: "Filtrar por categoría (opcional)",
        kind: "text",
        placeholder: "p.ej. venta, no_califica, sin_respuesta",
        description: "Si lo dejas vacío, dispara para cualquier categoría.",
      },
    ],
  },
  {
    value: "webhook_received",
    label: "Webhook entrante",
    description: "Cuando un sistema externo hace POST al URL del workflow.",
    fields: [],
  },
  {
    value: "tag_updated",
    label: "Tag actualizado",
    description: "Se agregó o se quitó un tag a la conversación.",
    fields: [
      {
        key: "action",
        label: "Cuándo dispara",
        kind: "select",
        options: [
          { value: "", label: "Agregado o quitado" },
          { value: "added", label: "Solo cuando se agrega" },
          { value: "removed", label: "Solo cuando se quita" },
        ],
      },
      {
        key: "tags",
        label: "Tags específicos (opcional, separados por coma)",
        kind: "csv",
        placeholder: "vip, urgente, calificado",
        description: "Si lo dejas vacío, dispara para cualquier tag.",
      },
    ],
  },
  {
    value: "field_updated",
    label: "Campo de contacto actualizado",
    description: "Un campo del contacto cambió de valor.",
    fields: [
      { key: "field", label: "Campo", kind: "text", placeholder: "tipo_credito", description: "Nombre del campo (custom o estándar)." },
    ],
  },
  {
    value: "field_extracted",
    label: "Campo extraído por IA",
    description: "Un Agente IA extrajo un valor de la conversación.",
    fields: [
      { key: "field", label: "Campo", kind: "text", placeholder: "plan_credito" },
    ],
  },
  {
    value: "stage_entered",
    label: "Entró a etapa",
    description: "El lead llegó a una etapa específica del pipeline.",
    fields: [
      { key: "to", label: "Etapa de destino", kind: "stage" },
    ],
  },
  {
    value: "stage_changed",
    label: "Cambió de etapa",
    description: "El lead pasó de una etapa a otra (con filtros opcionales).",
    fields: [
      { key: "from", label: "Etapa origen (opcional)", kind: "stage" },
      { key: "to", label: "Etapa destino (opcional)", kind: "stage" },
    ],
  },
  {
    value: "appointment_created",
    label: "Cita creada",
    description: "Se agendó una cita para el contacto.",
    fields: [],
  },
  {
    value: "bot_paused",
    label: "Bot pausado",
    description: "Un humano (o un stage auto-handoff) pausó el bot para esta conversación.",
    fields: [],
  },
  // Fase 1+3+4 triggers — wired in the runner so workflows can react
  // to docs received, papelería completa, and handoff requests
  // without polling. Keep this block in sync with TRIGGERS in
  // core/atendia/workflows/engine.py.
  {
    value: "document_accepted",
    label: "Documento aceptado",
    description: "Vision validó una imagen y se marcó un DOCS_* en el cliente.",
    fields: [
      {
        key: "document_type",
        label: "Tipo de documento (opcional)",
        kind: "text",
        placeholder: "DOCS_INE_FRENTE, ine, comprobante…",
        description: "Limita el trigger a un DOCS_* específico. Vacío = cualquier doc aceptado.",
      },
    ],
  },
  {
    value: "document_rejected",
    label: "Documento rechazado",
    description: "Vision rechazó una imagen (reflejo, ilegible, etc.).",
    fields: [
      {
        key: "document_type",
        label: "Tipo de documento (opcional)",
        kind: "text",
        placeholder: "DOCS_INE_FRENTE, ine, comprobante…",
      },
    ],
  },
  {
    value: "docs_complete_for_plan",
    label: "Papelería completa",
    description: "El cliente cumplió todos los documentos requeridos por su plan.",
    fields: [
      {
        key: "plan_credito",
        label: "Filtrar por plan (opcional)",
        kind: "text",
        placeholder: "nomina_tarjeta_10, sin_comprobantes_25…",
        description: "Si lo dejas vacío, dispara para cualquier plan.",
      },
    ],
  },
  {
    value: "human_handoff_requested",
    label: "Handoff humano solicitado",
    description: "El bot solicitó intervención humana (papelería completa, fuera de 24h, error, etc.).",
    fields: [
      {
        key: "reason",
        label: "Razón específica (opcional)",
        kind: "select",
        options: [
          { value: "", label: "Cualquier razón" },
          { value: "docs_complete_for_plan", label: "Papelería completa" },
          { value: "outside_24h_window", label: "Fuera de 24h" },
          { value: "composer_failed", label: "Composer falló" },
          { value: "obstacle_no_solution", label: "Obstáculo sin solución" },
          { value: "stage_triggered_handoff", label: "Stage con auto-handoff" },
          { value: "antiguedad_lt_6m", label: "Antigüedad < 6 meses" },
        ],
      },
    ],
  },
];

function triggerLabel(value: string): string {
  return TRIGGER_CATALOG.find((t) => t.value === value)?.label ?? value;
}

function nodeMetrics(workflow: WorkflowItem, nodeId: string) {
  const ops = workflow.definition.ops as { node_metrics?: Record<string, Record<string, unknown>> } | undefined;
  return ops?.node_metrics?.[nodeId] ?? {};
}

function pct(value: unknown, fallback = 0) {
  return typeof value === "number" ? `${value}%` : `${fallback}%`;
}

export function WorkflowEditor({ workflow, onRunSimulation, onContextMenu, onShowExecutions, focusNodeId }: WorkflowEditorProps) {
  const qc = useQueryClient();
  const nodes = workflow.definition.nodes;
  const [selectedNodeId, setSelectedNodeId] = useState(nodes[0]?.id ?? "");
  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) ?? nodes[0],
    [nodes, selectedNodeId],
  );
  const [titleDraft, setTitleDraft] = useState("");
  const [configDraft, setConfigDraft] = useState("{}");
  const [nameDraft, setNameDraft] = useState(workflow.name);
  const [renaming, setRenaming] = useState(false);
  const [mode, setMode] = useState<EditorMode>("design");
  const [publishOpen, setPublishOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);

  useEffect(() => {
    setNameDraft(workflow.name);
    setRenaming(false);
  }, [workflow.id, workflow.name]);

  const readOnly = workflow.active;

  useEffect(() => {
    if (!selectedNode) return;
    setSelectedNodeId(selectedNode.id);
    setTitleDraft(selectedNode.title ?? "");
    setConfigDraft(JSON.stringify(selectedNode.config ?? {}, null, 2));
  }, [selectedNode?.id]);

  useEffect(() => {
    if (focusNodeId && nodes.some((n) => n.id === focusNodeId)) {
      setSelectedNodeId(focusNodeId);
      requestAnimationFrame(() => {
        const el = document.querySelector(`[data-node-row="${focusNodeId}"]`);
        if (el && "scrollIntoView" in el) {
          (el as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
    }
  }, [focusNodeId, nodes]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["workflows"] });

  const renameWorkflow = useMutation({
    mutationFn: (name: string) => workflowsApi.patch(workflow.id, { name }),
    onSuccess: () => {
      void invalidate();
      toast.success("Nombre actualizado");
    },
    onError: (error) => {
      setNameDraft(workflow.name);
      toast.error("No se pudo renombrar", { description: error.message });
    },
  });

  const commitRename = () => {
    const next = nameDraft.trim();
    setRenaming(false);
    if (!next) {
      setNameDraft(workflow.name);
      return;
    }
    if (next === workflow.name) return;
    renameWorkflow.mutate(next);
  };

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
    mutationFn: (body: AddNodeTemplate["body"]) => workflowsApi.addNode(workflow.id, body),
    onSuccess: (updated) => {
      void invalidate();
      const last = updated.definition.nodes.at(-1);
      if (last) setSelectedNodeId(last.id);
      toast.success("Nodo agregado");
    },
  });

  const agentsQuery = useQuery({
    queryKey: ["agents", "for-workflow-editor"],
    queryFn: agentsApi.list,
    staleTime: 60_000,
  });
  const agents = agentsQuery.data ?? [];
  const agentNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const agent of agents) map.set(agent.id, agent.name);
    return map;
  }, [agents]);

  const stagesQuery = useQuery({
    queryKey: ["pipeline", "stages"],
    queryFn: pipelineStagesApi.list,
    staleTime: 60_000,
  });
  const stages = stagesQuery.data ?? [];

  const patchTrigger = useMutation({
    mutationFn: (body: { trigger_type: string; trigger_config: Record<string, unknown> }) =>
      workflowsApi.patch(workflow.id, body),
    onSuccess: () => {
      void invalidate();
      toast.success("Disparador actualizado");
    },
    onError: (error) => toast.error("No se pudo actualizar el disparador", { description: error.message }),
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

  const saveDraft = useMutation({
    mutationFn: () => workflowsApi.saveDraft(workflow.id),
    onSuccess: () => {
      void invalidate();
      toast.success("Borrador guardado");
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

  const showNodeMetrics = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    // Defer so the row is rendered+selected before we ask the browser to scroll.
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-node-row="${nodeId}"]`);
      if (el && "scrollIntoView" in el) {
        (el as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    const metrics = nodeMetrics(workflow, nodeId);
    const entered = String(metrics.entered ?? "0");
    const completed = String(metrics.completed ?? "0");
    const dropoff = pct(metrics.dropoff);
    toast.info(`Métricas del nodo`, {
      description: `Entraron ${entered} · completaron ${completed} · drop-off ${dropoff}`,
    });
  };

  const nodeActions = (node: WorkflowNode): ContextAction[] => [
    { label: "Editar configuración", action: () => setSelectedNodeId(node.id) },
    { label: "Duplicar nodo", action: () => duplicateNode.mutate(node.id) },
    { label: "Desactivar nodo", action: () => patchNode.mutate({ nodeId: node.id, body: { enabled: node.enabled === false } }) },
    { label: "Mover arriba", action: () => moveNode(node.id, -1) },
    { label: "Mover abajo", action: () => moveNode(node.id, 1) },
    { label: "Ver métricas", action: () => showNodeMetrics(node.id) },
    {
      label: "Ver ejecuciones relacionadas",
      action: () => {
        if (onShowExecutions) {
          onShowExecutions(node.id);
        } else {
          toast.info("Filtro de ejecuciones no disponible en esta vista");
        }
      },
    },
    { label: "Eliminar", action: () => deleteNode.mutate(node.id), danger: true },
  ];

  return (
    <section className="flex min-w-0 flex-1 flex-col overflow-hidden border border-white/10 bg-[#0d1822]">
      <div className="flex flex-col gap-2 border-b border-white/10 px-3 py-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="shrink-0 text-sm font-semibold text-slate-100">Editor:</span>
            {renaming && !readOnly ? (
              <Input
                autoFocus
                value={nameDraft}
                onChange={(event) => setNameDraft(event.target.value)}
                onBlur={commitRename}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    (event.target as HTMLInputElement).blur();
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setNameDraft(workflow.name);
                    setRenaming(false);
                  }
                }}
                className="h-6 max-w-[260px] border-blue-400/40 bg-white/10 px-1.5 text-sm font-semibold text-slate-100"
              />
            ) : (
              <button
                type="button"
                disabled={readOnly}
                onClick={() => !readOnly && setRenaming(true)}
                title={readOnly ? "Detén el workflow para editar el nombre" : "Click para renombrar"}
                className={cn(
                  "truncate rounded px-1 text-sm font-semibold text-slate-100",
                  readOnly ? "cursor-not-allowed opacity-80" : "hover:bg-white/10",
                )}
              >
                {workflow.name}
              </button>
            )}
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
          <Button variant="outline" size="sm" className="h-7 border-white/10 bg-white/5 text-[11px] text-slate-200" onClick={() => setCompareOpen(true)}>
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
          <Button size="sm" className="h-7 bg-blue-600 text-[11px] hover:bg-blue-500" onClick={() => setPublishOpen(true)}>
            Publicar cambios
          </Button>
        </div>
      </div>

      <div className="border-b border-white/10 px-3">
        <Tabs
          value={mode}
          onValueChange={(value) => {
            const next = value as EditorMode;
            setMode(next);
            if (next === "simulation") onRunSimulation();
          }}
        >
          <TabsList className="h-8 bg-transparent p-0">
            <TabsTrigger value="design" className="h-7 px-3 text-[11px] data-[state=active]:bg-white/10 data-[state=active]:text-slate-100">
              Diseño
            </TabsTrigger>
            <TabsTrigger value="simulation" className="h-7 px-3 text-[11px] data-[state=active]:bg-white/10 data-[state=active]:text-slate-100">
              Simulación
            </TabsTrigger>
            <TabsTrigger value="production" className="h-7 px-3 text-[11px] data-[state=active]:bg-white/10 data-[state=active]:text-slate-100">
              Producción
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(430px,1fr)_300px]">
        <WorkflowCanvas
          nodes={nodes}
          edges={workflow.definition.edges ?? []}
          selectedNodeId={selectedNode?.id ?? ""}
          onSelect={setSelectedNodeId}
          onContextMenu={(event, nodeId) => {
            const node = nodes.find((n) => n.id === nodeId);
            if (node) onContextMenu?.(event, nodeActions(node));
          }}
          nodeMeta={(type) => NODE_META[type] ?? DEFAULT_NODE_META}
          titleFor={titleFor}
          summaryFor={(node) => summaryFor(node, agentNameById, workflow.trigger_type)}
          nodeMetrics={(nodeId) => nodeMetrics(workflow, nodeId)}
          issueForNode={(nodeId) => {
            const issue = workflow.validation.issues.find((item) => item.node_id === nodeId);
            return issue ? { message: issue.message } : undefined;
          }}
          readOnly={readOnly}
          addNodeMenu={
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-md text-slate-300 hover:bg-white/5"
                  disabled={readOnly}
                  title="Agregar nodo"
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-72">
                {ADD_NODE_TEMPLATES.map((template) => (
                  <DropdownMenuItem
                    key={template.key}
                    onClick={() => addNode.mutate(template.body)}
                    className="flex flex-col items-start gap-0.5"
                  >
                    <span className="font-medium">{template.label}</span>
                    <span className="text-[10px] text-muted-foreground">{template.description}</span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          }
        />

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
                  disabled={readOnly}
                />
              </div>
              {selectedNode.type === "trigger" && (
                <div className="space-y-2 rounded-md border border-white/10 bg-white/5 p-2">
                  <div>
                    <Label className="text-[10px] uppercase text-slate-400">Tipo de disparador</Label>
                    <select
                      className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                      value={workflow.trigger_type}
                      disabled={readOnly}
                      onChange={(event) => {
                        patchTrigger.mutate({
                          trigger_type: event.target.value,
                          trigger_config: {},
                        });
                      }}
                    >
                      {TRIGGER_CATALOG.map((trigger) => (
                        <option key={trigger.value} value={trigger.value}>
                          {trigger.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-[10px] text-slate-400">
                      {TRIGGER_CATALOG.find((t) => t.value === workflow.trigger_type)?.description}
                    </p>
                  </div>
                  {workflow.trigger_type === "webhook_received" && (
                    <div>
                      <Label className="text-[10px] uppercase text-slate-400">URL del webhook</Label>
                      {workflow.webhook_url ? (
                        <div className="mt-1 flex gap-1">
                          <Input
                            readOnly
                            value={`${window.location.origin}${workflow.webhook_url}`}
                            className="h-8 border-white/10 bg-black/30 font-mono text-[10px] text-slate-100"
                            onClick={(event) => (event.target as HTMLInputElement).select()}
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8 border-white/10 bg-white/5 text-[10px] text-slate-200"
                            onClick={() => {
                              void navigator.clipboard.writeText(`${window.location.origin}${workflow.webhook_url}`);
                              toast.success("URL copiada");
                            }}
                          >
                            Copiar
                          </Button>
                        </div>
                      ) : (
                        <p className="mt-1 rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
                          Guarda el workflow para generar la URL pública.
                        </p>
                      )}
                      <p className="mt-1 text-[10px] text-slate-500">
                        Envía un POST con JSON a este URL. El workflow debe estar publicado para aceptar peticiones.
                      </p>
                    </div>
                  )}
                  {(TRIGGER_CATALOG.find((t) => t.value === workflow.trigger_type)?.fields ?? []).map((field) => {
                    const rawValue = (workflow.trigger_config as Record<string, unknown>)[field.key];
                    const currentValue =
                      field.kind === "csv" && Array.isArray(rawValue)
                        ? (rawValue as string[]).join(", ")
                        : String(rawValue ?? "");
                    const commit = (next: string) => {
                      const config = { ...(workflow.trigger_config as Record<string, unknown>) };
                      if (field.kind === "csv") {
                        const items = next.split(",").map((t) => t.trim()).filter(Boolean);
                        if (items.length) config[field.key] = items;
                        else delete config[field.key];
                      } else if (next) {
                        config[field.key] = next;
                      } else {
                        delete config[field.key];
                      }
                      patchTrigger.mutate({ trigger_type: workflow.trigger_type, trigger_config: config });
                    };
                    return (
                      <div key={field.key}>
                        <Label className="text-[10px] uppercase text-slate-400">{field.label}</Label>
                        {(field.kind === "text" || field.kind === "csv") && (
                          <Input
                            className="mt-1 h-8 border-white/10 bg-white/5 text-xs text-slate-100"
                            placeholder={field.placeholder}
                            defaultValue={currentValue}
                            disabled={readOnly}
                            onBlur={(event) => {
                              if (event.target.value !== currentValue) commit(event.target.value);
                            }}
                          />
                        )}
                        {field.kind === "select" && (
                          <select
                            className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                            value={currentValue}
                            disabled={readOnly}
                            onChange={(event) => commit(event.target.value)}
                          >
                            <option value="">— Selecciona —</option>
                            {field.options.map((option) => (
                              <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                          </select>
                        )}
                        {field.kind === "stage" && (
                          stages.length === 0 ? (
                            <p className="mt-1 rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
                              No hay pipeline activo. Configura uno en la sección de Pipeline.
                            </p>
                          ) : (
                            <select
                              className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                              value={currentValue}
                              disabled={readOnly}
                              onChange={(event) => commit(event.target.value)}
                            >
                              <option value="">— Cualquier etapa —</option>
                              {stages.map((stage) => (
                                <option key={stage.id} value={stage.id}>{stage.label}</option>
                              ))}
                            </select>
                          )
                        )}
                        {field.description && (
                          <p className="mt-1 text-[10px] text-slate-500">{field.description}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {selectedNode.type === "move_stage" && (
                <div>
                  <Label className="text-[10px] uppercase text-slate-400">Etapa destino</Label>
                  {stages.length === 0 ? (
                    <p className="mt-1 rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
                      No hay pipeline activo. Configura uno en la sección de Pipeline.
                    </p>
                  ) : (
                    <select
                      className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                      value={readConfigString(configDraft, "stage_id")}
                      disabled={readOnly}
                      onChange={(event) => setConfigDraft(writeConfigValue(configDraft, "stage_id", event.target.value))}
                    >
                      <option value="">— Selecciona una etapa —</option>
                      {stages.map((stage) => (
                        <option key={stage.id} value={stage.id}>{stage.label}</option>
                      ))}
                    </select>
                  )}
                </div>
              )}
              {selectedNode.type === "delay" && (
                <div className="grid grid-cols-[1fr_120px] gap-2">
                  <div>
                    <Label className="text-[10px] uppercase text-slate-400">Esperar</Label>
                    <Input
                      type="number"
                      min={1}
                      className="mt-1 h-8 border-white/10 bg-white/5 text-xs text-slate-100"
                      value={readDelayParts(configDraft).amount}
                      disabled={readOnly}
                      onChange={(event) => {
                        const amount = Math.max(1, Number(event.target.value || 1));
                        const { unit } = readDelayParts(configDraft);
                        setConfigDraft(writeDelayParts(configDraft, amount, unit));
                      }}
                    />
                  </div>
                  <div>
                    <Label className="text-[10px] uppercase text-slate-400">Unidad</Label>
                    <select
                      className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                      value={readDelayParts(configDraft).unit}
                      disabled={readOnly}
                      onChange={(event) => {
                        const { amount } = readDelayParts(configDraft);
                        setConfigDraft(writeDelayParts(configDraft, amount, event.target.value as DelayUnit));
                      }}
                    >
                      <option value="seconds">Segundos</option>
                      <option value="minutes">Minutos</option>
                      <option value="hours">Horas</option>
                      <option value="days">Días</option>
                    </select>
                  </div>
                </div>
              )}
              {selectedNode.type === "jump_to" && (
                <div>
                  <Label className="text-[10px] uppercase text-slate-400">Saltar a nodo</Label>
                  <select
                    className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                    value={readConfigString(configDraft, "target_node_id")}
                    disabled={readOnly}
                    onChange={(event) => setConfigDraft(writeConfigValue(configDraft, "target_node_id", event.target.value))}
                  >
                    <option value="">— Selecciona un nodo —</option>
                    {nodes
                      .filter((n) => n.id !== selectedNode.id && n.type !== "end")
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {titleFor(n)} ({n.type})
                        </option>
                      ))}
                  </select>
                  <p className="mt-1 text-[10px] text-slate-500">
                    Útil para reintentar una pregunta o volver a un paso anterior. El motor corta loops al pasar de 100 pasos.
                  </p>
                </div>
              )}
              {selectedNode.type === "branch" && (
                <BranchEditor
                  configDraft={configDraft}
                  readOnly={readOnly}
                  onChange={setConfigDraft}
                />
              )}
              {selectedNode.type === "http_request" && (
                <div className="space-y-2 rounded-md border border-white/10 bg-white/5 p-2">
                  <div className="grid grid-cols-[100px_1fr] gap-2">
                    <div>
                      <Label className="text-[10px] uppercase text-slate-400">Método</Label>
                      <select
                        className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                        value={readConfigString(configDraft, "method") || "GET"}
                        disabled={readOnly}
                        onChange={(event) => setConfigDraft(writeConfigValue(configDraft, "method", event.target.value))}
                      >
                        <option value="GET">GET</option>
                        <option value="POST">POST</option>
                        <option value="PUT">PUT</option>
                        <option value="PATCH">PATCH</option>
                        <option value="DELETE">DELETE</option>
                      </select>
                    </div>
                    <div>
                      <Label className="text-[10px] uppercase text-slate-400">URL</Label>
                      <Input
                        className="mt-1 h-8 border-white/10 bg-white/5 text-xs text-slate-100"
                        placeholder="https://api.tu-servicio.com/leads"
                        defaultValue={readConfigString(configDraft, "url")}
                        disabled={readOnly}
                        onBlur={(event) => setConfigDraft(writeConfigValue(configDraft, "url", event.target.value))}
                      />
                    </div>
                  </div>
                  <div>
                    <Label className="text-[10px] uppercase text-slate-400">Timeout (s)</Label>
                    <Input
                      type="number"
                      min={1}
                      max={60}
                      className="mt-1 h-8 border-white/10 bg-white/5 text-xs text-slate-100"
                      defaultValue={readConfigString(configDraft, "timeout_seconds") || "10"}
                      disabled={readOnly}
                      onBlur={(event) => setConfigDraft(writeConfigValue(configDraft, "timeout_seconds", String(Math.max(1, Math.min(60, Number(event.target.value || 10))))))}
                    />
                  </div>
                  <p className="text-[10px] text-slate-500">
                    Headers y body se editan en el Config JSON. La respuesta se guardará en variables si configuras <code>save_to</code>.
                  </p>
                </div>
              )}
              {selectedNode.type === "assign_agent" && (
                <div>
                  <Label className="text-[10px] uppercase text-slate-400">Agente IA</Label>
                  {agents.length === 0 ? (
                    <p className="mt-1 rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
                      Aún no tienes agentes. Crea uno en la sección de Agentes para poder seleccionarlo aquí.
                    </p>
                  ) : (
                    <select
                      className="mt-1 h-8 w-full rounded-md border border-white/10 bg-white/5 px-2 text-xs text-slate-100"
                      value={readSelectedAgentId(configDraft)}
                      disabled={readOnly}
                      onChange={(event) => {
                        const nextId = event.target.value;
                        setConfigDraft((previous) => writeSelectedAgentId(previous, nextId));
                      }}
                    >
                      <option value="">— Selecciona un agente —</option>
                      {agents.map((agent) => (
                        <option key={agent.id} value={agent.id}>
                          {agent.name} {agent.status !== "production" ? `· ${agent.status}` : ""}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
              <div className="min-h-0 flex-1">
                <Label className="text-[10px] uppercase text-slate-400">Config JSON</Label>
                <Textarea
                  className="mt-1 h-[calc(100%-1.25rem)] resize-none border-white/10 bg-[#08131d] font-mono text-[11px] text-slate-200"
                  value={configDraft}
                  onChange={(event) => setConfigDraft(event.target.value)}
                  disabled={readOnly}
                />
              </div>
              {workflow.validation.issues.some((issue) => issue.node_id === selectedNode.id) && (
                <div className="rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[11px] text-amber-100">
                  <AlertTriangle className="mr-1 inline h-3 w-3" />
                  {workflow.validation.issues.find((issue) => issue.node_id === selectedNode.id)?.message}
                </div>
              )}
              {readOnly && (
                <div className="rounded-md border border-emerald-400/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-100">
                  Este workflow está publicado. Detén el workflow para poder editarlo.
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" className="h-8 border-white/10 bg-white/5 text-xs text-slate-200" onClick={() => duplicateNode.mutate(selectedNode.id)} disabled={readOnly}>
                  <Copy className="mr-1 h-3 w-3" /> Duplicar
                </Button>
                <Button className="h-8 text-xs" onClick={saveSelectedNode} disabled={readOnly}>
                  <Save className="mr-1 h-3 w-3" /> Guardar nodo
                </Button>
                <Button variant="outline" className="h-8 border-white/10 bg-white/5 text-xs text-slate-200" onClick={() => moveNode(selectedNode.id, -1)} disabled={readOnly}>
                  <ArrowUp className="mr-1 h-3 w-3" /> Subir
                </Button>
                <Button variant="outline" className="h-8 border-white/10 bg-white/5 text-xs text-slate-200" onClick={() => moveNode(selectedNode.id, 1)} disabled={readOnly}>
                  <ArrowDown className="mr-1 h-3 w-3" /> Bajar
                </Button>
                <Button
                  variant="destructive"
                  className="col-span-2 h-8 text-xs"
                  disabled={selectedNode.type === "trigger" || readOnly}
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

      <PublishDialog
        workflow={workflow}
        open={publishOpen}
        onOpenChange={setPublishOpen}
        onPublished={() => qc.invalidateQueries({ queryKey: ["workflows"] })}
      />
      <VersionCompareDialog workflow={workflow} open={compareOpen} onOpenChange={setCompareOpen} />
    </section>
  );
}

type BranchRule = { field: string; operator: string; value: string };
type BranchGroup = { op: "and" | "or"; rules: BranchRule[] };
type Branch = { label: string; group: BranchGroup };
type BranchConfig = { branches: Branch[] };

const BRANCH_OPERATORS: Array<{ value: string; label: string; needsValue: boolean }> = [
  { value: "eq", label: "es igual a", needsValue: true },
  { value: "neq", label: "no es igual a", needsValue: true },
  { value: "contains", label: "contiene", needsValue: true },
  { value: "not_contains", label: "no contiene", needsValue: true },
  { value: "gt", label: ">", needsValue: true },
  { value: "gte", label: "≥", needsValue: true },
  { value: "lt", label: "<", needsValue: true },
  { value: "lte", label: "≤", needsValue: true },
  { value: "exists", label: "existe", needsValue: false },
  { value: "not_exists", label: "no existe", needsValue: false },
];

function parseBranchConfig(configDraft: string): BranchConfig {
  try {
    const parsed = JSON.parse(configDraft) as Partial<BranchConfig>;
    if (Array.isArray(parsed.branches)) {
      return {
        branches: parsed.branches.map((branch) => ({
          label: typeof branch.label === "string" ? branch.label : "rama",
          group: {
            op: branch.group?.op === "or" ? "or" : "and",
            rules: Array.isArray(branch.group?.rules)
              ? branch.group.rules
                  .filter((rule): rule is BranchRule => rule != null && typeof rule === "object" && !("rules" in rule))
                  .map((rule) => ({
                    field: String(rule.field ?? ""),
                    operator: String(rule.operator ?? "eq"),
                    value: rule.value == null ? "" : String(rule.value),
                  }))
              : [],
          },
        })),
      };
    }
  } catch {
    // fall through
  }
  return { branches: [] };
}

function serializeBranchConfig(config: BranchConfig): string {
  return JSON.stringify(
    {
      branches: config.branches.map((branch) => ({
        label: branch.label,
        group: {
          op: branch.group.op,
          rules: branch.group.rules.map((rule) => {
            const operator = BRANCH_OPERATORS.find((op) => op.value === rule.operator);
            const out: Record<string, unknown> = { field: rule.field, operator: rule.operator };
            if (operator?.needsValue) out.value = rule.value;
            return out;
          }),
        },
      })),
    },
    null,
    2,
  );
}

function BranchEditor({
  configDraft,
  readOnly,
  onChange,
}: {
  configDraft: string;
  readOnly: boolean;
  onChange: (next: string) => void;
}) {
  const config = parseBranchConfig(configDraft);
  const commit = (next: BranchConfig) => onChange(serializeBranchConfig(next));

  const updateBranch = (branchIndex: number, update: (branch: Branch) => Branch) => {
    const branches = config.branches.map((branch, index) =>
      index === branchIndex ? update(branch) : branch,
    );
    commit({ branches });
  };

  const updateRule = (
    branchIndex: number,
    ruleIndex: number,
    update: (rule: BranchRule) => BranchRule,
  ) => {
    updateBranch(branchIndex, (branch) => ({
      ...branch,
      group: {
        ...branch.group,
        rules: branch.group.rules.map((rule, index) => (index === ruleIndex ? update(rule) : rule)),
      },
    }));
  };

  const addBranch = () => {
    commit({
      branches: [
        ...config.branches,
        { label: `rama_${config.branches.length + 1}`, group: { op: "and", rules: [{ field: "extracted.", operator: "eq", value: "" }] } },
      ],
    });
  };

  return (
    <div className="space-y-2 rounded-md border border-white/10 bg-white/5 p-2">
      <div className="flex items-center justify-between">
        <Label className="text-[10px] uppercase text-slate-400">Ramas (en orden de evaluación)</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-6 border-white/10 bg-white/5 text-[10px] text-slate-200"
          disabled={readOnly}
          onClick={addBranch}
        >
          <Plus className="mr-1 h-3 w-3" /> Rama
        </Button>
      </div>
      {config.branches.length === 0 && (
        <p className="text-[10px] text-slate-500">Sin ramas. Agrega al menos una; las que no coincidan caerán a la rama "else".</p>
      )}
      {config.branches.map((branch, branchIndex) => (
        <div key={branchIndex} className="space-y-1.5 rounded-md border border-white/10 bg-black/20 p-2">
          <div className="flex items-center gap-1.5">
            <Input
              className="h-7 flex-1 border-white/10 bg-white/5 text-[11px] text-slate-100"
              placeholder="Etiqueta (debe coincidir con la arista)"
              defaultValue={branch.label}
              disabled={readOnly}
              onBlur={(event) => {
                const value = event.target.value.trim() || `rama_${branchIndex + 1}`;
                updateBranch(branchIndex, (current) => ({ ...current, label: value }));
              }}
            />
            <select
              className="h-7 rounded-md border border-white/10 bg-white/5 px-1.5 text-[11px] text-slate-100"
              value={branch.group.op}
              disabled={readOnly}
              onChange={(event) => {
                const op = event.target.value as "and" | "or";
                updateBranch(branchIndex, (current) => ({ ...current, group: { ...current.group, op } }));
              }}
            >
              <option value="and">Y</option>
              <option value="or">O</option>
            </select>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-red-300 hover:text-red-200"
              disabled={readOnly}
              onClick={() => {
                commit({ branches: config.branches.filter((_, index) => index !== branchIndex) });
              }}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
          {branch.group.rules.map((rule, ruleIndex) => {
            const operatorDef = BRANCH_OPERATORS.find((op) => op.value === rule.operator);
            return (
              <div key={ruleIndex} className="grid grid-cols-[1fr_110px_1fr_24px] gap-1">
                <Input
                  className="h-7 border-white/10 bg-white/5 text-[10px] text-slate-100"
                  placeholder="extracted.campo"
                  defaultValue={rule.field}
                  disabled={readOnly}
                  onBlur={(event) => {
                    const value = event.target.value;
                    updateRule(branchIndex, ruleIndex, (current) => ({ ...current, field: value }));
                  }}
                />
                <select
                  className="h-7 rounded-md border border-white/10 bg-white/5 px-1 text-[10px] text-slate-100"
                  value={rule.operator}
                  disabled={readOnly}
                  onChange={(event) => {
                    const operator = event.target.value;
                    updateRule(branchIndex, ruleIndex, (current) => ({ ...current, operator }));
                  }}
                >
                  {BRANCH_OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>{op.label}</option>
                  ))}
                </select>
                <Input
                  className="h-7 border-white/10 bg-white/5 text-[10px] text-slate-100"
                  placeholder={operatorDef?.needsValue ? "valor" : "(sin valor)"}
                  defaultValue={rule.value}
                  disabled={readOnly || !operatorDef?.needsValue}
                  onBlur={(event) => {
                    const value = event.target.value;
                    updateRule(branchIndex, ruleIndex, (current) => ({ ...current, value }));
                  }}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-slate-400 hover:text-red-300"
                  disabled={readOnly}
                  onClick={() => {
                    updateBranch(branchIndex, (current) => ({
                      ...current,
                      group: {
                        ...current.group,
                        rules: current.group.rules.filter((_, index) => index !== ruleIndex),
                      },
                    }));
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            );
          })}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-6 w-full border-dashed border-white/15 bg-white/5 text-[10px] text-slate-200"
            disabled={readOnly}
            onClick={() => {
              updateBranch(branchIndex, (current) => ({
                ...current,
                group: {
                  ...current.group,
                  rules: [...current.group.rules, { field: "extracted.", operator: "eq", value: "" }],
                },
              }));
            }}
          >
            <Plus className="mr-1 h-3 w-3" /> Regla
          </Button>
        </div>
      ))}
      <p className="text-[10px] text-slate-500">
        Conecta una arista por cada etiqueta de rama. Para una rama "else", conecta una arista con etiqueta <code>else</code>.
      </p>
    </div>
  );
}

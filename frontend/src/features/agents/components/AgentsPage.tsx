import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  BrainCircuit,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  Download,
  FileJson,
  FlaskConical,
  GitBranch,
  Globe2,
  History,
  Loader2,
  MessageCircle,
  MoreVertical,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  TestTube2,
  Trash2,
  UploadCloud,
  UserCheck,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  agentsApi,
  type AgentItem,
  type AgentPayload,
  type DecisionMap,
  type ExtractionField,
  type Guardrail,
  type PreviewResult,
  type ValidationResult,
} from "@/features/agents/api";
import { DemoBadge } from "@/components/DemoBadge";
import { NYIButton } from "@/components/NYIButton";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

const roleOptions = [
  { value: "reception", label: "Recepcionista", detail: "Entrada, calificación y captura" },
  { value: "sales_agent", label: "Sales agent", detail: "Venta, objeciones y cotización" },
  { value: "duda_general", label: "Duda general", detail: "FAQ, horarios y catálogo" },
  { value: "postventa", label: "Postventa", detail: "Servicio, garantía y seguimiento" },
  { value: "sales", label: "Ventas", detail: "Rol legacy" },
  { value: "support", label: "Soporte", detail: "Rol legacy" },
  { value: "custom", label: "Custom", detail: "Configuración libre" },
] as const;

const toneOptions = ["Cálido", "Claro y conciso", "Consultivo", "Formal", "Empático", "Directo"];
const languageOptions = [
  { value: "es", label: "Español (México)" },
  { value: "en", label: "English" },
  { value: "both", label: "Bilingüe" },
];
const intentOptions = [
  "GREETING",
  "ASK_INFO",
  "ASK_PRICE",
  "BUY",
  "SCHEDULE",
  "COMPLAIN",
  "OFF_TOPIC",
  "UNCLEAR",
  "CREDIT_APPLICATION",
  "SERVICE_REQUEST",
  "POSTSALE",
  "HUMAN_REQUESTED",
];

// Wired tabs: each one reads or writes data the runner actually uses
// on every inbound turn. Decision Map / Pruebas remain hidden until
// their backends are real.
const tabs = [
  "Identidad",
  "Guardrails",
  "Knowledge",
  "Monitor",
  "Extracción",
] as const;

type AgentTab = (typeof tabs)[number];
type ComparisonResult = Awaited<ReturnType<typeof agentsApi.compare>>;
type ContextMenuTarget =
  | { kind: "agent"; agentId: string }
  | { kind: "guardrail"; itemId: string }
  | { kind: "field"; itemId: string };
type ContextMenuState = ContextMenuTarget & { x: number; y: number };

function roleLabel(role: string): string {
  return roleOptions.find((item) => item.value === role)?.label ?? role;
}

function roleDetail(role: string): string {
  return roleOptions.find((item) => item.value === role)?.detail ?? "Perfil operativo";
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: "Borrador",
    validation: "Validación",
    testing: "Pruebas",
    production: "Producción",
    paused: "Pausado",
  };
  return labels[status] ?? status;
}

function modeLabel(mode: string): string {
  const labels: Record<string, string> = {
    normal: "Normal",
    conservative: "Conservador",
    strict: "Estricto",
  };
  return labels[mode] ?? mode;
}

function pct(value: number | undefined): string {
  return `${Math.round(value ?? 0)}%`;
}

function scoreTone(score: number | undefined): string {
  const value = score ?? 0;
  if (value >= 88) return "text-emerald-300";
  if (value >= 72) return "text-amber-300";
  return "text-red-300";
}

function statusClass(status: string): string {
  if (status === "production") return "border-emerald-400/30 bg-emerald-500/10 text-emerald-200";
  if (status === "paused") return "border-amber-400/30 bg-amber-500/10 text-amber-200";
  if (status === "testing") return "border-sky-400/30 bg-sky-500/10 text-sky-200";
  return "border-white/10 bg-white/5 text-slate-200";
}

function severityClass(severity: string): string {
  if (severity === "critical") return "border-red-400/40 bg-red-500/10 text-red-200";
  if (severity === "high") return "border-orange-400/40 bg-orange-500/10 text-orange-200";
  if (severity === "medium") return "border-amber-400/40 bg-amber-500/10 text-amber-200";
  return "border-sky-400/40 bg-sky-500/10 text-sky-200";
}

function cloneAgent(agent: AgentItem): AgentItem {
  return JSON.parse(JSON.stringify(agent)) as AgentItem;
}

function agentPatch(agent: AgentItem): Partial<AgentPayload> {
  return {
    name: agent.name,
    role: agent.role,
    status: agent.status,
    behavior_mode: agent.behavior_mode,
    version: agent.version,
    dealership_id: agent.dealership_id,
    branch_id: agent.branch_id,
    goal: agent.goal,
    style: agent.style,
    tone: agent.tone,
    language: agent.language,
    max_sentences: agent.max_sentences,
    no_emoji: agent.no_emoji,
    return_to_flow: agent.return_to_flow,
    is_default: agent.is_default,
    system_prompt: agent.system_prompt,
    active_intents: agent.active_intents,
    extraction_config: agent.extraction_config,
    auto_actions: agent.auto_actions,
    knowledge_config: agent.knowledge_config,
    flow_mode_rules: agent.flow_mode_rules,
    ops_config: agent.ops_config,
  };
}

function compactPatchKey(agent: AgentItem): string {
  return JSON.stringify(agentPatch(agent));
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function downloadJson(filename: string, value: unknown): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function Panel({
  title,
  icon,
  action,
  children,
  className,
}: {
  title: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-white/10 bg-slate-950/70 shadow-sm shadow-black/20", className)}>
      <div className="flex min-h-10 items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          {icon}
          {title}
        </div>
        {action}
      </div>
      <div className="p-3">{children}</div>
    </section>
  );
}

function MetricTile({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail?: string; tone?: "good" | "warn" | "bad" | "neutral" }) {
  const color = tone === "good" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : tone === "bad" ? "text-red-300" : "text-slate-100";
  return (
    <button
      type="button"
      onClick={() => toast.info(`${label}: ${value}`)}
      className="min-w-0 rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-left transition hover:border-sky-400/40 hover:bg-sky-500/10"
    >
      <div className="text-[11px] text-slate-400">{label}</div>
      <div className={cn("mt-1 text-xl font-semibold leading-none", color)}>{value}</div>
      {detail ? <div className="mt-1 truncate text-[10px] text-slate-500">{detail}</div> : null}
    </button>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-9 rounded-full border transition",
        checked ? "border-sky-300/60 bg-sky-500" : "border-white/15 bg-slate-800",
      )}
    >
      <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white transition", checked ? "left-4" : "left-0.5")} />
    </button>
  );
}

function AgentCard({
  agent,
  selected,
  compareSelected,
  onSelect,
  onCompare,
  onMenu,
}: {
  agent: AgentItem;
  selected: boolean;
  compareSelected: boolean;
  onSelect: () => void;
  onCompare: () => void;
  onMenu: (event: React.MouseEvent) => void;
}) {
  const riskTone = agent.metrics.risk_score >= 70 ? "text-red-300" : agent.metrics.risk_score >= 45 ? "text-amber-300" : "text-emerald-300";
  return (
    <button
      type="button"
      onClick={onSelect}
      onContextMenu={onMenu}
      className={cn(
        "group w-full rounded-lg border p-3 text-left transition",
        selected ? "border-sky-400/70 bg-sky-500/10" : "border-white/10 bg-white/[0.035] hover:border-sky-400/40 hover:bg-sky-500/5",
        compareSelected && "ring-1 ring-amber-300/70",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full", agent.status === "production" ? "bg-emerald-400" : agent.status === "paused" ? "bg-amber-400" : "bg-sky-400")} />
            <span className="truncate text-sm font-semibold text-slate-100">{agent.name}</span>
          </div>
          <div className="mt-1 text-[11px] text-slate-400">{roleLabel(agent.role)}</div>
        </div>
        <span className={cn("text-xl font-semibold leading-none", scoreTone(agent.health.score))}>{agent.health.score}</span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <div className="text-slate-500">Activas</div>
          <div className="font-medium text-slate-200">{agent.metrics.active_conversations}</div>
        </div>
        <div>
          <div className="text-slate-500">Precisión</div>
          <div className="font-medium text-emerald-300">{pct(agent.metrics.response_accuracy)}</div>
        </div>
        <div>
          <div className="text-slate-500">Riesgo</div>
          <div className={cn("font-medium", riskTone)}>{agent.metrics.risk_score}</div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <Badge variant="outline" className={cn("h-5 border text-[10px]", statusClass(agent.status))}>
          {statusLabel(agent.status)}
        </Badge>
        <div className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
          <span
            role="checkbox"
            aria-checked={compareSelected}
            tabIndex={0}
            onClick={(event) => {
              event.stopPropagation();
              onCompare();
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                onCompare();
              }
            }}
            className={cn("grid h-6 w-6 place-items-center rounded border", compareSelected ? "border-amber-300 bg-amber-400/20 text-amber-100" : "border-white/10 text-slate-400")}
            title="Comparar"
          >
            <Check className="h-3.5 w-3.5" />
          </span>
          <span
            role="button"
            tabIndex={0}
            onClick={(event) => {
              event.stopPropagation();
              onMenu(event);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                onMenu(event as unknown as React.MouseEvent);
              }
            }}
            className="grid h-6 w-6 place-items-center rounded border border-white/10 text-slate-400 hover:text-slate-100"
            title="Más acciones"
          >
            <MoreVertical className="h-3.5 w-3.5" />
          </span>
        </div>
      </div>
    </button>
  );
}

function TopBar({
  selected,
  dirty,
  saving,
  onSave,
  onDiscard,
  onCreate,
  onValidate,
  onPublish,
  onRollback,
  onOpenCommands,
}: {
  selected: AgentItem | null;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onCreate: () => void;
  onValidate: () => void;
  onPublish: () => void;
  onRollback: () => void;
  onOpenCommands: () => void;
}) {
  return (
    <header className="flex min-h-14 items-center gap-3 border-b border-white/10 bg-slate-950 px-4 text-slate-100">
      <div className="flex min-w-56 items-center gap-2">
        <Bot className="h-5 w-5 text-sky-300" />
        <div>
          <div className="text-sm font-semibold">Agents</div>
          <div className="text-[11px] text-slate-500">Centro de comportamiento IA</div>
        </div>
      </div>
      <button
        type="button"
        onClick={() => toast.info("Distribuidora del Norte seleccionada")}
        className="hidden h-8 items-center gap-2 rounded-md border border-white/10 bg-white/[0.035] px-3 text-xs text-slate-300 transition hover:border-sky-400/40 md:flex"
      >
        <Globe2 className="h-3.5 w-3.5" />
        Distribuidora del Norte
      </button>
      <button
        type="button"
        onClick={onOpenCommands}
        className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md border border-white/10 bg-black/20 px-3 text-left text-xs text-slate-500 transition hover:border-sky-400/40"
      >
        <Search className="h-3.5 w-3.5" />
        Ctrl/Cmd+K para buscar acción, agente o prueba
      </button>
      <Badge variant="outline" className="hidden h-7 border-emerald-400/30 bg-emerald-500/10 text-emerald-200 lg:flex">
        En vivo
      </Badge>
      {selected ? (
        <Badge variant="outline" className="hidden h-7 border-white/10 bg-white/[0.035] text-slate-200 md:flex">
          Salud IA <span className={cn("ml-1 font-semibold", scoreTone(selected.health.score))}>{selected.health.score}/100</span>
        </Badge>
      ) : null}
      {dirty ? (
        <Badge variant="outline" className="h-7 border-amber-400/30 bg-amber-500/10 text-amber-200">
          Cambios sin guardar
        </Badge>
      ) : null}
      <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={onValidate} disabled={!selected}>
        <ClipboardCheck className="mr-1.5 h-3.5 w-3.5" />
        Validar
      </Button>
      <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={onRollback} disabled={!selected}>
        <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
        Revertir
      </Button>
      <Button size="sm" className="h-8 bg-sky-600 text-xs hover:bg-sky-500" onClick={onSave} disabled={!selected || !dirty || saving}>
        {saving ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
        Guardar
      </Button>
      <Button size="sm" className="h-8 bg-emerald-600 text-xs hover:bg-emerald-500" onClick={onPublish} disabled={!selected}>
        <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
        Publicar
      </Button>
      <Button size="sm" className="h-8 bg-blue-600 text-xs hover:bg-blue-500" onClick={onCreate}>
        <Plus className="mr-1.5 h-3.5 w-3.5" />
        Nuevo
      </Button>
      {dirty ? (
        <Button size="icon" variant="ghost" className="h-8 w-8 text-slate-400" onClick={onDiscard} title="Descartar cambios">
          <X className="h-4 w-4" />
        </Button>
      ) : null}
    </header>
  );
}

function IdentityPanel({
  draft,
  onChange,
}: {
  draft: AgentItem;
  onChange: (patch: Partial<AgentItem>) => void;
}) {
  const toggleIntent = (intent: string) => {
    const next = draft.active_intents.includes(intent)
      ? draft.active_intents.filter((item) => item !== intent)
      : [...draft.active_intents, intent];
    onChange({ active_intents: next });
  };

  return (
    <Panel title="Identidad del agente" icon={<Bot className="h-4 w-4 text-sky-300" />}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <label className="space-y-1.5">
          <span className="text-[11px] text-slate-400">Nombre</span>
          <Input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} className="h-8 border-white/10 bg-black/20 text-sm text-slate-100" />
        </label>
        <label className="space-y-1.5">
          <span className="text-[11px] text-slate-400">Rol</span>
          <select
            value={draft.role}
            onChange={(event) => onChange({ role: event.target.value })}
            className="h-8 w-full rounded-md border border-white/10 bg-slate-950 px-2 text-sm text-slate-100"
          >
            {roleOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5">
          <span className="text-[11px] text-slate-400">
            Tono <span className="text-slate-500">— cómo suena</span>
          </span>
          <select
            value={draft.tone ?? "Cálido"}
            onChange={(event) => onChange({ tone: event.target.value })}
            className="h-8 w-full rounded-md border border-white/10 bg-slate-950 px-2 text-sm text-slate-100"
          >
            {toneOptions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <span className="text-[10px] text-slate-500">
            Registro emocional. Ej: cálido = "¡Qué gusto saludarte!".
            Directo = "Sí, lo tenemos.".
          </span>
        </label>
        <label className="space-y-1.5">
          <span className="text-[11px] text-slate-400">
            Estilo <span className="text-slate-500">— cómo se escribe</span>
          </span>
          <Input
            value={draft.style ?? ""}
            onChange={(event) => onChange({ style: event.target.value })}
            placeholder="Ej. Claro y conciso, frases cortas, sin tecnicismos"
            className="h-8 border-white/10 bg-black/20 text-sm text-slate-100"
          />
          <span className="text-[10px] text-slate-500">
            Forma de redactar. Define largo de oración, vocabulario,
            estructura.
          </span>
        </label>
        <label className="space-y-1.5">
          <span className="text-[11px] text-slate-400">Máx. oraciones</span>
          <Input
            type="number"
            min={1}
            max={5}
            value={draft.max_sentences ?? 3}
            onChange={(event) => onChange({ max_sentences: Number(event.target.value) })}
            className="h-8 border-white/10 bg-black/20 text-sm text-slate-100"
          />
          <span className="text-[10px] text-slate-500">
            Tope duro por respuesta. WhatsApp = mensajes cortos.
          </span>
        </label>
        <label className="space-y-1.5">
          <span className="text-[11px] text-slate-400">Idioma</span>
          <select
            value={draft.language ?? "es"}
            onChange={(event) => onChange({ language: event.target.value })}
            className="h-8 w-full rounded-md border border-white/10 bg-slate-950 px-2 text-sm text-slate-100"
          >
            {languageOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="mt-3 block space-y-1.5">
        <span className="text-[11px] text-slate-400">
          Objetivo operativo{" "}
          <span className="text-slate-500">— qué debe lograr</span>
        </span>
        <Textarea
          value={draft.goal ?? ""}
          onChange={(event) => onChange({ goal: event.target.value })}
          placeholder="Ej. Identificar si el cliente tiene 6+ meses de empleo y agendarle cita."
          className="min-h-16 border-white/10 bg-black/20 text-sm text-slate-100"
        />
        <span className="text-[10px] text-slate-500">
          Una o dos oraciones. Se inyecta al prompt como meta del turno.
        </span>
      </label>

      {/* Prompt Maestro — the canonical user-authored system prompt.
          Goes into `agent.system_prompt`, which the runner already
          reads and injects into `brand_facts.agent_system_prompt`. */}
      <label className="mt-3 block space-y-1.5">
        <span className="text-[11px] text-slate-400">
          Prompt maestro{" "}
          <span className="text-slate-500">
            — instrucciones específicas para el LLM
          </span>
        </span>
        <Textarea
          value={draft.system_prompt ?? ""}
          onChange={(event) => onChange({ system_prompt: event.target.value })}
          rows={6}
          placeholder={
            "Ej.\n- Siempre confirma el nombre del cliente antes de pasar a precio.\n- Si pregunta por garantía, recuerda que cubre 12 meses.\n- Nunca prometas aprobación sin que pase por buró."
          }
          className="min-h-32 border-white/10 bg-black/20 font-mono text-xs text-slate-100"
        />
        <span className="text-[10px] text-slate-500">
          Es la fuente de verdad sobre cómo se comporta el agente.
          Tono / estilo / objetivo se le suman al inicio; esto puede
          sobrescribirlos si lo necesitas. Pruébalo con "Vista previa"
          antes de guardar.
        </span>
      </label>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2">
          <span className="text-xs text-slate-300">Evitar emojis</span>
          <Toggle checked={draft.no_emoji} onChange={(value) => onChange({ no_emoji: value })} />
        </div>
        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2">
          <span className="text-xs text-slate-300">Regresar al flujo</span>
          <Toggle checked={draft.return_to_flow} onChange={(value) => onChange({ return_to_flow: value })} />
        </div>
        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2">
          <span className="text-xs text-slate-300">Predeterminado</span>
          <Toggle checked={draft.is_default} onChange={(value) => onChange({ is_default: value })} />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {intentOptions.map((intent) => (
          <button
            key={intent}
            type="button"
            onClick={() => toggleIntent(intent)}
            className={cn(
              "rounded-md border px-2 py-1 text-[11px] transition",
              draft.active_intents.includes(intent)
                ? "border-sky-300/50 bg-sky-500/15 text-sky-100"
                : "border-white/10 bg-white/[0.035] text-slate-400 hover:text-slate-100",
            )}
          >
            {intent}
          </button>
        ))}
      </div>
    </Panel>
  );
}

function WhatsAppPreview({
  draft,
  preview,
  previewMessage,
  onPreviewMessageChange,
  onRunPreview,
  loading,
}: {
  draft: AgentItem;
  preview: PreviewResult | null;
  previewMessage: string;
  onPreviewMessageChange: (next: string) => void;
  onRunPreview: (message: string) => void;
  loading: boolean;
}) {
  const trace = preview?.trace ?? [];
  const llmStatus = trace.find((step) => step.step === "llm_call")?.status;
  const isReal = llmStatus === "ok";
  const hasError = llmStatus === "error" || llmStatus === "no_llm";

  const submit = () => {
    const trimmed = previewMessage.trim();
    if (!trimmed || loading) return;
    onRunPreview(trimmed);
  };

  return (
    <Panel
      title="Vista previa"
      icon={<MessageCircle className="h-4 w-4 text-emerald-300" />}
    >
      {/* Input row — the operator types the customer message that would
          arrive on WhatsApp and the agent's response is generated live
          using the saved+draft identity (tono / estilo / objetivo /
          prompt maestro). */}
      <div className="space-y-1.5">
        <span className="text-[11px] text-slate-400">
          Simula el mensaje del cliente
        </span>
        <div className="flex gap-2">
          <Input
            value={previewMessage}
            onChange={(e) => onPreviewMessageChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Hola, ¿qué tipo de crédito manejan?"
            className="h-8 border-white/10 bg-black/20 text-sm text-slate-100"
          />
          <Button
            size="sm"
            onClick={submit}
            disabled={loading || !previewMessage.trim()}
            className="h-8 bg-emerald-600 hover:bg-emerald-500"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </div>

      {/* Bubble: the agent's actual reply (or a placeholder before any
          run). */}
      <div className="mt-3 space-y-2">
        {/* User bubble */}
        {preview ? (
          <div className="flex justify-end">
            <div className="max-w-[84%] rounded-lg rounded-tr-sm bg-slate-700 px-3 py-2 text-sm leading-relaxed text-white shadow">
              {previewMessage}
            </div>
          </div>
        ) : null}
        {/* Agent bubble */}
        <div
          className={cn(
            "rounded-lg border p-3",
            isReal && "border-emerald-300/20 bg-emerald-500/10",
            hasError && "border-amber-300/20 bg-amber-500/10",
            !preview && "border-white/10 bg-white/[0.02]",
          )}
        >
          {preview ? (
            <div className="max-w-[84%] rounded-lg rounded-tl-sm bg-emerald-700 px-3 py-2 text-sm leading-relaxed text-white shadow whitespace-pre-wrap">
              {preview.finalResponse}
            </div>
          ) : (
            <p className="text-[11px] italic text-slate-400">
              Escribe un mensaje y presiona Enter para ver la respuesta real
              del agente. Usa los campos del panel "Identidad" (tono,
              estilo, objetivo, prompt maestro) sin que tengas que mandar
              WhatsApp.
            </p>
          )}
        </div>
      </div>

      {/* Trace + status — honest about what just happened */}
      {trace.length > 0 ? (
        <div className="mt-3 space-y-1">
          {trace.map((step, idx) => (
            <div
              key={`${step.step}-${idx}`}
              className={cn(
                "flex items-start gap-2 rounded-md border px-2 py-1 text-[10px]",
                step.status === "ok"
                  ? "border-emerald-300/20 bg-emerald-500/5 text-emerald-200"
                  : step.status === "error"
                    ? "border-rose-300/20 bg-rose-500/5 text-rose-200"
                    : "border-amber-300/20 bg-amber-500/5 text-amber-200",
              )}
            >
              <span className="font-mono uppercase">{step.step}</span>
              <span className="flex-1 text-slate-400">{step.detail}</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* System prompt the LLM actually saw, for transparency */}
      {preview?.systemPrompt ? (
        <details className="mt-2 rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-[10px]">
          <summary className="cursor-pointer text-slate-400">
            Prompt enviado al LLM
          </summary>
          <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-slate-300">
            {preview.systemPrompt}
          </pre>
        </details>
      ) : null}
    </Panel>
  );
}

// Read-only view of the documents and customer fields the runner ACTUALLY
// extracts — sourced from the pipeline definition, not from the agent's
// (stub) extraction_fields list. The operator edits these in the
// pipeline editor; the panel only shows them so they know what their
// agent already understands.
function ExtractionReadonlyPanel() {
  return (
    <Panel
      title="Extracción de campos"
      icon={<MessageCircle className="h-4 w-4 text-emerald-300" />}
    >
      <p className="text-[11px] text-slate-400">
        La extracción real la maneja el pipeline (catálogo de documentos +
        campos del cliente). Edítalos desde el editor del pipeline; aquí
        verás reflejado lo que el agente entiende cuando llega un mensaje.
      </p>
      <p className="mt-3 text-[11px] text-slate-500">
        Vista de solo lectura. Próxima iteración: listar aquí los docs y
        custom fields activos de tu pipeline para que confirmes qué
        extrae el agente sin tener que abrir el editor.
      </p>
    </Panel>
  );
}

// ── Real Guardrails: edits `agent.ops_config.guardrails` directly on
// the draft so saving the agent persists them. The runner reads each
// active rule's `rule_text` and appends it to the system prompt as a
// "REGLAS QUE NO PUEDES ROMPER" block, so the LLM treats them as hard
// constraints. Editing here has immediate effect on the next inbound.
function GuardrailsRealPanel({
  draft,
  onChange,
}: {
  draft: AgentItem;
  onChange: (patch: Partial<AgentItem>) => void;
}) {
  const guardrails = draft.guardrails ?? [];

  const setAll = (next: Guardrail[]) => {
    onChange({
      guardrails: next,
      ops_config: { ...(draft.ops_config ?? {}), guardrails: next },
    } as Partial<AgentItem>);
  };

  const addGuardrail = () => {
    const id = `gr_${Date.now().toString(36)}`;
    setAll([
      ...guardrails,
      {
        id,
        name: "Nueva regla",
        severity: "medium",
        rule_text: "",
        allowed_examples: [],
        forbidden_examples: [],
        active: true,
        enforcement_mode: "rewrite",
        violation_count: 0,
      },
    ]);
  };

  const updateGuardrail = (id: string, patch: Partial<Guardrail>) => {
    setAll(guardrails.map((g) => (g.id === id ? { ...g, ...patch } : g)));
  };

  const removeGuardrail = (id: string) => {
    setAll(guardrails.filter((g) => g.id !== id));
  };

  return (
    <Panel
      title="Guardrails"
      icon={<MessageCircle className="h-4 w-4 text-emerald-300" />}
      action={
        <Button
          size="sm"
          variant="outline"
          className="h-7 border-white/10 bg-white/[0.035] text-xs text-slate-200"
          onClick={addGuardrail}
        >
          <Plus className="mr-1 h-3 w-3" />
          Agregar regla
        </Button>
      }
    >
      <p className="mb-3 text-[11px] text-slate-400">
        Reglas duras que se inyectan al prompt del LLM como restricciones.
        Cada regla activa se agrega al system prompt como bullet con
        prefijo "no puedes romper". Pruébalas en la vista previa antes de
        guardar.
      </p>

      {guardrails.length === 0 ? (
        <p className="rounded-md border border-dashed border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] italic text-slate-500">
          Sin reglas. Agrega la primera arriba.
        </p>
      ) : (
        <div className="space-y-2">
          {guardrails.map((g) => (
            <div
              key={g.id}
              className="rounded-md border border-white/10 bg-black/20 p-2.5"
            >
              <div className="mb-2 flex items-center gap-2">
                <Toggle
                  checked={g.active}
                  onChange={(value) =>
                    updateGuardrail(g.id, { active: value })
                  }
                />
                <Input
                  value={g.name}
                  onChange={(e) =>
                    updateGuardrail(g.id, { name: e.target.value })
                  }
                  placeholder="Nombre corto (ej. No prometer aprobación)"
                  className="h-7 flex-1 border-white/10 bg-black/30 text-xs"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-rose-300 hover:bg-rose-500/10"
                  onClick={() => removeGuardrail(g.id)}
                  aria-label={`Eliminar ${g.name}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              <Textarea
                value={g.rule_text}
                onChange={(e) =>
                  updateGuardrail(g.id, { rule_text: e.target.value })
                }
                placeholder="Ej. Nunca prometas aprobación, tasa o monto sin validación humana."
                rows={2}
                className="min-h-16 border-white/10 bg-black/30 text-xs text-slate-100"
              />
              <p className="mt-1 text-[10px] text-slate-500">
                {g.active
                  ? "Activa — va al system prompt en cada turno."
                  : "Desactivada — guardada pero el LLM no la ve."}
              </p>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

// ── Real Knowledge: writes `agent.knowledge_config.collection_ids`,
// which the runner uses to scope FAQ + catalog lookups. The collection
// list comes from `GET /api/v1/knowledge/collections`.
function KnowledgeRealPanel({
  draft,
  onChange,
}: {
  draft: AgentItem;
  onChange: (patch: Partial<AgentItem>) => void;
}) {
  const { data: collections, isLoading } = useQuery({
    queryKey: ["kb", "collections"],
    queryFn: async () =>
      (
        await api.get<
          Array<{ id: string; slug: string; name: string; description: string | null }>
        >("/knowledge/collections")
      ).data,
    staleTime: 30_000,
  });
  const cfg = (draft.knowledge_config ?? {}) as {
    collection_ids?: string[];
  };
  const selected = new Set(cfg.collection_ids ?? []);

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange({
      knowledge_config: {
        ...cfg,
        collection_ids: Array.from(next),
      },
    } as Partial<AgentItem>);
  };

  return (
    <Panel
      title="Conocimiento"
      icon={<MessageCircle className="h-4 w-4 text-emerald-300" />}
    >
      <p className="mb-3 text-[11px] text-slate-400">
        Elige las colecciones de Conocimiento que este agente puede leer.
        Cuando llegue un mensaje, el runner filtrará las FAQs y el
        catálogo a estas colecciones — el resto del KB del tenant queda
        invisible para este agente. Sin selección = acceso a todo.
      </p>

      {isLoading ? (
        <p className="text-[11px] italic text-slate-500">Cargando colecciones…</p>
      ) : !collections || collections.length === 0 ? (
        <p className="rounded-md border border-dashed border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] italic text-slate-500">
          No hay colecciones definidas en Conocimiento todavía. Créalas
          desde la sección Conocimiento y vuelve aquí para vincular.
        </p>
      ) : (
        <div className="space-y-1.5">
          {collections.map((c) => {
            const checked = selected.has(c.id);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => toggle(c.id)}
                aria-pressed={checked}
                className={cn(
                  "flex w-full items-start gap-2 rounded-md border px-2.5 py-2 text-left text-[11px] transition",
                  checked
                    ? "border-emerald-500/40 bg-emerald-500/5"
                    : "border-white/10 bg-black/20 hover:bg-white/[0.04]",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                    checked
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : "border-white/20 bg-black/30",
                  )}
                  aria-hidden
                >
                  {checked ? "✓" : ""}
                </span>
                <span className="flex-1">
                  <span className="block font-medium text-slate-100">
                    {c.name}
                  </span>
                  <span className="block font-mono text-[10px] text-slate-500">
                    {c.slug}
                  </span>
                  {c.description ? (
                    <span className="block text-[10px] text-slate-400">
                      {c.description}
                    </span>
                  ) : null}
                </span>
              </button>
            );
          })}
        </div>
      )}
      <p className="mt-3 text-[10px] text-slate-500">
        {selected.size === 0
          ? "Sin restricción — el agente puede consultar todas las FAQs y catálogo del tenant."
          : `${selected.size} colección(es) seleccionada(s). El resto del KB queda fuera de alcance.`}
      </p>
    </Panel>
  );
}

// ── Real Monitor: pulls runtime metrics from /agents/{id}/monitor,
// which aggregates over `turn_traces` joined through
// `conversations.assigned_agent_id`. Refreshes every 30s.
function MonitorRealPanel({ agentId }: { agentId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["agents", agentId, "monitor"],
    queryFn: () => agentsApi.monitor(agentId),
    refetchInterval: 30_000,
  });

  const fmtCost = (n: number) =>
    `$${n.toFixed(4)} USD`;
  const fmtRelative = (iso: string | null) => {
    if (!iso) return "sin actividad";
    const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `hace ${seconds}s`;
    if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
    if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)} h`;
    return `hace ${Math.floor(seconds / 86400)} d`;
  };

  return (
    <Panel
      title="Monitor"
      icon={<MessageCircle className="h-4 w-4 text-emerald-300" />}
    >
      {isLoading || !data ? (
        <p className="text-[11px] italic text-slate-500">Cargando métricas…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-md border border-white/10 bg-white/[0.035] p-2">
              <div className="text-slate-500">Conversaciones activas (24h)</div>
              <div className="mt-1 text-base font-semibold text-emerald-300">
                {data.active_conversations_24h}
              </div>
            </div>
            <div className="rounded-md border border-white/10 bg-white/[0.035] p-2">
              <div className="text-slate-500">Turnos en 24h</div>
              <div className="mt-1 text-base font-semibold text-slate-100">
                {data.turns_24h}
              </div>
            </div>
            <div className="rounded-md border border-white/10 bg-white/[0.035] p-2">
              <div className="text-slate-500">Costo 24h</div>
              <div className="mt-1 text-base font-semibold text-slate-100">
                {fmtCost(data.cost_usd_24h)}
              </div>
            </div>
            <div className="rounded-md border border-white/10 bg-white/[0.035] p-2">
              <div className="text-slate-500">Latencia promedio</div>
              <div className="mt-1 text-base font-semibold text-slate-100">
                {data.avg_latency_ms} ms
              </div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] text-slate-400">
            <div>
              <span className="text-slate-500">Turnos totales:</span>{" "}
              <span className="text-slate-200">{data.turns_total}</span>
            </div>
            <div>
              <span className="text-slate-500">Costo total:</span>{" "}
              <span className="text-slate-200">{fmtCost(data.cost_usd_total)}</span>
            </div>
            <div>
              <span className="text-slate-500">Último turno:</span>{" "}
              <span className="text-slate-200">{fmtRelative(data.last_turn_at)}</span>
            </div>
          </div>
          {data.covers_default_fallback ? (
            <p className="mt-3 rounded-md border border-amber-500/20 bg-amber-500/5 px-2.5 py-1.5 text-[10px] text-amber-200">
              Este agente está marcado como predeterminado: las métricas
              incluyen conversaciones sin agente explícitamente asignado
              que cayeron en él vía fallback.
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

function GuardrailsPanel({
  guardrails,
  onAdd,
  onTest,
  onContext,
}: {
  guardrails: Guardrail[];
  onAdd: () => void;
  onTest: (guardrail: Guardrail) => void;
  onContext: (event: React.MouseEvent, guardrail: Guardrail) => void;
}) {
  return (
    <Panel
      title="Guardrails"
      icon={<ShieldCheck className="h-4 w-4 text-amber-300" />}
      action={
        <Button size="sm" variant="outline" className="h-7 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={onAdd}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          Regla
        </Button>
      }
    >
      <div className="grid gap-2 lg:grid-cols-3">
        {guardrails.slice(0, 6).map((guardrail) => (
          <div
            key={guardrail.id}
            onContextMenu={(event) => onContext(event, guardrail)}
            className={cn("rounded-lg border p-3", severityClass(guardrail.severity))}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{guardrail.name}</div>
                <div className="mt-1 line-clamp-2 text-[11px] text-slate-300">{guardrail.rule_text}</div>
              </div>
              <Toggle checked={guardrail.active} onChange={() => toast.info("Edita la regla desde el menú contextual")} />
            </div>
            <div className="mt-3 flex items-center justify-between text-[11px]">
              <span>{guardrail.violation_count} violaciones</span>
              <Button size="sm" variant="outline" className="h-7 border-white/10 bg-black/20 text-[11px]" onClick={() => onTest(guardrail)}>
                <TestTube2 className="mr-1 h-3 w-3" />
                Probar
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ExtractionPanel({
  fields,
  onAdd,
  onTest,
  onContext,
}: {
  fields: ExtractionField[];
  onAdd: () => void;
  onTest: (field: ExtractionField) => void;
  onContext: (event: React.MouseEvent, field: ExtractionField) => void;
}) {
  return (
    <Panel
      title="Extracción de campos"
      icon={<ClipboardCheck className="h-4 w-4 text-sky-300" />}
      action={
        <Button size="sm" variant="outline" className="h-7 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={onAdd}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          Campo
        </Button>
      }
    >
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/10 text-left text-slate-500">
              <th className="py-2 pr-3 font-medium">Campo</th>
              <th className="py-2 pr-3 font-medium">Tipo</th>
              <th className="py-2 pr-3 font-medium">Confianza</th>
              <th className="py-2 pr-3 font-medium">Autoguardado</th>
              <th className="py-2 pr-3 font-medium">Estado</th>
              <th className="py-2 text-right font-medium">Acción</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.id} onContextMenu={(event) => onContext(event, field)} className="border-b border-white/5 text-slate-200">
                <td className="py-2 pr-3">
                  <div className="font-medium">{field.label}</div>
                  <div className="text-[10px] text-slate-500">{field.field_key}</div>
                </td>
                <td className="py-2 pr-3 text-slate-400">{field.type}</td>
                <td className="py-2 pr-3 text-emerald-300">{pct((field.confidence ?? field.confidence_threshold) * 100)}</td>
                <td className="py-2 pr-3">{field.auto_save ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" /> : <span className="text-slate-500">Pendiente</span>}</td>
                <td className="py-2 pr-3">
                  <Badge variant="outline" className={cn("h-5 border text-[10px]", field.status === "pending" ? "border-amber-300/30 bg-amber-500/10 text-amber-200" : "border-emerald-300/30 bg-emerald-500/10 text-emerald-200")}>
                    {field.status ?? "confirmed"}
                  </Badge>
                </td>
                <td className="py-2 text-right">
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px] text-sky-200" onClick={() => onTest(field)}>
                    Ver
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function MonitorPanel({ agent }: { agent: AgentItem }) {
  const monitor = agent.live_monitor;
  const risky = monitor.risky_leads.slice(0, 2);
  return (
    <Panel title="Monitor en vivo" icon={<Activity className="h-4 w-4 text-emerald-300" />}>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricTile label="Conversaciones" value={String(monitor.conversations_active)} tone="neutral" />
        <MetricTile label="Leads en riesgo" value={String(monitor.leads_at_risk)} tone={monitor.leads_at_risk > 6 ? "bad" : "warn"} />
        <MetricTile label="Esperando humano" value={String(monitor.leads_waiting_human)} tone={monitor.leads_waiting_human > 4 ? "warn" : "good"} />
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-2">
        {risky.map((lead, index) => (
          <div key={String(lead.id ?? index)} className="rounded-lg border border-red-300/20 bg-red-500/10 p-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-red-100">{String(lead.name ?? "Lead en riesgo")}</span>
              <Badge variant="outline" className="border-red-300/30 text-red-200">{String(lead.risk ?? "Alto")}</Badge>
            </div>
            <div className="mt-2 text-slate-300">{String(lead.reason ?? "Documento incompleto")}</div>
            <div className="mt-3 flex gap-2">
              <NYIButton label="Abrir" size="sm" />
              <Button size="sm" variant="outline" className="h-7 border-white/10 bg-black/20 text-[11px]" onClick={() => toast.success("Asignado a humano")}>Asignar</Button>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function SupervisorPanel({ agent }: { agent: AgentItem }) {
  const supervisor = agent.supervisor;
  return (
    <Panel title="Supervisor IA" icon={<UserCheck className="h-4 w-4 text-emerald-300" />}>
      <div className="grid gap-2 sm:grid-cols-2">
        {[
          ["Riesgo de alucinación", supervisor.hallucination_risk],
          ["Guardrails", supervisor.guardrail_compliance],
          ["Tono", supervisor.tone],
          ["Handoff correcto", pct(supervisor.handoff_correctness)],
          ["Extracción confiable", pct(supervisor.extraction_reliability)],
        ].map(([label, value]) => (
          <div key={label} className="flex items-center justify-between rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-xs">
            <span className="text-slate-400">{label}</span>
            <span className="font-semibold text-emerald-300">{value}</span>
          </div>
        ))}
      </div>
      {supervisor.alert ? (
        <div className="mt-3 rounded-lg border border-amber-300/30 bg-amber-500/10 p-3 text-xs text-amber-100">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {supervisor.alert}
        </div>
      ) : null}
    </Panel>
  );
}

function KnowledgePanel({ agent }: { agent: AgentItem }) {
  const coverage = agent.knowledge_coverage;
  return (
    <Panel title="Cobertura de conocimiento" icon={<BrainCircuit className="h-4 w-4 text-violet-300" />}>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricTile label="Cobertura" value={pct(coverage.coverage)} tone={coverage.coverage >= 80 ? "good" : "warn"} />
        <MetricTile label="FAQ conectadas" value={String(coverage.faq_answered)} tone="good" />
        <MetricTile label="Sin respuesta" value={String(coverage.unanswered_queries)} tone={coverage.unanswered_queries > 10 ? "warn" : "good"} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {coverage.weak_topics.map((topic) => (
          <Badge key={topic} variant="outline" className="border-red-300/20 bg-red-500/10 text-[10px] text-red-200">
            {topic}
          </Badge>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="sm" className="h-7 bg-blue-600 text-[11px] hover:bg-blue-500" onClick={() => toast.success("FAQ preparada")}>Agregar FAQ</Button>
        <NYIButton label="Subir documento" />
        <NYIButton label="Ver fallidas" />
      </div>
    </Panel>
  );
}

function toFlowNodes(map: DecisionMap): Node[] {
  return map.nodes.map((rawNode, index) => {
    const node = asRecord(rawNode);
    const position = asRecord(node.position);
    const id = String(node.id ?? `node_${index}`);
    const enabled = node.enabled !== false;
    return {
      id,
      position: {
        x: Number(position.x ?? index * 150),
        y: Number(position.y ?? 80),
      },
      data: { label: String(node.label ?? id) },
      style: {
        background: enabled ? "rgba(14, 165, 233, 0.16)" : "rgba(71, 85, 105, 0.35)",
        border: enabled ? "1px solid rgba(125, 211, 252, 0.55)" : "1px solid rgba(148, 163, 184, 0.2)",
        color: "#e2e8f0",
        borderRadius: 8,
        fontSize: 11,
        minWidth: 130,
      },
    };
  });
}

function toFlowEdges(map: DecisionMap): Edge[] {
  return map.edges.map((rawEdge, index) => {
    const edge = asRecord(rawEdge);
    return {
      id: String(edge.id ?? `edge_${index}`),
      source: String(edge.source ?? ""),
      target: String(edge.target ?? ""),
      animated: true,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: "rgba(56, 189, 248, 0.65)" },
    };
  });
}

function DecisionMapPanel({
  map,
  onValidate,
  onSave,
}: {
  map: DecisionMap;
  onValidate: () => void;
  onSave: () => void;
}) {
  const nodes = useMemo(() => toFlowNodes(map), [map]);
  const edges = useMemo(() => toFlowEdges(map), [map]);
  return (
    <Panel
      title="Decision Map"
      icon={<GitBranch className="h-4 w-4 text-violet-300" />}
      action={
        <div className="flex gap-2">
          <Button size="sm" variant="outline" className="h-7 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={onValidate}>
            Validar
          </Button>
          <Button size="sm" className="h-7 bg-sky-600 text-xs hover:bg-sky-500" onClick={onSave}>
            Guardar
          </Button>
        </div>
      }
    >
      <div className="h-72 overflow-hidden rounded-lg border border-white/10 bg-slate-950">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
          <Background color="rgba(148, 163, 184, 0.16)" gap={18} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </Panel>
  );
}

function ScenarioPanel({
  agent,
  onRun,
  onStress,
}: {
  agent: AgentItem;
  onRun: (scenarioId: string) => void;
  onStress: () => void;
}) {
  const passed = agent.scenarios.filter((item) => item.status === "passed").length;
  return (
    <Panel
      title="Pruebas de escenarios"
      icon={<FlaskConical className="h-4 w-4 text-emerald-300" />}
      action={
        <Button size="sm" variant="outline" className="h-7 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={onStress}>
          Ejecutar todas
        </Button>
      }
    >
      <div className="grid gap-3 lg:grid-cols-[1fr_170px]">
        <div className="space-y-1.5">
          {agent.scenarios.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              onClick={() => onRun(scenario.id)}
              className="flex w-full items-center justify-between rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-left text-xs transition hover:border-sky-300/30"
            >
              <span className="text-slate-200">{scenario.name}</span>
              <Badge variant="outline" className={cn("h-5 text-[10px]", scenario.status === "failed" ? "border-red-300/30 text-red-200" : scenario.status === "warning" || scenario.status === "risky" ? "border-amber-300/30 text-amber-200" : "border-emerald-300/30 text-emerald-200")}>
                {scenario.status}
              </Badge>
            </button>
          ))}
        </div>
        <div className="grid place-items-center rounded-lg border border-white/10 bg-white/[0.035] p-3 text-center">
          <div className="grid h-24 w-24 place-items-center rounded-full border-8 border-emerald-400/70 text-2xl font-semibold text-slate-100">{agent.scenarios.length}</div>
          <div className="mt-2 text-xs text-slate-400">Escenarios</div>
          <div className="mt-1 text-[11px] text-emerald-300">{passed} aprobados</div>
        </div>
      </div>
    </Panel>
  );
}

function ValidationPanel({ validation }: { validation: ValidationResult | null }) {
  if (!validation) {
    return (
      <Panel title="Validación antes de publicar" icon={<ClipboardCheck className="h-4 w-4 text-sky-300" />}>
        <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4 text-sm text-slate-400">Sin validación reciente.</div>
      </Panel>
    );
  }
  return (
    <Panel title="Validación antes de publicar" icon={<ClipboardCheck className="h-4 w-4 text-sky-300" />}>
      <div className={cn("rounded-lg border p-3 text-sm", validation.status === "ok" ? "border-emerald-300/30 bg-emerald-500/10 text-emerald-100" : "border-red-300/30 bg-red-500/10 text-red-100")}>
        {validation.summary}
      </div>
      <div className="mt-2 space-y-1">
        {validation.checks.map((check) => (
          <div key={check.label} className="flex items-center justify-between rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-xs">
            <span className="text-slate-300">{check.label}</span>
            <span className={check.status === "ok" ? "text-emerald-300" : check.status === "warning" ? "text-amber-300" : "text-red-300"}>{check.status}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ComparePanel({ comparison, onClose }: { comparison: ComparisonResult; onClose: () => void }) {
  const first = comparison.agents[0];
  const second = comparison.agents[1];
  if (!first || !second) return null;
  return (
    <div className="border-t border-white/10 bg-slate-950">
      <div className="flex items-center justify-between px-4 py-2">
        <div className="text-sm font-semibold text-slate-100">Comparación de agentes</div>
        <Button size="sm" variant="ghost" className="h-7 text-xs text-slate-300" onClick={onClose}>
          <X className="mr-1.5 h-3.5 w-3.5" />
          Cerrar
        </Button>
      </div>
      <div className="grid max-h-64 gap-3 overflow-auto px-4 pb-4 lg:grid-cols-2">
        <Panel title={`${first.name} vs ${second.name}`}>
          <table className="w-full text-xs">
            <tbody>
              {comparison.differences.length === 0 ? (
                <tr><td className="py-2 text-slate-400">Sin diferencias críticas.</td></tr>
              ) : (
                comparison.differences.map((diff) => (
                  <tr key={String(diff.field)} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-slate-400">{String(diff.label ?? diff.field)}</td>
                    <td className="py-2 pr-3 text-slate-200">{String(diff.from ?? "-")}</td>
                    <td className="py-2 text-emerald-300">{String(diff.to ?? "-")}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </Panel>
        <Panel title="Métricas comparadas">
          <div className="space-y-2">
            {comparison.performance.map((metric) => (
              <div key={String(metric.metric)} className="grid grid-cols-[1fr_70px_70px] items-center rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-xs">
                <span className="text-slate-300">{String(metric.metric)}</span>
                <span className="text-sky-200">{String(metric.a)}</span>
                <span className="text-emerald-200">{String(metric.b)}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ContextMenuLayer({
  state,
  selected,
  onClose,
  onDuplicate,
  onDisable,
  onExport,
  onDelete,
  onTestNested,
}: {
  state: ContextMenuState | null;
  selected: AgentItem | null;
  onClose: () => void;
  onDuplicate: (agentId: string) => void;
  onDisable: (agentId: string) => void;
  onExport: (agentId: string) => void;
  onDelete: (agentId: string) => void;
  onTestNested: (kind: "guardrail" | "field", id: string) => void;
}) {
  if (!state) return null;
  const currentAgentId = state.kind === "agent" ? state.agentId : selected?.id;
  const items = state.kind === "agent"
    ? [
        { label: "Duplicar", icon: Copy, action: () => currentAgentId && onDuplicate(currentAgentId) },
        { label: "Deshabilitar", icon: Pause, action: () => currentAgentId && onDisable(currentAgentId) },
        { label: "Exportar JSON", icon: FileJson, action: () => currentAgentId && onExport(currentAgentId) },
        { label: "Eliminar", icon: Trash2, danger: true, action: () => currentAgentId && onDelete(currentAgentId) },
      ]
    : [
        { label: "Probar", icon: TestTube2, action: () => onTestNested(state.kind, state.itemId) },
        { label: "Copiar ID", icon: Copy, action: () => void navigator.clipboard.writeText(state.itemId).then(() => toast.success("ID copiado")) },
        { label: "Ver historial", icon: History, action: () => toast.info("Feature en construcción", { description: '"Ver historial" estará disponible próximamente.' }) },
      ];
  return (
    <div className="fixed inset-0 z-50" onClick={onClose}>
      <div
        className="absolute w-44 rounded-lg border border-white/10 bg-slate-950 p-1 text-xs text-slate-200 shadow-2xl shadow-black/40"
        style={{ left: state.x, top: state.y }}
      >
        {items.map(({ label, icon: Icon, danger, action }) => (
          <button
            key={label}
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              action();
              onClose();
            }}
            className={cn("flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-white/10", danger && "text-red-200 hover:bg-red-500/10")}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function CommandPalette({
  open,
  onClose,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  actions: Array<{ label: string; icon: ReactNode; action: () => void }>;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-start bg-black/45 p-6 pt-24" onClick={onClose}>
      <div className="mx-auto w-full max-w-xl rounded-xl border border-white/10 bg-slate-950 p-2 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
          <Search className="h-4 w-4 text-slate-500" />
          <span className="text-sm text-slate-300">Comandos rápidos</span>
        </div>
        <div className="max-h-96 overflow-auto py-2">
          {actions.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                item.action();
                onClose();
              }}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-200 hover:bg-white/10"
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function ShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  const rows = [
    ["Ctrl/Cmd + K", "Abrir comandos"],
    ["Ctrl/Cmd + S", "Guardar configuración"],
    ["Shift + clic", "Seleccionar para comparar"],
    ["?", "Ver atajos"],
    ["Esc", "Cerrar paneles"],
  ];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-6" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-white/10 bg-slate-950 p-4 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-100">Atajos</div>
          <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="space-y-2">
          {rows.map(([key, label]) => (
            <div key={key} className="flex items-center justify-between rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-xs">
              <span className="text-slate-300">{label}</span>
              <code className="rounded bg-black/30 px-2 py-1 text-slate-400">{key}</code>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Sidebar({
  agents,
  selectedId,
  compareIds,
  search,
  onSearch,
  onSelect,
  onCompare,
  onContext,
  onCreate,
  loading,
}: {
  agents: AgentItem[];
  selectedId: string | null;
  compareIds: string[];
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onCompare: (id: string) => void;
  onContext: (event: React.MouseEvent, agentId: string) => void;
  onCreate: () => void;
  loading: boolean;
}) {
  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-white/10 bg-slate-950">
      <div className="border-b border-white/10 p-3">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
              Agentes
              <DemoBadge className="ml-1.5 inline-block" />
            </div>
            <div className="text-[11px] text-slate-500">{agents.length} perfiles configurados</div>
          </div>
          <Button size="sm" className="h-8 bg-blue-600 text-xs hover:bg-blue-500" onClick={onCreate}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Nuevo
          </Button>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
          <Input
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Buscar agente..."
            className="h-8 border-white/10 bg-black/20 pl-8 text-sm text-slate-100"
          />
        </div>
      </div>
      <div className="flex-1 space-y-2 overflow-auto p-3">
        {loading ? (
          Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 rounded-lg bg-white/10" />)
        ) : agents.length === 0 ? (
          <div className="rounded-lg border border-dashed border-white/10 p-6 text-center text-sm text-slate-400">
            Sin agentes para este filtro.
          </div>
        ) : (
          agents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              selected={selectedId === agent.id}
              compareSelected={compareIds.includes(agent.id)}
              onSelect={() => onSelect(agent.id)}
              onCompare={() => onCompare(agent.id)}
              onMenu={(event) => onContext(event, agent.id)}
            />
          ))
        )}
      </div>
      <div className="border-t border-white/10 p-3">
        <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-xs">
          <div className="flex items-center justify-between text-slate-300">
            <span>Modo comparación</span>
            <span className="text-amber-300">{compareIds.length}/2</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div className="h-full bg-amber-400" style={{ width: `${Math.min(compareIds.length, 2) * 50}%` }} />
          </div>
        </div>
      </div>
    </aside>
  );
}

export function AgentsPage() {
  const queryClient = useQueryClient();
  const agentsQuery = useQuery({ queryKey: ["agents", "operations-center"], queryFn: agentsApi.list });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<AgentItem | null>(null);
  const [activeTab, setActiveTab] = useState<AgentTab>("Identidad");
  const [search, setSearch] = useState("");
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewMessage, setPreviewMessage] = useState(
    "Hola, ¿qué tipo de crédito manejan?",
  );
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  const agents = agentsQuery.data ?? [];
  const filteredAgents = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter((agent) => `${agent.name} ${agent.role} ${agent.goal ?? ""}`.toLowerCase().includes(needle));
  }, [agents, search]);
  const selected = useMemo(() => agents.find((agent) => agent.id === selectedId) ?? null, [agents, selectedId]);
  const dirty = Boolean(selected && draft && compactPatchKey(selected) !== compactPatchKey(draft));

  const invalidateAgents = () => queryClient.invalidateQueries({ queryKey: ["agents", "operations-center"] });

  useEffect(() => {
    if (!selectedId && agents.length > 0) {
      setSelectedId(agents[0]?.id ?? null);
    }
  }, [agents, selectedId]);

  useEffect(() => {
    setDraft(selected ? cloneAgent(selected) : null);
    setValidation(null);
    setPreview(null);
  }, [selected?.id, selected?.updated_at]);

  const updateDraft = (patch: Partial<AgentItem>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
  };

  const saveMutation = useMutation({
    mutationFn: (agent: AgentItem) => agentsApi.patchConfig(agent.id, agentPatch(agent)),
    onSuccess: (agent) => {
      setDraft(cloneAgent(agent));
      void invalidateAgents();
      toast.success("Agente guardado");
    },
    onError: (error: Error) => toast.error("No se pudo guardar", { description: error.message }),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      agentsApi.create({
        name: "Nuevo agente",
        role: "sales_agent",
        status: "draft",
        behavior_mode: "normal",
        goal: "Calificar lead, responder con claridad y escalar cuando falte contexto.",
        tone: "Cálido",
        style: "Claro y conciso",
        language: "es",
        max_sentences: 3,
        active_intents: ["GREETING", "ASK_INFO", "ASK_PRICE", "HUMAN_REQUESTED"],
      }),
    onSuccess: (agent) => {
      setSelectedId(agent.id);
      void invalidateAgents();
      toast.success("Agente creado");
    },
    onError: (error: Error) => toast.error("No se pudo crear", { description: error.message }),
  });

  const duplicateMutation = useMutation({
    mutationFn: agentsApi.duplicate,
    onSuccess: (agent) => {
      setSelectedId(agent.id);
      void invalidateAgents();
      toast.success("Agente duplicado");
    },
    onError: (error: Error) => toast.error("No se pudo duplicar", { description: error.message }),
  });

  const disableMutation = useMutation({
    mutationFn: agentsApi.disable,
    onSuccess: () => {
      void invalidateAgents();
      toast.success("Agente pausado");
    },
    onError: (error: Error) => toast.error("No se pudo pausar", { description: error.message }),
  });

  const deleteMutation = useMutation({
    mutationFn: agentsApi.delete,
    onSuccess: (_, id) => {
      if (selectedId === id) setSelectedId(null);
      setCompareIds((current) => current.filter((item) => item !== id));
      void invalidateAgents();
      toast.success("Agente eliminado");
    },
    onError: (error: Error) => toast.error("No se pudo eliminar", { description: error.message }),
  });

  const publishMutation = useMutation({
    mutationFn: agentsApi.publish,
    onSuccess: (agent) => {
      setDraft(cloneAgent(agent));
      void invalidateAgents();
      toast.success("Publicado en producción");
    },
    onError: (error: Error) => toast.error("Publicación bloqueada", { description: error.message }),
  });

  const rollbackMutation = useMutation({
    mutationFn: (id: string) => agentsApi.rollback(id),
    onSuccess: (agent) => {
      setDraft(cloneAgent(agent));
      void invalidateAgents();
      toast.success("Rollback aplicado");
    },
    onError: (error: Error) => toast.error("No se pudo revertir", { description: error.message }),
  });

  const validateMutation = useMutation({
    mutationFn: (agent: AgentItem) => agentsApi.validateConfig(agent.id, agentPatch(agent)),
    onSuccess: (result) => {
      setValidation(result);
      toast[result.status === "ok" ? "success" : "warning"](result.summary);
    },
    onError: (error: Error) => toast.error("No se pudo validar", { description: error.message }),
  });

  const previewMutation = useMutation({
    mutationFn: ({ agent, message }: { agent: AgentItem; message: string }) =>
      agentsApi.previewResponse(agent.id, message, agentPatch(agent)),
    onSuccess: (result) => {
      setPreview(result);
      toast.success("Preview generado");
    },
    onError: (error: Error) => toast.error("No se pudo probar", { description: error.message }),
  });

  const createGuardrailMutation = useMutation({
    mutationFn: (agentId: string) =>
      agentsApi.createGuardrail(agentId, {
        severity: "high",
        name: "No prometer aprobación",
        rule_text: "No prometer aprobación, tasa, monto ni entrega sin validación humana.",
        allowed_examples: ["Puedo revisar requisitos contigo."],
        forbidden_examples: ["Ya estás aprobado."],
        active: true,
        enforcement_mode: "rewrite",
      }),
    onSuccess: () => {
      void invalidateAgents();
      toast.success("Guardrail creado");
    },
    onError: (error: Error) => toast.error("No se pudo crear la regla", { description: error.message }),
  });

  const createFieldMutation = useMutation({
    mutationFn: (agentId: string) =>
      agentsApi.createExtractionField(agentId, {
        field_key: `campo_${Date.now().toString().slice(-4)}`,
        label: "Campo nuevo",
        description: "Dato capturado durante la conversación",
        type: "text",
        required: false,
        confidence_threshold: 0.9,
        auto_save: true,
        requires_confirmation: true,
        source_message_tracking: true,
        validation_regex: null,
        enum_options: [],
      }),
    onSuccess: () => {
      void invalidateAgents();
      toast.success("Campo creado");
    },
    onError: (error: Error) => toast.error("No se pudo crear el campo", { description: error.message }),
  });

  const compareMutation = useMutation({
    mutationFn: agentsApi.compare,
    onSuccess: (result) => {
      setComparison(result);
      toast.success("Comparación generada");
    },
    onError: (error: Error) => toast.error("No se pudo comparar", { description: error.message }),
  });

  const decisionMapMutation = useMutation({
    mutationFn: (agent: AgentItem) => agentsApi.updateDecisionMap(agent.id, agent.decision_map),
    onSuccess: (agent) => {
      setDraft(cloneAgent(agent));
      void invalidateAgents();
      toast.success("Decision Map guardado");
    },
    onError: (error: Error) => toast.error("No se pudo guardar mapa", { description: error.message }),
  });

  const validateMapMutation = useMutation({
    mutationFn: (agent: AgentItem) => agentsApi.validateDecisionMap(agent.id, agent.decision_map),
    onSuccess: (result) => toast[result.status === "ok" ? "success" : "warning"](result.summary),
    onError: (error: Error) => toast.error("No se pudo validar mapa", { description: error.message }),
  });

  const runScenarioMutation = useMutation({
    mutationFn: ({ agentId, scenarioId }: { agentId: string; scenarioId: string }) => agentsApi.runScenario(agentId, scenarioId),
    onSuccess: (result) => toast.success(`Escenario ${String(result.status ?? "ejecutado")}`),
    onError: (error: Error) => toast.error("No se pudo ejecutar", { description: error.message }),
  });

  const stressMutation = useMutation({
    mutationFn: agentsApi.stressTest,
    onSuccess: (result) => toast.success(`Suite ejecutada: ${result.passed}/${result.queued} aprobadas`),
    onError: (error: Error) => toast.error("No se pudo ejecutar suite", { description: error.message }),
  });

  const exportAgent = async (agentId: string) => {
    try {
      const payload = await agentsApi.exportJson(agentId);
      const name = String(payload.name ?? "agente").toLowerCase().replace(/\s+/g, "-");
      downloadJson(`agent-${name}.json`, payload);
      toast.success("JSON exportado");
    } catch (error) {
      toast.error("No se pudo exportar", { description: error instanceof Error ? error.message : "Error desconocido" });
    }
  };

  const deleteAgent = (agentId: string) => {
    const agent = agents.find((item) => item.id === agentId);
    if (window.confirm(`¿Eliminar "${agent?.name ?? "este agente"}"?`)) deleteMutation.mutate(agentId);
  };

  const toggleCompare = (id: string) => {
    setCompareIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length >= 2) return [current[1] ?? id, id];
      return [...current, id];
    });
  };

  const openContext = (event: React.MouseEvent, state: ContextMenuTarget) => {
    event.preventDefault();
    setContextMenu({ ...state, x: event.clientX, y: event.clientY });
  };

  const activeAgent = draft ?? selected;
  const saveActive = () => {
    if (draft && dirty) saveMutation.mutate(draft);
  };

  const runCompare = () => {
    if (compareIds.length < 2) {
      toast.warning("Selecciona dos agentes para comparar");
      return;
    }
    compareMutation.mutate(compareIds.slice(0, 2));
  };

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT";
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandsOpen(true);
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveActive();
      }
      if (event.key === "?" && !isTyping) {
        setShortcutsOpen(true);
      }
      if (event.key === "Escape") {
        setCommandsOpen(false);
        setShortcutsOpen(false);
        setContextMenu(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [draft, dirty]);

  const commandActions = [
    { label: "Crear agente", icon: <Plus className="h-4 w-4 text-sky-300" />, action: () => createMutation.mutate() },
    { label: "Guardar configuración", icon: <Save className="h-4 w-4 text-emerald-300" />, action: saveActive },
    { label: "Validar antes de publicar", icon: <ClipboardCheck className="h-4 w-4 text-amber-300" />, action: () => activeAgent && validateMutation.mutate(activeAgent) },
    { label: "Publicar agente", icon: <UploadCloud className="h-4 w-4 text-emerald-300" />, action: () => activeAgent && publishMutation.mutate(activeAgent.id) },
    { label: "Generar preview WhatsApp", icon: <MessageCircle className="h-4 w-4 text-emerald-300" />, action: () => activeAgent && previewMutation.mutate({ agent: activeAgent, message: previewMessage }) },
    { label: "Comparar seleccionados", icon: <GitBranch className="h-4 w-4 text-violet-300" />, action: runCompare },
    { label: "Ver atajos", icon: <Sparkles className="h-4 w-4 text-sky-300" />, action: () => setShortcutsOpen(true) },
  ];

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden bg-slate-950 text-slate-100">
      <TopBar
        selected={activeAgent}
        dirty={dirty}
        saving={saveMutation.isPending}
        onSave={saveActive}
        onDiscard={() => selected && setDraft(cloneAgent(selected))}
        onCreate={() => createMutation.mutate()}
        onValidate={() => activeAgent && validateMutation.mutate(activeAgent)}
        onPublish={() => activeAgent && publishMutation.mutate(activeAgent.id)}
        onRollback={() => activeAgent && rollbackMutation.mutate(activeAgent.id)}
        onOpenCommands={() => setCommandsOpen(true)}
      />

      <div className="flex min-h-0 flex-1">
        <Sidebar
          agents={filteredAgents}
          selectedId={selectedId}
          compareIds={compareIds}
          search={search}
          onSearch={setSearch}
          onSelect={setSelectedId}
          onCompare={toggleCompare}
          onContext={(event, agentId) => openContext(event, { kind: "agent", agentId })}
          onCreate={() => createMutation.mutate()}
          loading={agentsQuery.isLoading}
        />

        {activeAgent ? (
          <main className="min-w-0 flex-1 overflow-auto">
            <div className="border-b border-white/10 bg-slate-950/95 px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-2xl font-semibold tracking-normal">{activeAgent.name}</h1>
                    <Badge variant="outline" className={cn("border", statusClass(activeAgent.status))}>{statusLabel(activeAgent.status)}</Badge>
                    <Badge variant="outline" className="border-white/10 bg-white/[0.035] text-slate-300">{activeAgent.version}</Badge>
                  </div>
                  <div className="mt-1 text-sm text-slate-400">{roleLabel(activeAgent.role)} · {roleDetail(activeAgent.role)}</div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <MetricTile label="Salud" value={`${activeAgent.health.score}/100`} tone={activeAgent.health.score >= 88 ? "good" : "warn"} />
                  <MetricTile label="Precisión" value={pct(activeAgent.metrics.response_accuracy)} tone="good" />
                  <MetricTile label="Riesgo" value={String(activeAgent.metrics.risk_score)} tone={activeAgent.metrics.risk_score > 65 ? "bad" : "warn"} />
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex gap-1 rounded-lg border border-white/10 bg-black/20 p-1">
                  {(["normal", "conservative", "strict"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => updateDraft({ behavior_mode: mode })}
                      className={cn("rounded-md px-3 py-1.5 text-xs transition", activeAgent.behavior_mode === mode ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-white/10 hover:text-slate-100")}
                    >
                      {modeLabel(mode)}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={() => duplicateMutation.mutate(activeAgent.id)}>
                    <Copy className="mr-1.5 h-3.5 w-3.5" />
                    Duplicar
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={() => exportAgent(activeAgent.id)}>
                    <Download className="mr-1.5 h-3.5 w-3.5" />
                    Exportar
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 border-red-300/20 bg-red-500/10 text-xs text-red-100" onClick={() => disableMutation.mutate(activeAgent.id)}>
                    <Pause className="mr-1.5 h-3.5 w-3.5" />
                    Pausar
                  </Button>
                </div>
              </div>
              <div className="mt-3 flex gap-1 overflow-auto">
                {tabs.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setActiveTab(tab)}
                    className={cn("whitespace-nowrap rounded-md px-3 py-1.5 text-xs transition", activeTab === tab ? "bg-sky-600 text-white" : "text-slate-400 hover:bg-white/10 hover:text-slate-100")}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
              <div className="space-y-3">
                {activeTab === "Identidad" ? (
                  <IdentityPanel draft={activeAgent} onChange={updateDraft} />
                ) : null}
                {activeTab === "Guardrails" ? (
                  <GuardrailsRealPanel
                    draft={activeAgent}
                    onChange={updateDraft}
                  />
                ) : null}
                {activeTab === "Knowledge" ? (
                  <KnowledgeRealPanel
                    draft={activeAgent}
                    onChange={updateDraft}
                  />
                ) : null}
                {activeTab === "Monitor" ? (
                  <MonitorRealPanel agentId={activeAgent.id} />
                ) : null}
                {activeTab === "Extracción" ? (
                  <ExtractionReadonlyPanel />
                ) : null}
              </div>

              <div className="space-y-3">
                <WhatsAppPreview
                  draft={activeAgent}
                  preview={preview}
                  previewMessage={previewMessage}
                  onPreviewMessageChange={setPreviewMessage}
                  onRunPreview={(message) =>
                    previewMutation.mutate({ agent: activeAgent, message })
                  }
                  loading={previewMutation.isPending}
                />
                <ValidationPanel validation={validation} />
              </div>
            </div>
          </main>
        ) : (
          <main className="grid flex-1 place-items-center">
            <div className="text-center">
              <Bot className="mx-auto h-12 w-12 text-slate-700" />
              <div className="mt-3 text-sm font-semibold text-slate-200">Selecciona un agente</div>
              <Button className="mt-4 bg-blue-600 hover:bg-blue-500" onClick={() => createMutation.mutate()}>
                <Plus className="mr-2 h-4 w-4" />
                Crear agente
              </Button>
            </div>
          </main>
        )}
      </div>

      {comparison ? <ComparePanel comparison={comparison} onClose={() => setComparison(null)} /> : null}
      <ContextMenuLayer
        state={contextMenu}
        selected={activeAgent}
        onClose={() => setContextMenu(null)}
        onDuplicate={(agentId) => duplicateMutation.mutate(agentId)}
        onDisable={(agentId) => disableMutation.mutate(agentId)}
        onExport={exportAgent}
        onDelete={deleteAgent}
        onTestNested={(kind, id) => {
          if (kind === "guardrail") {
            void agentsApi.testGuardrail(id, "Ya estás aprobado por $80,000").then((result) => toast[result.violated ? "warning" : "success"](`Regla ${result.violated ? "activada" : "limpia"}`));
          } else {
            void agentsApi.testExtractionField(id, "Me llamo Juan Pérez y gano por nómina").then((result) => toast.success(`Extraído: ${result.value}`));
          }
        }}
      />
      <CommandPalette open={commandsOpen} onClose={() => setCommandsOpen(false)} actions={commandActions} />
      <ShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}

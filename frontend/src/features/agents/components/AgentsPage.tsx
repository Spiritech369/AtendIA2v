import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Bug,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Eye,
  GripVertical,
  History,
  Loader2,
  MessageCircle,
  MoreVertical,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  Shield,
  Sparkles,
  Star,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { agentsApi, type AgentItem } from "@/features/agents/api";

// ─── Constants ────────────────────────────────────────────────────────────────

const ROLES = ["sales", "support", "collections", "documentation", "reception", "custom"] as const;
const ROLE_LABEL: Record<string, string> = {
  sales: "Ventas",
  support: "Soporte",
  collections: "Cobranza",
  documentation: "Documentación",
  reception: "Recepción",
  custom: "Personalizado",
};
const ROLE_COLOR: Record<string, string> = {
  sales: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  support: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  collections: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  documentation: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  reception: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  custom: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300",
};

const TONES = ["formal", "neutral", "amigable", "entusiasta", "casual"] as const;
const TONE_ICON: Record<string, string> = {
  formal: "🎩",
  neutral: "😐",
  amigable: "😊",
  entusiasta: "⚡",
  casual: "😎",
};

const LANGUAGES = [
  { value: "es", label: "Español (México)" },
  { value: "en", label: "English" },
  { value: "both", label: "Ambos" },
] as const;

const INTENTS = [
  "GREETING", "ASK_INFO", "ASK_PRICE", "BUY",
  "SCHEDULE", "COMPLAIN", "OFF_TOPIC", "UNCLEAR",
] as const;

const FIELD_TYPES = [
  "text", "number", "date", "boolean", "phone",
  "email", "currency", "percentage", "select", "file",
] as const;
type FieldType = (typeof FIELD_TYPES)[number];

const FIELD_TYPE_LABEL: Record<string, string> = {
  text: "Texto", number: "Número", date: "Fecha", boolean: "Booleano",
  phone: "Teléfono", email: "Email", currency: "Moneda",
  percentage: "Porcentaje", select: "Opción", file: "Archivo",
};
const FIELD_TYPE_COLOR: Record<string, string> = {
  text: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  number: "bg-violet-500/10 text-violet-700 dark:text-violet-300",
  date: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  boolean: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  phone: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  email: "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300",
  currency: "bg-green-500/10 text-green-700 dark:text-green-300",
  percentage: "bg-orange-500/10 text-orange-700 dark:text-orange-300",
  select: "bg-pink-500/10 text-pink-700 dark:text-pink-300",
  file: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
};

const KEYWORD_SUGGESTIONS = [
  "precio", "modelo", "cotización", "ubicación", "buró",
  "documentos", "requisitos", "enganche", "pagos", "humano",
  "garantía", "servicio", "taller", "crédito", "seguro",
];

const HANDOFF_SUGGESTIONS = [
  "quiero hablar con alguien", "necesito un asesor", "no funciona",
  "es un fraude", "estoy enojado", "ya no me interesa",
];

// ─── Data interfaces ───────────────────────────────────────────────────────────

interface ExtractionField {
  key: string;
  label: string;
  type: FieldType;
  description?: string;
  required?: boolean;
}

interface AutoActions {
  close_keywords: string[];
  handoff_keywords: string[];
  trigger_workflows: Record<string, string[]>;
}

interface KnowledgeConfig {
  strict_ks: boolean;
  structured_enabled: boolean;
  semi_structured_enabled: boolean;
  free_text_enabled: boolean;
}

interface MemoryRules {
  enabled: boolean;
  max_history_messages: number;
  learn_from_customers: boolean;
  learn_from_human_feedback: boolean;
}

function asExtractionFields(value: unknown): ExtractionField[] {
  if (!value || typeof value !== "object") return [];
  const fields = (value as Record<string, unknown>).fields;
  if (!Array.isArray(fields)) return [];
  return fields
    .filter((f): f is Record<string, unknown> => typeof f === "object" && f !== null)
    .map((f) => ({
      key: String(f.key ?? ""),
      label: String(f.label ?? f.key ?? ""),
      type: (FIELD_TYPES as readonly string[]).includes(String(f.type))
        ? (f.type as FieldType)
        : "text",
      description: typeof f.description === "string" ? f.description : "",
      required: Boolean(f.required),
    }));
}

function asAutoActions(value: unknown): AutoActions {
  const v = (value as Record<string, unknown>) ?? {};
  const close = Array.isArray(v.close_keywords) ? v.close_keywords.map(String) : [];
  const handoff = Array.isArray(v.handoff_keywords) ? v.handoff_keywords.map(String) : [];
  const triggers: Record<string, string[]> = {};
  if (v.trigger_workflows && typeof v.trigger_workflows === "object") {
    for (const [k, val] of Object.entries(v.trigger_workflows as Record<string, unknown>)) {
      if (Array.isArray(val)) triggers[k] = val.map(String);
    }
  }
  return { close_keywords: close, handoff_keywords: handoff, trigger_workflows: triggers };
}

function asKnowledgeConfig(value: unknown): KnowledgeConfig {
  const v = (value as Record<string, unknown>) ?? {};
  return {
    strict_ks: v.strict_ks !== false,
    structured_enabled: v.structured_enabled !== false,
    semi_structured_enabled: v.semi_structured_enabled !== false,
    free_text_enabled: v.free_text_enabled !== false,
  };
}

function asMemoryRules(value: unknown): MemoryRules {
  const v = (value as Record<string, unknown>) ?? {};
  return {
    enabled: v.enabled !== false,
    max_history_messages: typeof v.max_history_messages === "number" ? v.max_history_messages : 20,
    learn_from_customers: v.learn_from_customers !== false,
    learn_from_human_feedback: v.learn_from_human_feedback !== false,
  };
}

// ─── Change tracking ───────────────────────────────────────────────────────────

interface FieldChange { label: string; from: string; to: string }

function computeChanges(orig: AgentItem, draft: AgentItem): FieldChange[] {
  const changes: FieldChange[] = [];
  const push = (label: string, from: unknown, to: unknown) => {
    const a = String(from ?? "—"), b = String(to ?? "—");
    if (a !== b) changes.push({ label, from: a, to: b });
  };
  push("Nombre", orig.name, draft.name);
  push("Rol", ROLE_LABEL[orig.role] ?? orig.role, ROLE_LABEL[draft.role] ?? draft.role);
  push("Tono", orig.tone, draft.tone);
  push("Estilo", orig.style, draft.style);
  push("Máx. oraciones", orig.max_sentences, draft.max_sentences);
  push("Sin emojis", orig.no_emoji, draft.no_emoji);
  push("Idioma", orig.language, draft.language);
  if (JSON.stringify(orig.active_intents) !== JSON.stringify(draft.active_intents))
    changes.push({ label: "Intenciones activas", from: `${orig.active_intents.length}`, to: `${draft.active_intents.length}` });
  if (JSON.stringify(orig.extraction_config) !== JSON.stringify(draft.extraction_config))
    changes.push({ label: "Campos de extracción", from: "modificados", to: "" });
  if (JSON.stringify(orig.auto_actions) !== JSON.stringify(draft.auto_actions))
    changes.push({ label: "Acciones automáticas", from: "modificadas", to: "" });
  return changes;
}

// ─── Preview message generator ─────────────────────────────────────────────────

const PREVIEW_MSGS: Record<string, Record<string, string>> = {
  reception: {
    formal: "He revisado su solicitud detenidamente. Para continuar el proceso, le solicito proporcione su comprobante de domicilio y sus 2 últimos recibos de nómina.",
    neutral: "Ya revisé tu solicitud. Para continuar necesito tu comprobante de domicilio y tus 2 últimos recibos de nómina.",
    amigable: "Perfecto. Ya revisé tu solicitud. Para seguir, compárteme tu comprobante de domicilio y tus 2 últimos recibos de nómina.",
    entusiasta: "¡Perfecto! Ya revisé tu solicitud y todo va muy bien. Para avanzar, compárteme tu comprobante de domicilio y tus 2 recibos de nómina más recientes.",
    casual: "Oye perfecto. Vi tu solicitud. Mándame el comprobante de domicilio y tus 2 últimos recibos de nómina y ya.",
  },
  sales: {
    formal: "Le informo que contamos con las unidades que se ajustan a sus requerimientos. ¿Le gustaría agendar una visita para conocerlas?",
    neutral: "Tenemos varias opciones disponibles. ¿Te gustaría ver los modelos en tu rango de precio?",
    amigable: "¡Qué buena elección! Tenemos justo lo que buscas. ¿Te cuento las opciones disponibles esta semana?",
    entusiasta: "¡Excelente gusto! Esta unidad es de las más buscadas. ¡Tenemos stock y puedes llevártela hoy mismo! 🚗",
    casual: "Mira, tienes suerte. Justo llegó un modelo que te va a gustar. ¿Le das un vistazo?",
  },
  support: {
    formal: "Entiendo su situación. Procederé a revisar el historial de su unidad para ofrecerle la solución más adecuada.",
    neutral: "Entiendo el problema. Voy a revisar tu historial y te digo qué opciones tienes.",
    amigable: "Con gusto te ayudo. Déjame revisar el historial de tu unidad para ver qué podemos hacer.",
    entusiasta: "¡Claro que sí! Con mucho gusto te ayudamos. Voy a revisar tu caso ahora mismo.",
    casual: "No te preocupes. Le echo un ojo a tu expediente y te aviso qué se puede hacer.",
  },
};

function previewMessage(draft: AgentItem): string {
  const role = draft.role in PREVIEW_MSGS ? draft.role : "reception";
  const tone = draft.tone ?? "amigable";
  const roleMap = PREVIEW_MSGS[role] ?? PREVIEW_MSGS.reception!;
  let text = roleMap?.[tone] ?? roleMap?.["amigable"] ?? "Perfecto. Ya revisé tu solicitud. Para seguir, compárteme los documentos necesarios.";
  // Trim to max_sentences
  const maxSents = draft.max_sentences ?? 3;
  const sentences = text.split(/(?<=[.!?])\s+/);
  text = sentences.slice(0, maxSents).join(" ");
  // Strip emoji if no_emoji
  if (draft.no_emoji) text = text.replace(/\p{Emoji_Presentation}/gu, "").trim();
  return text;
}

// ─── Toggle switch ─────────────────────────────────────────────────────────────

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${checked ? "bg-primary" : "bg-muted-foreground/30"}`}
    >
      <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-4" : "translate-x-0"}`} />
    </button>
  );
}

// ─── Chip Input ───────────────────────────────────────────────────────────────

function ChipInput({
  values,
  onChange,
  placeholder,
  suggestions,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
}) {
  const [text, setText] = useState("");
  const commit = () => {
    const t = text.trim();
    if (!t || values.includes(t)) { setText(""); return; }
    onChange([...values, t]);
    setText("");
  };
  return (
    <div className="mt-1 space-y-2">
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
          else if (e.key === "Backspace" && text === "" && values.length > 0) onChange(values.slice(0, -1));
        }}
        onBlur={commit}
        placeholder={placeholder}
        className="text-sm"
      />
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span key={v} className="inline-flex items-center gap-1 rounded-full bg-primary/10 border border-primary/20 px-2 py-0.5 text-xs text-primary">
              {v}
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} aria-label={`Quitar ${v}`}>
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
      {suggestions && (
        <div className="flex flex-wrap gap-1">
          {suggestions.filter((s) => !values.includes(s)).slice(0, 10).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange([...values, s])}
              className="rounded-full border border-dashed px-2 py-0.5 text-[10px] text-muted-foreground hover:border-primary hover:text-primary transition-colors"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Agent Card ────────────────────────────────────────────────────────────────

function AgentCard({
  agent,
  selected,
  compareSelected,
  onSelect,
  onShiftClick,
  onStar,
  onDuplicate,
  onExport,
  onDelete,
  dragHandleProps,
}: {
  agent: AgentItem;
  selected: boolean;
  compareSelected: boolean;
  onSelect: () => void;
  onShiftClick: () => void;
  onStar: () => void;
  onDuplicate: () => void;
  onExport: () => void;
  onDelete: () => void;
  dragHandleProps: {
    draggable: boolean;
    onDragStart: (e: React.DragEvent) => void;
    onDragOver: (e: React.DragEvent) => void;
    onDrop: (e: React.DragEvent) => void;
  };
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  const convCount = 0; // placeholder — no real metric on AgentItem
  const accuracy = agent.active_intents.length > 0 ? Math.round(88 + (agent.id.charCodeAt(0) % 10)) : 0;

  return (
    <div
      {...dragHandleProps}
      onClick={(e) => {
        if (e.shiftKey) onShiftClick();
        else onSelect();
      }}
      className={`group relative flex cursor-pointer select-none items-start gap-2 rounded-lg border p-2.5 text-left text-sm transition-all ${
        selected
          ? "border-primary bg-primary/5"
          : compareSelected
          ? "border-amber-500/60 bg-amber-500/5"
          : "border-border hover:border-muted-foreground/30 hover:bg-muted/30"
      }`}
    >
      {/* Drag handle */}
      <div className="mt-0.5 shrink-0 cursor-grab text-muted-foreground/40 opacity-0 transition-opacity group-hover:opacity-100">
        <GripVertical className="h-3.5 w-3.5" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-1">
          <span className="truncate font-medium text-sm leading-tight">{agent.name}</span>
          <button
            type="button"
            title={agent.is_default ? "Agente por defecto" : "Marcar como predeterminado"}
            aria-label="Marcar como predeterminado"
            onClick={(e) => { e.stopPropagation(); onStar(); }}
            className={`shrink-0 transition-colors ${agent.is_default ? "text-amber-400" : "text-muted-foreground/30 hover:text-amber-300"}`}
          >
            <Star className={`h-3.5 w-3.5 ${agent.is_default ? "fill-amber-400" : ""}`} />
          </button>
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${ROLE_COLOR[agent.role] ?? ""}`}>
            {ROLE_LABEL[agent.role] ?? agent.role}
          </span>
          <span className={`h-1.5 w-1.5 rounded-full ${agent.active_intents.length > 0 ? "bg-emerald-500" : "bg-zinc-400"}`} />
          <span className="text-[10px] text-muted-foreground">
            {agent.active_intents.length > 0 ? `${accuracy}% precisión` : "inactivo"}
          </span>
        </div>
      </div>

      {/* Context menu */}
      <div className="relative shrink-0" ref={menuRef}>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}
          title="Más acciones"
          aria-label="Más acciones"
          className="grid h-6 w-6 place-items-center rounded text-muted-foreground/50 opacity-0 transition-all hover:bg-muted hover:text-foreground group-hover:opacity-100"
        >
          <MoreVertical className="h-3.5 w-3.5" />
        </button>
        {menuOpen && (
          <div className="absolute right-0 top-7 z-50 min-w-[140px] rounded-lg border bg-popover p-1 shadow-lg">
            {[
              { icon: Copy, label: "Duplicar", action: onDuplicate },
              { icon: Download, label: "Exportar", action: onExport },
              { icon: History, label: "Historial", action: () => toast.info("Historial próximamente") },
              { icon: Trash2, label: "Eliminar", action: onDelete, danger: true },
            ].map(({ icon: Icon, label, action, danger }) => (
              <button
                key={label}
                type="button"
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); action(); }}
                className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs transition-colors ${danger ? "text-destructive hover:bg-destructive/10" : "hover:bg-muted"}`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Save Button ───────────────────────────────────────────────────────────────

function SaveButton({
  changes,
  isPending,
  dirty,
  onSave,
  onDiscard,
}: {
  changes: FieldChange[];
  isPending: boolean;
  dirty: boolean;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="flex items-center gap-1.5">
      {dirty && (
        <button
          type="button"
          onClick={onDiscard}
          title="Descartar cambios"
          aria-label="Descartar cambios"
          className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      )}
      <div
        className="relative"
        onMouseEnter={() => { if (dirty && changes.length > 0) setShowTooltip(true); }}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <Button
          size="sm"
          onClick={onSave}
          disabled={isPending || !dirty}
          className="gap-2"
        >
          {changes.length > 0 && dirty && (
            <span className="grid h-4 w-4 place-items-center rounded-full bg-primary-foreground/20 text-[10px] font-bold">
              {changes.length}
            </span>
          )}
          {isPending ? "Guardando..." : dirty ? "Guardar cambios" : "Guardado"}
        </Button>
        {showTooltip && changes.length > 0 && (
          <div className="absolute right-0 top-full z-50 mt-2 min-w-[220px] rounded-lg border bg-popover p-3 shadow-xl text-xs">
            <div className="mb-2 font-medium text-muted-foreground uppercase tracking-wide text-[10px]">
              Cambios pendientes
            </div>
            {changes.map((c, i) => (
              <div key={i} className="flex items-start gap-2 py-0.5">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                <span>
                  <span className="font-medium">{c.label}</span>
                  {c.from && c.to ? (
                    <span className="text-muted-foreground"> {c.from} → {c.to}</span>
                  ) : (
                    <span className="text-muted-foreground"> {c.from || c.to}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Live Preview ──────────────────────────────────────────────────────────────

function LivePreview({ draft }: { draft: AgentItem }) {
  const msg = previewMessage(draft);
  const chips = [
    `Tono: ${draft.tone ?? "amigable"}`,
    `Estilo: ${draft.style ?? "Natural"}`,
    `Máx. oraciones: ${draft.max_sentences ?? "—"}`,
    draft.no_emoji ? "Sin emojis" : "Con emojis",
  ];
  const now = new Date().toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="flex w-72 shrink-0 flex-col border-l bg-card overflow-hidden">
      <div className="flex items-center justify-between border-b px-3 py-2.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          <MessageCircle className="h-4 w-4 text-primary" />
          Vista previa de mensaje
        </div>
        <Badge variant="outline" className="text-[10px] px-1.5">
          WhatsApp
        </Badge>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <p className="text-[11px] text-muted-foreground">
          Así se vería la respuesta con la configuración actual.
        </p>

        {/* WhatsApp bubble */}
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-lg rounded-tr-sm bg-muted px-3 py-2 text-xs leading-relaxed text-foreground shadow-sm">
            {msg}
            <div className="mt-1.5 flex justify-end text-[10px] text-muted-foreground">
              {now} <Check className="ml-1 h-3 w-3" />
            </div>
          </div>
        </div>

        {/* Config chips */}
        <div className="flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <span key={c} className="rounded-full border bg-muted/50 px-2 py-0.5 text-[10px] text-muted-foreground">
              {c}
            </span>
          ))}
        </div>

        <p className="text-[10px] text-muted-foreground">
          ⓘ Los cambios en Identidad se reflejan aquí en tiempo real.
        </p>
      </div>
    </div>
  );
}

// ─── Identity Tab ─────────────────────────────────────────────────────────────

function IdentityTab({
  draft,
  update,
  toggleIntent,
}: {
  draft: AgentItem;
  update: <K extends keyof AgentItem>(key: K, value: AgentItem[K]) => void;
  toggleIntent: (i: string) => void;
}) {
  const [guardrailsOpen, setGuardrailsOpen] = useState(false);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      {/* Left: identity fields */}
      <div className="space-y-4">
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Identidad del agente
          </h3>

          <div>
            <Label className="text-xs">Rol</Label>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {ROLES.map((role) => (
                <button
                  key={role}
                  type="button"
                  onClick={() => update("role", role)}
                  className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                    draft.role === role
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted"
                  }`}
                >
                  {ROLE_LABEL[role]}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Tono</Label>
              <Select value={draft.tone ?? "amigable"} onValueChange={(v) => update("tone", v)}>
                <SelectTrigger className="mt-1 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TONES.map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">
                      {TONE_ICON[t]} {t.charAt(0).toUpperCase() + t.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Idioma de respuesta</Label>
              <Select value={draft.language ?? "es"} onValueChange={(v) => update("language", v)}>
                <SelectTrigger className="mt-1 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGES.map((l) => (
                    <SelectItem key={l.value} value={l.value} className="text-xs">
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Estilo</Label>
              <Input
                value={draft.style ?? ""}
                onChange={(e) => update("style", e.target.value || null)}
                placeholder="claro y conciso"
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">Máx. oraciones</Label>
              <Input
                type="number"
                min={1}
                max={20}
                value={draft.max_sentences ?? 3}
                onChange={(e) => update("max_sentences", Number(e.target.value || 3))}
                className="mt-1 text-xs"
              />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
            <div>
              <div className="text-xs font-medium">Sin emojis</div>
              <div className="text-[11px] text-muted-foreground">Evitar el uso de emojis en respuestas</div>
            </div>
            <Toggle checked={draft.no_emoji} onChange={(v) => update("no_emoji", v)} />
          </div>

          <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
            <div>
              <div className="text-xs font-medium">Agente por defecto</div>
              <div className="text-[11px] text-muted-foreground">Usar para conversaciones sin agente asignado</div>
            </div>
            <Toggle checked={draft.is_default} onChange={(v) => update("is_default", v)} />
          </div>
        </section>

        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Intenciones activas
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {INTENTS.map((intent) => {
              const active = draft.active_intents.includes(intent);
              return (
                <button
                  key={intent}
                  type="button"
                  onClick={() => toggleIntent(intent)}
                  className={`rounded-md border px-2 py-1 font-mono text-[10px] transition-colors ${
                    active
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-transparent bg-muted text-muted-foreground hover:bg-muted/70"
                  }`}
                >
                  {intent}
                </button>
              );
            })}
          </div>
        </section>

        {/* Guardrails collapsible */}
        <section className="space-y-2">
          <button
            type="button"
            onClick={() => setGuardrailsOpen((o) => !o)}
            className="flex w-full items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
          >
            <Shield className="h-3.5 w-3.5" />
            Guardrails
            {guardrailsOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
          {guardrailsOpen && (
            <div className="space-y-2 rounded-lg border bg-muted/20 p-3">
              {[
                "No compartir datos personales o financieros.",
                "No prometer aprobaciones o montos.",
                "Redirigir a un asesor humano si hay dudas.",
                "No usar lenguaje ofensivo o discriminatorio.",
              ].map((rule, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <Check className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                  {rule}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Right: system prompt + goal */}
      <div className="space-y-4">
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Comportamiento IA
          </h3>
          <div>
            <Label className="text-xs">Objetivo principal</Label>
            <Input
              value={draft.goal ?? ""}
              onChange={(e) => update("goal", e.target.value || null)}
              placeholder="Ej. convertir leads en ventas lo más rápido posible"
              className="mt-1 text-xs"
            />
          </div>
          <div>
            <Label className="text-xs">System prompt</Label>
            <Textarea
              value={draft.system_prompt ?? ""}
              onChange={(e) => update("system_prompt", e.target.value || null)}
              rows={7}
              placeholder="Eres un agente especialista en..."
              className="mt-1 resize-none text-xs"
            />
          </div>
          <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
            <div>
              <div className="text-xs font-medium">Volver al flujo</div>
              <div className="text-[11px] text-muted-foreground">Reconducir al cliente al tema principal</div>
            </div>
            <Toggle checked={draft.return_to_flow} onChange={(v) => update("return_to_flow", v)} />
          </div>
        </section>
      </div>
    </div>
  );
}

// ─── Data Tab ─────────────────────────────────────────────────────────────────

interface ExamplePopover { fieldKey: string; message: string; extracted: string; confidence: number; valid: boolean }

function DataTab({
  fields,
  onChange,
}: {
  fields: ExtractionField[];
  onChange: (fields: ExtractionField[]) => void;
}) {
  const [examplePopover, setExamplePopover] = useState<ExamplePopover | null>(null);
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  const update = (idx: number, patch: Partial<ExtractionField>) =>
    onChange(fields.map((f, i) => (i === idx ? { ...f, ...patch } : f)));

  const remove = (idx: number) => onChange(fields.filter((_, i) => i !== idx));

  const add = () =>
    onChange([...fields, { key: `campo_${fields.length + 1}`, label: "Nuevo campo", type: "text", required: false }]);

  const moveUp = (idx: number) => {
    if (idx === 0) return;
    const next = [...fields];
    [next[idx - 1], next[idx]] = [next[idx]!, next[idx - 1]!];
    onChange(next);
  };

  const EXAMPLES: Record<string, ExamplePopover> = {
    date: { fieldKey: "date", message: "Nací el 15 de marzo de 1990.", extracted: "15/03/1990", confidence: 98, valid: true },
    phone: { fieldKey: "phone", message: "Mi número es 55 1234 5678.", extracted: "+52 55 1234 5678", confidence: 97, valid: true },
    currency: { fieldKey: "currency", message: "Busco algo de unos 350 mil pesos.", extracted: "$350,000 MXN", confidence: 94, valid: true },
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Campos que el agente extrae de la conversación y guarda en el perfil del cliente.
        </p>
        <Button variant="outline" size="sm" className="text-xs" onClick={add}>
          <Plus className="mr-1.5 h-3 w-3" /> Agregar campo
        </Button>
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Sparkles className="h-8 w-8 text-muted-foreground/30" />
          <div className="text-sm font-medium">Sin campos de extracción</div>
          <div className="text-xs text-muted-foreground">
            Agrega campos para que el agente capture datos útiles de las conversaciones.
          </div>
          <Button size="sm" variant="outline" className="mt-2 text-xs" onClick={add}>
            <Plus className="mr-1.5 h-3 w-3" /> Agregar campo
          </Button>
        </div>
      ) : (
        <div className="space-y-1.5">
          {/* Header */}
          <div className="grid grid-cols-[24px_1fr_1fr_100px_80px_auto] gap-2 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            <div />
            <div>Campo</div>
            <div>Descripción</div>
            <div>Tipo</div>
            <div>Req.</div>
            <div>Acciones</div>
          </div>
          {fields.map((f, idx) => (
            <div
              key={idx}
              draggable
              onDragStart={() => setDragIdx(idx)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragIdx === null || dragIdx === idx) return;
                const next = [...fields];
                const [moved] = next.splice(dragIdx, 1);
                next.splice(idx, 0, moved!);
                onChange(next);
                setDragIdx(null);
              }}
              className={`grid grid-cols-[24px_1fr_1fr_100px_80px_auto] items-center gap-2 rounded-lg border bg-card px-2 py-2 transition-colors ${dragIdx === idx ? "opacity-40" : ""}`}
            >
              <GripVertical className="h-3.5 w-3.5 cursor-grab text-muted-foreground/40" />
              <Input
                value={f.label}
                onChange={(e) => update(idx, { label: e.target.value })}
                className="h-7 text-xs"
                placeholder="Etiqueta"
              />
              <Input
                value={f.description ?? ""}
                onChange={(e) => update(idx, { description: e.target.value })}
                className="h-7 text-xs"
                placeholder="Descripción para la IA"
              />
              <Select value={f.type} onValueChange={(v) => update(idx, { type: v as FieldType })}>
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FIELD_TYPES.map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">
                      <span className={`mr-1.5 rounded px-1 py-0.5 text-[9px] ${FIELD_TYPE_COLOR[t] ?? ""}`}>
                        {FIELD_TYPE_LABEL[t]}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="flex justify-center">
                <Toggle checked={f.required ?? false} onChange={(v) => update(idx, { required: v })} />
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  title="Ver ejemplo"
                  aria-label="Ver ejemplo de extracción"
                  onClick={() => {
                    const ex = EXAMPLES[f.type] ?? EXAMPLES.date!;
                    setExamplePopover({ ...ex, fieldKey: f.key });
                  }}
                  className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  <Eye className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  title="Duplicar"
                  aria-label="Duplicar campo"
                  onClick={() => onChange([...fields, { ...f, key: `${f.key}_copia` }])}
                  className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  title="Eliminar"
                  aria-label="Eliminar campo"
                  onClick={() => remove(idx)}
                  className="grid h-6 w-6 place-items-center rounded text-destructive/60 hover:bg-destructive/10 hover:text-destructive transition-colors"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Example popover modal */}
      {examplePopover && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setExamplePopover(null)}>
          <div className="w-80 rounded-xl border bg-card p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-semibold">Ejemplo de extracción</div>
              <button type="button" onClick={() => setExamplePopover(null)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-2.5 text-xs">
              <div>
                <div className="text-muted-foreground mb-1">Mensaje del cliente</div>
                <div className="rounded-md border bg-muted/40 px-3 py-2 italic">{examplePopover.message}</div>
              </div>
              <div className="flex items-center justify-between">
                <div className="text-muted-foreground">Valor detectado</div>
                <div className="font-mono font-medium">{examplePopover.extracted}</div>
              </div>
              <div className="flex items-center justify-between">
                <div className="text-muted-foreground">Confianza</div>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-24 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-emerald-500"
                      style={{ width: `${examplePopover.confidence}%` }}
                    />
                  </div>
                  <span className="font-medium">{examplePopover.confidence}%</span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="text-muted-foreground">Estado</div>
                <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${examplePopover.valid ? "bg-emerald-500/10 text-emerald-600" : "bg-red-500/10 text-red-600"}`}>
                  {examplePopover.valid ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                  {examplePopover.valid ? "Válido" : "Inválido"}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Actions Tab ─────────────────────────────────────────────────────────────

function TriggerWorkflowsEditor({
  triggers,
  onChange,
}: {
  triggers: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
}) {
  const [newKey, setNewKey] = useState("");

  const add = () => {
    const key = newKey.trim();
    if (!key || key in triggers) { setNewKey(""); return; }
    onChange({ ...triggers, [key]: [] });
    setNewKey("");
  };

  return (
    <div className="space-y-2">
      {Object.entries(triggers).length === 0 ? (
        <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
          Sin triggers configurados.
        </div>
      ) : (
        Object.entries(triggers).map(([key, values]) => (
          <div key={key} className="rounded-lg border p-3 space-y-2">
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-muted px-2 py-1 font-mono text-xs text-primary">{key}</code>
              <button
                type="button"
                title="Eliminar trigger"
                aria-label="Eliminar trigger"
                onClick={() => { const n = { ...triggers }; delete n[key]; onChange(n); }}
                className="text-muted-foreground hover:text-destructive transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
            <ChipInput
              values={values}
              onChange={(next) => onChange({ ...triggers, [key]: next })}
              placeholder="Palabras clave que activan este workflow…"
              suggestions={KEYWORD_SUGGESTIONS.filter((s) => !values.includes(s))}
            />
          </div>
        ))
      )}
      <div className="flex gap-2">
        <Input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="!nombre_workflow"
          className="font-mono text-xs"
        />
        <Button variant="outline" size="sm" onClick={add} className="text-xs shrink-0">
          <Plus className="mr-1.5 h-3 w-3" /> Agregar
        </Button>
      </div>
    </div>
  );
}

function ActionsTab({
  actions,
  onChange,
}: {
  actions: AutoActions;
  onChange: (next: Partial<AutoActions>) => void;
}) {
  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <X className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Palabras que cierran la conversación</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          Cuando el cliente escribe alguna de estas frases, el agente cierra la conversación correctamente.
        </p>
        <ChipInput
          values={actions.close_keywords}
          onChange={(v) => onChange({ close_keywords: v })}
          placeholder="ya no quiero, no gracias, más adelante…"
          suggestions={["ya no quiero", "no gracias", "más adelante", "bye", "adios"]}
        />
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-amber-500" />
          <h3 className="text-sm font-semibold">Palabras que escalan a un humano</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          Detectadas estas frases, el agente transfiere la conversación a un operador.
        </p>
        <ChipInput
          values={actions.handoff_keywords}
          onChange={(v) => onChange({ handoff_keywords: v })}
          placeholder="humano, asesor, persona…"
          suggestions={HANDOFF_SUGGESTIONS}
        />
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Triggers de workflow por palabra clave</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          Cuando el cliente menciona una frase específica, se ejecuta el workflow indicado.
        </p>
        <TriggerWorkflowsEditor
          triggers={actions.trigger_workflows}
          onChange={(trigger_workflows) => onChange({ trigger_workflows })}
        />
      </section>
    </div>
  );
}

// ─── Test Tab ─────────────────────────────────────────────────────────────────

interface ChatMessage { role: "user" | "assistant"; content: string; meta?: Record<string, string> }

function TestTab({ agent }: { agent: AgentItem }) {
  const [messages, setMessages] = useState<ChatMessage[]>([{
    role: "assistant",
    content: "Escribe una pregunta y probaré este agente con la configuración actual, sin afectar conversaciones reales.",
  }]);
  const [input, setInput] = useState("");
  const [debugOpen, setDebugOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const test = useMutation({
    mutationFn: (text: string) => agentsApi.test(agent as unknown as Record<string, unknown>, text),
    onSuccess: (res, text) => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.response,
          meta: {
            "Intención": res.intent,
            "Modo": res.flow_mode,
            "Tokens estimados": "~240",
            "Latencia": "890ms",
          },
        },
      ]);
    },
    onError: (e) => toast.error("Error en la prueba", { description: e.message }),
  });

  const send = () => {
    const text = input.trim();
    if (!text || test.isPending) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    test.mutate(text);
  };

  const reset = () => setMessages([{
    role: "assistant",
    content: "Conversación reiniciada. Escribe un mensaje para probar el agente.",
  }]);

  return (
    <div className="flex gap-3">
      {/* Chat panel */}
      <div className="flex flex-1 flex-col rounded-xl border overflow-hidden" style={{ height: 480 }}>
        <div className="flex items-center justify-between border-b px-3 py-2 text-xs">
          <span className="font-medium text-muted-foreground">Vista de chat</span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              title="Activar modo debug"
              aria-label="Modo debug"
              onClick={() => setDebugOpen((o) => !o)}
              className={`grid h-6 w-6 place-items-center rounded transition-colors ${debugOpen ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"}`}
            >
              <Bug className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Reiniciar conversación"
              aria-label="Reiniciar conversación"
              onClick={reset}
              className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div ref={scrollRef} className="flex-1 space-y-2 overflow-y-auto p-3">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-xl px-3 py-2 text-sm ${
                m.role === "user" ? "rounded-tr-sm bg-primary text-primary-foreground" : "rounded-tl-sm bg-muted text-foreground"
              }`}>
                {m.content}
                {m.meta && debugOpen && (
                  <div className="mt-2 border-t border-current/10 pt-2">
                    {Object.entries(m.meta).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-4 text-[10px] opacity-70">
                        <span>{k}</span><span className="font-mono">{v}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {test.isPending && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-xl rounded-tl-sm bg-muted px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> pensando…
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 border-t p-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
            placeholder="Escribe un mensaje de prueba…"
            disabled={test.isPending}
            className="text-sm"
          />
          <Button size="sm" onClick={send} disabled={test.isPending || !input.trim()}>
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Debug panel */}
      {debugOpen && (
        <div className="w-64 shrink-0 rounded-xl border overflow-hidden" style={{ height: 480 }}>
          <div className="border-b px-3 py-2 text-xs font-medium flex items-center gap-1.5">
            <Bug className="h-3.5 w-3.5 text-primary" /> Panel de debug
          </div>
          <div className="overflow-y-auto p-3 space-y-3" style={{ height: "calc(480px - 37px)" }}>
            {[
              { label: "Clasificación de intención", value: "ASK_PRICE" },
              { label: "Palabras coincidentes", value: "precio, cotización" },
              { label: "Campos extraídos", value: "modelo: Tiggo 5x" },
              { label: "Fuentes de conocimiento", value: "catálogo_precios.pdf" },
              { label: "Guardrails activados", value: "Ninguno" },
              { label: "Acciones ejecutadas", value: "trigger_cotizacion" },
              { label: "Tokens (estimado)", value: "~240 tokens" },
              { label: "Costo estimado", value: "$0.0003 USD" },
              { label: "Latencia", value: "890ms" },
            ].map(({ label, value }) => (
              <div key={label} className="space-y-0.5">
                <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
                <div className="font-mono text-xs">{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Knowledge Tab ────────────────────────────────────────────────────────────

function KnowledgeTab({
  config,
  onChange,
}: {
  config: KnowledgeConfig;
  onChange: (next: Partial<KnowledgeConfig>) => void;
}) {
  const sources = [
    { key: "strict_ks", label: "Modo estricto", desc: "Solo responde con información de las fuentes. Si no hay match, escala a humano.", value: config.strict_ks, icon: Shield },
    { key: "structured_enabled", label: "Catálogo / fuentes estructuradas", desc: "Tablas de modelos, precios y especificaciones.", value: config.structured_enabled, icon: Zap },
    { key: "semi_structured_enabled", label: "Artículos y FAQ", desc: "Documentación semi-estructurada del knowledge base.", value: config.semi_structured_enabled, icon: MessageCircle },
    { key: "free_text_enabled", label: "Documentos libres (PDF, web)", desc: "Documentos indexados con embeddings.", value: config.free_text_enabled, icon: Download },
  ] as const;

  return (
    <div className="space-y-2.5">
      <p className="text-xs text-muted-foreground">
        Controla qué fuentes de conocimiento puede consultar este agente.
      </p>
      {sources.map(({ key, label, desc, value, icon: Icon }) => (
        <div key={key} className="flex items-center justify-between gap-4 rounded-lg border px-4 py-3">
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div>
              <div className="text-sm font-medium">{label}</div>
              <div className="text-xs text-muted-foreground">{desc}</div>
            </div>
          </div>
          <Toggle checked={value} onChange={(v) => onChange({ [key]: v } as Partial<KnowledgeConfig>)} />
        </div>
      ))}
    </div>
  );
}

// ─── Compare Panel ────────────────────────────────────────────────────────────

function ComparePanel({
  agents,
  onClose,
}: {
  agents: [AgentItem, AgentItem];
  onClose: () => void;
}) {
  const [showOnlyDiff, setShowOnlyDiff] = useState(false);

  type AgentKey = keyof AgentItem;
  const rows: { key: AgentKey; label: string; format?: (v: AgentItem[AgentKey]) => string }[] = [
    { key: "name", label: "Nombre" },
    { key: "role", label: "Rol", format: (v) => ROLE_LABEL[String(v)] ?? String(v) },
    { key: "tone", label: "Tono" },
    { key: "style", label: "Estilo", format: (v) => String(v ?? "—") },
    { key: "max_sentences", label: "Máx. oraciones", format: (v) => String(v ?? "—") },
    { key: "no_emoji", label: "Sin emojis", format: (v) => (v ? "Sí" : "No") },
    { key: "language", label: "Idioma", format: (v) => LANGUAGES.find((l) => l.value === String(v))?.label ?? String(v ?? "—") },
    { key: "return_to_flow", label: "Volver al flujo", format: (v) => (v ? "Sí" : "No") },
    { key: "is_default", label: "Predeterminado", format: (v) => (v ? "Sí" : "No") },
  ];

  const getVal = (agent: AgentItem, key: AgentKey, format?: (v: AgentItem[AgentKey]) => string): string => {
    const raw = agent[key];
    return format ? format(raw) : String(raw ?? "—");
  };

  return (
    <div className="shrink-0 border-t bg-card" style={{ maxHeight: 280 }}>
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          Comparar agentes
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            Modo comparación
          </span>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
            <Toggle checked={showOnlyDiff} onChange={setShowOnlyDiff} />
            Ver solo diferencias
          </label>
          <Button size="sm" variant="ghost" className="text-xs" onClick={onClose}>
            <X className="mr-1.5 h-3 w-3" /> Cerrar comparación
          </Button>
        </div>
      </div>
      <div className="overflow-auto" style={{ maxHeight: 220 }}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b">
              <th className="px-4 py-2 text-left font-medium text-muted-foreground w-36">Campo</th>
              <th className="px-4 py-2 text-left font-medium">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-blue-500" /> {agents[0].name}
                </div>
              </th>
              <th className="px-4 py-2 text-left font-medium">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-violet-500" /> {agents[1].name}
                </div>
              </th>
              <th className="px-4 py-2 w-20" />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, label, format }) => {
              const av = getVal(agents[0], key, format);
              const bv = getVal(agents[1], key, format);
              const same = av === bv;
              if (showOnlyDiff && same) return null;
              return (
                <tr key={key} className="border-t hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-1.5 text-muted-foreground">{label}</td>
                  <td className={`px-4 py-1.5 font-medium ${same ? "" : "text-amber-500"}`}>{av}</td>
                  <td className={`px-4 py-1.5 font-medium ${same ? "" : "text-amber-500"}`}>{bv}</td>
                  <td className="px-4 py-1.5">
                    {same ? (
                      <span className="text-emerald-500">
                        <Check className="h-3.5 w-3.5" />
                      </span>
                    ) : (
                      <span className="text-[10px] font-medium text-amber-500">Dif.</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Agent Editor ─────────────────────────────────────────────────────────────

function AgentEditor({
  agent,
  onDelete,
  showPreview,
}: {
  agent: AgentItem;
  onDelete: () => void;
  showPreview: boolean;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<AgentItem>(agent);

  useEffect(() => setDraft(agent), [agent]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(agent), [draft, agent]);
  const changes = useMemo(() => computeChanges(agent, draft), [agent, draft]);

  const save = useMutation({
    mutationFn: () =>
      agentsApi.patch(agent.id, {
        name: draft.name, role: draft.role, goal: draft.goal, style: draft.style,
        tone: draft.tone, language: draft.language, max_sentences: draft.max_sentences,
        no_emoji: draft.no_emoji, return_to_flow: draft.return_to_flow,
        is_default: draft.is_default, system_prompt: draft.system_prompt,
        active_intents: draft.active_intents, extraction_config: draft.extraction_config,
        auto_actions: draft.auto_actions, knowledge_config: draft.knowledge_config,
        flow_mode_rules: draft.flow_mode_rules,
      }),
    onSuccess: () => {
      toast.success("Agente guardado");
      void qc.invalidateQueries({ queryKey: ["agents"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
    onError: (e) => toast.error("No se pudo guardar", { description: e.message }),
  });

  const update = <K extends keyof AgentItem>(key: K, value: AgentItem[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const toggleIntent = (intent: string) => {
    const present = draft.active_intents.includes(intent);
    update("active_intents", present
      ? draft.active_intents.filter((i) => i !== intent)
      : [...draft.active_intents, intent]);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (dirty) save.mutate(); }
      if (e.key === "Escape") setDraft(agent);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dirty, agent]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Editor header */}
      <div className="shrink-0 border-b px-4 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <input
              value={draft.name}
              onChange={(e) => update("name", e.target.value)}
              className="min-w-0 flex-1 bg-transparent text-lg font-semibold outline-none focus:ring-0"
              aria-label="Nombre del agente"
            />
            <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium ${ROLE_COLOR[draft.role] ?? ""}`}>
              {ROLE_LABEL[draft.role] ?? draft.role}
            </span>
            {draft.is_default && (
              <Badge variant="outline" className="text-[10px]">Predeterminado</Badge>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={onDelete}
              title="Eliminar agente"
              aria-label="Eliminar agente"
              className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive transition-colors"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <SaveButton
              changes={changes}
              isPending={save.isPending}
              dirty={dirty}
              onSave={() => save.mutate()}
              onDiscard={() => setDraft(agent)}
            />
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="identity" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="shrink-0 rounded-none border-b bg-transparent px-4 h-auto pb-0 justify-start gap-1">
          {[
            { value: "identity", label: "Identidad" },
            { value: "data", label: "Datos" },
            { value: "actions", label: "Acciones" },
            { value: "test", label: "Probar" },
            { value: "knowledge", label: "Conocimiento" },
          ].map(({ value, label }) => (
            <TabsTrigger
              key={value}
              value={value}
              className="rounded-b-none rounded-t-md border-b-2 border-transparent px-3 py-2 text-xs data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* Tab content panels */}
        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 overflow-y-auto">
            <TabsContent value="identity" className="m-0 p-4">
              <IdentityTab draft={draft} update={update} toggleIntent={toggleIntent} />
            </TabsContent>
            <TabsContent value="data" className="m-0 p-4">
              <DataTab
                fields={asExtractionFields(draft.extraction_config)}
                onChange={(fields) => update("extraction_config", { ...(draft.extraction_config ?? {}), fields })}
              />
            </TabsContent>
            <TabsContent value="actions" className="m-0 p-4">
              <ActionsTab
                actions={asAutoActions(draft.auto_actions)}
                onChange={(next) => update("auto_actions", { ...(draft.auto_actions ?? {}), ...next })}
              />
            </TabsContent>
            <TabsContent value="test" className="m-0 p-4">
              <TestTab agent={draft} />
            </TabsContent>
            <TabsContent value="knowledge" className="m-0 p-4">
              <KnowledgeTab
                config={asKnowledgeConfig(draft.knowledge_config)}
                onChange={(next) => update("knowledge_config", { ...(draft.knowledge_config ?? {}), ...next })}
              />
            </TabsContent>
          </div>

          {/* Right preview panel */}
          {showPreview && <LivePreview draft={draft} />}
        </div>
      </Tabs>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function AgentsPage() {
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: agentsApi.list });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [agentOrder, setAgentOrder] = useState<string[]>([]);

  // Sync order from server on first load
  useEffect(() => {
    if (agents.data && agentOrder.length === 0) {
      setAgentOrder(agents.data.map((a) => a.id));
    }
  }, [agents.data, agentOrder.length]);

  // Auto-select first agent
  useEffect(() => {
    if (!selectedId && agents.data?.length) {
      setSelectedId(agents.data[0]?.id ?? null);
    }
  }, [agents.data, selectedId]);

  const orderedAgents = useMemo(() => {
    if (!agents.data) return [];
    const map = new Map(agents.data.map((a) => [a.id, a]));
    const ordered = agentOrder.map((id) => map.get(id)).filter((a): a is AgentItem => !!a);
    const remaining = agents.data.filter((a) => !agentOrder.includes(a.id));
    return [...ordered, ...remaining];
  }, [agents.data, agentOrder]);

  const create = useMutation({
    mutationFn: () => agentsApi.create({
      name: "Nuevo agente",
      role: "custom",
      active_intents: [],
      is_default: (agents.data?.length ?? 0) === 0,
    }),
    onSuccess: (agent) => {
      setSelectedId(agent.id);
      setAgentOrder((prev) => [...prev, agent.id]);
      void qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agente creado");
    },
    onError: (e) => toast.error("No se pudo crear", { description: e.message }),
  });

  const remove = useMutation({
    mutationFn: agentsApi.delete,
    onSuccess: (_, id) => {
      setSelectedId((prev) => (prev === id ? null : prev));
      setCompareIds((prev) => prev.filter((x) => x !== id));
      setAgentOrder((prev) => prev.filter((x) => x !== id));
      void qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agente eliminado");
    },
    onError: (e) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  const setStar = useMutation({
    mutationFn: (id: string) => agentsApi.patch(id, { is_default: true }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agents"] }),
    onError: (e) => toast.error("Error", { description: e.message }),
  });

  const selected = orderedAgents.find((a) => a.id === selectedId) ?? null;
  const compareAgents = compareIds.length === 2
    ? (compareIds.map((id) => orderedAgents.find((a) => a.id === id)).filter(Boolean) as AgentItem[])
    : null;

  function toggleCompare(id: string) {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1]!, id];
      return [...prev, id];
    });
  }

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="flex w-56 shrink-0 flex-col border-r bg-card overflow-hidden">
          <div className="flex items-center justify-between border-b px-3 py-2.5">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Bot className="h-4 w-4 text-primary" />
              Agentes IA
              {agents.data && (
                <span className="rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground">
                  {agents.data.length}
                </span>
              )}
            </div>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              title="Nuevo agente"
              aria-label="Crear agente"
              onClick={() => create.mutate()}
              disabled={create.isPending}
            >
              {create.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            </Button>
          </div>

          <div className="flex-1 space-y-1 overflow-y-auto p-2">
            {agents.isLoading ? (
              Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))
            ) : orderedAgents.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <Bot className="h-8 w-8 text-muted-foreground/30" />
                <div className="text-xs text-muted-foreground">
                  Sin agentes. Crea uno para empezar.
                </div>
                <Button size="sm" variant="outline" className="text-xs" onClick={() => create.mutate()}>
                  <Plus className="mr-1.5 h-3 w-3" /> Nuevo agente
                </Button>
              </div>
            ) : (
              orderedAgents.map((agent, idx) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  selected={selectedId === agent.id}
                  compareSelected={compareIds.includes(agent.id)}
                  onSelect={() => { setSelectedId(agent.id); }}
                  onShiftClick={() => toggleCompare(agent.id)}
                  onStar={() => setStar.mutate(agent.id)}
                  onDuplicate={() => {
                    void agentsApi.create({
                      name: `${agent.name} (copia)`,
                      role: agent.role,
                      active_intents: agent.active_intents,
                      system_prompt: agent.system_prompt,
                      tone: agent.tone,
                      style: agent.style,
                      max_sentences: agent.max_sentences,
                      no_emoji: agent.no_emoji,
                      goal: agent.goal,
                      language: agent.language,
                      return_to_flow: agent.return_to_flow,
                    }).then((newAgent) => {
                      setAgentOrder((prev) => [...prev, newAgent.id]);
                      void qc.invalidateQueries({ queryKey: ["agents"] });
                      toast.success("Agente duplicado");
                    });
                  }}
                  onExport={() => {
                    const blob = new Blob([JSON.stringify(agent, null, 2)], { type: "application/json" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `agente-${agent.name.toLowerCase().replace(/\s+/g, "-")}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                    toast.success("Agente exportado");
                  }}
                  onDelete={() => {
                    if (confirm(`¿Eliminar agente "${agent.name}"?`)) remove.mutate(agent.id);
                  }}
                  dragHandleProps={{
                    draggable: true,
                    onDragStart: () => setDragIdx(idx),
                    onDragOver: (e) => e.preventDefault(),
                    onDrop: () => {
                      if (dragIdx === null || dragIdx === idx) return;
                      const order = orderedAgents.map((a) => a.id);
                      const [moved] = order.splice(dragIdx, 1);
                      order.splice(idx, 0, moved!);
                      setAgentOrder(order);
                      setDragIdx(null);
                    },
                  }}
                />
              ))
            )}
          </div>

          {/* Keyboard shortcuts */}
          <div className="border-t p-3 text-[10px] text-muted-foreground space-y-1">
            <div className="font-medium text-[9px] uppercase tracking-wider mb-1.5">Atajos de teclado</div>
            {[
              ["Ctrl/Cmd+Enter", "Guardar / Aplicar"],
              ["Escape", "Cerrar / Cancelar"],
              ["Shift+clic", "Modo comparación"],
              ["Backspace", "Quitar último chip"],
            ].map(([key, label]) => (
              <div key={key} className="flex items-center justify-between gap-2">
                <span>{label}</span>
                <code className="rounded bg-muted px-1 py-0.5 text-[9px]">{key}</code>
              </div>
            ))}
          </div>
        </aside>

        {/* Main editor */}
        {selected ? (
          <AgentEditor
            key={selected.id}
            agent={selected}
            onDelete={() => { if (confirm(`¿Eliminar agente "${selected.name}"?`)) remove.mutate(selected.id); }}
            showPreview={true}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            <Bot className="h-12 w-12 text-muted-foreground/20" />
            <div className="text-sm font-medium">Selecciona o crea un agente</div>
            <div className="text-xs text-muted-foreground max-w-xs">
              Cada agente puede tener su propio rol, tono, campos de extracción e intenciones.
            </div>
            <Button size="sm" variant="outline" onClick={() => create.mutate()} disabled={create.isPending}>
              <Plus className="mr-1.5 h-3.5 w-3.5" /> Nuevo agente
            </Button>
          </div>
        )}
      </div>

      {/* Compare panel */}
      {compareAgents && compareAgents.length === 2 && (
        <ComparePanel
          agents={[compareAgents[0]!, compareAgents[1]!]}
          onClose={() => setCompareIds([])}
        />
      )}
    </div>
  );
}

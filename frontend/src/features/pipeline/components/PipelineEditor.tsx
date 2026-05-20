import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  FileText,
  GripVertical,
  MoreHorizontal,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { tenantsApi } from "@/features/config/api";
import { fieldsApi } from "@/features/customers/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

import { AuditLogDrawer } from "./AuditLogDrawer";
import { PipelineVersionHistoryButton } from "./PipelineVersionHistoryDrawer";
import { FIELD_CATALOG, RuleBuilder, type RuleFieldOption } from "./RuleBuilder";
import { StageDeleteDialog } from "./StageDeleteDialog";
import { StageDependencyView } from "./StageDependencyView";
import { UnsavedChangesGuard } from "./UnsavedChangesGuard";

// Operators must match the backend Condition.operator literal in
// core/atendia/contracts/pipeline_definition.py. If you add one here,
// add it there too (the contract test pins both lists).
export type RuleOperator =
  | "exists"
  | "not_exists"
  | "equals"
  | "not_equals"
  | "contains"
  | "greater_than"
  | "less_than"
  | "in"
  | "not_in"
  | "docs_complete_for_plan";

export const OPERATORS_WITHOUT_VALUE: ReadonlySet<RuleOperator> = new Set([
  "exists",
  "not_exists",
  "docs_complete_for_plan",
]);

export const OPERATORS_NEEDING_LIST: ReadonlySet<RuleOperator> = new Set(["in", "not_in"]);

export interface ConditionDraft {
  field: string;
  operator: RuleOperator;
  // string for scalars, string[] for in/not_in. Undefined for presence ops.
  value?: string | string[];
}

export interface AutoEnterRulesDraft {
  enabled: boolean;
  match: "all" | "any";
  conditions: ConditionDraft[];
}

export interface StageDraft {
  id: string;
  label: string;
  timeout_hours: number;
  is_terminal: boolean;
  color: string;
  // M1: declarative auto-enter rules. Undefined means "no rules set" —
  // distinct from `enabled=false` (rules authored but turned off).
  auto_enter_rules?: AutoEnterRulesDraft;
  // M1: never let auto-rules move a conversation backward unless this is
  // explicitly true. Terminal stages always block backward regardless.
  allow_auto_backward?: boolean;
  // Fase 6 — opt-in flow-mode override per stage. Empty string ("") in
  // the editor means "use the per-turn flow router rules". The
  // serialiser strips the empty value so the JSONB stays clean.
  behavior_mode?: BehaviorMode | "";
  // Fase 4 — when entered, pause the bot and create a handoff. The
  // matching reason string is persisted on `human_handoffs.reason`.
  pause_bot_on_enter?: boolean;
  handoff_reason?: string;
  actions_allowed: string[];
}

// P11 — long pipelines are unwieldy to scan. The roadmap pain point is
// >20 stages; the filter input surfaces a bit earlier so it's there
// before scanning hurts, but stays hidden for the typical 5-6 stage
// pipeline to avoid clutter.
const STAGE_SEARCH_MIN = 8;

// P11 — the editor list filters by this predicate; an empty query shows
// everything. Matches against both the human label and the stage_id so
// operators can search by either.
export function stageMatchesQuery(stage: StageDraft, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return stage.label.toLowerCase().includes(q) || stage.id.toLowerCase().includes(q);
}

// Mirror of FlowMode in core/atendia/contracts/flow_mode.py. Kept as a
// readonly tuple so the dropdown options stay in lockstep with both
// validator branches.
export const BEHAVIOR_MODES = ["PLAN", "SALES", "DOC", "OBSTACLE", "RETENTION", "SUPPORT"] as const;
export type BehaviorMode = (typeof BEHAVIOR_MODES)[number];

// Curated reasons surfaced in the dropdown. Operators can still type a
// custom string (free-form text) — these are the canonical ones the
// backend HandoffReason enum understands. Free-form strings are
// accepted by StageDefinition.handoff_reason validator on the backend.
export const HANDOFF_REASON_PRESETS: Array<{ value: string; label: string }> = [
  { value: "docs_complete_for_plan", label: "Papelería completa" },
  { value: "stage_triggered_handoff", label: "Handoff genérico por etapa" },
  { value: "antiguedad_lt_6m", label: "Antigüedad menor a 6 meses" },
  { value: "obstacle_no_solution", label: "Obstáculo sin solución" },
  { value: "user_signaled_papeleria_completa", label: "Cliente dijo: ya envié todo" },
  { value: "papeleria_completa_form_pending", label: "Falta formulario después de papelería" },
];

export const ACTION_OPTIONS: Array<{ value: string; label: string; hint: string }> = [
  { value: "greet", label: "Saludar", hint: "Primer contacto o reenganche suave." },
  { value: "ask_field", label: "Pedir dato", hint: "Solicita campos faltantes del cliente." },
  { value: "ask_clarification", label: "Aclarar", hint: "Responde cuando el mensaje no encaja." },
  {
    value: "lookup_faq",
    label: "Usar KB",
    hint: "Busca politicas, requisitos o respuestas guardadas.",
  },
  { value: "book_appointment", label: "Agendar", hint: "Propone o confirma una cita." },
  { value: "close", label: "Cerrar venta", hint: "Avanza cuando el cliente acepta comprar." },
  { value: "escalate_to_human", label: "Handoff humano", hint: "Pausa o deriva a asesor humano." },
];

const DEFAULT_ACTIONS_ALLOWED = ACTION_OPTIONS.map((action) => action.value);
const ACTIVE_ACTION_VALUES = new Set(ACTION_OPTIONS.map((action) => action.value));

export interface DocumentSpecDraft {
  key: string;
  label: string;
  hint: string;
}

export interface PipelineDraft {
  stages: StageDraft[];
  docs_per_plan: Record<string, string[]>;
  documents_catalog: DocumentSpecDraft[];
  // Legacy: Vision auto-mapping used to live in this editor. Keep the
  // draft field so old persisted payloads can be loaded, but the UI and
  // serialiser intentionally clear it now.
  vision_doc_mapping: Record<string, string[]>;
  // Per-flow-mode composer guidance, keyed by UPPERCASE FlowMode. Empty
  // / missing entry → composer falls back to its generic default.
  mode_prompts: Record<string, string>;
  mode_labels: Record<string, string>;
  hidden_modes: string[];
  fallback?: string;
  extra: Record<string, unknown>;
}

// The 6 composer flow modes (mirror core/atendia/contracts/flow_mode.py
// — keys are UPPERCASE). Per-mode guidance is tenant-authored; an empty
// box means the composer uses its generic, vertical-neutral default
// (NOT the moto-credit playbook).
export const FLOW_MODES = ["PLAN", "SALES", "DOC", "OBSTACLE", "RETENTION", "SUPPORT"] as const;
export type FlowModeKey = (typeof FLOW_MODES)[number];

export const FLOW_MODE_LABELS: Record<FlowModeKey, string> = {
  PLAN: "PLAN — calificar al cliente",
  SALES: "SALES — cotizar / ofertar",
  DOC: "DOC — recibir y validar documentos",
  OBSTACLE: "OBSTACLE — destrabar una objeción",
  RETENTION: "RETENTION — reenganchar si se enfría",
  SUPPORT: "SUPPORT — responder dudas generales",
};

export const FLOW_MODE_PURPOSES: Record<FlowModeKey, string> = {
  PLAN: "calificar al cliente",
  SALES: "cotizar u ofertar",
  DOC: "recibir y validar documentos",
  OBSTACLE: "destrabar una objecion",
  RETENTION: "reenganchar si se enfria",
  SUPPORT: "responder dudas generales",
};

export const FLOW_MODE_ALIAS_PLACEHOLDERS: Record<FlowModeKey, string> = {
  PLAN: "Calificacion de credito",
  SALES: "Cotizacion de moto",
  DOC: "Papeleria",
  OBSTACLE: "Objeciones",
  RETENTION: "Seguimiento",
  SUPPORT: "Dudas generales",
};

function modeAlias(draft: PipelineDraft, mode: FlowModeKey): string {
  return (draft.mode_labels?.[mode] ?? "").trim();
}

export function modeDisplayLabel(draft: PipelineDraft, mode: FlowModeKey): string {
  const alias = modeAlias(draft, mode);
  return alias ? `${alias} (${mode})` : FLOW_MODE_LABELS[mode];
}

// Documents are tenant-configured identifiers. Legacy DOCS_* keys still
// work, but new tenants can use clean names like INE_FRENTE.
function buildRuleFieldCatalog(
  fieldDefinitions: Array<{ key: string; label: string }> | undefined,
  documentsCatalog: DocumentSpecDraft[],
): RuleFieldOption[] {
  const byId = new Map<string, RuleFieldOption>();
  const add = (option: RuleFieldOption) => {
    if (!byId.has(option.id)) byId.set(option.id, option);
  };

  for (const definition of fieldDefinitions ?? []) {
    add({ id: definition.key, label: definition.label, group: "Datos del cliente" });
  }
  for (const option of FIELD_CATALOG) {
    add(option);
  }
  for (const doc of documentsCatalog) {
    add({ id: `${doc.key}.status`, label: `${doc.label} - status`, group: "Documentos" });
  }

  return Array.from(byId.values());
}

const DOC_KEY_RE = /^[A-Z][A-Z0-9_]*$/;

const STAGE_ID_RE = /^[a-z][a-z0-9_]{2,29}$/;
const STAGE_COLORS = [
  "#6366f1",
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#84cc16",
];

function defaultColor(idx: number): string {
  return STAGE_COLORS[idx % STAGE_COLORS.length] ?? "#6366f1";
}

function parseAutoEnterRules(raw: unknown): AutoEnterRulesDraft | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const obj = raw as Record<string, unknown>;
  const match = obj.match === "any" ? "any" : "all";
  const enabled = obj.enabled === true;
  const rawConditions = Array.isArray(obj.conditions) ? obj.conditions : [];
  const conditions: ConditionDraft[] = rawConditions.flatMap((c) => {
    if (typeof c !== "object" || c === null) return [];
    const co = c as Record<string, unknown>;
    if (typeof co.field !== "string" || typeof co.operator !== "string") return [];
    const op = co.operator as RuleOperator;
    if (OPERATORS_WITHOUT_VALUE.has(op)) {
      return [{ field: co.field, operator: op }];
    }
    if (OPERATORS_NEEDING_LIST.has(op)) {
      // Accept already-parsed list or comma-separated string for forward
      // compat with seed pipelines stored either way.
      const list = Array.isArray(co.value)
        ? co.value.map((x) => String(x))
        : typeof co.value === "string"
          ? co.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean)
          : [];
      return [{ field: co.field, operator: op, value: list }];
    }
    const scalar = co.value === null || co.value === undefined ? "" : String(co.value);
    return [{ field: co.field, operator: op, value: scalar }];
  });
  return { enabled, match, conditions };
}

function serializeAutoEnterRules(
  rules: AutoEnterRulesDraft | undefined,
): Record<string, unknown> | undefined {
  if (!rules) return undefined;
  const conditions = rules.conditions.map((c) => {
    if (OPERATORS_WITHOUT_VALUE.has(c.operator)) {
      // Backend rejects presence ops carrying a value, so don't send one.
      return { field: c.field, operator: c.operator };
    }
    if (OPERATORS_NEEDING_LIST.has(c.operator)) {
      const list = Array.isArray(c.value)
        ? c.value
        : typeof c.value === "string"
          ? c.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean)
          : [];
      return { field: c.field, operator: c.operator, value: list };
    }
    return { field: c.field, operator: c.operator, value: c.value ?? "" };
  });
  return { enabled: rules.enabled, match: rules.match, conditions };
}

export function parsePipeline(raw: Record<string, unknown> | undefined): PipelineDraft {
  const def = raw ?? {};
  const rawStages = Array.isArray(def.stages) ? def.stages : [];
  const stages: StageDraft[] = rawStages.flatMap((s: unknown, idx: number) => {
    if (typeof s !== "object" || s === null) return [];
    const obj = s as Record<string, unknown>;
    if (typeof obj.id !== "string") return [];
    // Fase 6 — accept any of the 6 known modes; reject typos so the
    // dropdown doesn't render a phantom value the backend won't take.
    const rawBehavior = typeof obj.behavior_mode === "string" ? obj.behavior_mode : "";
    const behaviorMode = (BEHAVIOR_MODES as readonly string[]).includes(rawBehavior)
      ? (rawBehavior as BehaviorMode)
      : "";
    return [
      {
        id: obj.id,
        label: typeof obj.label === "string" && obj.label.length > 0 ? obj.label : obj.id,
        timeout_hours: typeof obj.timeout_hours === "number" ? obj.timeout_hours : 0,
        is_terminal: obj.is_terminal === true,
        color: typeof obj.color === "string" ? obj.color : defaultColor(idx),
        auto_enter_rules: parseAutoEnterRules(obj.auto_enter_rules),
        allow_auto_backward: obj.allow_auto_backward === true,
        behavior_mode: behaviorMode,
        pause_bot_on_enter: obj.pause_bot_on_enter === true,
        handoff_reason: typeof obj.handoff_reason === "string" ? obj.handoff_reason : "",
        actions_allowed: Array.isArray(obj.actions_allowed)
          ? obj.actions_allowed.filter(
              (action): action is string =>
                typeof action === "string" && ACTIVE_ACTION_VALUES.has(action),
            )
          : [...DEFAULT_ACTIONS_ALLOWED],
      },
    ];
  });
  const docs =
    typeof def.docs_per_plan === "object" && def.docs_per_plan !== null
      ? (def.docs_per_plan as Record<string, string[]>)
      : {};
  const documents_catalog: DocumentSpecDraft[] = Array.isArray(def.documents_catalog)
    ? def.documents_catalog.flatMap((d: unknown) => {
        if (typeof d !== "object" || d === null) return [];
        const obj = d as Record<string, unknown>;
        if (typeof obj.key !== "string" || typeof obj.label !== "string") return [];
        return [
          {
            key: obj.key,
            label: obj.label,
            hint: typeof obj.hint === "string" ? obj.hint : "",
          },
        ];
      })
    : [];
  const fallback = typeof def.fallback === "string" ? def.fallback : undefined;
  const vision_doc_mapping: Record<string, string[]> = {};
  // mode_prompts: { "PLAN": "...", ... }. Keep only known UPPERCASE
  // modes with string bodies; ignore operator-edited noise.
  const rawMp =
    typeof def.mode_prompts === "object" && def.mode_prompts !== null
      ? (def.mode_prompts as Record<string, unknown>)
      : {};
  const mode_prompts: Record<string, string> = {};
  for (const [mode, txt] of Object.entries(rawMp)) {
    if ((FLOW_MODES as readonly string[]).includes(mode) && typeof txt === "string") {
      mode_prompts[mode] = txt;
    }
  }
  const rawModeLabels =
    typeof def.mode_labels === "object" && def.mode_labels !== null
      ? (def.mode_labels as Record<string, unknown>)
      : {};
  const mode_labels: Record<string, string> = {};
  for (const [mode, label] of Object.entries(rawModeLabels)) {
    if ((FLOW_MODES as readonly string[]).includes(mode) && typeof label === "string") {
      mode_labels[mode] = label;
    }
  }
  const rawHiddenModes = Array.isArray(def.hidden_modes) ? def.hidden_modes : [];
  const hiddenSet = new Set(
    rawHiddenModes.filter(
      (mode): mode is FlowModeKey =>
        typeof mode === "string" && (FLOW_MODES as readonly string[]).includes(mode),
    ),
  );
  const hidden_modes = FLOW_MODES.filter((mode) => hiddenSet.has(mode));
  const extra: Record<string, unknown> = { ...def };
  delete extra.stages;
  delete extra.docs_per_plan;
  delete extra.documents_catalog;
  delete extra.fallback;
  delete extra.vision_doc_mapping;
  delete extra.mode_prompts;
  delete extra.mode_labels;
  delete extra.hidden_modes;
  return {
    stages,
    docs_per_plan: docs,
    documents_catalog,
    vision_doc_mapping,
    mode_prompts,
    mode_labels,
    hidden_modes,
    fallback,
    extra,
  };
}

export function serialisePipelineDraft(draft: PipelineDraft): Record<string, unknown> {
  return serialise(draft);
}

function serialise(draft: PipelineDraft): Record<string, unknown> {
  // Drop empty mode_prompts so a blank box means "use the generic
  // default" rather than persisting an empty string.
  const modePrompts: Record<string, string> = {};
  for (const [m, t] of Object.entries(draft.mode_prompts ?? {})) {
    if (typeof t === "string" && t.trim().length > 0) modePrompts[m] = t;
  }
  const modeLabels: Record<string, string> = {};
  for (const mode of FLOW_MODES) {
    const label = (draft.mode_labels?.[mode] ?? "").trim();
    if (label.length > 0) modeLabels[mode] = label;
  }
  const hiddenSet = new Set(draft.hidden_modes ?? []);
  const hiddenModes = FLOW_MODES.filter((mode) => hiddenSet.has(mode));
  return {
    ...draft.extra,
    stages: draft.stages.map((s) => {
      const rulesSerialized = serializeAutoEnterRules(s.auto_enter_rules);
      const handoffReason = (s.handoff_reason ?? "").trim();
      return {
        id: s.id,
        label: s.label,
        timeout_hours: s.timeout_hours,
        color: s.color,
        ...(s.is_terminal ? { is_terminal: true } : {}),
        ...(s.allow_auto_backward ? { allow_auto_backward: true } : {}),
        ...(rulesSerialized ? { auto_enter_rules: rulesSerialized } : {}),
        ...(s.behavior_mode ? { behavior_mode: s.behavior_mode } : {}),
        ...(s.pause_bot_on_enter ? { pause_bot_on_enter: true } : {}),
        ...(handoffReason ? { handoff_reason: handoffReason } : {}),
        actions_allowed: s.actions_allowed,
      };
    }),
    docs_per_plan: draft.docs_per_plan,
    documents_catalog: draft.documents_catalog.map((d) => ({
      key: d.key,
      label: d.label,
      ...(d.hint ? { hint: d.hint } : {}),
    })),
    ...(Object.keys(modePrompts).length > 0 ? { mode_prompts: modePrompts } : {}),
    ...(Object.keys(modeLabels).length > 0 ? { mode_labels: modeLabels } : {}),
    ...(hiddenModes.length > 0 ? { hidden_modes: hiddenModes } : {}),
    ...(draft.fallback ? { fallback: draft.fallback } : {}),
  };
}

// Mirrors backend _RULE_FIELD_RE in pipeline_definition.py. Accepts
// dot-separated identifiers (INE_FRENTE.status, modelo_interes).
const RULE_FIELD_RE = /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/;

export function validatePipelineDraft(draft: PipelineDraft): string | null {
  return validate(draft);
}

function validate(draft: PipelineDraft): string | null {
  if (draft.stages.length === 0) return "El pipeline debe tener al menos una etapa.";
  const docKeys = new Set<string>();
  for (const d of draft.documents_catalog) {
    if (!DOC_KEY_RE.test(d.key)) {
      return `Documento "${d.key || "(vacío)"}": el ID debe iniciar con letra y usar solo letras mayúsculas, números y guion bajo.`;
    }
    if (docKeys.has(d.key)) {
      return `Documento duplicado: ${d.key}`;
    }
    docKeys.add(d.key);
    if (!d.label.trim()) {
      return `Documento "${d.key}": la etiqueta no puede estar vacía.`;
    }
  }
  const ids = new Set<string>();
  for (const s of draft.stages) {
    if (!STAGE_ID_RE.test(s.id)) {
      return `ID inválido "${s.id}": usa a-z, 0-9, _ (mín 3, máx 30 caracteres, inicia con letra).`;
    }
    if (ids.has(s.id)) return `ID duplicado: ${s.id}`;
    ids.add(s.id);
    if (!s.label.trim()) return `Etiqueta vacía en "${s.id}".`;
    if (s.timeout_hours < 0 || s.timeout_hours > 8760) {
      return `timeout_hours en "${s.id}" debe estar entre 0 y 8760.`;
    }
    if (s.is_terminal && s.allow_auto_backward) {
      return `"${s.id}": una etapa terminal no puede permitir movimiento hacia atrás.`;
    }
    // Fase 6 — behavior_mode is open-set on the type but pinned to the
    // 6 known modes; reject typed-in JSON drift before save.
    if (s.actions_allowed.length === 0) {
      return `"${s.id}": selecciona al menos una accion permitida.`;
    }
    if (s.behavior_mode && !(BEHAVIOR_MODES as readonly string[]).includes(s.behavior_mode)) {
      return `"${s.id}": behavior_mode "${s.behavior_mode}" no es uno de ${BEHAVIOR_MODES.join(", ")}.`;
    }
    // Fase 4 — handoff_reason without pause_bot_on_enter is a config
    // mistake (the reason would never reach human_handoffs.payload).
    if ((s.handoff_reason ?? "").trim() && !s.pause_bot_on_enter) {
      return `"${s.id}": handoff_reason solo aplica cuando "Pausar bot al entrar" está activo.`;
    }
    const rules = s.auto_enter_rules;
    if (rules?.enabled) {
      if (rules.conditions.length === 0) {
        return `"${s.id}": auto-entrada habilitada requiere al menos una condición.`;
      }
      for (const [i, c] of rules.conditions.entries()) {
        if (!RULE_FIELD_RE.test(c.field)) {
          return `"${s.id}": condición #${i + 1} tiene un campo inválido (${c.field || "vacío"}).`;
        }
        if (OPERATORS_WITHOUT_VALUE.has(c.operator)) continue;
        if (OPERATORS_NEEDING_LIST.has(c.operator)) {
          const list = Array.isArray(c.value)
            ? c.value
            : typeof c.value === "string"
              ? c.value
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean)
              : [];
          if (list.length === 0) {
            return `"${s.id}": condición #${i + 1} (${c.operator}) requiere una lista de valores.`;
          }
          continue;
        }
        if (c.value === undefined || c.value === null || c.value === "") {
          return `"${s.id}": condición #${i + 1} (${c.operator}) requiere un valor.`;
        }
      }
    }
  }
  for (const mode of Object.keys(draft.mode_labels ?? {})) {
    if (!(FLOW_MODES as readonly string[]).includes(mode)) {
      return `Alias de modo "${mode}" no es válido (debe ser uno de ${FLOW_MODES.join(", ")}).`;
    }
  }
  for (const mode of draft.hidden_modes ?? []) {
    if (!(FLOW_MODES as readonly string[]).includes(mode)) {
      return `Modo oculto "${mode}" no es válido (debe ser uno de ${FLOW_MODES.join(", ")}).`;
    }
  }
  return null;
}

function validateStageId(id: string): string | null {
  if (!id) return "Requerido";
  if (!STAGE_ID_RE.test(id)) return "Solo a-z, 0-9, _ · 3-30 chars · inicia con letra";
  return null;
}

function validateTimeout(h: number): string | null {
  if (h < 0) return "Mínimo 0 horas";
  if (h > 8760) return "Máximo 8760 horas (1 año)";
  return null;
}

interface Props {
  onClose?: () => void;
}

export function PipelineEditor({ onClose }: Props) {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const canEdit = user?.role === "tenant_admin" || user?.role === "superadmin";

  const query = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });
  const customerFieldDefinitions = useQuery({
    queryKey: ["field-definitions"],
    queryFn: fieldsApi.listDefinitions,
  });

  const [draft, setDraft] = useState<PipelineDraft | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [showDocsByPlan, setShowDocsByPlan] = useState(false);
  const [showDocsCatalog, setShowDocsCatalog] = useState(true);
  const [showModePrompts, setShowModePrompts] = useState(false);
  const [newDocLabel, setNewDocLabel] = useState("");
  const [newDocHint, setNewDocHint] = useState("");
  const [newPlanName, setNewPlanName] = useState("");
  const [dragOver, setDragOver] = useState<number | null>(null);
  const [draggingIdx, setDraggingIdx] = useState<number | null>(null);
  const [stageFilter, setStageFilter] = useState("");

  useEffect(() => {
    if (query.data) {
      const parsed = parsePipeline(query.data.definition);
      setDraft(parsed);
      if (parsed.stages.length > 0) setSelectedIdx((prev) => prev ?? 0);
    } else if (query.isError) {
      const seed: PipelineDraft = {
        stages: [
          {
            id: "nuevo",
            label: "Nuevo lead",
            timeout_hours: 24,
            is_terminal: false,
            color: "#6366f1",
            actions_allowed: [...DEFAULT_ACTIONS_ALLOWED],
          },
          {
            id: "en_conversacion",
            label: "En conversación",
            timeout_hours: 12,
            is_terminal: false,
            color: "#3b82f6",
            actions_allowed: [...DEFAULT_ACTIONS_ALLOWED],
          },
          {
            id: "propuesta",
            label: "Propuesta",
            timeout_hours: 48,
            is_terminal: false,
            color: "#f59e0b",
            actions_allowed: [...DEFAULT_ACTIONS_ALLOWED],
          },
        ],
        docs_per_plan: {},
        documents_catalog: [],
        vision_doc_mapping: {},
        mode_prompts: {},
        mode_labels: {},
        hidden_modes: [],
        fallback: "escalate_to_human",
        extra: {},
      };
      setDraft(seed);
      setSelectedIdx(0);
    }
  }, [query.data, query.isError]);

  const globalError = useMemo(() => (draft ? validate(draft) : null), [draft]);
  // Dirty detection: serialise the draft and compare against the loaded
  // definition. Doing it via JSON.stringify is cheap (the pipeline def
  // is small), and avoids carrying a separate "lastSavedSnapshot" state.
  const isDirty = useMemo(() => {
    if (!draft) return false;
    const loaded = query.data?.definition;
    if (!loaded) return draft.stages.length > 0;
    try {
      return JSON.stringify(serialise(draft)) !== JSON.stringify(loaded);
    } catch {
      // Defensive — JSON.stringify on cyclic data would throw; treat as dirty.
      return true;
    }
  }, [draft, query.data?.definition]);

  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("No draft");
      const v = validate(draft);
      if (v) throw new Error(v);
      return tenantsApi.putPipeline(serialise(draft));
    },
    onSuccess: (data) => {
      toast.success(`Pipeline guardado (v${data.version})`);
      void qc.invalidateQueries({ queryKey: ["tenants", "pipeline"] });
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
    onError: (e) => toast.error("Error al guardar", { description: e.message }),
  });

  // Destructive: blow away every pipeline version for this tenant. The
  // operator is then bounced back to the empty-state seed (the editor's
  // useEffect refills draft from the seed when query.isError fires). The
  // backend endpoint is admin-only — we still gate the button on canEdit
  // for the same reason.
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  // Per-stage delete confirmation. Tracks which stage in the local draft
  // is pending deletion so the Dialog can show its name. `null` = no
  // dialog open. The actual mutation of the draft happens only after the
  // user confirms — the row stays in the list until then. Saving the
  // draft afterwards persists the deletion.
  const [stagePendingDelete, setStagePendingDelete] = useState<number | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const remove = useMutation({
    mutationFn: () => tenantsApi.deletePipeline(),
    onSuccess: () => {
      toast.success("Pipeline eliminado", {
        description: "Edita el seed y guarda para crear uno nuevo.",
      });
      setConfirmDeleteOpen(false);
      // Force the editor back to its empty-state path by clearing local
      // draft and refetching. The query will 404, which the useEffect
      // catches and replaces draft with the seed defaults.
      setDraft(null);
      setSelectedIdx(null);
      void qc.invalidateQueries({ queryKey: ["tenants", "pipeline"] });
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
    onError: (e) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  if (query.isLoading || !draft) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <Skeleton className="h-5 w-40" />
        {["stage-skeleton-1", "stage-skeleton-2", "stage-skeleton-3", "stage-skeleton-4"].map(
          (key) => (
            <Skeleton key={key} className="h-10 w-full" />
          ),
        )}
      </div>
    );
  }

  const updateStage = (idx: number, patch: Partial<StageDraft>) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, stages: prev.stages.map((s, i) => (i === idx ? { ...s, ...patch } : s)) };
    });
  };

  // Document catalog CRUD. Operator types only the human name; we
  // derive the stable uppercase identifier the auto_enter_rules
  // conditions reference. The derived key is fixed at create-time:
  // renaming the label later doesn't break existing rules.
  const deriveDocKey = (label: string): string => {
    const clean = label
      .trim()
      .toUpperCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "") // strip accents (CURP, NÓMINA, etc.)
      .replace(/^DOCS[_\s]?/i, "")
      .replace(/[^A-Z0-9_]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/_+/g, "_");
    return clean;
  };

  // Live preview of the key the operator would get, so they can see
  // collisions before they hit Add.
  const previewKey = deriveDocKey(newDocLabel);
  const previewCollides = previewKey
    ? draft.documents_catalog.some((d) => d.key === previewKey)
    : false;

  const addDoc = () => {
    const label = newDocLabel.trim();
    const key = deriveDocKey(label);
    if (!key || !label) return;
    setDraft((prev) => {
      if (!prev) return prev;
      if (prev.documents_catalog.some((d) => d.key === key)) return prev;
      return {
        ...prev,
        documents_catalog: [...prev.documents_catalog, { key, label, hint: newDocHint.trim() }],
      };
    });
    setNewDocLabel("");
    setNewDocHint("");
  };

  const updateDoc = (idx: number, patch: Partial<DocumentSpecDraft>) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        documents_catalog: prev.documents_catalog.map((d, i) =>
          i === idx ? { ...d, ...patch } : d,
        ),
      };
    });
  };

  const removeDoc = (idx: number) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        documents_catalog: prev.documents_catalog.filter((_, i) => i !== idx),
      };
    });
  };

  // docs_per_plan CRUD.
  // extracted them — typically snake_case or short tokens).
  // Keep exact display values like "Sin Comprobantes"; the backend validator
  // rejects docs_per_plan keys that are not selectable by docs_plan_field.
  const normalizePlanName = (raw: string): string => raw.trim().replace(/\s+/g, " ");

  const addPlan = () => {
    const name = normalizePlanName(newPlanName);
    if (!name) return;
    setDraft((prev) => {
      if (!prev) return prev;
      if (prev.docs_per_plan[name]) return prev;
      return {
        ...prev,
        docs_per_plan: { ...prev.docs_per_plan, [name]: [] },
      };
    });
    setNewPlanName("");
  };

  const removePlan = (name: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = { ...prev.docs_per_plan };
      delete next[name];
      return { ...prev, docs_per_plan: next };
    });
  };

  const togglePlanDoc = (plan: string, docKey: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const current = prev.docs_per_plan[plan] ?? [];
      const next = current.includes(docKey)
        ? current.filter((k) => k !== docKey)
        : [...current, docKey];
      return {
        ...prev,
        docs_per_plan: { ...prev.docs_per_plan, [plan]: next },
      };
    });
  };

  const removeStage = (idx: number) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const stages = prev.stages.filter((_, i) => i !== idx);
      return { ...prev, stages };
    });
    setSelectedIdx((prev) => {
      if (prev === null) return null;
      if (prev === idx) return Math.max(0, idx - 1);
      if (prev > idx) return prev - 1;
      return prev;
    });
  };

  const addStage = () => {
    setDraft((prev) => {
      if (!prev) return prev;
      const newIdx = prev.stages.length;
      const newId = `etapa_${newIdx + 1}`;
      return {
        ...prev,
        stages: [
          ...prev.stages,
          {
            id: newId,
            label: "Nueva etapa",
            timeout_hours: 24,
            is_terminal: false,
            color: defaultColor(newIdx),
            actions_allowed: [...DEFAULT_ACTIONS_ALLOWED],
          },
        ],
      };
    });
    setDraft((prev) => {
      if (!prev) return prev;
      setSelectedIdx(prev.stages.length - 1);
      return prev;
    });
  };

  const moveStage = (idx: number, dir: -1 | 1) => {
    const target = idx + dir;
    if (!draft || target < 0 || target >= draft.stages.length) return;
    setDraft((prev) => {
      if (!prev) return prev;
      const stages = [...prev.stages];
      const a = stages[idx]!;
      const b = stages[target]!;
      stages[idx] = b;
      stages[target] = a;
      return { ...prev, stages };
    });
    setSelectedIdx(target);
  };

  // Drag-to-reorder for stage list
  const handleDragStart = (idx: number) => setDraggingIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setDragOver(idx);
  };
  const handleDrop = (e: React.DragEvent, toIdx: number) => {
    e.preventDefault();
    if (draggingIdx === null || draggingIdx === toIdx) {
      setDragOver(null);
      setDraggingIdx(null);
      return;
    }
    setDraft((prev) => {
      if (!prev) return prev;
      const stages = [...prev.stages];
      const [moved] = stages.splice(draggingIdx, 1);
      if (!moved) return prev;
      stages.splice(toIdx, 0, moved);
      return { ...prev, stages };
    });
    setSelectedIdx(toIdx);
    setDragOver(null);
    setDraggingIdx(null);
  };
  const handleDragEnd = () => {
    setDragOver(null);
    setDraggingIdx(null);
  };

  const selected = selectedIdx !== null ? (draft.stages[selectedIdx] ?? null) : null;
  const idError = selected ? validateStageId(selected.id) : null;
  const timeoutError = selected ? validateTimeout(selected.timeout_hours) : null;
  const hiddenModeSet = new Set(draft.hidden_modes ?? []);
  const configuredModeCount = FLOW_MODES.filter(
    (mode) => (draft.mode_prompts?.[mode] ?? "").trim().length > 0,
  ).length;
  const visibleModeCount = FLOW_MODES.filter((mode) => !hiddenModeSet.has(mode)).length;
  const behaviorModeOptions = selected
    ? FLOW_MODES.filter((mode) => !hiddenModeSet.has(mode) || selected.behavior_mode === mode)
    : FLOW_MODES.filter((mode) => !hiddenModeSet.has(mode));
  const ruleFieldCatalog = buildRuleFieldCatalog(
    customerFieldDefinitions.data,
    draft.documents_catalog,
  );

  const updateModeLabel = (mode: FlowModeKey, value: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = { ...prev.mode_labels };
      if (value.trim().length > 0) next[mode] = value;
      else delete next[mode];
      return { ...prev, mode_labels: next };
    });
  };

  const updateModePrompt = (mode: FlowModeKey, value: string) => {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            mode_prompts: {
              ...prev.mode_prompts,
              [mode]: value,
            },
          }
        : prev,
    );
  };

  const setModeVisible = (mode: FlowModeKey, visible: boolean) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = new Set(prev.hidden_modes ?? []);
      if (visible) next.delete(mode);
      else next.add(mode);
      return {
        ...prev,
        hidden_modes: FLOW_MODES.filter((m) => next.has(m)),
      };
    });
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Guards against navigating away with unsaved local edits. Renders
          no DOM — only attaches a beforeunload listener while dirty. */}
      <UnsavedChangesGuard dirty={isDirty} />
      {/* Panel header */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">PipelineEditor</span>
          {query.data && (
            <Badge variant="outline" className="text-[10px]">
              v{query.data.version}
            </Badge>
          )}
          {isDirty && (
            <Badge
              variant="outline"
              className="border-amber-500/40 bg-amber-500/10 text-[10px] text-amber-700 dark:text-amber-300"
              title="Tienes cambios sin guardar"
            >
              Sin guardar
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={() => save.mutate()}
            disabled={!canEdit || save.isPending || !!globalError}
            title="Guardar nueva versión"
          >
            <Save className="mr-1 size-3" />
            {save.isPending ? "Guardando…" : "Guardar"}
          </Button>
          {/* P1 — version history with rollback. Read-only browse for
              everyone; the rollback action inside the drawer is admin-
              gated by the backend so non-admins can still inspect. */}
          <PipelineVersionHistoryButton />
          {/* Audit drawer trigger. Always visible — viewing history is
              a read-only action, no role gate. */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            onClick={() => setAuditOpen(true)}
            title="Ver auditoría"
          >
            <Clock className="size-3.5" />
          </Button>
          {/* Pipeline-wide reset. The primary delete affordance lives on
              each stage's three-dot menu; this is the "reset to factory"
              escape hatch — small icon-only, secondary visual weight, no
              text label. Disabled when there's nothing saved or the user
              isn't an admin. */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setConfirmDeleteOpen(true)}
            disabled={!canEdit || !query.data || save.isPending || remove.isPending}
            title={
              !query.data
                ? "Sin pipeline guardado"
                : "Eliminar todas las versiones del pipeline (reset)"
            }
          >
            <Trash2 className="size-3.5" />
          </Button>
          {onClose && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onClose}
              title="Cerrar editor"
            >
              <X className="size-3.5" />
            </Button>
          )}
        </div>
      </div>

      <Dialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>¿Eliminar el pipeline?</DialogTitle>
            <DialogDescription>
              Esto borra <span className="font-medium">todas las versiones</span> del pipeline para
              este tenant. Las conversaciones existentes conservarán su etapa actual, pero el bot
              dejará de procesar nuevos turnos hasta que guardes un pipeline nuevo. No se puede
              deshacer.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmDeleteOpen(false)}
              disabled={remove.isPending}
            >
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
            >
              <Trash2 className="mr-1.5 size-3.5" />
              {remove.isPending ? "Eliminando…" : "Eliminar pipeline"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <StageDeleteDialog
        stage={stagePendingDelete !== null ? (draft.stages[stagePendingDelete] ?? null) : null}
        onCancel={() => setStagePendingDelete(null)}
        onConfirm={() => {
          if (stagePendingDelete !== null) {
            removeStage(stagePendingDelete);
          }
          setStagePendingDelete(null);
        }}
      />

      <AuditLogDrawer open={auditOpen} onOpenChange={setAuditOpen} />

      <div className="flex-1 overflow-y-auto">
        {/* Global error */}
        {globalError && (
          <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            {globalError}
          </div>
        )}

        {/* Pipeline-wide composer-mode labels and prompts. This lives above
            stages so operators understand these are reusable internal
            modes, while each stage can optionally pin one below. */}
        <div className="hidden" data-section="mode_prompts">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-medium"
            onClick={() => setShowModePrompts((v) => !v)}
          >
            {showModePrompts ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            Modo Composer: nombres y guiones ({configuredModeCount}/6 configurados ·{" "}
            {visibleModeCount}/6 visibles)
          </button>

          {showModePrompts && (
            <div className="space-y-3 px-4 pb-4">
              <div className="rounded-md border bg-muted/20 p-3 text-[10px] leading-relaxed text-muted-foreground">
                <strong className="text-foreground">PLAN es un modo interno.</strong> Puedes
                llamarlo como quieras para este negocio; el nombre visible ayuda al operador, pero
                el runner conserva PLAN, SALES, DOC, OBSTACLE, RETENTION y SUPPORT. Las reglas de
                etapa se editan en <strong>Auto-entrada</strong>, y este bloque define lo que el
                agente dice cuando cae en cada modo.
              </div>

              {FLOW_MODES.map((mode) => {
                const hidden = hiddenModeSet.has(mode);
                return (
                  <div
                    key={mode}
                    className={cn(
                      "space-y-2 rounded-md border bg-muted/10 p-3",
                      hidden && "bg-muted/5 opacity-75",
                    )}
                    data-mode-prompt={mode}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="rounded bg-background px-1.5 py-0.5 text-[10px]">
                            {mode}
                          </code>
                          <span className="text-xs font-medium">
                            {modeDisplayLabel(draft!, mode)}
                          </span>
                        </div>
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          Uso base: {FLOW_MODE_PURPOSES[mode]}.
                        </p>
                      </div>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={!hidden}
                        onClick={() => setModeVisible(mode, hidden)}
                        disabled={!canEdit}
                        className={cn(
                          "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          hidden ? "bg-muted" : "bg-primary",
                          !canEdit && "cursor-not-allowed opacity-50",
                        )}
                        title={hidden ? "Mostrar modo en el editor" : "Ocultar modo no usado"}
                      >
                        <span
                          className={cn(
                            "pointer-events-none inline-block size-4 rounded-full bg-white shadow-lg transition-transform",
                            hidden ? "translate-x-0" : "translate-x-4",
                          )}
                        />
                      </button>
                    </div>

                    <div className="grid gap-2 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)]">
                      <div className="flex flex-col gap-1">
                        <Label className="text-[10px]" htmlFor={`ml-${mode}`}>
                          Nombre visible para este negocio
                        </Label>
                        <Input
                          id={`ml-${mode}`}
                          value={draft!.mode_labels?.[mode] ?? ""}
                          onChange={(e) => updateModeLabel(mode, e.target.value)}
                          placeholder={FLOW_MODE_ALIAS_PLACEHOLDERS[mode]}
                          className="h-8 text-xs"
                          disabled={!canEdit}
                        />
                      </div>

                      {hidden ? (
                        <div className="flex items-center rounded-md border border-dashed bg-background/40 px-3 py-2 text-[10px] text-muted-foreground">
                          Oculto en el editor y selectores. No borra su prompt ni invalida etapas
                          existentes que ya lo usen.
                        </div>
                      ) : (
                        <div className="flex flex-col gap-1">
                          <Label className="text-[10px]" htmlFor={`mp-${mode}`}>
                            Prompt del modo
                          </Label>
                          <Textarea
                            id={`mp-${mode}`}
                            rows={4}
                            className="text-xs"
                            placeholder="Vacio = guion generico neutral para este modo"
                            value={draft!.mode_prompts?.[mode] ?? ""}
                            onChange={(e) => updateModePrompt(mode, e.target.value)}
                            disabled={!canEdit}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Stage list section */}
        <div className="px-4 pb-2 pt-4">
          <div className="mb-1 flex items-center justify-between">
            <p className="text-xs font-semibold">Etapas del pipeline</p>
            <span className="text-[10px] text-muted-foreground">Arrastra para reordenar</span>
          </div>

          {draft.stages.length > STAGE_SEARCH_MIN && (
            <div className="relative mb-2">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={stageFilter}
                onChange={(e) => setStageFilter(e.target.value)}
                placeholder={`Filtrar ${draft.stages.length} etapas por nombre o stage_id…`}
                className="h-8 pl-7 pr-7 text-xs"
                aria-label="Filtrar etapas"
              />
              {stageFilter && (
                <button
                  type="button"
                  onClick={() => setStageFilter("")}
                  aria-label="Limpiar filtro de etapas"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
          )}

          <div className="space-y-1">
            {draft.stages.map((stage, idx) => {
              if (!stageMatchesQuery(stage, stageFilter)) return null;
              return (
                // biome-ignore lint/a11y/useSemanticElements: this row is draggable and contains nested menu buttons.
                <div
                  key={stage.id}
                  draggable
                  role="button"
                  tabIndex={0}
                  onDragStart={() => handleDragStart(idx)}
                  onDragOver={(e) => handleDragOver(e, idx)}
                  onDrop={(e) => handleDrop(e, idx)}
                  onDragEnd={handleDragEnd}
                  onClick={() => setSelectedIdx(idx)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedIdx(idx);
                    }
                  }}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 transition-colors",
                    selectedIdx === idx
                      ? "border-primary/40 bg-primary/5"
                      : "border-transparent hover:border-border hover:bg-muted/40",
                    dragOver === idx && draggingIdx !== idx && "border-primary bg-primary/10",
                    draggingIdx === idx && "opacity-40",
                  )}
                >
                  <GripVertical
                    className="size-3.5 shrink-0 cursor-grab text-muted-foreground/50 active:cursor-grabbing"
                    aria-hidden
                  />
                  <div
                    className="size-2.5 shrink-0 rounded-full border-2"
                    style={{ backgroundColor: stage.color, borderColor: stage.color }}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{stage.label}</p>
                    <p className="truncate font-mono text-[9px] text-muted-foreground">
                      {stage.id}
                    </p>
                  </div>
                  {stage.is_terminal && (
                    <Badge variant="secondary" className="shrink-0 text-[9px] px-1 py-0">
                      terminal
                    </Badge>
                  )}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 shrink-0 text-muted-foreground hover:text-foreground"
                        title="Opciones de etapa"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <MoreHorizontal className="size-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-48">
                      <DropdownMenuItem onClick={() => moveStage(idx, -1)} disabled={idx === 0}>
                        Subir
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => moveStage(idx, 1)}
                        disabled={idx === draft.stages.length - 1}
                      >
                        Bajar
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => {
                          void navigator.clipboard.writeText(stage.id);
                          toast.success("stage_id copiado", { description: stage.id });
                        }}
                      >
                        Copiar stage_id
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => {
                          // Duplicate by appending "(copia)" to the label and a
                          // numeric suffix to the id until unique. Save-on-edit
                          // will reject duplicates anyway, but we pre-empt that.
                          const existingIds = new Set(draft.stages.map((s) => s.id));
                          let suffix = 2;
                          let newId = `${stage.id}_copia`;
                          while (existingIds.has(newId)) {
                            newId = `${stage.id}_copia_${suffix++}`;
                          }
                          setDraft((prev) => {
                            if (!prev) return prev;
                            const copy: StageDraft = {
                              ...stage,
                              id: newId,
                              label: `${stage.label} (copia)`,
                            };
                            const stages = [
                              ...prev.stages.slice(0, idx + 1),
                              copy,
                              ...prev.stages.slice(idx + 1),
                            ];
                            return { ...prev, stages };
                          });
                          setSelectedIdx(idx + 1);
                        }}
                        disabled={!canEdit}
                      >
                        Duplicar etapa
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={() => setStagePendingDelete(idx)}
                        disabled={!canEdit || draft.stages.length === 1}
                        title={
                          draft.stages.length === 1
                            ? "No puedes eliminar la última etapa"
                            : undefined
                        }
                      >
                        <Trash2 className="mr-2 size-3.5" /> Eliminar etapa
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            })}
            {draft.stages.length > STAGE_SEARCH_MIN &&
              stageFilter.trim() !== "" &&
              !draft.stages.some((s) => stageMatchesQuery(s, stageFilter)) && (
                <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">
                  Ninguna etapa coincide con “{stageFilter}”.
                </p>
              )}
          </div>

          <Button
            variant="outline"
            size="sm"
            className="mt-2 h-7 w-full text-xs"
            onClick={addStage}
            disabled={!canEdit}
          >
            <Plus className="mr-1 size-3" /> Agregar etapa
          </Button>
        </div>

        {/* Selected stage editor */}
        {selected !== null && selectedIdx !== null && (
          <div className="border-t px-4 pb-4 pt-3">
            <p className="mb-3 text-xs font-semibold text-muted-foreground">
              Editar etapa seleccionada
            </p>

            <div className="space-y-3">
              {/* Name + color */}
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Nombre
                  </Label>
                  <Input
                    className="h-8 text-sm"
                    value={selected.label}
                    onChange={(e) => updateStage(selectedIdx, { label: e.target.value })}
                    placeholder="Nombre visible"
                    disabled={!canEdit}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Color
                  </Label>
                  <div className="relative">
                    <input
                      type="color"
                      value={selected.color}
                      onChange={(e) => updateStage(selectedIdx, { color: e.target.value })}
                      disabled={!canEdit}
                      className="h-8 w-10 cursor-pointer rounded-md border border-input bg-background p-0.5"
                      title="Color de etapa"
                    />
                  </div>
                </div>
              </div>

              {/* stage_id */}
              <div>
                <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  stage_id{" "}
                  <span className="font-mono normal-case text-muted-foreground/70">
                    (regex: ^[a-z][a-z0-9_]&#123;2,29&#125;$)
                  </span>
                </Label>
                <div className="relative">
                  <Input
                    className={cn(
                      "h-8 pr-8 font-mono text-xs",
                      idError ? "border-destructive" : selected.id && "border-emerald-500",
                    )}
                    value={selected.id}
                    onChange={(e) =>
                      updateStage(selectedIdx, { id: e.target.value.trim().toLowerCase() })
                    }
                    placeholder="snake_case"
                    disabled={!canEdit}
                  />
                  <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2">
                    {idError ? (
                      <X className="size-3.5 text-destructive" />
                    ) : selected.id ? (
                      <Check className="size-3.5 text-emerald-500" />
                    ) : null}
                  </span>
                </div>
                {idError && <p className="mt-0.5 text-[10px] text-destructive">{idError}</p>}
              </div>

              {/* timeout_hours */}
              <div>
                <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  timeout_hours{" "}
                  <span className="font-mono normal-case text-muted-foreground/70">
                    (0 = sin alerta, máx 8760)
                  </span>
                </Label>
                <div className="relative">
                  <Input
                    type="number"
                    min={0}
                    max={8760}
                    step={1}
                    className={cn(
                      "h-8 pr-8 text-sm",
                      timeoutError ? "border-destructive" : "border-emerald-500",
                    )}
                    value={selected.timeout_hours}
                    onChange={(e) =>
                      updateStage(selectedIdx, { timeout_hours: Number(e.target.value) || 0 })
                    }
                    disabled={!canEdit}
                  />
                  <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2">
                    {timeoutError ? (
                      <X className="size-3.5 text-destructive" />
                    ) : (
                      <Check className="size-3.5 text-emerald-500" />
                    )}
                  </span>
                </div>
                {timeoutError && (
                  <p className="mt-0.5 text-[10px] text-destructive">{timeoutError}</p>
                )}
              </div>

              {/* is_terminal toggle */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  role="switch"
                  aria-checked={selected.is_terminal}
                  onClick={() => updateStage(selectedIdx, { is_terminal: !selected.is_terminal })}
                  disabled={!canEdit}
                  className={cn(
                    "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected.is_terminal ? "bg-primary" : "bg-muted",
                  )}
                  title={selected.is_terminal ? "Etapa terminal: sí" : "Etapa terminal: no"}
                >
                  <span
                    className={cn(
                      "pointer-events-none inline-block size-4 rounded-full bg-white shadow-lg transition-transform",
                      selected.is_terminal ? "translate-x-4" : "translate-x-0",
                    )}
                  />
                </button>
                <Label className="text-xs">
                  Etapa terminal
                  <span className="ml-1 text-muted-foreground">
                    (no se puede mover a etapas anteriores)
                  </span>
                </Label>
              </div>

              {/* allow_auto_backward toggle. Greyed out when the stage is
                  terminal — the validator rejects that combination anyway,
                  surfaced here so it's obvious why the toggle is disabled. */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  role="switch"
                  aria-checked={selected.allow_auto_backward === true}
                  onClick={() =>
                    updateStage(selectedIdx, {
                      allow_auto_backward: !(selected.allow_auto_backward === true),
                    })
                  }
                  disabled={!canEdit || selected.is_terminal}
                  className={cn(
                    "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected.allow_auto_backward ? "bg-primary" : "bg-muted",
                    (selected.is_terminal || !canEdit) && "cursor-not-allowed opacity-50",
                  )}
                  title={
                    selected.is_terminal
                      ? "No disponible en etapas terminales"
                      : "Permitir que reglas auto-muevan hacia atrás"
                  }
                >
                  <span
                    className={cn(
                      "pointer-events-none inline-block size-4 rounded-full bg-white shadow-lg transition-transform",
                      selected.allow_auto_backward ? "translate-x-4" : "translate-x-0",
                    )}
                  />
                </button>
                <Label className="text-xs">Permitir movimiento hacia atrás automático</Label>
              </div>

              {/* Fase 6 — behavior_mode dropdown. Empty = use the per-turn
                  flow router rules (legacy behaviour). Any non-empty value
                  pins this stage's mode regardless of router output. */}
              <div className="flex flex-col gap-1.5" data-field="behavior_mode">
                <Label className="text-xs" htmlFor="behavior-mode-select">
                  Modo del Composer
                  <span className="ml-1 text-muted-foreground">
                    (opcional, fija el prompt-block que se usa en esta etapa)
                  </span>
                </Label>
                <select
                  id="behavior-mode-select"
                  className="h-8 rounded-md border bg-background px-2 text-xs disabled:opacity-50"
                  disabled={!canEdit}
                  value={selected.behavior_mode ?? ""}
                  onChange={(e) =>
                    updateStage(selectedIdx, {
                      behavior_mode: (e.target.value as BehaviorMode | "") || "",
                    })
                  }
                >
                  <option value="">— Usar reglas del router (default) —</option>
                  {behaviorModeOptions.map((m) => (
                    <option key={m} value={m}>
                      {modeDisplayLabel(draft, m)}
                      {hiddenModeSet.has(m) ? " — oculto" : ""}
                    </option>
                  ))}
                </select>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  {selected.behavior_mode
                    ? `${selected.behavior_mode} es el modo interno; el nombre visible se edita en "Guion del agente por modo".`
                    : "Si no fijas modo, mandan las reglas del router. Puedes renombrar y ocultar modos abajo sin cambiar el contrato interno."}
                </p>
              </div>

              {/* Fase 4 — pause_bot_on_enter toggle + handoff_reason input.
                  When the conversation enters this stage, the runner pauses
                  the bot, persists a `human_handoffs` row tagged with the
                  selected reason, and emits the BOT_PAUSED + HUMAN_HANDOFF
                  events. The reason input becomes editable only when the
                  toggle is on. */}
              <div className="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <Label className="text-xs">Acciones permitidas</Label>
                    <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                      El clasificador detecta la intencion; esta lista decide que puede ejecutar el
                      bot dentro de esta etapa.
                    </p>
                  </div>
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    {selected.actions_allowed.length}
                  </Badge>
                </div>
                <div className="grid gap-1.5 sm:grid-cols-2">
                  {ACTION_OPTIONS.map((action) => {
                    const checked = selected.actions_allowed.includes(action.value);
                    return (
                      <button
                        key={action.value}
                        type="button"
                        disabled={!canEdit}
                        aria-pressed={checked}
                        onClick={() => {
                          const next = checked
                            ? selected.actions_allowed.filter((value) => value !== action.value)
                            : [...selected.actions_allowed, action.value];
                          updateStage(selectedIdx, { actions_allowed: next });
                        }}
                        className={cn(
                          "min-h-12 rounded-md border px-2 py-1.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                          checked
                            ? "border-primary/40 bg-primary/10"
                            : "border-border bg-background hover:border-primary/30",
                        )}
                      >
                        <span className="flex items-center gap-1.5 text-[11px] font-medium">
                          <span
                            className={cn(
                              "flex size-3.5 items-center justify-center rounded border",
                              checked
                                ? "border-primary bg-primary text-primary-foreground"
                                : "border-input",
                            )}
                          >
                            {checked && <Check className="size-2.5" />}
                          </span>
                          {action.label}
                        </span>
                        <span className="mt-0.5 block pl-5 text-[10px] leading-snug text-muted-foreground">
                          {action.value}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="flex items-center gap-3" data-field="pause_bot_on_enter">
                <button
                  type="button"
                  role="switch"
                  aria-checked={selected.pause_bot_on_enter === true}
                  onClick={() =>
                    updateStage(selectedIdx, {
                      pause_bot_on_enter: !(selected.pause_bot_on_enter === true),
                    })
                  }
                  disabled={!canEdit}
                  className={cn(
                    "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected.pause_bot_on_enter ? "bg-primary" : "bg-muted",
                    !canEdit && "cursor-not-allowed opacity-50",
                  )}
                  title="Cuando la conversación entra a esta etapa, pausa el bot y crea un handoff humano"
                >
                  <span
                    className={cn(
                      "pointer-events-none inline-block size-4 rounded-full bg-white shadow-lg transition-transform",
                      selected.pause_bot_on_enter ? "translate-x-4" : "translate-x-0",
                    )}
                  />
                </button>
                <Label className="text-xs">
                  Pausar bot al entrar
                  <span className="ml-1 text-muted-foreground">
                    (crea handoff humano automático)
                  </span>
                </Label>
              </div>

              {selected.pause_bot_on_enter && (
                <div className="flex flex-col gap-1.5" data-field="handoff_reason">
                  <Label className="text-xs" htmlFor="handoff-reason-input">
                    Razón del handoff
                    <span className="ml-1 text-muted-foreground">
                      (se guarda en <code>human_handoffs.reason</code>)
                    </span>
                  </Label>
                  <div className="flex gap-2">
                    <select
                      id="handoff-reason-input"
                      className="h-8 flex-1 rounded-md border bg-background px-2 text-xs disabled:opacity-50"
                      disabled={!canEdit}
                      value={
                        HANDOFF_REASON_PRESETS.some(
                          (r) => r.value === (selected.handoff_reason ?? ""),
                        )
                          ? selected.handoff_reason
                          : "__custom__"
                      }
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "__custom__") {
                          // Leave the current value; the input below
                          // becomes the source of truth.
                          if (
                            HANDOFF_REASON_PRESETS.some(
                              (r) => r.value === (selected.handoff_reason ?? ""),
                            )
                          ) {
                            updateStage(selectedIdx, { handoff_reason: "" });
                          }
                          return;
                        }
                        updateStage(selectedIdx, { handoff_reason: v });
                      }}
                    >
                      {HANDOFF_REASON_PRESETS.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                      <option value="__custom__">Personalizado…</option>
                    </select>
                    <Input
                      className="h-8 flex-1 text-xs"
                      placeholder="o escribe una razón personalizada"
                      disabled={!canEdit}
                      value={
                        HANDOFF_REASON_PRESETS.some(
                          (r) => r.value === (selected.handoff_reason ?? ""),
                        )
                          ? ""
                          : (selected.handoff_reason ?? "")
                      }
                      onChange={(e) =>
                        updateStage(selectedIdx, {
                          handoff_reason: e.target.value,
                        })
                      }
                    />
                  </div>
                </div>
              )}
            </div>

            {/* M2: per-stage auto-enter rules. RuleBuilder owns the toggle,
                match mode, and condition rows. We hand it the stage's
                rules and a setter that patches the draft. Live JSON
                preview below picks the change up because serialise
                already round-trips auto_enter_rules. */}
            <div className="mt-4 border-t pt-3">
              <RuleBuilder
                stageLabel={selected.label || selected.id}
                rules={selected.auto_enter_rules}
                onChange={(next) => updateStage(selectedIdx, { auto_enter_rules: next })}
                disabled={!canEdit}
                fieldCatalog={ruleFieldCatalog}
              />
            </div>

            {/* P6: read-only dependency view. Surfaces the same
                impacted-references data the delete dialog uses, but
                here so an operator sees how many conversations sit in
                this stage and which workflows reference it BEFORE
                editing behavior_mode / rules — not only on delete.
                Keyed on the persisted stage id; while a brand-new
                stage's id is still being typed the query is disabled. */}
            <StageDependencyView stageId={selected.id} />
          </div>
        )}

        {/* JSON toggle section */}
        <div className="border-t">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setShowJson((v) => !v)}
          >
            {showJson ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            <Code2 className="size-3.5" />
            Ver JSON del pipeline
          </button>
          {showJson && (
            <div className="px-4 pb-4">
              <Textarea
                rows={14}
                spellCheck={false}
                className="font-mono text-[11px]"
                value={JSON.stringify(serialise(draft), null, 2)}
                onChange={(e) => {
                  try {
                    const parsed = JSON.parse(e.target.value);
                    setDraft(parsePipeline(parsed));
                  } catch {
                    /* keep typing */
                  }
                }}
                disabled={!canEdit}
              />
            </div>
          )}
        </div>

        {/* Document catalog — tenant-configurable list of document keys
            the operator can reference from any stage's auto_enter_rules. */}
        <div className="border-t">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setShowDocsCatalog((v) => !v)}
          >
            {showDocsCatalog ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            <FileText className="size-3.5" />
            Catálogo de documentos ({draft.documents_catalog.length})
          </button>
          {showDocsCatalog && (
            <div className="space-y-3 px-4 pb-4">
              <p className="text-[11px] text-muted-foreground">
                Define los documentos que tus clientes deben subir. Cada entrada se puede usar en
                reglas de auto-entrada como <code>{`<DOCUMENTO>.status`}</code> y aparece en el
                panel "Documentos" del contacto.
              </p>

              {/* List of existing entries */}
              {draft.documents_catalog.length > 0 && (
                <div className="space-y-1.5">
                  {draft.documents_catalog.map((doc, idx) => (
                    <div key={doc.key} className="rounded-md border bg-card p-2">
                      <div className="mb-1.5 flex items-center justify-between gap-2">
                        <code className="truncate font-mono text-[10px] text-muted-foreground">
                          {doc.key}
                        </code>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5 text-destructive hover:bg-destructive/10"
                          onClick={() => removeDoc(idx)}
                          disabled={!canEdit}
                          aria-label={`Eliminar ${doc.label || doc.key}`}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                      <div className="space-y-1.5">
                        <div>
                          <Label className="text-[10px] text-muted-foreground">
                            Nombre visible
                          </Label>
                          <Input
                            value={doc.label}
                            onChange={(e) => updateDoc(idx, { label: e.target.value })}
                            placeholder="Ej. CURP"
                            className="h-7 text-xs"
                            disabled={!canEdit}
                          />
                        </div>
                        <div>
                          <Label className="text-[10px] text-muted-foreground">
                            Descripción corta (opcional)
                          </Label>
                          <Input
                            value={doc.hint}
                            onChange={(e) => updateDoc(idx, { hint: e.target.value })}
                            placeholder="Ej. Frente y vuelta, vigente"
                            className="h-7 text-xs"
                            disabled={!canEdit}
                          />
                          <p className="mt-0.5 text-[10px] text-muted-foreground">
                            Aparece en gris debajo del nombre.
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Add-row — single primary field + optional hint. The
                  internal document key is auto-derived from the name. */}
              {canEdit && (
                <div className="rounded-md border border-dashed bg-muted/20 p-2">
                  <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    Agregar documento
                  </p>
                  <div className="space-y-1.5">
                    <div>
                      <Label className="text-[10px] text-muted-foreground">
                        Nombre del documento
                      </Label>
                      <Input
                        value={newDocLabel}
                        onChange={(e) => setNewDocLabel(e.target.value)}
                        placeholder="Ej. CURP, Comprobante de ingresos"
                        className="h-7 text-xs"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newDocLabel.trim() && !previewCollides) {
                            e.preventDefault();
                            addDoc();
                          }
                        }}
                      />
                      {previewKey && (
                        <p
                          className={cn(
                            "mt-1 text-[10px]",
                            previewCollides ? "text-destructive" : "text-muted-foreground",
                          )}
                        >
                          {previewCollides ? (
                            `Ya existe un documento con el ID ${previewKey}. Renómbralo.`
                          ) : (
                            <>
                              ID interno: <code className="font-mono">{previewKey}</code>
                            </>
                          )}
                        </p>
                      )}
                    </div>
                    <div>
                      <Label className="text-[10px] text-muted-foreground">
                        Descripción corta (opcional)
                      </Label>
                      <Input
                        value={newDocHint}
                        onChange={(e) => setNewDocHint(e.target.value)}
                        placeholder="Ej. Recibo CFE / agua, no mayor a 3 meses"
                        className="h-7 text-xs"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newDocLabel.trim() && !previewCollides) {
                            e.preventDefault();
                            addDoc();
                          }
                        }}
                      />
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        Aparece en gris debajo del nombre. Útil para aclarar "qué versión
                        exactamente" sin meterlo en el nombre.
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 w-full"
                      onClick={addDoc}
                      disabled={!newDocLabel.trim() || previewCollides}
                    >
                      <Plus className="mr-1 size-3.5" />
                      Agregar al catálogo
                    </Button>
                  </div>
                </div>
              )}

              {draft.documents_catalog.length === 0 && (
                <p className="text-[11px] italic text-muted-foreground">
                  Aún no defines documentos. Agrega el primero arriba — cuando guardes el pipeline
                  aparecerán como checkboxes en cada etapa para que marques cuáles requiere cada
                  una.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Docs-per-plan: which documents each credit plan requires.
            Used by the new `docs_complete_for_plan` operator so a stage
            can auto-enter when "every doc this customer's plan needs
            has status=ok". */}
        <div className="border-t">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setShowDocsByPlan((v) => !v)}
          >
            {showDocsByPlan ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            <FileText className="size-3.5" />
            Documentos por plan de crédito ({Object.keys(draft.docs_per_plan).length})
          </button>
          {showDocsByPlan && (
            <div className="space-y-3 px-4 pb-4">
              <p className="text-[11px] text-muted-foreground">
                Por cada plan que tu agente identifica (campo{" "}
                <code className="rounded bg-muted px-1 text-[10px]">plan_credito</code>), marca los
                documentos del catálogo que el cliente debe entregar. La regla "tiene todos los docs
                del plan completos" usa exactamente este mapa.
              </p>

              {Object.keys(draft.docs_per_plan).length === 0 && (
                <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
                  Aún no defines planes. Agrega el primero abajo.
                </p>
              )}

              {Object.entries(draft.docs_per_plan).map(([plan, docKeys]) => (
                <div key={plan} className="rounded-md border bg-card p-2">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <code className="font-mono text-[11px] font-semibold">{plan}</code>
                    <span className="text-[10px] text-muted-foreground">
                      {(docKeys || []).length} doc(s)
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="ml-auto h-6 px-1.5 text-destructive hover:bg-destructive/10"
                      onClick={() => removePlan(plan)}
                      disabled={!canEdit}
                      aria-label={`Eliminar plan ${plan}`}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                  {draft.documents_catalog.length === 0 ? (
                    <p className="text-[11px] italic text-muted-foreground">
                      Primero define documentos en el catálogo (arriba).
                    </p>
                  ) : (
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                      {draft.documents_catalog.map((doc) => {
                        const checked = (docKeys || []).includes(doc.key);
                        return (
                          <button
                            key={doc.key}
                            type="button"
                            onClick={() => togglePlanDoc(plan, doc.key)}
                            disabled={!canEdit}
                            aria-pressed={checked}
                            className={cn(
                              "flex items-start gap-2 rounded-md border px-2 py-1.5 text-left text-[11px] transition",
                              checked
                                ? "border-emerald-500/40 bg-emerald-500/5"
                                : "border-border bg-background hover:bg-muted/40",
                              !canEdit && "cursor-not-allowed opacity-50",
                            )}
                          >
                            <span
                              className={cn(
                                "mt-0.5 inline-flex size-3.5 shrink-0 items-center justify-center rounded border",
                                checked
                                  ? "border-emerald-500 bg-emerald-500 text-white"
                                  : "border-input bg-background",
                              )}
                              aria-hidden
                            >
                              {checked ? "✓" : ""}
                            </span>
                            <span className="flex-1">
                              <span className="block font-medium text-foreground">{doc.label}</span>
                              <span className="block font-mono text-[9px] text-muted-foreground">
                                {doc.key}
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}

              {canEdit && (
                <div className="flex items-end gap-2 rounded-md border border-dashed bg-muted/20 p-2">
                  <div className="flex-1">
                    <Label className="text-[10px] text-muted-foreground">Nuevo plan</Label>
                    <Input
                      value={newPlanName}
                      onChange={(e) => setNewPlanName(e.target.value)}
                      placeholder="Ej. nomina_tarjeta, tradicional"
                      className="h-7 font-mono text-[11px]"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && newPlanName.trim()) {
                          e.preventDefault();
                          addPlan();
                        }
                      }}
                    />
                    <p className="mt-0.5 text-[10px] text-muted-foreground">
                      El nombre debe coincidir con el valor que tu agente escribe en{" "}
                      <code>plan_credito</code>.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7"
                    onClick={addPlan}
                    disabled={!newPlanName.trim()}
                  >
                    <Plus className="mr-1 size-3.5" />
                    Agregar plan
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer note */}
        <p className="px-4 pb-4 pt-2 text-[10px] text-muted-foreground">
          Cada guardado crea una nueva versión. Las conversaciones en etapas eliminadas aparecerán
          como huérfanas en el Pipeline hasta ser movidas.
        </p>
      </div>
    </div>
  );
}

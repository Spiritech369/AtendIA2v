import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  GripVertical,
  MoreHorizontal,
  Plus,
  Save,
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
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

import { RuleBuilder } from "./RuleBuilder";

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
  | "not_in";

export const OPERATORS_WITHOUT_VALUE: ReadonlySet<RuleOperator> = new Set([
  "exists",
  "not_exists",
]);

export const OPERATORS_NEEDING_LIST: ReadonlySet<RuleOperator> = new Set([
  "in",
  "not_in",
]);

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

interface StageDraft {
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
}

interface PipelineDraft {
  stages: StageDraft[];
  docs_per_plan: Record<string, string[]>;
  fallback?: string;
  extra: Record<string, unknown>;
}

const STAGE_ID_RE = /^[a-z][a-z0-9_]{2,29}$/;
const STAGE_COLORS = [
  "#6366f1", "#3b82f6", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#06b6d4", "#84cc16",
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
          ? co.value.split(",").map((x) => x.trim()).filter(Boolean)
          : [];
      return [{ field: co.field, operator: op, value: list }];
    }
    const scalar = co.value === null || co.value === undefined ? "" : String(co.value);
    return [{ field: co.field, operator: op, value: scalar }];
  });
  return { enabled, match, conditions };
}

function serializeAutoEnterRules(rules: AutoEnterRulesDraft | undefined): Record<string, unknown> | undefined {
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
          ? c.value.split(",").map((x) => x.trim()).filter(Boolean)
          : [];
      return { field: c.field, operator: c.operator, value: list };
    }
    return { field: c.field, operator: c.operator, value: c.value ?? "" };
  });
  return { enabled: rules.enabled, match: rules.match, conditions };
}

function parsePipeline(raw: Record<string, unknown> | undefined): PipelineDraft {
  const def = raw ?? {};
  const rawStages = Array.isArray(def.stages) ? def.stages : [];
  const stages: StageDraft[] = rawStages.flatMap((s: unknown, idx: number) => {
    if (typeof s !== "object" || s === null) return [];
    const obj = s as Record<string, unknown>;
    if (typeof obj.id !== "string") return [];
    return [
      {
        id: obj.id,
        label: typeof obj.label === "string" && obj.label.length > 0 ? obj.label : obj.id,
        timeout_hours: typeof obj.timeout_hours === "number" ? obj.timeout_hours : 0,
        is_terminal: obj.is_terminal === true,
        color: typeof obj.color === "string" ? obj.color : defaultColor(idx),
        auto_enter_rules: parseAutoEnterRules(obj.auto_enter_rules),
        allow_auto_backward: obj.allow_auto_backward === true,
      },
    ];
  });
  const docs =
    typeof def.docs_per_plan === "object" && def.docs_per_plan !== null
      ? (def.docs_per_plan as Record<string, string[]>)
      : {};
  const fallback = typeof def.fallback === "string" ? def.fallback : undefined;
  const extra: Record<string, unknown> = { ...def };
  delete extra.stages;
  delete extra.docs_per_plan;
  delete extra.fallback;
  return { stages, docs_per_plan: docs, fallback, extra };
}

function serialise(draft: PipelineDraft): Record<string, unknown> {
  return {
    ...draft.extra,
    stages: draft.stages.map((s) => {
      const rulesSerialized = serializeAutoEnterRules(s.auto_enter_rules);
      return {
        id: s.id,
        label: s.label,
        timeout_hours: s.timeout_hours,
        color: s.color,
        ...(s.is_terminal ? { is_terminal: true } : {}),
        ...(s.allow_auto_backward ? { allow_auto_backward: true } : {}),
        ...(rulesSerialized ? { auto_enter_rules: rulesSerialized } : {}),
      };
    }),
    docs_per_plan: draft.docs_per_plan,
    ...(draft.fallback ? { fallback: draft.fallback } : {}),
  };
}

// Mirrors backend _RULE_FIELD_RE in pipeline_definition.py. Accepts
// dot-separated identifiers (DOCS_INE.status, modelo_interes).
const RULE_FIELD_RE = /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/;

function validate(draft: PipelineDraft): string | null {
  if (draft.stages.length === 0) return "El pipeline debe tener al menos una etapa.";
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
              ? c.value.split(",").map((x) => x.trim()).filter(Boolean)
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

  const [draft, setDraft] = useState<PipelineDraft | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [showDocsJson, setShowDocsJson] = useState(false);
  const [docsRaw, setDocsRaw] = useState("");
  const [dragOver, setDragOver] = useState<number | null>(null);
  const [draggingIdx, setDraggingIdx] = useState<number | null>(null);

  useEffect(() => {
    if (query.data) {
      const parsed = parsePipeline(query.data.definition);
      setDraft(parsed);
      setDocsRaw(JSON.stringify(parsed.docs_per_plan, null, 2));
      if (parsed.stages.length > 0 && selectedIdx === null) setSelectedIdx(0);
    } else if (query.isError) {
      const seed: PipelineDraft = {
        stages: [
          { id: "nuevo", label: "Nuevo lead", timeout_hours: 24, is_terminal: false, color: "#6366f1" },
          { id: "en_conversacion", label: "En conversación", timeout_hours: 12, is_terminal: false, color: "#3b82f6" },
          { id: "propuesta", label: "Propuesta", timeout_hours: 48, is_terminal: false, color: "#f59e0b" },
        ],
        docs_per_plan: { default: [] },
        fallback: "escalate_to_human",
        extra: {},
      };
      setDraft(seed);
      setDocsRaw(JSON.stringify(seed.docs_per_plan, null, 2));
      setSelectedIdx(0);
    }
  }, [query.data, query.isError]); // eslint-disable-line react-hooks/exhaustive-deps

  const globalError = useMemo(() => (draft ? validate(draft) : null), [draft]);

  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("No draft");
      let docs: Record<string, string[]>;
      try {
        const parsed = JSON.parse(docsRaw);
        if (typeof parsed !== "object" || parsed === null) throw new Error("not object");
        docs = parsed as Record<string, string[]>;
      } catch {
        throw new Error("docs_per_plan no es JSON válido (esperado un objeto)");
      }
      const v = validate(draft);
      if (v) throw new Error(v);
      return tenantsApi.putPipeline(serialise({ ...draft, docs_per_plan: docs }));
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
    onError: (e) =>
      toast.error("No se pudo eliminar", { description: e.message }),
  });

  if (query.isLoading || !draft) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <Skeleton className="h-5 w-40" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  const updateStage = (idx: number, patch: Partial<StageDraft>) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, stages: prev.stages.map((s, i) => (i === idx ? { ...s, ...patch } : s)) };
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

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Panel header */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">PipelineEditor</span>
          {query.data && (
            <Badge variant="outline" className="text-[10px]">
              v{query.data.version}
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
              Esto borra <span className="font-medium">todas las versiones</span> del
              pipeline para este tenant. Las conversaciones existentes
              conservarán su etapa actual, pero el bot dejará de procesar
              nuevos turnos hasta que guardes un pipeline nuevo. No se puede
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

      {/* Per-stage delete confirmation. Mutates the local draft so the
          change isn't persisted until the user hits Guardar. Conversations
          currently in this stage_id become orphaned in the board until
          moved — surfaced in the dialog copy so the operator knows the
          downstream impact before confirming. */}
      <Dialog
        open={stagePendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setStagePendingDelete(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              ¿Eliminar la etapa{" "}
              <span className="font-mono text-sm">
                {stagePendingDelete !== null
                  ? draft.stages[stagePendingDelete]?.id ?? ""
                  : ""}
              </span>
              ?
            </DialogTitle>
            <DialogDescription>
              Las conversaciones que estén actualmente en esta etapa
              aparecerán como <span className="font-medium">huérfanas</span>{" "}
              en el board hasta que las muevas a otra etapa. Los workflows
              que referencien este <span className="font-mono">stage_id</span>{" "}
              dejarán de disparar. El cambio se aplica al pulsar{" "}
              <span className="font-medium">Guardar</span>.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setStagePendingDelete(null)}
            >
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (stagePendingDelete !== null) {
                  removeStage(stagePendingDelete);
                }
                setStagePendingDelete(null);
              }}
            >
              <Trash2 className="mr-1.5 size-3.5" />
              Eliminar etapa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="flex-1 overflow-y-auto">
        {/* Global error */}
        {globalError && (
          <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            {globalError}
          </div>
        )}

        {/* Stage list section */}
        <div className="px-4 pb-2 pt-4">
          <div className="mb-1 flex items-center justify-between">
            <p className="text-xs font-semibold">Etapas del pipeline</p>
            <span className="text-[10px] text-muted-foreground">Arrastra para reordenar</span>
          </div>

          <div className="space-y-1">
            {draft.stages.map((stage, idx) => (
              <div
                key={`${stage.id}-${idx}`}
                draggable
                onDragStart={() => handleDragStart(idx)}
                onDragOver={(e) => handleDragOver(e, idx)}
                onDrop={(e) => handleDrop(e, idx)}
                onDragEnd={handleDragEnd}
                onClick={() => setSelectedIdx(idx)}
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
                  <p className="truncate font-mono text-[9px] text-muted-foreground">{stage.id}</p>
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
                      title={draft.stages.length === 1 ? "No puedes eliminar la última etapa" : undefined}
                    >
                      <Trash2 className="mr-2 size-3.5" /> Eliminar etapa
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))}
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
                    onChange={(e) => updateStage(selectedIdx, { id: e.target.value.trim().toLowerCase() })}
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
                  <span className="font-mono normal-case text-muted-foreground/70">(0 = sin alerta, máx 8760)</span>
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
                    onChange={(e) => updateStage(selectedIdx, { timeout_hours: Number(e.target.value) || 0 })}
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
                {timeoutError && <p className="mt-0.5 text-[10px] text-destructive">{timeoutError}</p>}
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
                <Label className="text-xs">
                  Permitir movimiento hacia atrás automático
                </Label>
              </div>
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
                onChange={(next) =>
                  updateStage(selectedIdx, { auto_enter_rules: next })
                }
                disabled={!canEdit}
              />
            </div>
          </div>
        )}

        {/* JSON toggle section */}
        <div className="border-t">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setShowJson((v) => !v)}
          >
            {showJson ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
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

        {/* Docs per plan section */}
        <div className="border-t">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setShowDocsJson((v) => !v)}
          >
            {showDocsJson ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            Documentos por plan de crédito
          </button>
          {showDocsJson && (
            <div className="px-4 pb-4">
              <p className="mb-2 text-[10px] text-muted-foreground">
                Mapa <code>plan → lista de campos</code>. Ej:{" "}
                <code>{`{"36m":["docs_ine","docs_comprobante"]}`}</code>
              </p>
              <Textarea
                rows={6}
                spellCheck={false}
                className="font-mono text-[11px]"
                value={docsRaw}
                onChange={(e) => setDocsRaw(e.target.value)}
                disabled={!canEdit}
              />
            </div>
          )}
        </div>

        {/* Footer note */}
        <p className="px-4 pb-4 pt-2 text-[10px] text-muted-foreground">
          Cada guardado crea una nueva versión. Las conversaciones en etapas eliminadas
          aparecerán como huérfanas en el Pipeline hasta ser movidas.
        </p>
      </div>
    </div>
  );
}

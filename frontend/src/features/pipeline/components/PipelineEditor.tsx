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

interface StageDraft {
  id: string;
  label: string;
  timeout_hours: number;
  is_terminal: boolean;
  color: string;
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
    stages: draft.stages.map((s) => ({
      id: s.id,
      label: s.label,
      timeout_hours: s.timeout_hours,
      color: s.color,
      ...(s.is_terminal ? { is_terminal: true } : {}),
    })),
    docs_per_plan: draft.docs_per_plan,
    ...(draft.fallback ? { fallback: draft.fallback } : {}),
  };
}

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
          {/* Eliminar pipeline — only visible when a saved pipeline exists.
              Disabled while a save/delete is mid-flight or the user is not
              an admin. Clicks open a confirmation dialog rather than
              firing the destructive call directly. */}
          {query.data && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 border-destructive/40 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setConfirmDeleteOpen(true)}
              disabled={!canEdit || save.isPending || remove.isPending}
              title="Eliminar todas las versiones del pipeline"
            >
              <Trash2 className="mr-1 size-3" />
              Eliminar
            </Button>
          )}
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
                      className="h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 hover:opacity-100 focus:opacity-100"
                      title="Opciones de etapa"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <MoreHorizontal className="size-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
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
                      className="text-destructive focus:text-destructive"
                      onClick={() => removeStage(idx)}
                      disabled={draft.stages.length === 1}
                    >
                      <Trash2 className="mr-2 size-3.5" /> Eliminar
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

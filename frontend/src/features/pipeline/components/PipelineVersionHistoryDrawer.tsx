// P1 — Pipeline version history drawer.
//
// Lists past pipeline snapshots, lets the operator inspect a chosen
// version's definition and diff it against the live config, and roll
// back with an explicit confirmation dialog. Mirrors the structure of
// the agent VersionHistoryDrawer but the diff is pipeline-shaped:
// stages added/removed/renamed, rule counts, doc catalog size,
// vision mapping size — not flat scalar fields.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  History,
  Layers,
  RotateCcw,
} from "lucide-react";
import { useState } from "react";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { type PipelineVersionListItem, tenantsApi } from "@/features/config/api";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type View = { mode: "list" } | { mode: "detail"; index: number };

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diff = Date.now() - d.getTime();
  const sec = Math.round(diff / 1000);
  if (sec < 60) return "hace unos segundos";
  const min = Math.round(sec / 60);
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h} h`;
  const days = Math.round(h / 24);
  if (days < 30) return `hace ${days} d`;
  return d.toLocaleDateString("es-MX", { dateStyle: "medium" });
}

// Pipeline definitions are deeply nested; we project a few high-level
// counters so the diff is operator-readable without dumping JSON.
interface PipelineShape {
  stageIds: string[];
  stageLabels: Record<string, string>;
  ruleCount: number;
  docCatalogCount: number;
  visionMappingCount: number;
  planDocCount: number;
  flowModeRuleCount: number;
}

function shapeOf(definition: Record<string, unknown> | undefined): PipelineShape {
  const stages = Array.isArray(definition?.stages)
    ? (definition?.stages as Record<string, unknown>[])
    : [];
  const stageIds: string[] = [];
  const stageLabels: Record<string, string> = {};
  let ruleCount = 0;
  for (const s of stages) {
    const id = typeof s.id === "string" ? s.id : null;
    if (!id) continue;
    stageIds.push(id);
    stageLabels[id] = typeof s.label === "string" ? s.label : id;
    const rules = s.auto_enter_rules as { conditions?: unknown[] } | undefined;
    if (rules && Array.isArray(rules.conditions)) {
      ruleCount += rules.conditions.length;
    }
  }
  const docCatalog = definition?.documents_catalog;
  const docCatalogCount =
    docCatalog && typeof docCatalog === "object" && !Array.isArray(docCatalog)
      ? Object.keys(docCatalog).length
      : Array.isArray(docCatalog)
        ? docCatalog.length
        : 0;
  const visionMapping = definition?.vision_mapping;
  const visionMappingCount =
    visionMapping && typeof visionMapping === "object" ? Object.keys(visionMapping).length : 0;
  const planDocs = definition?.docs_per_plan;
  const planDocCount = planDocs && typeof planDocs === "object" ? Object.keys(planDocs).length : 0;
  const flowModeRules = Array.isArray(definition?.flow_mode_rules)
    ? (definition?.flow_mode_rules as unknown[])
    : [];
  return {
    stageIds,
    stageLabels,
    ruleCount,
    docCatalogCount,
    visionMappingCount,
    planDocCount,
    flowModeRuleCount: flowModeRules.length,
  };
}

function VersionRow({
  version,
  onClick,
}: {
  version: PipelineVersionListItem;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-md border bg-card p-3 text-left transition-colors hover:bg-muted/50"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="font-mono text-[10px] border-sky-500/40 bg-sky-500/10 text-sky-700"
          >
            v#{version.index}
          </Badge>
          {version.is_current && (
            <Badge variant="outline" className="text-[10px]">
              actual
            </Badge>
          )}
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">
          {formatRelative(version.captured_at)}
        </span>
      </div>
      <div className="mt-1.5 text-xs text-muted-foreground">
        <Layers className="mr-1 inline h-3 w-3" />
        {version.stage_count} etapa{version.stage_count === 1 ? "" : "s"}
        {version.captured_by && (
          <span className="ml-2 font-mono">· {version.captured_by.slice(0, 8)}</span>
        )}
      </div>
    </button>
  );
}

interface DiffStats {
  added: string[];
  removed: string[];
  kept: string[];
  ruleDelta: number;
  docDelta: number;
  visionDelta: number;
  planDelta: number;
  flowModeDelta: number;
}

function computeDiff(current: PipelineShape, version: PipelineShape): DiffStats {
  const currentSet = new Set(current.stageIds);
  const versionSet = new Set(version.stageIds);
  return {
    // "added" = in current but not in the version → the operator added
    // these since this version. "removed" = in the version but missing
    // from current → would come back if we rolled back to this version.
    added: current.stageIds.filter((id) => !versionSet.has(id)),
    removed: version.stageIds.filter((id) => !currentSet.has(id)),
    kept: current.stageIds.filter((id) => versionSet.has(id)),
    ruleDelta: current.ruleCount - version.ruleCount,
    docDelta: current.docCatalogCount - version.docCatalogCount,
    visionDelta: current.visionMappingCount - version.visionMappingCount,
    planDelta: current.planDocCount - version.planDocCount,
    flowModeDelta: current.flowModeRuleCount - version.flowModeRuleCount,
  };
}

function CountDelta({
  label,
  versionValue,
  delta,
}: {
  label: string;
  versionValue: number;
  delta: number;
}) {
  const currentValue = versionValue + delta;
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1.5 font-mono">
        <span>{versionValue}</span>
        <ArrowRight className="h-3 w-3 text-muted-foreground" />
        <span
          className={cn(
            delta === 0
              ? "text-muted-foreground"
              : delta > 0
                ? "text-emerald-600"
                : "text-rose-600",
          )}
        >
          {currentValue}
          {delta !== 0 && (
            <span className="ml-1 text-[10px]">
              ({delta > 0 ? "+" : ""}
              {delta})
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

function VersionDetail({
  index,
  current,
  onBack,
  onRollback,
  rollbackPending,
}: {
  index: number;
  current: PipelineShape;
  onBack: () => void;
  onRollback: () => void;
  rollbackPending: boolean;
}) {
  const versionQuery = useQuery({
    queryKey: ["pipeline-version", index],
    queryFn: () => tenantsApi.getPipelineVersion(index),
  });

  if (versionQuery.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (versionQuery.isError || !versionQuery.data) {
    return (
      <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-800">
        No se pudo cargar la versión.
      </div>
    );
  }

  const v = versionQuery.data;
  const versionShape = shapeOf(v.definition);
  const diff = computeDiff(current, versionShape);
  const isCurrent = v.is_current;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack} className="h-8 px-2">
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Volver
        </Button>
        {!isCurrent && (
          <Button
            size="sm"
            variant="outline"
            onClick={onRollback}
            disabled={rollbackPending}
            className="h-8"
          >
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
            {rollbackPending ? "Restaurando…" : "Restaurar esta versión"}
          </Button>
        )}
      </div>

      <div className="rounded-md border bg-card p-3 text-xs">
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="font-mono text-[10px] border-sky-500/40 bg-sky-500/10 text-sky-700"
          >
            v#{v.index}
          </Badge>
          <span className="text-muted-foreground">·</span>
          <Clock className="h-3 w-3 text-muted-foreground" />
          <span className="font-mono text-[11px]">
            {new Date(v.captured_at).toLocaleString("es-MX")}
          </span>
        </div>
        {v.captured_by && (
          <div className="mt-1.5">
            Por <span className="font-mono">{v.captured_by.slice(0, 8)}</span>
          </div>
        )}
        {isCurrent && (
          <div className="mt-2 flex items-center gap-1 text-emerald-700">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Esta es la versión activa.
          </div>
        )}
      </div>

      <div className="rounded-md border bg-card">
        <div className="border-b px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Diff (versión → actual)
        </div>
        <div className="space-y-2 px-3 py-2">
          <CountDelta
            label="Etapas"
            versionValue={versionShape.stageIds.length}
            delta={current.stageIds.length - versionShape.stageIds.length}
          />
          <CountDelta
            label="Reglas auto-enter"
            versionValue={versionShape.ruleCount}
            delta={diff.ruleDelta}
          />
          <CountDelta
            label="Documentos en catálogo"
            versionValue={versionShape.docCatalogCount}
            delta={diff.docDelta}
          />
          <CountDelta
            label="Planes con requirements"
            versionValue={versionShape.planDocCount}
            delta={diff.planDelta}
          />
          <CountDelta
            label="Mapeo Vision"
            versionValue={versionShape.visionMappingCount}
            delta={diff.visionDelta}
          />
          <CountDelta
            label="Reglas flow_mode"
            versionValue={versionShape.flowModeRuleCount}
            delta={diff.flowModeDelta}
          />
        </div>

        {(diff.added.length > 0 || diff.removed.length > 0) && (
          <div className="border-t px-3 py-2">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Etapas</div>
            {diff.removed.length > 0 && (
              <div className="mt-1 space-y-0.5">
                <div className="text-[10px] text-rose-700">
                  En esta versión, ausentes en actual:
                </div>
                <div className="flex flex-wrap gap-1">
                  {diff.removed.map((id) => (
                    <Badge
                      key={`rm-${id}`}
                      variant="outline"
                      className="border-rose-500/40 bg-rose-500/10 text-rose-700 font-mono text-[10px]"
                    >
                      − {versionShape.stageLabels[id] ?? id}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {diff.added.length > 0 && (
              <div className="mt-1.5 space-y-0.5">
                <div className="text-[10px] text-emerald-700">
                  Sólo en actual (se perderán si restauras):
                </div>
                <div className="flex flex-wrap gap-1">
                  {diff.added.map((id) => (
                    <Badge
                      key={`add-${id}`}
                      variant="outline"
                      className="border-emerald-500/40 bg-emerald-500/10 text-emerald-700 font-mono text-[10px]"
                    >
                      + {current.stageLabels[id] ?? id}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <details className="rounded-md border bg-card text-xs">
        <summary className="cursor-pointer px-3 py-2 text-muted-foreground hover:text-foreground">
          Ver JSON completo
        </summary>
        <pre className="max-h-64 overflow-auto border-t bg-muted/30 p-2 text-[10px]">
          {JSON.stringify(v.definition, null, 2)}
        </pre>
      </details>
    </div>
  );
}

export function PipelineVersionHistoryDrawer({ open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>({ mode: "list" });
  const [pendingRollback, setPendingRollback] = useState<number | null>(null);

  const versionsQuery = useQuery({
    queryKey: ["pipeline-versions"],
    queryFn: tenantsApi.listPipelineVersions,
    enabled: open,
  });
  const pipelineQuery = useQuery({
    queryKey: ["pipeline"],
    queryFn: tenantsApi.getPipeline,
    enabled: open,
  });

  const rollbackMutation = useMutation({
    mutationFn: (index: number) => tenantsApi.rollbackPipeline(index),
    onSuccess: () => {
      toast.success("Pipeline restaurado a la versión seleccionada");
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-versions"] });
      setPendingRollback(null);
      setView({ mode: "list" });
      onOpenChange(false);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "no se pudo restaurar";
      toast.error(`Rollback falló: ${msg}`);
    },
  });

  const versions = versionsQuery.data ?? [];
  const currentShape = shapeOf(
    pipelineQuery.data?.definition as Record<string, unknown> | undefined,
  );

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-[520px] sm:max-w-[520px] flex flex-col">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <History className="h-4 w-4" />
              Historial del pipeline
            </SheetTitle>
            <SheetDescription>
              <span className="text-muted-foreground/70">{versions.length} versiones · cap 10</span>
            </SheetDescription>
          </SheetHeader>
          <Separator className="my-3" />
          <ScrollArea className="flex-1">
            <div className="px-4 pb-4">
              {versionsQuery.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ) : versions.length === 0 ? (
                <div className="rounded-md border bg-muted/30 p-4 text-xs text-muted-foreground">
                  Sin versiones todavía. Guarda el pipeline al menos una vez para iniciar el
                  historial.
                </div>
              ) : view.mode === "list" ? (
                <div className="space-y-2">
                  {versions.map((v) => (
                    <VersionRow
                      key={v.index}
                      version={v}
                      onClick={() => setView({ mode: "detail", index: v.index })}
                    />
                  ))}
                </div>
              ) : (
                <VersionDetail
                  index={view.index}
                  current={currentShape}
                  onBack={() => setView({ mode: "list" })}
                  onRollback={() => setPendingRollback(view.index)}
                  rollbackPending={rollbackMutation.isPending}
                />
              )}
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>

      <Dialog open={pendingRollback !== null} onOpenChange={(o) => !o && setPendingRollback(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>¿Restaurar esta versión del pipeline?</DialogTitle>
            <DialogDescription>
              Reemplaza la configuración activa por la versión{" "}
              <span className="font-mono">v#{pendingRollback}</span>. Las conversaciones en curso
              quedan en su etapa actual; las nuevas transiciones se evaluarán contra las reglas
              restauradas. La versión actual queda registrada en el historial.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setPendingRollback(null)}>
              Cancelar
            </Button>
            <Button
              variant="default"
              onClick={() => {
                if (pendingRollback != null) {
                  rollbackMutation.mutate(pendingRollback);
                }
              }}
              disabled={rollbackMutation.isPending}
            >
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
              {rollbackMutation.isPending ? "Restaurando…" : "Restaurar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function PipelineVersionHistoryButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} className="h-8">
        <History className="mr-1.5 h-3.5 w-3.5" />
        Historial
      </Button>
      <PipelineVersionHistoryDrawer open={open} onOpenChange={setOpen} />
    </>
  );
}

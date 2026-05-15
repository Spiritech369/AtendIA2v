import { useQuery } from "@tanstack/react-query";
import { GitBranch, MinusCircle, Pencil, PlusCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type WorkflowItem, workflowsApi } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

type ComparePayload = {
  from: string;
  to: string;
  added: Array<{ node_id: string; title?: string }>;
  changed: Array<{ node_id: string; field: string; before: unknown; after: unknown }>;
  removed: Array<{ node_id: string; title?: string }>;
  risk: "low" | "medium" | "high" | string;
};

interface VersionCompareDialogProps {
  workflow: WorkflowItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fromVersion?: string;
  toVersion?: string;
}

const RISK_TONES: Record<string, { label: string; classes: string }> = {
  low: {
    label: "Riesgo bajo",
    classes: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  },
  medium: { label: "Riesgo medio", classes: "border-amber-400/40 bg-amber-500/10 text-amber-200" },
  high: { label: "Riesgo alto", classes: "border-red-400/40 bg-red-500/10 text-red-200" },
};

function nodeLabel(workflow: WorkflowItem, nodeId: string) {
  const found = workflow.definition.nodes.find((n) => n.id === nodeId);
  return found?.title || found?.type || nodeId;
}

function valuePreview(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function VersionCompareDialog({
  workflow,
  open,
  onOpenChange,
  fromVersion = `v${Math.max(1, workflow.published_version)}`,
  toVersion = `v${Math.max(1, workflow.draft_version)}`,
}: VersionCompareDialogProps) {
  const query = useQuery({
    queryKey: ["workflows", workflow.id, "compare", fromVersion, toVersion],
    queryFn: () =>
      workflowsApi.compare(workflow.id, fromVersion, toVersion) as Promise<ComparePayload>,
    enabled: open,
    staleTime: 30_000,
  });

  const data = query.data;
  const risk = data?.risk ? (RISK_TONES[data.risk] ?? RISK_TONES.medium!) : null;
  const totalChanges = data ? data.added.length + data.changed.length + data.removed.length : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-white/10 bg-[#0d1822] text-slate-100 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <GitBranch className="h-4 w-4 text-blue-400" />
            Comparar versiones — {fromVersion} → {toVersion}
          </DialogTitle>
          <DialogDescription className="text-xs text-slate-400">
            Diferencias entre la versión en producción y el borrador actual.
          </DialogDescription>
        </DialogHeader>

        {query.isLoading && (
          <div className="py-10 text-center text-xs text-slate-400">Calculando diff…</div>
        )}
        {query.isError && (
          <div className="rounded-md border border-red-400/30 bg-red-500/10 p-3 text-[11px] text-red-200">
            No se pudo cargar la comparación: {(query.error as Error).message}
          </div>
        )}

        {data && (
          <>
            {/* Risk + counts summary */}
            <div className="flex flex-wrap items-center gap-1.5">
              {risk && (
                <span
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[10px] font-medium",
                    risk.classes,
                  )}
                >
                  {risk.label}
                </span>
              )}
              <span className="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200">
                +{data.added.length} agregados
              </span>
              <span className="rounded-full border border-blue-400/30 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-200">
                ~{data.changed.length} modificados
              </span>
              <span className="rounded-full border border-red-400/30 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-200">
                -{data.removed.length} eliminados
              </span>
              <span className="ml-auto text-[10px] text-slate-400">{totalChanges} cambios</span>
            </div>

            <div className="max-h-[420px] space-y-2 overflow-auto pr-1">
              {data.added.length > 0 && (
                <DiffSection
                  title="Nodos agregados"
                  icon={PlusCircle}
                  tone="emerald"
                  rows={data.added.map((row) => ({
                    nodeId: row.node_id,
                    label: row.title || nodeLabel(workflow, row.node_id),
                    detail: "Nuevo nodo",
                  }))}
                />
              )}
              {data.changed.length > 0 && (
                <DiffSection
                  title="Nodos modificados"
                  icon={Pencil}
                  tone="blue"
                  rows={data.changed.map((row) => ({
                    nodeId: row.node_id,
                    label: nodeLabel(workflow, row.node_id),
                    detail: row.field,
                    before: valuePreview(row.before),
                    after: valuePreview(row.after),
                  }))}
                />
              )}
              {data.removed.length > 0 && (
                <DiffSection
                  title="Nodos eliminados"
                  icon={MinusCircle}
                  tone="red"
                  rows={data.removed.map((row) => ({
                    nodeId: row.node_id,
                    label: row.title || nodeLabel(workflow, row.node_id),
                    detail: "Eliminado del borrador",
                  }))}
                />
              )}
              {totalChanges === 0 && (
                <div className="rounded-md border border-white/10 bg-white/5 p-4 text-center text-xs text-slate-400">
                  No hay diferencias entre {fromVersion} y {toVersion}.
                </div>
              )}
            </div>
          </>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            className="h-8 border-white/10 bg-white/5 text-[11px] text-slate-200"
            onClick={() => onOpenChange(false)}
          >
            Cerrar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type DiffRow = { nodeId: string; label: string; detail: string; before?: string; after?: string };

function DiffSection({
  title,
  icon: Icon,
  tone,
  rows,
}: {
  title: string;
  icon: typeof PlusCircle;
  tone: "emerald" | "blue" | "red";
  rows: DiffRow[];
}) {
  const headerTones = {
    emerald: "text-emerald-300",
    blue: "text-blue-300",
    red: "text-red-300",
  } as const;
  return (
    <section className="rounded-md border border-white/10 bg-white/[0.03] p-2">
      <header
        className={cn(
          "mb-1.5 flex items-center gap-1.5 text-[11px] font-medium",
          headerTones[tone],
        )}
      >
        <Icon className="h-3 w-3" />
        {title} · {rows.length}
      </header>
      <ul className="space-y-1">
        {rows.map((row, idx) => (
          <li
            key={`${row.nodeId}-${idx}`}
            className="rounded border border-white/5 bg-black/20 px-2 py-1.5 text-[11px]"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-slate-200">{row.label}</span>
              <span className="shrink-0 font-mono text-[9px] text-slate-500">{row.nodeId}</span>
            </div>
            {row.before !== undefined && row.after !== undefined ? (
              <div className="mt-1 grid grid-cols-[60px_1fr_8px_1fr] gap-1 text-[10px]">
                <span className="text-slate-500">{row.detail}</span>
                <span
                  className="truncate rounded bg-red-500/10 px-1 text-red-200"
                  title={row.before}
                >
                  {row.before}
                </span>
                <span className="text-slate-500">→</span>
                <span
                  className="truncate rounded bg-emerald-500/10 px-1 text-emerald-200"
                  title={row.after}
                >
                  {row.after}
                </span>
              </div>
            ) : (
              <p className="mt-0.5 text-[10px] text-slate-500">{row.detail}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

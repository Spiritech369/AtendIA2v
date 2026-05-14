// A1 — Agent version history drawer.
//
// Shows every version the operator has published for an agent, lets
// them inspect the snapshot (prompt + tone + guardrails filter etc.),
// diff it against the live config, and roll back to a specific version
// after explicit confirmation.
//
// Built on top of the snapshot persistence shipped in agents_routes:
// every /publish stores a full `snapshot` on the version dict and
// /rollback restores it byte-for-byte.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock,
  History,
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
import {
  type AgentItem,
  type AgentVersion,
  type AgentVersionSnapshot,
  agentsApi,
} from "@/features/agents/api";
import { cn } from "@/lib/utils";

interface Props {
  agent: AgentItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type SelectedView = { mode: "list" } | { mode: "detail"; version: AgentVersion };

const STATUS_TONE: Record<string, string> = {
  production: "bg-emerald-500/15 text-emerald-700 border-emerald-500/40",
  validation: "bg-amber-500/15 text-amber-700 border-amber-500/40",
  testing: "bg-sky-500/15 text-sky-700 border-sky-500/40",
  draft: "bg-slate-500/15 text-slate-700 border-slate-500/40",
  paused: "bg-rose-500/15 text-rose-700 border-rose-500/40",
};

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "hace unos segundos";
  const min = Math.round(sec / 60);
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h} h`;
  const days = Math.round(h / 24);
  if (days < 30) return `hace ${days} d`;
  return d.toLocaleDateString("es-MX", { dateStyle: "medium" });
}

function fmtField(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "sí" : "no";
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.length === 0 ? "—" : value.join(", ");
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

const DIFFABLE_FIELDS: Array<{
  key: keyof AgentVersionSnapshot;
  label: string;
}> = [
  { key: "system_prompt", label: "Prompt maestro" },
  { key: "tone", label: "Tono" },
  { key: "style", label: "Estilo" },
  { key: "goal", label: "Objetivo" },
  { key: "language", label: "Idioma" },
  { key: "max_sentences", label: "Máx. oraciones" },
  { key: "behavior_mode", label: "Modo de comportamiento" },
  { key: "no_emoji", label: "Sin emoji" },
  { key: "return_to_flow", label: "Volver al flujo" },
  { key: "active_intents", label: "Intents activos" },
  { key: "role", label: "Rol" },
];

function snapshotFromAgent(agent: AgentItem): AgentVersionSnapshot {
  return {
    role: agent.role,
    behavior_mode: agent.behavior_mode,
    goal: agent.goal,
    style: agent.style,
    tone: agent.tone,
    language: agent.language,
    max_sentences: agent.max_sentences,
    no_emoji: agent.no_emoji,
    return_to_flow: agent.return_to_flow,
    system_prompt: agent.system_prompt,
    active_intents: agent.active_intents,
    knowledge_config: agent.knowledge_config,
    flow_mode_rules: agent.flow_mode_rules,
  };
}

function VersionRow({
  version,
  isCurrent,
  onClick,
}: {
  version: AgentVersion;
  isCurrent: boolean;
  onClick: () => void;
}) {
  const tone = STATUS_TONE[String(version.status)] ?? STATUS_TONE.draft;
  const hasSnapshot = Boolean(version.snapshot);
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-md border bg-card p-3 text-left transition-colors hover:bg-muted/50"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className={cn("font-mono text-[10px]", tone)}>
            {version.version}
          </Badge>
          {isCurrent && (
            <Badge variant="outline" className="text-[10px]">
              actual
            </Badge>
          )}
          {!hasSnapshot && (
            <Badge
              variant="outline"
              className="border-amber-500/40 bg-amber-500/10 text-amber-700 text-[10px]"
            >
              <AlertTriangle className="mr-1 h-3 w-3" />
              sin snapshot
            </Badge>
          )}
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">
          {formatRelative(version.created_at)}
        </span>
      </div>
      <div className="mt-1.5 text-xs text-muted-foreground">
        Por <span className="font-mono">{version.author}</span>
      </div>
      {version.reason && <div className="mt-1 text-xs">{version.reason}</div>}
    </button>
  );
}

function DiffRow({
  label,
  current,
  versionValue,
}: {
  label: string;
  current: unknown;
  versionValue: unknown;
}) {
  const changed = JSON.stringify(current) !== JSON.stringify(versionValue);
  return (
    <div className="grid grid-cols-[160px_1fr_1fr] gap-2 py-1.5 text-xs">
      <div className="text-muted-foreground">{label}</div>
      <div
        className={cn(
          "rounded bg-muted/30 px-1.5 py-1 font-mono",
          changed && "ring-1 ring-amber-500/40",
        )}
      >
        <div className="text-[9px] uppercase tracking-wide text-muted-foreground">versión</div>
        {fmtField(versionValue)}
      </div>
      <div
        className={cn(
          "rounded bg-muted/30 px-1.5 py-1 font-mono",
          changed && "ring-1 ring-emerald-500/40",
        )}
      >
        <div className="text-[9px] uppercase tracking-wide text-muted-foreground">actual</div>
        {fmtField(current)}
      </div>
    </div>
  );
}

function VersionDetail({
  version,
  liveSnapshot,
  isCurrent,
  onBack,
  onRollback,
  rollbackPending,
}: {
  version: AgentVersion;
  liveSnapshot: AgentVersionSnapshot;
  isCurrent: boolean;
  onBack: () => void;
  onRollback: () => void;
  rollbackPending: boolean;
}) {
  const snapshot = version.snapshot;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack} className="h-8 px-2">
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Volver
        </Button>
        {!isCurrent && snapshot && (
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
            className={cn(
              "font-mono text-[10px]",
              STATUS_TONE[String(version.status)] ?? STATUS_TONE.draft,
            )}
          >
            {version.version}
          </Badge>
          <span className="text-muted-foreground">·</span>
          <Clock className="h-3 w-3 text-muted-foreground" />
          <span className="font-mono text-[11px]">
            {new Date(version.created_at).toLocaleString("es-MX")}
          </span>
        </div>
        <div className="mt-1.5">
          Publicado por <span className="font-mono">{version.author}</span>
        </div>
        {version.reason && (
          <div className="mt-1 text-muted-foreground italic">{version.reason}</div>
        )}
        {isCurrent && (
          <div className="mt-2 flex items-center gap-1 text-emerald-700">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Esta es la versión en producción.
          </div>
        )}
      </div>

      {!snapshot ? (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-800">
          <div className="flex items-center gap-1.5 font-semibold">
            <AlertTriangle className="h-3.5 w-3.5" />
            Sin snapshot
          </div>
          <div className="mt-1">
            Esta versión fue publicada antes de que se persistieran snapshots completos. El
            historial existe pero no se puede restaurar el contenido exacto.
          </div>
        </div>
      ) : (
        <div className="rounded-md border bg-card">
          <div className="border-b px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Diff vs configuración actual
          </div>
          <div className="divide-y px-3 py-1">
            {DIFFABLE_FIELDS.map(({ key, label }) => (
              <DiffRow
                key={key}
                label={label}
                versionValue={snapshot[key]}
                current={liveSnapshot[key]}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function VersionHistoryDrawer({ agent, open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [view, setView] = useState<SelectedView>({ mode: "list" });
  const [pendingRollback, setPendingRollback] = useState<AgentVersion | null>(null);

  const versions = agent.versions ?? [];
  const currentId = versions[0]?.id;

  const rollbackMutation = useMutation({
    mutationFn: ({ id, version_id }: { id: string; version_id: string }) =>
      agentsApi.rollback(id, version_id),
    onSuccess: () => {
      toast.success("Rollback aplicado");
      queryClient.invalidateQueries({ queryKey: ["agents", "operations-center"] });
      setPendingRollback(null);
      setView({ mode: "list" });
      onOpenChange(false);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "no se pudo restaurar";
      toast.error(`Rollback falló: ${msg}`);
    },
  });

  const liveSnapshot = snapshotFromAgent(agent);

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-[480px] sm:max-w-[480px] flex flex-col">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <History className="h-4 w-4" />
              Historial de versiones
            </SheetTitle>
            <SheetDescription>
              <Bot className="mr-1 inline h-3 w-3" />
              {agent.name}{" "}
              <span className="text-muted-foreground/70">· {versions.length} versiones</span>
            </SheetDescription>
          </SheetHeader>
          <Separator className="my-3" />
          <ScrollArea className="flex-1">
            <div className="px-4 pb-4">
              {versions.length === 0 ? (
                <div className="rounded-md border bg-muted/30 p-4 text-xs text-muted-foreground">
                  Sin versiones todavía. Publica al menos una vez para iniciar el historial.
                </div>
              ) : view.mode === "list" ? (
                <div className="space-y-2">
                  {versions.map((v) => (
                    <VersionRow
                      key={v.id}
                      version={v}
                      isCurrent={v.id === currentId}
                      onClick={() => setView({ mode: "detail", version: v })}
                    />
                  ))}
                </div>
              ) : (
                <VersionDetail
                  version={view.version}
                  liveSnapshot={liveSnapshot}
                  isCurrent={view.version.id === currentId}
                  onBack={() => setView({ mode: "list" })}
                  onRollback={() => setPendingRollback(view.version)}
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
            <DialogTitle>¿Restaurar esta versión?</DialogTitle>
            <DialogDescription>
              Se reemplazará la configuración actual de{" "}
              <span className="font-mono">{agent.name}</span> por el snapshot de{" "}
              <span className="font-mono">{pendingRollback?.version}</span>. La versión actual queda
              guardada en el historial; puedes re-restaurarla más tarde.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setPendingRollback(null)}>
              Cancelar
            </Button>
            <Button
              variant="default"
              onClick={() => {
                if (pendingRollback) {
                  rollbackMutation.mutate({
                    id: agent.id,
                    version_id: pendingRollback.id,
                  });
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

export function VersionHistoryButton({ agent }: { agent: AgentItem }) {
  const [open, setOpen] = useState(false);
  if (!agent) return null;
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} className="h-8">
        <History className="mr-1.5 h-3.5 w-3.5" />
        Historial ({agent.versions?.length ?? 0})
      </Button>
      <VersionHistoryDrawer agent={agent} open={open} onOpenChange={setOpen} />
    </>
  );
}

// Loading skeleton for callers that want to render the trigger button
// while the agent query is in flight.
export function VersionHistoryButtonSkeleton() {
  return <Skeleton className="h-8 w-28" />;
}

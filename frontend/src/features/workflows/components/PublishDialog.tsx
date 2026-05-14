import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Rocket, ShieldAlert, Users, Workflow } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { workflowsApi, type WorkflowItem } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

const ROLLOUTS = [10, 25, 50, 100] as const;
type Rollout = (typeof ROLLOUTS)[number];

interface PublishDialogProps {
  workflow: WorkflowItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPublished?: () => void;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-MX").format(value);
}

export function PublishDialog({ workflow, open, onOpenChange, onPublished }: PublishDialogProps) {
  const [rollout, setRollout] = useState<Rollout>(100);

  const validation = workflow.validation;
  const blocked = validation.status === "blocked" || validation.critical_count > 0;
  const warnings = validation.warning_count;

  const impact = useMemo(() => {
    const deps = workflow.dependencies;
    const affectedLeads = Math.round((workflow.metrics.leads_affected_today * rollout) / 100);
    const agents = deps.filter((d) => d.type === "agent" || d.type === "agente_ia").length;
    const templates = deps.filter((d) => d.type === "template" || d.type === "plantilla").length;
    const stages = deps.filter((d) => d.type === "stage" || d.type === "etapa").length;
    const changedNodes = workflow.definition.nodes.length;
    const brokenDeps = deps.filter((d) => d.status !== "ok").length;
    return { affectedLeads, agents, templates, stages, changedNodes, brokenDeps };
  }, [workflow, rollout]);

  const publish = useMutation({
    mutationFn: () => workflowsApi.publish(workflow.id),
    onSuccess: () => {
      const note =
        rollout === 100
          ? "Cambios publicados al 100%"
          : `Cambios publicados (rollout ${rollout}% — el backend aplica 100% mientras se completa la entrega escalonada)`;
      toast.success(note);
      onOpenChange(false);
      onPublished?.();
    },
    onError: (error) =>
      toast.error("Publicación bloqueada", {
        description: error.message,
      }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl border-white/10 bg-[#0d1822] text-slate-100 sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Rocket className="h-4 w-4 text-blue-400" />
            Publicar cambios — {workflow.name}
          </DialogTitle>
          <DialogDescription className="text-xs text-slate-400">
            Borrador v{workflow.draft_version} → Producción v{workflow.published_version + 1}.
            Esta acción es auditada y no se puede deshacer automáticamente; podrás restaurar la versión anterior si surge un problema.
          </DialogDescription>
        </DialogHeader>

        {/* Validation banner */}
        <div
          className={cn(
            "flex items-start gap-2 rounded-md border p-2.5 text-[11px]",
            blocked
              ? "border-red-400/40 bg-red-500/10 text-red-200"
              : warnings > 0
                ? "border-amber-400/40 bg-amber-500/10 text-amber-200"
                : "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
          )}
        >
          {blocked ? (
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          ) : warnings > 0 ? (
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          ) : (
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          )}
          <div className="min-w-0">
            <p className="font-medium">{validation.summary || "Listo para publicar"}</p>
            <p className="text-[10px] opacity-80">
              {validation.critical_count} crítico{validation.critical_count === 1 ? "" : "s"} · {warnings} advertencia
              {warnings === 1 ? "" : "s"} · {validation.ok_count} OK
            </p>
          </div>
        </div>

        {/* Rollout selector */}
        <div>
          <p className="mb-1.5 text-[10px] uppercase text-slate-400">Rollout escalonado</p>
          <div className="grid grid-cols-4 gap-1.5">
            {ROLLOUTS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRollout(value)}
                className={cn(
                  "rounded-md border px-2 py-1.5 text-center text-xs font-medium transition",
                  rollout === value
                    ? "border-blue-400/60 bg-blue-500/15 text-blue-100"
                    : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10",
                )}
              >
                {value}%
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-slate-500">
            {rollout === 100
              ? "Despliegue total — todos los leads que coincidan con el disparador entran de inmediato."
              : `Solo el ${rollout}% de los nuevos disparos entrará al workflow las próximas 24 h. Los demás quedarán en la versión anterior.`}
          </p>
        </div>

        {/* Impact summary grid */}
        <div>
          <p className="mb-1.5 text-[10px] uppercase text-slate-400">Resumen de impacto</p>
          <div className="grid grid-cols-3 gap-1.5 text-[11px]">
            <ImpactCard
              icon={Users}
              label="Leads afectados / 24h"
              value={formatNumber(impact.affectedLeads)}
              tone="info"
            />
            <ImpactCard icon={Workflow} label="Nodos en producción" value={String(impact.changedNodes)} tone="info" />
            <ImpactCard
              icon={ShieldAlert}
              label="Dependencias rotas"
              value={String(impact.brokenDeps)}
              tone={impact.brokenDeps > 0 ? "warn" : "ok"}
            />
            <ImpactCard icon={Users} label="Agentes IA usados" value={String(impact.agents)} tone="info" />
            <ImpactCard icon={Users} label="Plantillas usadas" value={String(impact.templates)} tone="info" />
            <ImpactCard icon={Users} label="Etapas pipeline" value={String(impact.stages)} tone="info" />
          </div>
        </div>

        <DialogFooter className="gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="h-8 border-white/10 bg-white/5 text-[11px] text-slate-200"
            onClick={() => onOpenChange(false)}
          >
            Cancelar
          </Button>
          <Button
            size="sm"
            className="h-8 bg-blue-600 text-[11px] hover:bg-blue-500"
            disabled={blocked || publish.isPending}
            onClick={() => publish.mutate()}
          >
            {publish.isPending ? "Publicando…" : `Publicar (${rollout}%)`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImpactCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Users;
  label: string;
  value: string;
  tone: "ok" | "warn" | "info";
}) {
  const tones = {
    ok: "border-emerald-400/30 bg-emerald-500/5 text-emerald-200",
    warn: "border-amber-400/30 bg-amber-500/5 text-amber-200",
    info: "border-white/10 bg-white/5 text-slate-200",
  } as const;
  return (
    <div className={cn("rounded-md border p-2", tones[tone])}>
      <div className="flex items-center gap-1 text-[9px] uppercase tracking-wide opacity-70">
        <Icon className="h-3 w-3" />
        <span className="truncate">{label}</span>
      </div>
      <p className="mt-1 text-base font-semibold">{value}</p>
    </div>
  );
}

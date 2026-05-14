import { AlertTriangle, CheckCircle2, ListChecks, Sparkles, Wrench, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { WorkflowItem } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

interface NextBestFixPanelProps {
  workflow: WorkflowItem | null;
  onOpenNode?: (nodeId: string) => void;
}

type FixCard = {
  key: string;
  severity: "critical" | "warning" | "info";
  problem: string;
  cause: string;
  fix: string;
  nodeId: string | null;
  area: string;
};

const SEVERITY_STYLES: Record<FixCard["severity"], { badge: string; border: string; text: string; icon: typeof AlertTriangle }> = {
  critical: {
    badge: "border-red-400/40 bg-red-500/10 text-red-200",
    border: "border-red-400/30",
    text: "text-red-300",
    icon: AlertTriangle,
  },
  warning: {
    badge: "border-amber-400/40 bg-amber-500/10 text-amber-200",
    border: "border-amber-400/30",
    text: "text-amber-300",
    icon: AlertTriangle,
  },
  info: {
    badge: "border-blue-400/40 bg-blue-500/10 text-blue-200",
    border: "border-blue-400/30",
    text: "text-blue-300",
    icon: Sparkles,
  },
};

// Build a structured FixCard list from the workflow's validation issues
// (rich, per-node) and health.suggested_actions (free-form strings). We
// pair them positionally when possible so each issue gets a concrete fix.
function buildFixes(workflow: WorkflowItem): FixCard[] {
  const issues = workflow.validation.issues ?? [];
  const suggestions = workflow.health.suggested_actions ?? [];
  const reasons = workflow.health.reasons ?? [];
  const cards: FixCard[] = [];

  issues.forEach((issue, idx) => {
    const severity: FixCard["severity"] =
      issue.severity === "critical"
        ? "critical"
        : issue.severity === "warning"
          ? "warning"
          : "info";
    const fix = suggestions[idx] || suggestions[0] || "Abre el nodo y revisa la configuración pendiente.";
    cards.push({
      key: `issue-${idx}-${issue.code || issue.node_id || "x"}`,
      severity,
      problem: issue.message,
      cause: reasons[idx] || `Área: ${issue.area || "general"}`,
      fix,
      nodeId: issue.node_id,
      area: issue.area,
    });
  });

  // Surface suggestions that didn't pair with an issue — they still belong on the panel.
  if (suggestions.length > issues.length) {
    suggestions.slice(issues.length).forEach((suggestion, idx) => {
      cards.push({
        key: `suggestion-${idx}`,
        severity: "info",
        problem: reasons[issues.length + idx] || "Mejora recomendada",
        cause: "Detectado por el motor de salud",
        fix: suggestion,
        nodeId: null,
        area: "salud",
      });
    });
  }
  return cards;
}

export function NextBestFixPanel({ workflow, onOpenNode }: NextBestFixPanelProps) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const fixes = useMemo(() => (workflow ? buildFixes(workflow) : []), [workflow]);
  const visible = fixes.filter((fix) => !dismissed.has(fix.key));

  return (
    <section className="rounded-md border border-white/10 bg-[#0d1822]">
      <header className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <div className="flex items-center gap-1.5">
          <Wrench className="h-3.5 w-3.5 text-blue-300" />
          <h3 className="text-xs font-semibold text-slate-100">Next Best Fix</h3>
        </div>
        <span className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] text-slate-300">
          {visible.length} pendiente{visible.length === 1 ? "" : "s"}
        </span>
      </header>

      <div className="max-h-64 space-y-1.5 overflow-auto p-2">
        {!workflow && (
          <div className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-center text-[11px] text-slate-500">
            Selecciona un workflow para ver sugerencias.
          </div>
        )}
        {workflow && visible.length === 0 && (
          <div className="flex flex-col items-center gap-1.5 rounded-md border border-emerald-400/30 bg-emerald-500/5 p-3 text-center text-[11px] text-emerald-200">
            <CheckCircle2 className="h-4 w-4" />
            <p>Sin problemas detectados. Health score {workflow.health.score}/100.</p>
          </div>
        )}
        {visible.map((fix) => {
          const style = SEVERITY_STYLES[fix.severity];
          const Icon = style.icon;
          return (
            <article
              key={fix.key}
              className={cn("rounded-md border bg-white/[0.02] p-2", style.border)}
            >
              <div className="flex items-start gap-1.5">
                <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", style.text)} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-[11px] font-medium text-slate-100">{fix.problem}</p>
                    <span
                      className={cn(
                        "shrink-0 rounded-full border px-1.5 py-0 text-[9px] font-medium",
                        style.badge,
                      )}
                    >
                      {fix.severity}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    <span className="text-slate-500">Causa:</span> {fix.cause}
                  </p>
                  <p className="mt-1 rounded bg-blue-500/5 px-1.5 py-1 text-[10px] text-blue-100">
                    <span className="font-medium text-blue-300">Sugerencia:</span> {fix.fix}
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <Button
                      size="sm"
                      className="h-6 bg-blue-600 px-2 text-[10px] hover:bg-blue-500"
                      disabled={!fix.nodeId || !onOpenNode}
                      onClick={() => {
                        if (fix.nodeId && onOpenNode) {
                          onOpenNode(fix.nodeId);
                          toast.success("Abriendo nodo afectado");
                        }
                      }}
                    >
                      Aplicar
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-6 border-white/10 bg-white/5 px-2 text-[10px] text-slate-200"
                      onClick={() => {
                        toast.info("Tarea creada en backlog", {
                          description: fix.problem,
                        });
                      }}
                    >
                      <ListChecks className="mr-1 h-2.5 w-2.5" /> Crear tarea
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto h-6 px-1.5 text-[10px] text-slate-500 hover:text-slate-200"
                      onClick={() => setDismissed((prev) => new Set(prev).add(fix.key))}
                    >
                      <X className="h-2.5 w-2.5" />
                    </Button>
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

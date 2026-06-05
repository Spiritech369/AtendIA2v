import { ShieldAlert, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  asRecordArray,
  formatValue,
  type UniversalTraceRecord,
} from "@/features/turn-traces/lib/universalTrace";
import { cn } from "@/lib/utils";
import { PanelHeading } from "./DecisionTimeline";

const GUARD_CLASS: Record<string, string> = {
  passed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  warned: "border-amber-500/40 bg-amber-500/10 text-amber-700",
  blocked: "border-red-500/40 bg-red-500/10 text-red-700",
  rewrote: "border-sky-500/40 bg-sky-500/10 text-sky-700",
};

export function GuardCards({ trace }: { trace: UniversalTraceRecord }) {
  const guards = asRecordArray(trace.guards);
  if (guards.length === 0) {
    return (
      <section className="space-y-2">
        <PanelHeading title="Guards" />
        <div className="text-xs text-muted-foreground">Sin guards reportados.</div>
      </section>
    );
  }

  return (
    <section className="space-y-2" aria-label="Guard cards">
      <PanelHeading title="Guards" badge={`${guards.length}`} />
      <div className="space-y-1.5">
        {guards.map((guard) => {
          const result = String(guard.result ?? "warned");
          const Icon = result === "passed" ? ShieldCheck : ShieldAlert;
          const key = [guard.guard_id, guard.action, guard.result, guard.reason]
            .map(formatValue)
            .join(":");
          return (
            <div key={key} className="rounded-md border bg-card p-2 text-xs">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-mono font-medium">
                    <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                    {formatValue(guard.guard_id)}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    Motivo: {formatValue(guard.reason)}
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className={cn("text-[10px]", GUARD_CLASS[result] ?? GUARD_CLASS.warned)}
                >
                  {result}
                </Badge>
              </div>
              <div className="mt-1.5 grid gap-1.5 text-[11px] sm:grid-cols-2">
                <Info label="scope" value={guard.scope ?? guard.action ?? "final_message"} />
                <Info label="affected" value={guard.affected_items ?? guard.affected ?? []} />
                <Info label="evidence" value={guard.evidence_refs ?? []} />
                <Info label="next_step" value={nextStep(result, guard)} />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Info({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border bg-muted/20 px-2 py-1">
      <div className="font-mono text-[10px] text-muted-foreground">{label}</div>
      <div className="break-words">{formatValue(value, 70)}</div>
    </div>
  );
}

function nextStep(result: string, guard: Record<string, unknown>): string {
  if (result === "passed") return "continuar";
  if (result === "rewrote") return "usar la respuesta ajustada por AtendIA";
  if (result === "blocked") {
    const reason = String(guard.reason ?? "");
    if (reason.includes("quote")) return "ejecutar quote.resolve o pedir dato faltante";
    if (reason.includes("tool")) return "ejecutar la tool obligatoria";
    return "validar la evidencia antes de responder";
  }
  return "revisar antes de confirmar";
}

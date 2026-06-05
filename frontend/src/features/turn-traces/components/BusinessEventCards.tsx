import { Workflow } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  asRecordArray,
  formatValue,
  type UniversalTraceRecord,
} from "@/features/turn-traces/lib/universalTrace";
import { cn } from "@/lib/utils";
import { PanelHeading } from "./DecisionTimeline";

const EVENT_CLASS: Record<string, string> = {
  emitted: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  executed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  blocked: "border-red-500/40 bg-red-500/10 text-red-700",
  "dry-run": "border-slate-500/40 bg-slate-500/10 text-slate-700",
  dry_run: "border-slate-500/40 bg-slate-500/10 text-slate-700",
};

export function BusinessEventCards({ trace }: { trace: UniversalTraceRecord }) {
  const events: Array<Record<string, unknown> & { kind: string }> = [
    ...asRecordArray(trace.business_events).map((event) => ({ ...event, kind: "business" })),
    ...asRecordArray(trace.workflow_results).map((event) => ({ ...event, kind: "workflow" })),
  ];

  if (events.length === 0) {
    return (
      <section className="space-y-2">
        <PanelHeading title="Eventos y workflows" />
        <div className="text-xs text-muted-foreground">
          Sin eventos de negocio ni workflows ejecutados este turno.
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-2" aria-label="Business events">
      <PanelHeading title="Eventos y workflows" badge={`${events.length}`} />
      <div className="space-y-1.5">
        {events.map((event) => {
          const status = eventStatus(event);
          const key = [
            event.kind,
            event.event_type ?? event.workflow_id ?? event.name,
            status,
            event.reason,
          ]
            .map(formatValue)
            .join(":");
          return (
            <div key={key} className="rounded-md border bg-card p-2 text-xs">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-medium">
                    <Workflow className="h-3.5 w-3.5 text-muted-foreground" />
                    {formatValue(event.event_type ?? event.workflow_id ?? event.name)}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {formatValue(event.kind)} - {formatValue(event.reason)}
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className={cn("text-[10px]", EVENT_CLASS[status] ?? EVENT_CLASS["dry-run"])}
                >
                  {status}
                </Badge>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function eventStatus(event: Record<string, unknown>): string {
  const raw = String(event.status ?? event.result ?? "");
  if (raw) return raw;
  if (event.dry_run === true || event.executed === false) return "dry-run";
  if (event.blocked === true) return "blocked";
  if (event.executed === true) return "executed";
  return "emitted";
}

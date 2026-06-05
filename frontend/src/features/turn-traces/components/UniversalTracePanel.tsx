import { BrainCircuit } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  type UniversalTraceRecord,
  universalWhySummary,
} from "@/features/turn-traces/lib/universalTrace";
import { BusinessEventCards } from "./BusinessEventCards";
import { DecisionTimeline, PanelHeading } from "./DecisionTimeline";
import { GuardCards } from "./GuardCards";
import { PipelineCard } from "./PipelineCard";
import { StateWriterCards } from "./StateWriterCards";
import { ToolCards } from "./ToolCards";

export function UniversalTracePanel({ trace }: { trace: UniversalTraceRecord | null }) {
  if (!trace) {
    return (
      <section className="space-y-2" aria-label="Universal trace">
        <PanelHeading title="AtendIA audit" badge="metadata_missing" />
        <div className="rounded-md border bg-muted/20 p-2 text-xs text-muted-foreground">
          Este turno no trae universal_turn_trace. Se conserva la vista legacy y el raw JSON.
        </div>
      </section>
    );
  }

  const audit = trace.audit ?? {};
  const safeMode = audit.safe_mode === true;

  return (
    <section className="space-y-3" aria-label="Universal trace">
      <div className="rounded-md border bg-card p-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            <BrainCircuit className="h-3.5 w-3.5 text-muted-foreground" />
            Por que respondio asi
          </div>
          <div className="flex flex-wrap gap-1">
            <Badge variant="outline" className="font-mono text-[10px]">
              {trace.domain ?? "domain_unknown"}
            </Badge>
            {safeMode && (
              <Badge
                variant="outline"
                className="border-amber-500/40 bg-amber-500/10 text-[10px] text-amber-700"
              >
                safe_mode
              </Badge>
            )}
          </div>
        </div>
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {universalWhySummary(trace).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>

      <DecisionTimeline trace={trace} />
      <ToolCards trace={trace} />
      <StateWriterCards trace={trace} />
      <GuardCards trace={trace} />
      <PipelineCard trace={trace} />
      <BusinessEventCards trace={trace} />
    </section>
  );
}

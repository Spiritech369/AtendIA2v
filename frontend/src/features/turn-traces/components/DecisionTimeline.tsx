import {
  Bot,
  CheckCircle2,
  Eye,
  GitBranch,
  MessageSquareText,
  ShieldCheck,
  Workflow,
  Wrench,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  asRecord,
  asRecordArray,
  formatValue,
  type UniversalTraceRecord,
} from "@/features/turn-traces/lib/universalTrace";

export function DecisionTimeline({ trace }: { trace: UniversalTraceRecord }) {
  const input = asRecord(trace.input);
  const understanding = asRecord(trace.gpt_understanding);
  const proposed = asRecord(trace.gpt_proposed);
  const validation = asRecord(trace.atendia_validation);
  const stateWriter = asRecord(validation?.state_writer);
  const lifecycle = asRecord(trace.lifecycle);
  const mandatory = asRecordArray(trace.mandatory_tool_decisions);
  const tools = asRecordArray(trace.tool_results);
  const guards = asRecordArray(trace.guards);
  const businessEvents = asRecordArray(trace.business_events);
  const workflows = asRecordArray(trace.workflow_results);
  const finalOutput = asRecord(trace.final_output);
  const proposedState = asRecordArray(proposed?.state_changes);
  const proposedTools = asRecordArray(proposed?.required_tools);

  const steps = [
    {
      icon: MessageSquareText,
      title: "Cliente envio mensaje",
      body: formatValue(input?.inbound_text ?? "sin texto entrante", 120),
    },
    {
      icon: Bot,
      title: "GPT entendio intencion",
      body: formatValue(
        understanding?.customer_goal ??
          understanding?.next_best_action ??
          understanding?.response_plan,
        120,
      ),
    },
    {
      icon: GitBranch,
      title: "GPT propuso cambios",
      body: `${proposedState.length} campo(s), ${proposedTools.length} tool(s) requerida(s).`,
    },
    {
      icon: ShieldCheck,
      title: "AtendIA exigio tools obligatorias",
      body:
        mandatory.length > 0
          ? `${mandatory.length} decision(es) de tool obligatoria.`
          : "Sin tools obligatorias para este turno.",
    },
    {
      icon: Wrench,
      title: "Tools devolvieron datos",
      body:
        tools.length > 0 ? `${tools.length} resultado(s) estructurado(s).` : "Sin tool results.",
    },
    {
      icon: CheckCircle2,
      title: "StateWriter valido estado",
      body: `accepted ${asRecordArray(stateWriter?.accepted).length}, blocked ${
        asRecordArray(stateWriter?.blocked).length
      }, needs_review ${asRecordArray(stateWriter?.needs_review).length}.`,
    },
    {
      icon: ShieldCheck,
      title: "Guards evaluaron salida",
      body: guards.length > 0 ? guardSummary(guards) : "Sin guards reportados.",
    },
    {
      icon: GitBranch,
      title: "Pipeline/lifecycle",
      body:
        lifecycle?.stage_after || lifecycle?.stage_proposed
          ? `${formatValue(lifecycle.stage_before)} -> ${formatValue(
              lifecycle.stage_after ?? lifecycle.stage_proposed,
            )}`
          : "sin cambio de etapa",
    },
    {
      icon: Workflow,
      title: "Workflows y eventos",
      body: `${businessEvents.length} evento(s), ${workflows.length} workflow result(s).`,
    },
    {
      icon: Eye,
      title: "Cliente vio respuesta final",
      body: formatValue(finalOutput?.final_message, 140),
    },
  ];

  return (
    <section className="space-y-2" aria-label="Decision timeline">
      <PanelHeading title="Decision timeline" badge={trace.trace_version ?? "1.0"} />
      <ol className="space-y-1.5">
        {steps.map((step, index) => (
          <li key={step.title} className="flex gap-2 rounded-md border bg-card p-2 text-xs">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-muted text-muted-foreground">
              <step.icon className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[10px] text-muted-foreground">#{index + 1}</span>
                <span className="font-medium">{step.title}</span>
              </div>
              <div className="mt-0.5 break-words text-[11px] text-muted-foreground">
                {step.body}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function PanelHeading({ title, badge }: { title: string; badge?: string | null }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {badge && (
        <Badge variant="outline" className="font-mono text-[10px]">
          {badge}
        </Badge>
      )}
    </div>
  );
}

function guardSummary(guards: Array<Record<string, unknown>>): string {
  const counts = guards.reduce<Record<string, number>>((acc, guard) => {
    const result = String(guard.result ?? "unknown");
    acc[result] = (acc[result] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([result, count]) => `${result} ${count}`)
    .join(", ");
}

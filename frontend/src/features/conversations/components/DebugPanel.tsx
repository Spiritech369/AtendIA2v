// Per-turn inspector rendered as a side panel next to the chat. Reads
// turn_traces.id, narrates the turn as a vertical story, and surfaces
// secondary panels (entities, knowledge, state diff, latency, cost,
// fact pack, raw JSON). Vertical-agnostic: zero hardcoded vocabulary.
import { useQuery } from "@tanstack/react-query";
import { Cpu, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { turnTracesApi } from "@/features/turn-traces/api";
import { FlowModeBadge } from "@/features/turn-traces/components/FlowModeBadge";
import {
  AgentBadge,
  AnomalyChips,
  CostBreakdown,
  EntityPills,
  ErrorBanner,
  FactPackCard,
  KnowledgePanel,
  LatencyStackedBar,
  RawJsonFooter,
  RulesEvaluatedPanel,
  StateDiff,
} from "@/features/turn-traces/components/TurnPanels";
import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import { buildTurnStory } from "@/features/turn-traces/lib/turnStory";

interface Props {
  traceId: string;
  onClose: () => void;
}

export function DebugPanel({ traceId, onClose }: Props) {
  const { data: t, isLoading } = useQuery({
    queryKey: ["turn-trace", traceId],
    queryFn: () => turnTracesApi.getOne(traceId),
  });

  if (isLoading || !t) {
    return (
      <PanelShell onClose={onClose} title="Cargando…">
        <div className="space-y-3 p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </PanelShell>
    );
  }

  const createdAt = new Date(t.created_at);
  const createdAtLabel = createdAt.toLocaleString("es-MX", {
    dateStyle: "short",
    timeStyle: "short",
  });

  return (
    <PanelShell
      onClose={onClose}
      title={`Turno ${t.turn_number}`}
      subtitle={createdAtLabel}
      flowMode={t.flow_mode}
    >
      <ScrollArea className="flex-1">
        <div className="flex flex-col gap-4 p-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <AgentBadge trace={t} />
            <AnomalyChips trace={t} />
          </div>
          <ErrorBanner trace={t} />

          {/* The story — the operator-facing narrative. */}
          <TurnStoryView steps={buildTurnStory(t)} />

          <Separator />
          <EntityPills trace={t} />
          <Separator />
          <KnowledgePanel trace={t} />
          <Separator />
          <StateDiff trace={t} />
          <Separator />
          <RulesEvaluatedPanel trace={t} />
          <Separator />
          <LatencyStackedBar trace={t} />
          <CostBreakdown trace={t} />
          <Separator />
          <FactPackCard trace={t} />
          <RawJsonFooter trace={t} />
        </div>
      </ScrollArea>
    </PanelShell>
  );
}

function PanelShell({
  onClose,
  title,
  subtitle,
  flowMode,
  children,
}: {
  onClose: () => void;
  title: string;
  subtitle?: string;
  flowMode?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full w-[420px] shrink-0 flex-col overflow-hidden rounded-lg border bg-background shadow-lg">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Cpu className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-sm font-semibold">{title}</span>
              {flowMode && <FlowModeBadge mode={flowMode} />}
            </div>
            {subtitle && (
              <div className="truncate text-[10px] text-muted-foreground">{subtitle}</div>
            )}
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      {children}
    </div>
  );
}

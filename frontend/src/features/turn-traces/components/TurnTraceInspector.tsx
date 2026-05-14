// Modal version of DebugPanel used by the turn-trace admin list. Same
// content as the side panel but presented as a dialog. Kept in sync
// with DebugPanel so the operator and admin views never diverge.
import { useQuery } from "@tanstack/react-query";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { turnTracesApi } from "@/features/turn-traces/api";

import { buildTurnStory } from "../lib/turnStory";
import { FlowModeBadge } from "./FlowModeBadge";
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
} from "./TurnPanels";
import { TurnStoryView } from "./TurnStoryView";

export function TurnTraceInspector({
  traceId,
  open,
  onClose,
}: {
  traceId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["turn-trace", traceId],
    queryFn: () => (traceId ? turnTracesApi.getOne(traceId) : Promise.reject()),
    enabled: !!traceId && open,
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Turno {query.data?.turn_number ?? "…"}
            {query.data?.flow_mode && <FlowModeBadge mode={query.data.flow_mode} />}
          </DialogTitle>
        </DialogHeader>
        {query.isLoading || !query.data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-1.5">
              <AgentBadge trace={query.data} />
              <AnomalyChips trace={query.data} />
            </div>
            <ErrorBanner trace={query.data} />
            <TurnStoryView steps={buildTurnStory(query.data)} />
            <Separator />
            <EntityPills trace={query.data} />
            <Separator />
            <KnowledgePanel trace={query.data} />
            <Separator />
            <StateDiff trace={query.data} />
            <Separator />
            <RulesEvaluatedPanel trace={query.data} />
            <Separator />
            <LatencyStackedBar trace={query.data} />
            <CostBreakdown trace={query.data} />
            <Separator />
            <FactPackCard trace={query.data} />
            <RawJsonFooter trace={query.data} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

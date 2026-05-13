import { useQuery } from "@tanstack/react-query";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { turnTracesApi } from "@/features/turn-traces/api";

import { buildTurnStory } from "../lib/turnStory";
import { FlowModeBadge } from "./FlowModeBadge";
import { TurnStoryView } from "./TurnStoryView";
import {
  ComposerSection,
  ErrorsSection,
  NluSection,
  OverviewSection,
  PipelineSection,
  StateSection,
  ToolCallsSection,
} from "./TurnTraceSections";

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
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Turn {query.data?.turn_number ?? "…"}
            {query.data?.flow_mode && <FlowModeBadge mode={query.data.flow_mode} />}
          </DialogTitle>
        </DialogHeader>
        {query.isLoading || !query.data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <Tabs defaultValue="story">
            <TabsList>
              <TabsTrigger value="story">Resumen</TabsTrigger>
              <TabsTrigger value="detail">Detalle técnico</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>
            <TabsContent value="story" className="space-y-3">
              <TurnStoryView steps={buildTurnStory(query.data)} />
            </TabsContent>
            <TabsContent value="detail" className="space-y-0">
              <OverviewSection trace={query.data} />
              <Separator />
              <PipelineSection trace={query.data} />
              <Separator />
              <NluSection trace={query.data} />
              <Separator />
              <ComposerSection trace={query.data} />
              {query.data.tool_calls.length > 0 && (
                <>
                  <Separator />
                  <ToolCallsSection trace={query.data} />
                </>
              )}
              <Separator />
              <StateSection trace={query.data} />
              <Separator />
              <ErrorsSection trace={query.data} />
            </TabsContent>
            <TabsContent value="raw">
              <pre className="overflow-auto rounded bg-muted p-2 text-xs">
                {JSON.stringify(query.data, null, 2)}
              </pre>
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

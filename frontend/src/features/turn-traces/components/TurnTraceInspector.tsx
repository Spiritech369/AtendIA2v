import { useQuery } from "@tanstack/react-query";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { turnTracesApi } from "@/features/turn-traces/api";

function JsonBlock({ value }: { value: unknown }) {
  if (value == null) {
    return <div className="text-xs text-muted-foreground">(vacío)</div>;
  }
  return (
    <pre className="overflow-auto rounded bg-muted p-2 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

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
      <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Turn {query.data?.turn_number ?? "…"}
            {query.data?.flow_mode && ` · ${query.data.flow_mode}`}
          </DialogTitle>
        </DialogHeader>
        {query.isLoading || !query.data ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <Tabs defaultValue="nlu">
            <TabsList>
              <TabsTrigger value="nlu">NLU</TabsTrigger>
              <TabsTrigger value="composer">Composer</TabsTrigger>
              <TabsTrigger value="state">Estado</TabsTrigger>
              <TabsTrigger value="outbound">Outbound</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>
            <TabsContent value="nlu" className="space-y-3">
              <div>
                <div className="text-xs text-muted-foreground">Inbound</div>
                <div className="rounded-md bg-muted p-2 text-sm italic">
                  {query.data.inbound_text ?? "(sin texto)"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">NLU input</div>
                <JsonBlock value={query.data.nlu_input} />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">NLU output</div>
                <JsonBlock value={query.data.nlu_output} />
              </div>
            </TabsContent>
            <TabsContent value="composer" className="space-y-3">
              <div className="text-xs text-muted-foreground">
                {query.data.composer_model ?? "(sin composer)"}
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Composer input</div>
                <JsonBlock value={query.data.composer_input} />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Composer output</div>
                <JsonBlock value={query.data.composer_output} />
              </div>
            </TabsContent>
            <TabsContent value="state" className="space-y-3">
              <div>
                <div className="text-xs text-muted-foreground">Antes</div>
                <JsonBlock value={query.data.state_before} />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Después</div>
                <JsonBlock value={query.data.state_after} />
              </div>
              {query.data.stage_transition && (
                <div className="text-sm">
                  <span className="text-xs text-muted-foreground">Transición: </span>
                  {query.data.stage_transition}
                </div>
              )}
            </TabsContent>
            <TabsContent value="outbound">
              <JsonBlock value={query.data.outbound_messages} />
            </TabsContent>
            <TabsContent value="raw">
              <JsonBlock value={query.data} />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, ShieldAlert } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversation } from "@/features/conversations/hooks/useConversations";
import { turnTracesApi } from "@/features/turn-traces/api";
import { ChatWindow } from "./ChatWindow";
import { ContactPanel } from "./ContactPanel";
import { DebugPanel } from "./DebugPanel";

export function ConversationDetail({ conversationId }: { conversationId: string }) {
  const conv = useConversation(conversationId);
  const [debugTraceId, setDebugTraceId] = useState<string | null>(null);
  const [debugMessageId, setDebugMessageId] = useState<string | null>(null);

  const traces = useQuery({
    queryKey: ["turn-traces", conversationId],
    queryFn: () => turnTracesApi.list(conversationId),
    enabled: !!conversationId,
  });

  const messageToTrace = useMemo(() => {
    const map = new Map<string, string>();
    if (!traces.data?.items) return map;
    for (const t of traces.data.items) {
      if (t.inbound_message_id) {
        map.set(t.inbound_message_id, t.id);
      }
    }
    return map;
  }, [traces.data]);

  const handleDebug = useCallback(
    (messageId: string) => {
      const traceId = messageToTrace.get(messageId);
      if (traceId) {
        setDebugTraceId((prev) => (prev === traceId ? null : traceId));
        setDebugMessageId((prev) => (prev === messageId ? null : messageId));
      }
    },
    [messageToTrace],
  );

  if (conv.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-12 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (conv.isError || !conv.data) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">
          Conversación no encontrada.
        </CardContent>
      </Card>
    );
  }

  const c = conv.data;

  return (
    <div className="flex h-full gap-4">
      <Card className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" asChild>
              <Link to="/">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <div>
              <CardTitle className="text-base">{c.customer_name ?? "(sin nombre)"}</CardTitle>
              <div className="text-xs text-muted-foreground">{c.customer_phone}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-1">
            {c.has_pending_handoff && (
              <Badge variant="destructive" className="gap-1">
                <ShieldAlert className="h-3 w-3" /> Handoff
              </Badge>
            )}
            {c.bot_paused && <Badge variant="secondary">Bot pausado</Badge>}
            <Badge variant="outline">{c.current_stage}</Badge>
          </div>
        </CardHeader>

        <ChatWindow
          conversationId={conversationId}
          botPaused={c.bot_paused}
          messageToTrace={messageToTrace}
          debugMessageId={debugMessageId}
          onDebug={handleDebug}
        />
      </Card>

      {debugTraceId ? (
        <DebugPanel
          traceId={debugTraceId}
          onClose={() => {
            setDebugTraceId(null);
            setDebugMessageId(null);
          }}
        />
      ) : (
        <ContactPanel customerId={c.customer_id} />
      )}
    </div>
  );
}

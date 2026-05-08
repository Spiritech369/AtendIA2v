import { Link } from "@tanstack/react-router";
import { ArrowLeft, ShieldAlert } from "lucide-react";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversationStream } from "@/features/conversations/hooks/useConversationStream";
import { useConversation, useMessages } from "@/features/conversations/hooks/useConversations";
import { ContactPanel } from "./ContactPanel";
import { InterventionComposer } from "./InterventionComposer";
import { MessageBubble } from "./MessageBubble";

export function ConversationDetail({ conversationId }: { conversationId: string }) {
  const conv = useConversation(conversationId);
  const msgs = useMessages(conversationId);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useConversationStream(conversationId, () => {
    // Live-scroll to bottom on inbound. Defer one tick so the new
    // message lands in the DOM first.
    setTimeout(() => {
      scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }, 50);
  });

  // Initial scroll-to-bottom (top of the reverse-ordered list).
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, []);

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
  const messages = msgs.data?.pages.flatMap((p) => p.items) ?? [];

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
        <Separator />
        <ScrollArea className="flex-1" ref={scrollRef}>
          <div className="flex flex-col-reverse gap-2 p-4">
            {messages.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Sin mensajes en esta conversación.
              </div>
            ) : (
              messages.map((m) => <MessageBubble key={m.id} message={m} />)
            )}
            {msgs.hasNextPage && (
              <div className="flex justify-center pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => msgs.fetchNextPage()}
                  disabled={msgs.isFetchingNextPage}
                >
                  {msgs.isFetchingNextPage ? "Cargando…" : "Más mensajes"}
                </Button>
              </div>
            )}
          </div>
        </ScrollArea>
        <InterventionComposer conversationId={conversationId} botPaused={c.bot_paused} />
      </Card>

      <ContactPanel customerId={c.customer_id} />
    </div>
  );
}

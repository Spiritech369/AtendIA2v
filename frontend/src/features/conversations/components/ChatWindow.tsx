import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { conversationsApi } from "@/features/conversations/api";
import { useConversationStream } from "@/features/conversations/hooks/useConversationStream";
import { useMessages } from "@/features/conversations/hooks/useConversations";
import { InterventionComposer } from "./InterventionComposer";
import { MessageBubble } from "./MessageBubble";

interface Props {
  conversationId: string;
  botPaused: boolean;
  messageToTrace: Map<string, string>;
  debugMessageId: string | null;
  onDebug: (messageId: string) => void;
}

function messageTime(message: { sent_at: string | null; created_at: string }): number {
  const raw = message.sent_at ?? message.created_at;
  const parsed = new Date(raw).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function directionOrder(direction: string): number {
  if (direction === "inbound") return 0;
  if (direction === "system") return 1;
  return 2;
}

export function ChatWindow({
  conversationId,
  botPaused,
  messageToTrace,
  debugMessageId,
  onDebug,
}: Props) {
  const msgs = useMessages(conversationId);
  const queryClient = useQueryClient();
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = (behavior: ScrollBehavior = "auto") => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior,
    });
  };

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });

  const editMutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      conversationsApi.editMessage(conversationId, id, text),
    onSuccess: () => {
      invalidate();
      toast.success("Mensaje editado");
    },
    onError: (e: Error) => toast.error("No se pudo editar", { description: e.message }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => conversationsApi.deleteMessage(conversationId, id),
    onSuccess: () => {
      invalidate();
      toast.success("Mensaje eliminado");
    },
    onError: (e: Error) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  useConversationStream(conversationId, () => {
    setTimeout(() => scrollToBottom("smooth"), 50);
  });

  const messages = useMemo(
    () =>
      (msgs.data?.pages.flatMap((p) => p.items) ?? [])
        .slice()
        .sort((a, b) => {
          const timeDelta = messageTime(a) - messageTime(b);
          if (timeDelta !== 0) return timeDelta;
          const directionDelta = directionOrder(a.direction) - directionOrder(b.direction);
          if (directionDelta !== 0) return directionDelta;
          return a.id.localeCompare(b.id);
        }),
    [msgs.data],
  );

  useEffect(() => {
    scrollToBottom();
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages.length]);

  return (
    <>
      <ScrollArea className="flex-1" ref={scrollRef}>
        <div className="flex flex-col gap-2 p-4">
          {msgs.hasNextPage && (
            <div className="flex justify-center pb-2">
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
          {messages.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Sin mensajes en esta conversación.
            </div>
          ) : (
            messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                hasTrace={messageToTrace.has(m.id)}
                isSelected={m.id === debugMessageId}
                onDebug={onDebug}
                onEdit={
                  m.direction === "system"
                    ? undefined
                    : (id, text) => editMutation.mutate({ id, text })
                }
                onDelete={
                  m.direction === "system"
                    ? undefined
                    : (id) => {
                        if (window.confirm("¿Eliminar este mensaje?")) {
                          deleteMutation.mutate(id);
                        }
                      }
                }
              />
            ))
          )}
        </div>
      </ScrollArea>
      <Separator />
      <InterventionComposer conversationId={conversationId} botPaused={botPaused} />
    </>
  );
}

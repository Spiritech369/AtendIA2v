import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
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
    setTimeout(() => {
      scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }, 50);
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, []);

  const messages = msgs.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <ScrollArea className="flex-1" ref={scrollRef}>
        <div className="flex flex-col-reverse gap-2 p-4">
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
      <Separator />
      <InterventionComposer conversationId={conversationId} botPaused={botPaused} />
    </>
  );
}

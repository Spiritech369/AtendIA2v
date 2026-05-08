import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Hand, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api-client";

interface Props {
  conversationId: string;
  botPaused: boolean;
}

/**
 * Operator-takeover composer (Phase 4 T27).
 *
 * Sits at the bottom of ConversationDetail.
 * - When bot_paused === false: shows a "Tomar control" button. Click sends
 *   the first message (which sets bot_paused=True server-side).
 * - When bot_paused === true: shows the textarea + "Enviar" + "Devolver
 *   al bot" toggle. Each Enviar POSTs to /intervene; the bot stays paused
 *   until "Devolver al bot" calls /resume-bot.
 */
export function InterventionComposer({ conversationId, botPaused }: Props) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [composing, setComposing] = useState(false);

  const intervene = useMutation({
    mutationFn: async (message: string) => {
      await api.post(`/conversations/${conversationId}/intervene`, { text: message });
    },
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
      void qc.invalidateQueries({ queryKey: ["messages", conversationId] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error("Error al enviar", { description: e.message }),
  });

  const resume = useMutation({
    mutationFn: async () => {
      await api.post(`/conversations/${conversationId}/resume-bot`);
    },
    onSuccess: () => {
      toast.success("Bot reanudado");
      setComposing(false);
      void qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
    },
    onError: (e) => toast.error("Error al reanudar", { description: e.message }),
  });

  const send = () => {
    const t = text.trim();
    if (!t) return;
    intervene.mutate(t);
  };

  // Idle state: bot driving, operator hasn't started composing.
  if (!botPaused && !composing) {
    return (
      <div className="border-t p-3">
        <Button variant="outline" size="sm" onClick={() => setComposing(true)}>
          <Hand className="mr-2 h-4 w-4" /> Tomar control
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2 border-t p-3">
      <Textarea
        placeholder="Escribe la respuesta al cliente…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            send();
          }
        }}
      />
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            if (botPaused) {
              resume.mutate();
            } else {
              setComposing(false);
            }
          }}
          disabled={resume.isPending}
        >
          <Bot className="mr-2 h-4 w-4" />
          {botPaused ? "Devolver al bot" : "Cancelar"}
        </Button>
        <Button onClick={send} disabled={!text.trim() || intervene.isPending} size="sm">
          <Send className="mr-2 h-4 w-4" />
          {intervene.isPending ? "Enviando…" : "Enviar"}
        </Button>
      </div>
    </div>
  );
}

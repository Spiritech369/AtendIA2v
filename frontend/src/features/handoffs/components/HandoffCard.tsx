import { Link } from "@tanstack/react-router";
import { CheckCircle2, MessageCircle, UserCheck } from "lucide-react";

import { DemoBadge } from "@/components/DemoBadge";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import type { HandoffItem } from "@/features/handoffs/api";
import { useAssignHandoff, useResolveHandoff } from "@/features/handoffs/hooks/useHandoffs";
import { useAuthStore } from "@/stores/auth";

function ago(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60_000);
  if (m < 1) return "ahora";
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export function HandoffCard({ handoff }: { handoff: HandoffItem }) {
  const userId = useAuthStore((s) => s.user?.id);
  const assign = useAssignHandoff();
  const resolve = useResolveHandoff();
  const [note, setNote] = useState("");
  const [showResolve, setShowResolve] = useState(false);

  // The Phase 3c.2 HandoffSummary payload shape — defensive reads.
  const p = handoff.payload ?? {};
  const customer = (p["customer"] as string | undefined) ?? null;
  const reasonCode = (p["reason_code"] as string | undefined) ?? null;
  const lastInbound = (p["last_inbound"] as string | undefined) ?? null;
  const suggestedNextAction = (p["suggested_next_action"] as string | undefined) ?? null;
  const docsRecibidos = (p["docs_recibidos"] as string[] | undefined) ?? [];
  const docsPendientes = (p["docs_pendientes"] as string[] | undefined) ?? [];
  const isMock = (p["source"] as string | undefined) === "mock";

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0 py-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">
              {customer ?? "(cliente sin nombre)"}
              {isMock && <DemoBadge className="ml-1.5 inline-block" />}
            </CardTitle>
            {reasonCode && <Badge variant="outline">{reasonCode}</Badge>}
            <Badge
              variant={
                handoff.status === "open"
                  ? "destructive"
                  : handoff.status === "assigned"
                    ? "default"
                    : "secondary"
              }
            >
              {handoff.status}
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground">
            Hace {ago(handoff.requested_at)} · {handoff.reason}
          </div>
        </div>
        <Link
          to="/conversations/$conversationId"
          params={{ conversationId: handoff.conversation_id }}
        >
          <Button variant="ghost" size="sm" className="gap-1">
            <MessageCircle className="h-4 w-4" /> Conversación
          </Button>
        </Link>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {lastInbound && (
          <div className="rounded-md bg-muted p-3">
            <div className="text-xs text-muted-foreground">Último inbound</div>
            <div className="mt-1 italic">"{lastInbound}"</div>
          </div>
        )}
        {suggestedNextAction && (
          <div>
            <div className="text-xs text-muted-foreground">Sugerencia</div>
            <div>{suggestedNextAction}</div>
          </div>
        )}
        {(docsRecibidos.length > 0 || docsPendientes.length > 0) && (
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <div className="font-medium text-muted-foreground">Recibidos</div>
              <ul className="list-disc pl-4">
                {docsRecibidos.length === 0 ? (
                  <li className="list-none italic text-muted-foreground">ninguno</li>
                ) : (
                  docsRecibidos.map((d) => <li key={d}>{d}</li>)
                )}
              </ul>
            </div>
            <div>
              <div className="font-medium text-muted-foreground">Pendientes</div>
              <ul className="list-disc pl-4">
                {docsPendientes.length === 0 ? (
                  <li className="list-none italic text-muted-foreground">ninguno</li>
                ) : (
                  docsPendientes.map((d) => <li key={d}>{d}</li>)
                )}
              </ul>
            </div>
          </div>
        )}
        {showResolve && (
          <Textarea
            placeholder="Nota de resolución (opcional)…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
          />
        )}
        {handoff.status !== "resolved" && (
          <div className="flex flex-wrap gap-2">
            {handoff.status === "open" && userId && (
              <Button
                size="sm"
                variant="default"
                onClick={() =>
                  assign.mutate(
                    { id: handoff.id, user_id: userId },
                    {
                      onSuccess: () => toast.success("Handoff asignado"),
                      onError: (e) => toast.error("Error al asignar", { description: e.message }),
                    },
                  )
                }
                disabled={assign.isPending}
              >
                <UserCheck className="mr-1 h-4 w-4" /> Tomar
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (!showResolve) {
                  setShowResolve(true);
                  return;
                }
                resolve.mutate(
                  { id: handoff.id, note: note || undefined },
                  {
                    onSuccess: () => {
                      toast.success("Handoff resuelto");
                      setShowResolve(false);
                      setNote("");
                    },
                    onError: (e) => toast.error("Error al resolver", { description: e.message }),
                  },
                );
              }}
              disabled={resolve.isPending}
            >
              <CheckCircle2 className="mr-1 h-4 w-4" />
              {showResolve ? "Confirmar" : "Resolver"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

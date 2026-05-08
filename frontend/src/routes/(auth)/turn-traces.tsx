import { createFileRoute, useSearch } from "@tanstack/react-router";
import { z } from "zod";

import { Card, CardContent } from "@/components/ui/card";
import { TurnTraceList } from "@/features/turn-traces/components/TurnTraceList";

const searchSchema = z.object({
  conversation_id: z.string().uuid().optional(),
});

export const Route = createFileRoute("/(auth)/turn-traces")({
  validateSearch: searchSchema,
  component: TurnTracesPage,
});

function TurnTracesPage() {
  const { conversation_id } = useSearch({ from: "/(auth)/turn-traces" });

  if (!conversation_id) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          Pasa <code>?conversation_id=&lt;uuid&gt;</code> en la URL, o llega aquí desde una
          conversación. (UI cross-conversation aterriza en T56.)
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Debug de turnos</h1>
      <TurnTraceList conversationId={conversation_id} />
    </div>
  );
}

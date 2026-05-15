import { createFileRoute, Link, useSearch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TurnTraceList } from "@/features/turn-traces/components/TurnTraceList";
import { turnTracesApi } from "@/features/turn-traces/api";

const searchSchema = z.object({
  conversation_id: z.string().uuid().optional(),
  flow_mode: z.string().optional(),
});

export const Route = createFileRoute("/(auth)/turn-traces")({
  validateSearch: searchSchema,
  component: TurnTracesPage,
});

const FLOW_MODES = ["PLAN", "SALES", "DOC", "OBSTACLE", "RETENTION", "SUPPORT"] as const;

function TurnTracesPage() {
  const { conversation_id, flow_mode } = useSearch({ from: "/(auth)/turn-traces" });

  // Per-conversation view (legacy entry point) — unchanged.
  if (conversation_id) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight">Debug de turnos</h1>
        <TurnTraceList conversationId={conversation_id} />
      </div>
    );
  }

  return <CrossConversationExplorer initialFlowMode={flow_mode} />;
}

// Sprint C.2 / T56 — cross-conversation explorer. Lists the tenant's
// most-recent turn_traces across every conversation, with an optional
// flow_mode filter. Clicking a row deep-links to the conversation-scoped
// view above.
function CrossConversationExplorer({
  initialFlowMode,
}: {
  initialFlowMode?: string;
}) {
  const [flowMode, setFlowMode] = useState<string>(initialFlowMode ?? "");
  const recent = useQuery({
    queryKey: ["turn-traces", "recent", flowMode],
    queryFn: () =>
      turnTracesApi.listRecent({
        flow_mode: flowMode || undefined,
        limit: 100,
      }),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Debug de turnos</h1>
        <select
          value={flowMode}
          onChange={(e) => setFlowMode(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          aria-label="Filtrar por flow_mode"
        >
          <option value="">Todos los modos</option>
          {FLOW_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            Actividad reciente del runner
            {flowMode ? ` — ${flowMode}` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {recent.isLoading ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">Cargando…</div>
          ) : recent.error ? (
            <div className="px-4 py-6 text-sm text-destructive">
              No se pudo cargar la actividad reciente.
            </div>
          ) : (recent.data?.items ?? []).length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">
              No hay turnos registrados todavía. El bot empieza a llenar esta
              tabla en cuanto responde su primera conversación.
            </div>
          ) : (
            <ul className="divide-y">
              {(recent.data?.items ?? []).map((row) => (
                <li key={row.id} className="px-4 py-3">
                  <Link
                    to="/turn-traces"
                    search={{ conversation_id: row.conversation_id }}
                    className="flex items-baseline justify-between gap-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {row.inbound_preview ?? "(sin texto)"}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        turn #{row.turn_number} ·{" "}
                        {row.composer_model ?? "no-llm"} ·{" "}
                        {new Date(row.created_at).toLocaleString("es-MX")}
                      </p>
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-2">
                      {row.flow_mode && (
                        <Badge variant="secondary" className="text-[10px]">
                          {row.flow_mode}
                        </Badge>
                      )}
                      {row.bot_paused && (
                        <Badge variant="outline" className="text-[10px]">
                          paused
                        </Badge>
                      )}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

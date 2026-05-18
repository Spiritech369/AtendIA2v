import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { turnTracesApi } from "@/features/turn-traces/api";
import { TurnTraceList } from "@/features/turn-traces/components/TurnTraceList";

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

  if (conversation_id) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Debug de turnos</h1>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              conversation_id: {conversation_id}
            </p>
          </div>
          <Link
            to="/turn-traces"
            className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-muted"
          >
            Ver todas
          </Link>
        </div>
        <TurnTraceList conversationId={conversation_id} />
      </div>
    );
  }

  return <CrossConversationExplorer initialFlowMode={flow_mode} />;
}

function CrossConversationExplorer({ initialFlowMode }: { initialFlowMode?: string }) {
  const [flowMode, setFlowMode] = useState<string>(initialFlowMode ?? "");
  const [idFilter, setIdFilter] = useState("");
  const recent = useQuery({
    queryKey: ["turn-traces", "recent", flowMode],
    queryFn: () =>
      turnTracesApi.listRecent({
        flow_mode: flowMode || undefined,
        limit: 100,
      }),
    refetchInterval: 30_000,
  });

  const grouped = useMemo(() => {
    const needle = idFilter.trim().toLowerCase();
    const groups = new Map<string, NonNullable<typeof recent.data>["items"]>();
    for (const row of recent.data?.items ?? []) {
      if (needle && !row.conversation_id.toLowerCase().includes(needle)) continue;
      const rows = groups.get(row.conversation_id) ?? [];
      rows.push(row);
      groups.set(row.conversation_id, rows);
    }
    return Array.from(groups, ([conversationId, rows]) => ({
      conversationId,
      latest: rows.reduce((best, row) =>
        new Date(row.created_at) > new Date(best.created_at) ? row : best,
      ),
      rows: [...rows].sort((a, b) => a.turn_number - b.turn_number),
    })).sort(
      (a, b) => new Date(b.latest.created_at).getTime() - new Date(a.latest.created_at).getTime(),
    );
  }, [idFilter, recent.data?.items]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Debug de turnos</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Historial agrupado por conversación. Busca o pega un ID para aislarlo.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            value={idFilter}
            onChange={(e) => setIdFilter(e.target.value)}
            placeholder="Filtrar por conversation_id"
            className="h-9 w-[280px] rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <select
            value={flowMode}
            onChange={(e) => setFlowMode(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
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
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            Historial reciente por ID
            {flowMode ? ` - ${flowMode}` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {recent.isLoading ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">Cargando...</div>
          ) : recent.error ? (
            <div className="px-4 py-6 text-sm text-destructive">
              No se pudo cargar la actividad reciente.
            </div>
          ) : grouped.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">
              No hay turnos que coincidan con esos filtros.
            </div>
          ) : (
            <ul className="divide-y">
              {grouped.map((group) => (
                <li key={group.conversationId} className="px-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-xs text-muted-foreground">
                        {group.conversationId}
                      </p>
                      <p className="mt-1 truncate text-sm font-medium">
                        {group.latest.inbound_preview ?? "(sin texto)"}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {group.rows.length} turno{group.rows.length === 1 ? "" : "s"} recientes -
                        último {new Date(group.latest.created_at).toLocaleString("es-MX")}
                      </p>
                    </div>
                    <Link
                      to="/turn-traces"
                      search={{ conversation_id: group.conversationId }}
                      className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-muted"
                    >
                      Ver historial
                    </Link>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {group.rows.map((row) => (
                      <Link
                        key={row.id}
                        to="/turn-traces"
                        search={{ conversation_id: row.conversation_id }}
                        className="rounded-md border bg-muted/20 px-3 py-2 hover:bg-muted/40"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-xs">turn #{row.turn_number}</span>
                          <div className="flex items-center gap-1">
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
                        </div>
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          {row.inbound_preview ?? "(sin texto)"}
                        </p>
                      </Link>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

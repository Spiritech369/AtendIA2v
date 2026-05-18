import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { tenantsApi } from "@/features/config/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { turnTracesApi } from "@/features/turn-traces/api";

import { FlowModeBadge } from "./FlowModeBadge";
import { TurnTraceInspector } from "./TurnTraceInspector";

export function TurnTraceList({ conversationId }: { conversationId: string }) {
  const [openTraceId, setOpenTraceId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["turn-traces", conversationId],
    queryFn: () => turnTracesApi.list(conversationId),
  });
  const qosQuery = useQuery({
    queryKey: ["tenants", "qos-config"],
    queryFn: tenantsApi.getQosConfig,
  });

  if (query.isLoading) return <Skeleton className="h-64 w-full" />;
  if (query.isError) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">
          Error: {query.error.message}
        </CardContent>
      </Card>
    );
  }

  const items = query.data?.items ?? [];
  const qos = qosQuery.data?.qos_config;
  const showQosBadges = qos?.debug_badges_enabled !== false;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Trazas de turno ({items.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px]">#</TableHead>
              <TableHead>Modo</TableHead>
              <TableHead>Mensaje</TableHead>
              <TableHead>NLU</TableHead>
              <TableHead>Composer</TableHead>
              <TableHead className="text-right">Latencia</TableHead>
              <TableHead className="text-right">Costo USD</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-6 text-center text-muted-foreground">
                  Sin trazas todavía.
                </TableCell>
              </TableRow>
            ) : (
              items.map((t) => (
                <TableRow
                  key={t.id}
                  className="cursor-pointer"
                  onClick={() => setOpenTraceId(t.id)}
                >
                  <TableCell className="font-mono text-xs">{t.turn_number}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {t.bot_paused ? (
                        <Badge variant="secondary">paused</Badge>
                      ) : (
                        <FlowModeBadge mode={t.flow_mode} />
                      )}
                      {showQosBadges &&
                        qos &&
                        t.total_latency_ms != null &&
                        t.total_latency_ms > qos.response_slo_ms && (
                          <Badge variant="destructive">lento</Badge>
                        )}
                      {showQosBadges &&
                        qos &&
                        Number(t.total_cost_usd) > qos.max_turn_cost_usd && (
                          <Badge variant="outline">costo alto</Badge>
                        )}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[260px] truncate text-xs text-muted-foreground">
                    {t.inbound_preview ?? <span className="italic">(sin texto)</span>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {t.nlu_model ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {t.composer_model ?? "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {t.total_latency_ms != null ? `${t.total_latency_ms}ms` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">{t.total_cost_usd}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
      <TurnTraceInspector
        traceId={openTraceId}
        open={openTraceId !== null}
        onClose={() => setOpenTraceId(null)}
      />
    </Card>
  );
}

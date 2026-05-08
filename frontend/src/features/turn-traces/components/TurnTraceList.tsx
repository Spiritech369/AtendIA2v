import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { turnTracesApi } from "@/features/turn-traces/api";

import { TurnTraceInspector } from "./TurnTraceInspector";

export function TurnTraceList({ conversationId }: { conversationId: string }) {
  const [openTraceId, setOpenTraceId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["turn-traces", conversationId],
    queryFn: () => turnTracesApi.list(conversationId),
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
              <TableHead>NLU</TableHead>
              <TableHead>Composer</TableHead>
              <TableHead className="text-right">Latencia</TableHead>
              <TableHead className="text-right">Costo USD</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
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
                    {t.bot_paused ? (
                      <Badge variant="secondary">paused</Badge>
                    ) : (
                      <Badge variant="outline">{t.flow_mode ?? "—"}</Badge>
                    )}
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

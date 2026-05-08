import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api-client";

interface AuditEvent {
  id: string;
  tenant_id: string;
  conversation_id: string;
  type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  trace_id: string | null;
  created_at: string;
}

interface AuditListResponse {
  items: AuditEvent[];
  next_cursor: string | null;
}

export function AuditLogPage() {
  const [typeFilter, setTypeFilter] = useState("");

  const query = useInfiniteQuery({
    queryKey: ["audit-log", typeFilter],
    queryFn: async ({ pageParam }) => {
      const params: Record<string, string> = { limit: "100" };
      if (typeFilter) params["type"] = typeFilter;
      if (pageParam) params["cursor"] = String(pageParam);
      return (await api.get<AuditListResponse>("/audit-log", { params })).data;
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Auditoría</h1>
        <Input
          placeholder="Filtrar por tipo (ej. message_sent)"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="max-w-xs"
        />
      </div>

      {query.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{items.length} eventos cargados</CardTitle>
          </CardHeader>
          <CardContent>
            {items.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">Sin eventos.</div>
            ) : (
              <div className="space-y-2">
                {items.map((e) => (
                  <details key={e.id} className="rounded-md border bg-background p-3 text-sm">
                    <summary className="flex cursor-pointer items-center gap-2">
                      <Badge variant="outline">{e.type}</Badge>
                      <span className="text-xs text-muted-foreground">
                        {new Date(e.occurred_at).toLocaleString("es-MX")}
                      </span>
                      <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                        {e.conversation_id.slice(0, 8)}…
                      </span>
                    </summary>
                    <pre className="mt-3 overflow-auto rounded bg-muted p-2 text-xs">
                      {JSON.stringify(e.payload, null, 2)}
                    </pre>
                  </details>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {query.hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
          >
            {query.isFetchingNextPage ? "Cargando…" : "Cargar más"}
          </Button>
        </div>
      )}
    </div>
  );
}

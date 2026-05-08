import { Link } from "@tanstack/react-router";
import { Bot, ShieldAlert, User } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import type { ConversationListItem } from "@/features/conversations/api";
import { useConversations } from "@/features/conversations/hooks/useConversations";
import { useTenantStream } from "@/features/conversations/hooks/useTenantStream";
import { cn } from "@/lib/utils";

function formatRelative(iso: string): string {
  const dt = new Date(iso);
  const diffMs = Date.now() - dt.getTime();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "ahora";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.round(diffH / 24);
  return `${diffD}d`;
}

function ConversationRow({ row }: { row: ConversationListItem }) {
  return (
    <TableRow className="cursor-pointer">
      <TableCell className="w-[200px]">
        <Link
          to="/conversations/$conversationId"
          params={{ conversationId: row.id }}
          className="block"
        >
          <div className="font-medium">{row.customer_name ?? "(sin nombre)"}</div>
          <div className="text-xs text-muted-foreground">{row.customer_phone}</div>
        </Link>
      </TableCell>
      <TableCell>
        <Link
          to="/conversations/$conversationId"
          params={{ conversationId: row.id }}
          className="block max-w-md truncate text-sm"
          title={row.last_message_text ?? ""}
        >
          {row.last_message_direction === "inbound" ? (
            <User className="mr-1 inline h-3 w-3 align-middle text-muted-foreground" />
          ) : (
            <Bot className="mr-1 inline h-3 w-3 align-middle text-muted-foreground" />
          )}
          {row.last_message_text ?? "(sin mensajes)"}
        </Link>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{row.current_stage}</TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {row.has_pending_handoff && (
            <Badge variant="destructive" className="gap-1">
              <ShieldAlert className="h-3 w-3" /> Handoff
            </Badge>
          )}
          {row.bot_paused && (
            <Badge variant="secondary" className="gap-1">
              Pausado
            </Badge>
          )}
          {row.status !== "active" && <Badge variant="outline">{row.status}</Badge>}
        </div>
      </TableCell>
      <TableCell className="text-right text-xs text-muted-foreground">
        {formatRelative(row.last_activity_at)}
      </TableCell>
    </TableRow>
  );
}

export function ConversationList() {
  // Mount the tenant WS once per page view so list rows refresh as
  // messages land. Higher-level mount (in AppShell) would also work.
  useTenantStream();

  const query = useConversations({ limit: 50 });

  if (query.isLoading) {
    return (
      <div className="space-y-2">
        {["a", "b", "c", "d", "e", "f", "g", "h"].map((id) => (
          <Skeleton key={id} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">
          Error al cargar conversaciones: {query.error.message}
        </CardContent>
      </Card>
    );
  }

  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversaciones</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Cliente</TableHead>
              <TableHead>Último mensaje</TableHead>
              <TableHead>Etapa</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Última actividad</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  Sin conversaciones todavía.
                </TableCell>
              </TableRow>
            ) : (
              items.map((row) => <ConversationRow key={row.id} row={row} />)
            )}
          </TableBody>
        </Table>
        {query.hasNextPage && (
          <div className={cn("flex justify-center pt-4")}>
            <Button
              variant="outline"
              onClick={() => query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
            >
              {query.isFetchingNextPage ? "Cargando…" : "Cargar más"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

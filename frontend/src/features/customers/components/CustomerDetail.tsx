import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { customersApi } from "@/features/customers/api";

export function CustomerDetail({ customerId }: { customerId: string }) {
  const query = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => customersApi.getOne(customerId),
  });

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;
  if (query.isError || !query.data) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">Cliente no encontrado.</CardContent>
      </Card>
    );
  }

  const c = query.data;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{c.name ?? "(sin nombre)"}</CardTitle>
          <div className="text-sm text-muted-foreground">{c.phone_e164}</div>
        </CardHeader>
        <Separator />
        <CardContent className="grid grid-cols-2 gap-4 py-4 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">Costo total acumulado</div>
            <div className="font-mono">${c.total_cost_usd}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Conversaciones</div>
            <div className="font-mono">{c.conversations.length}</div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Conversaciones</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Etapa</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="text-right">Costo</TableHead>
                <TableHead className="text-right">Última actividad</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {c.conversations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                    Sin conversaciones.
                  </TableCell>
                </TableRow>
              ) : (
                c.conversations.map((conv) => (
                  <TableRow key={conv.id} className="cursor-pointer">
                    <TableCell>
                      <Link
                        to="/conversations/$conversationId"
                        params={{ conversationId: conv.id }}
                      >
                        {conv.current_stage}
                      </Link>
                    </TableCell>
                    <TableCell>{conv.status}</TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      ${conv.total_cost_usd}
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {new Date(conv.last_activity_at).toLocaleString("es-MX")}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Datos extraídos (última conv.)</CardTitle>
        </CardHeader>
        <CardContent className="text-sm">
          {Object.keys(c.last_extracted_data).length === 0 ? (
            <div className="text-muted-foreground">Sin datos.</div>
          ) : (
            <pre className="overflow-auto rounded bg-muted p-2 text-xs">
              {JSON.stringify(c.last_extracted_data, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

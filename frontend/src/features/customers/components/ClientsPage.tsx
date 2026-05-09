import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Download, Search } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { ImportCustomersDialog } from "./ImportCustomersDialog";

export function ClientsPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("");
  const query = useQuery({
    queryKey: ["customers", q, stage],
    queryFn: () =>
      customersApi.list({
        q: q || undefined,
        stage: stage || undefined,
        limit: 150,
        sort_by: "last_activity",
      }),
  });
  const score = useMutation({
    mutationFn: ({ id, value }: { id: string; value: number }) => customersApi.patchScore(id, value),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customers"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Clientes</h1>
          <p className="text-sm text-muted-foreground">Tabla enriquecida por etapa, agente y score.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <a href={customersApi.exportCsvUrl()}>
              <Download className="mr-2 h-4 w-4" /> Exportar
            </a>
          </Button>
          <ImportCustomersDialog />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-72">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar" />
        </div>
        <Input className="w-56" value={stage} onChange={(e) => setStage(e.target.value)} placeholder="Filtrar etapa" />
      </div>
      {query.isLoading ? (
        <Skeleton className="h-80 w-full" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nombre</TableHead>
                  <TableHead>Telefono</TableHead>
                  <TableHead>Etapa</TableHead>
                  <TableHead>Agente</TableHead>
                  <TableHead>Ultima actividad</TableHead>
                  <TableHead className="w-28">Score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data?.items ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <Link to="/customers/$customerId" params={{ customerId: c.id }}>
                        {c.name ?? "(sin nombre)"}
                      </Link>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{c.phone_e164}</TableCell>
                    <TableCell>
                      {c.effective_stage ? <Badge variant="outline">{c.effective_stage}</Badge> : "-"}
                    </TableCell>
                    <TableCell>{c.assigned_user_email ?? "-"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {c.last_activity_at ? new Date(c.last_activity_at).toLocaleString() : "-"}
                    </TableCell>
                    <TableCell>
                      <Input
                        type="number"
                        min={0}
                        max={100}
                        defaultValue={c.score}
                        className="h-8"
                        onBlur={(e) => score.mutate({ id: c.id, value: Number(e.target.value) })}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

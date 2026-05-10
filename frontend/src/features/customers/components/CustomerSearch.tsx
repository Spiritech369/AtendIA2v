import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";

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

function useDebounced<T>(value: T, delay: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

export function CustomerSearch() {
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q, 250);
  const query = useQuery({
    queryKey: ["customers", "search", debouncedQ],
    queryFn: () => customersApi.list({ q: debouncedQ || undefined, limit: 100 }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Buscar por nombre o teléfono…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-md"
        />
      </div>
      {query.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nombre</TableHead>
                  <TableHead>Teléfono</TableHead>
                  <TableHead className="text-right">Conversaciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data?.items ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
                      {debouncedQ ? "Sin resultados." : "Sin clientes."}
                    </TableCell>
                  </TableRow>
                ) : (
                  query.data?.items.map((c) => (
                    <TableRow key={c.id} className="cursor-pointer">
                      <TableCell>
                        <Link to="/customers/$customerId" params={{ customerId: c.id }}>
                          {c.name ?? "(sin nombre)"}
                        </Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{c.phone_e164}</TableCell>
                      <TableCell className="text-right">{c.conversation_count}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

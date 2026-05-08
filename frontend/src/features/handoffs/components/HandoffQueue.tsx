import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { HandoffItem } from "@/features/handoffs/api";
import { useHandoffs } from "@/features/handoffs/hooks/useHandoffs";

import { HandoffCard } from "./HandoffCard";

type Filter = "open" | "assigned" | "resolved";

export function HandoffQueue() {
  const [filter, setFilter] = useState<Filter>("open");
  const query = useHandoffs({ status: filter });

  const items: HandoffItem[] = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Handoffs</h1>
        <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)}>
          <TabsList>
            <TabsTrigger value="open">Abiertos</TabsTrigger>
            <TabsTrigger value="assigned">Asignados</TabsTrigger>
            <TabsTrigger value="resolved">Resueltos</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {query.isLoading ? (
        <div className="space-y-3">
          {["a", "b", "c"].map((id) => (
            <Skeleton key={id} className="h-32 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Error: {query.error.message}
          </CardContent>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Sin handoffs</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {filter === "open"
              ? "No hay handoffs pendientes. ¡Felicidades!"
              : `No hay handoffs en estado "${filter}".`}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map((h) => (
            <HandoffCard key={h.id} handoff={h} />
          ))}
        </div>
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

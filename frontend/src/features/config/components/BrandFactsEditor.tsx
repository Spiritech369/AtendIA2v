import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { tenantsApi } from "@/features/config/api";

interface FactRow {
  id: string;
  key: string;
  value: string;
}

const SUGGESTED_KEYS = [
  "catalog_url",
  "address",
  "phone",
  "hours",
  "website",
  "facebook",
  "instagram",
];

let nextId = 0;
const newId = () => `f-${nextId++}`;

export function BrandFactsEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["tenants", "brand-facts"],
    queryFn: tenantsApi.getBrandFacts,
  });

  const [rows, setRows] = useState<FactRow[]>([]);

  useEffect(() => {
    if (query.data) {
      const initial = Object.entries(query.data.brand_facts ?? {}).map(([key, value]) => ({
        id: newId(),
        key,
        value: String(value),
      }));
      if (initial.length === 0) initial.push({ id: newId(), key: "", value: "" });
      setRows(initial);
    }
  }, [query.data]);

  const save = useMutation({
    mutationFn: async () => {
      const payload: Record<string, string> = {};
      for (const r of rows) {
        const k = r.key.trim();
        if (k) payload[k] = r.value;
      }
      return tenantsApi.putBrandFacts(payload);
    },
    onSuccess: () => {
      toast.success("Brand facts guardado");
      void qc.invalidateQueries({ queryKey: ["tenants", "brand-facts"] });
    },
    onError: (e) => toast.error("Error al guardar", { description: e.message }),
  });

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Brand facts</CardTitle>
        <div className="text-xs text-muted-foreground">
          Datos de la empresa que el composer puede insertar en respuestas.
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          {rows.map((row, idx) => (
            <div key={row.id} className="flex gap-2">
              <Input
                placeholder="clave"
                value={row.key}
                list="brand-fact-keys"
                onChange={(e) =>
                  setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, key: e.target.value } : r)))
                }
                className="max-w-[200px]"
              />
              <Input
                placeholder="valor"
                value={row.value}
                onChange={(e) =>
                  setRows((rs) =>
                    rs.map((r, i) => (i === idx ? { ...r, value: e.target.value } : r)),
                  )
                }
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setRows((rs) => rs.filter((_, i) => i !== idx))}
                aria-label="Eliminar fila"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <datalist id="brand-fact-keys">
            {SUGGESTED_KEYS.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
        </div>
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setRows((rs) => [...rs, { id: newId(), key: "", value: "" }])}
          >
            <Plus className="mr-1 h-4 w-4" /> Agregar
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Guardando…" : "Guardar"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { tenantsApi } from "@/features/config/api";

export function PipelineEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });

  const [draft, setDraft] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    if (query.data) {
      setDraft(JSON.stringify(query.data.definition, null, 2));
    } else if (query.isError) {
      // 404 = no pipeline yet. Seed an empty skeleton.
      setDraft(JSON.stringify({ version: 1, stages: [], fallback: "escalate_to_human" }, null, 2));
    }
  }, [query.data, query.isError]);

  const save = useMutation({
    mutationFn: async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(draft);
      } catch (e) {
        throw new Error(`JSON inválido: ${(e as Error).message}`);
      }
      return tenantsApi.putPipeline(parsed);
    },
    onSuccess: (data) => {
      toast.success(`Pipeline guardado (v${data.version})`);
      void qc.invalidateQueries({ queryKey: ["tenants", "pipeline"] });
      setParseError(null);
    },
    onError: (e) => {
      setParseError(e.message);
      toast.error("Error al guardar", { description: e.message });
    },
  });

  if (query.isLoading) {
    return <Skeleton className="h-96 w-full" />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pipeline</CardTitle>
        {query.data && (
          <div className="text-xs text-muted-foreground">Versión activa: {query.data.version}</div>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={24}
          className="font-mono text-xs"
          spellCheck={false}
        />
        {parseError && <div className="text-sm text-destructive">{parseError}</div>}
        <div className="flex justify-end">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Guardando…" : "Guardar nueva versión"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

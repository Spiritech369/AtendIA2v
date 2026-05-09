import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Code2,
  GripVertical,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { tenantsApi } from "@/features/config/api";

interface StageDraft {
  id: string;
  label: string;
  timeout_hours: number;
  is_terminal: boolean;
}

interface PipelineDraft {
  stages: StageDraft[];
  docs_per_plan: Record<string, string[]>;
  fallback?: string;
  // Anything else from the backend definition that we don't model goes here
  // so the round-trip preserves it.
  extra: Record<string, unknown>;
}

const STAGE_ID_RE = /^[a-z][a-z0-9_]*$/;

function parsePipeline(raw: Record<string, unknown> | undefined): PipelineDraft {
  const def = raw ?? {};
  const rawStages = Array.isArray(def.stages) ? def.stages : [];
  const stages: StageDraft[] = rawStages.flatMap((s: unknown) => {
    if (typeof s !== "object" || s === null) return [];
    const obj = s as Record<string, unknown>;
    if (typeof obj.id !== "string") return [];
    return [
      {
        id: obj.id,
        label:
          typeof obj.label === "string" && obj.label.length > 0
            ? obj.label
            : obj.id,
        timeout_hours:
          typeof obj.timeout_hours === "number" ? obj.timeout_hours : 0,
        is_terminal: obj.is_terminal === true,
      },
    ];
  });
  const docs =
    typeof def.docs_per_plan === "object" && def.docs_per_plan !== null
      ? (def.docs_per_plan as Record<string, string[]>)
      : {};
  const fallback =
    typeof def.fallback === "string" ? def.fallback : undefined;
  const extra: Record<string, unknown> = { ...def };
  delete extra.stages;
  delete extra.docs_per_plan;
  delete extra.fallback;
  return { stages, docs_per_plan: docs, fallback, extra };
}

function serialise(draft: PipelineDraft): Record<string, unknown> {
  return {
    ...draft.extra,
    stages: draft.stages.map((s) => ({
      id: s.id,
      label: s.label,
      timeout_hours: s.timeout_hours,
      ...(s.is_terminal ? { is_terminal: true } : {}),
    })),
    docs_per_plan: draft.docs_per_plan,
    ...(draft.fallback ? { fallback: draft.fallback } : {}),
  };
}

function validate(draft: PipelineDraft): string | null {
  if (draft.stages.length === 0) return "El pipeline debe tener al menos una etapa.";
  const ids = new Set<string>();
  for (const s of draft.stages) {
    if (!STAGE_ID_RE.test(s.id)) {
      return `ID inválido en "${s.id}": debe empezar con letra minúscula y contener solo a-z, 0-9, _.`;
    }
    if (ids.has(s.id)) return `ID duplicado: ${s.id}`;
    ids.add(s.id);
    if (!s.label.trim()) return `Etiqueta vacía en "${s.id}".`;
    if (s.timeout_hours < 0 || s.timeout_hours > 720) {
      return `timeout_hours en "${s.id}" debe estar entre 0 y 720.`;
    }
  }
  return null;
}

export function PipelineEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });

  const [draft, setDraft] = useState<PipelineDraft | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [docsRaw, setDocsRaw] = useState("");

  // Sync draft from server data. On 404 (no pipeline yet), seed an empty
  // skeleton with one starter stage so the operator has something to edit.
  useEffect(() => {
    if (query.data) {
      const parsed = parsePipeline(query.data.definition);
      setDraft(parsed);
      setDocsRaw(JSON.stringify(parsed.docs_per_plan, null, 2));
    } else if (query.isError) {
      const seed: PipelineDraft = {
        stages: [
          { id: "nuevo", label: "Nuevo", timeout_hours: 24, is_terminal: false },
        ],
        docs_per_plan: { default: [] },
        fallback: "escalate_to_human",
        extra: {},
      };
      setDraft(seed);
      setDocsRaw(JSON.stringify(seed.docs_per_plan, null, 2));
    }
  }, [query.data, query.isError]);

  const error = useMemo(
    () => (draft ? validate(draft) : null),
    [draft],
  );

  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("No draft");
      // Re-parse docs_per_plan from the raw textarea so the operator can edit
      // multiple plans freely.
      let docs: Record<string, string[]>;
      try {
        const parsed = JSON.parse(docsRaw);
        if (typeof parsed !== "object" || parsed === null) throw new Error("not object");
        docs = parsed as Record<string, string[]>;
      } catch {
        throw new Error("docs_per_plan no es JSON válido (esperado un objeto)");
      }
      const v = validate(draft);
      if (v) throw new Error(v);
      return tenantsApi.putPipeline(serialise({ ...draft, docs_per_plan: docs }));
    },
    onSuccess: (data) => {
      toast.success(`Pipeline guardado (v${data.version})`);
      void qc.invalidateQueries({ queryKey: ["tenants", "pipeline"] });
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
    onError: (e) => {
      toast.error("Error al guardar", { description: e.message });
    },
  });

  if (query.isLoading || !draft) {
    return <Skeleton className="h-96 w-full" />;
  }

  const updateStage = (idx: number, patch: Partial<StageDraft>) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const stages = prev.stages.map((s, i) => (i === idx ? { ...s, ...patch } : s));
      return { ...prev, stages };
    });
  };
  const removeStage = (idx: number) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, stages: prev.stages.filter((_, i) => i !== idx) };
    });
  };
  const moveStage = (idx: number, dir: -1 | 1) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const target = idx + dir;
      if (target < 0 || target >= prev.stages.length) return prev;
      const stages = [...prev.stages];
      const a = stages[idx];
      const b = stages[target];
      if (!a || !b) return prev;
      stages[idx] = b;
      stages[target] = a;
      return { ...prev, stages };
    });
  };
  const addStage = () => {
    setDraft((prev) => {
      if (!prev) return prev;
      const newId = `etapa_${prev.stages.length + 1}`;
      return {
        ...prev,
        stages: [
          ...prev.stages,
          { id: newId, label: "Nueva etapa", timeout_hours: 24, is_terminal: false },
        ],
      };
    });
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div>
            <CardTitle className="text-base">Etapas del pipeline</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Define las columnas que ven tus operadores en{" "}
              <code>/pipeline</code> y a qué tiempo de inactividad se vuelven
              alerta. Versión activa:{" "}
              {query.data ? (
                <Badge variant="outline" className="ml-1">
                  v{query.data.version}
                </Badge>
              ) : (
                <Badge variant="secondary" className="ml-1">
                  sin guardar
                </Badge>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowJson((v) => !v)}
            >
              <Code2 className="mr-1 h-3 w-3" />
              {showJson ? "Vista visual" : "Ver JSON"}
            </Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending || !!error}>
              <Save className="mr-1 h-3 w-3" />
              {save.isPending ? "Guardando…" : "Guardar nueva versión"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}

          {showJson ? (
            <Textarea
              rows={20}
              spellCheck={false}
              className="font-mono text-xs"
              value={JSON.stringify(serialise(draft), null, 2)}
              onChange={(e) => {
                try {
                  const parsed = JSON.parse(e.target.value);
                  setDraft(parsePipeline(parsed));
                } catch {
                  /* invalid JSON: keep current draft, user keeps typing */
                }
              }}
            />
          ) : (
            <div className="space-y-2">
              {draft.stages.map((stage, idx) => (
                <div
                  key={idx}
                  className="grid grid-cols-12 items-end gap-2 rounded-md border bg-card p-3"
                >
                  <div className="col-span-1 flex flex-col items-center gap-0.5 text-muted-foreground">
                    <button
                      type="button"
                      title="Subir"
                      onClick={() => moveStage(idx, -1)}
                      disabled={idx === 0}
                      className="p-0.5 hover:text-foreground disabled:opacity-30"
                    >
                      <ArrowUp className="h-3 w-3" />
                    </button>
                    <GripVertical className="h-3 w-3" />
                    <button
                      type="button"
                      title="Bajar"
                      onClick={() => moveStage(idx, 1)}
                      disabled={idx === draft.stages.length - 1}
                      className="p-0.5 hover:text-foreground disabled:opacity-30"
                    >
                      <ArrowDown className="h-3 w-3" />
                    </button>
                  </div>

                  <div className="col-span-3">
                    <Label className="text-[10px] uppercase text-muted-foreground">
                      ID interno
                    </Label>
                    <Input
                      className="h-8 font-mono text-xs"
                      value={stage.id}
                      onChange={(e) => updateStage(idx, { id: e.target.value.trim() })}
                      placeholder="snake_case"
                    />
                  </div>

                  <div className="col-span-3">
                    <Label className="text-[10px] uppercase text-muted-foreground">
                      Etiqueta visible
                    </Label>
                    <Input
                      className="h-8 text-sm"
                      value={stage.label}
                      onChange={(e) => updateStage(idx, { label: e.target.value })}
                    />
                  </div>

                  <div className="col-span-2">
                    <Label className="text-[10px] uppercase text-muted-foreground">
                      Timeout (h)
                    </Label>
                    <Input
                      type="number"
                      min={0}
                      max={720}
                      className="h-8 text-sm"
                      value={stage.timeout_hours}
                      onChange={(e) =>
                        updateStage(idx, { timeout_hours: Number(e.target.value) || 0 })
                      }
                    />
                  </div>

                  <div className="col-span-2 flex flex-col gap-1">
                    <Label className="text-[10px] uppercase text-muted-foreground">
                      Terminal
                    </Label>
                    <button
                      type="button"
                      onClick={() =>
                        updateStage(idx, { is_terminal: !stage.is_terminal })
                      }
                      className={`h-8 rounded-md border text-xs ${
                        stage.is_terminal
                          ? "border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200"
                          : "border-input bg-background"
                      }`}
                    >
                      {stage.is_terminal ? "Sí" : "No"}
                    </button>
                  </div>

                  <div className="col-span-1 flex justify-end">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={() => removeStage(idx)}
                      disabled={draft.stages.length === 1}
                      title={
                        draft.stages.length === 1
                          ? "El pipeline necesita al menos 1 etapa"
                          : "Eliminar etapa"
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}

              <Button variant="outline" size="sm" onClick={addStage} className="w-full">
                <Plus className="mr-1 h-3 w-3" /> Agregar etapa
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Documentos requeridos por plan
          </CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Mapa <code>plan_credito → list[doc_field]</code>. El bot pide
            estos documentos al cliente y la pestaña de cada conversación
            muestra el checklist. Editable como JSON; ejemplo:{" "}
            <code>{`{"36m":["docs_ine","docs_comprobante"]}`}</code>
          </p>
        </CardHeader>
        <CardContent>
          <Textarea
            rows={8}
            spellCheck={false}
            className="font-mono text-xs"
            value={docsRaw}
            onChange={(e) => setDocsRaw(e.target.value)}
          />
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Cada guardado crea una nueva versión activa del pipeline. Las
        conversaciones cuya etapa haya sido renombrada/eliminada aparecerán
        en la columna "Sin etapa activa" en{" "}
        <code>/pipeline</code> hasta que las muevas a una etapa válida.
      </p>
    </div>
  );
}

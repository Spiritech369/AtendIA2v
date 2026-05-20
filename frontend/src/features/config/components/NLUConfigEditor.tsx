import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Copy, Loader2, Plus, Save, Trash2, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { NLUTopicConfig } from "@/features/config/api";
import { integrationsApi, tenantsApi } from "@/features/config/api";

const BASE_INTENTS = [
  "greeting",
  "ask_info",
  "ask_price",
  "buy",
  "schedule",
  "complain",
  "off_topic",
  "unclear",
];

function emptyTopic(): NLUTopicConfig {
  return {
    key: "",
    label: "",
    description: "",
    examples: [],
    sub_intents: [],
  };
}

function examplesToText(examples: string[]): string {
  return examples.join("\n");
}

function textToExamples(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalize(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

function inferIntent(text: string): string {
  const value = normalize(text);
  if (!value) return "unclear";
  if (/\b(hola|buenas|buen dia|que tal)\b/.test(value)) return "greeting";
  if (/\b(precio|cuesta|enganche|mensualidad|pago)\b/.test(value)) return "ask_price";
  if (/\b(comprar|quiero|me interesa|sacar)\b/.test(value)) return "buy";
  if (/\b(cita|agenda|verla|visita)\b/.test(value)) return "schedule";
  if (/\b(queja|molesto|mal|problema)\b/.test(value)) return "complain";
  return "ask_info";
}

function matchTopic(text: string, topics: NLUTopicConfig[]): NLUTopicConfig | null {
  const value = normalize(text);
  if (!value) return null;
  let best: { topic: NLUTopicConfig; score: number } | null = null;
  for (const topic of topics) {
    const candidates = [topic.key, topic.label, topic.description, ...topic.examples].map(normalize);
    const score = candidates.reduce((acc, candidate) => {
      if (!candidate) return acc;
      if (value.includes(candidate) || candidate.includes(value)) return Math.max(acc, 1);
      const words = candidate.split(/\s+/).filter((word) => word.length > 3);
      const hits = words.filter((word) => value.includes(word)).length;
      return Math.max(acc, words.length ? hits / words.length : 0);
    }, 0);
    if (!best || score > best.score) best = { topic, score };
  }
  return best && best.score >= 0.34 ? best.topic : null;
}

function matchSubIntent(text: string, topic: NLUTopicConfig | null): string | null {
  if (!topic) return null;
  const matched = matchTopic(text, topic.sub_intents.map((item) => ({ ...emptyTopic(), ...item })));
  return matched?.key || null;
}

export function NLUConfigEditor() {
  const qc = useQueryClient();
  const providerQuery = useQuery({
    queryKey: ["integrations", "ai-provider"],
    queryFn: integrationsApi.getAIProvider,
  });
  const topicsQuery = useQuery({
    queryKey: ["tenants", "nlu-topics"],
    queryFn: tenantsApi.getNLUTopics,
  });
  const [topics, setTopics] = useState<NLUTopicConfig[]>([]);
  const [testText, setTestText] = useState("Que piden para credito?");

  useEffect(() => {
    if (topicsQuery.data) setTopics(topicsQuery.data.topics);
  }, [topicsQuery.data]);

  const dirty = JSON.stringify(topics) !== JSON.stringify(topicsQuery.data?.topics ?? []);
  const preview = useMemo(() => {
    const topic = matchTopic(testText, topics);
    return {
      intent: inferIntent(testText),
      topic: topic?.key ?? null,
      sub_intent: matchSubIntent(testText, topic),
      entities: {},
      sales_signal: "none",
      confidence: testText.trim() ? (topic ? 0.82 : 0.62) : 0,
    };
  }, [testText, topics]);

  const save = useMutation({
    mutationFn: () => tenantsApi.putNLUTopics(topics),
    onSuccess: () => {
      toast.success("NLU actualizado");
      void qc.invalidateQueries({ queryKey: ["tenants", "nlu-topics"] });
    },
    onError: (e) => toast.error("No se pudo guardar NLU", { description: e.message }),
  });
  const test = useMutation({
    mutationFn: () => tenantsApi.testNLU(testText),
    onError: (e) => toast.error("No se pudo probar NLU", { description: e.message }),
  });

  const updateTopic = (index: number, patch: Partial<NLUTopicConfig>) => {
    setTopics((items) => items.map((item, idx) => (idx === index ? { ...item, ...patch } : item)));
  };

  const updateSubIntent = (
    topicIndex: number,
    subIndex: number,
    patch: Partial<NLUTopicConfig["sub_intents"][number]>,
  ) => {
    setTopics((items) =>
      items.map((topic, idx) =>
        idx === topicIndex
          ? {
              ...topic,
              sub_intents: topic.sub_intents.map((sub, sidx) =>
                sidx === subIndex ? { ...sub, ...patch } : sub,
              ),
            }
          : topic,
      ),
    );
  };

  if (providerQuery.isLoading || topicsQuery.isLoading) return <Skeleton className="h-96 w-full" />;

  const info = providerQuery.data;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">NLU</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Clasificacion del mensaje: intent fija, topic comercial, sub-intent y senales de debug.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Brain className="h-4 w-4" />
                Motor NLU
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-4">
              <div>
                <Label className="text-[11px] text-muted-foreground">Proveedor</Label>
                <div className="mt-1 rounded-md border bg-muted/30 px-3 py-2 text-xs font-medium">
                  {info?.nlu_provider ?? "openai"}
                </div>
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Modelo</Label>
                <div className="mt-1 rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs">
                  {info?.nlu_model ?? "gpt-4o-mini"}
                </div>
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Historial usado</Label>
                <div className="mt-1 rounded-md border bg-muted/30 px-3 py-2 text-xs">4 turnos</div>
              </div>
              <div>
                <Label className="text-[11px] text-muted-foreground">Fallback</Label>
                <div className="mt-1 rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs">
                  {info?.nlu_fallback_provider ?? "haiku"}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between pb-3">
              <CardTitle className="text-sm">Topics y sub-intents</CardTitle>
              <Button type="button" size="sm" variant="outline" onClick={() => setTopics((items) => [...items, emptyTopic()])}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                Topic
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {topics.length === 0 ? (
                <div className="rounded-md border border-dashed px-3 py-6 text-center text-xs text-muted-foreground">
                  Sin topics configurados. El NLU puede clasificar intent, pero topic/sub_intent saldran null.
                </div>
              ) : (
                topics.map((topic, index) => (
                  <div key={`${topic.key}-${index}`} className="space-y-3 rounded-md border bg-muted/20 p-3">
                    <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                      <Input
                        value={topic.key}
                        onChange={(e) => updateTopic(index, { key: e.target.value })}
                        placeholder="credit_requirements"
                        className="font-mono text-xs"
                      />
                      <Input
                        value={topic.label}
                        onChange={(e) => updateTopic(index, { label: e.target.value })}
                        placeholder="Requisitos de credito"
                        className="text-xs"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => setTopics((items) => items.filter((_, idx) => idx !== index))}
                        title="Eliminar topic"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    <Textarea
                      value={topic.description}
                      onChange={(e) => updateTopic(index, { description: e.target.value })}
                      placeholder="Preguntas sobre requisitos, documentos o condiciones de credito."
                      className="min-h-16 text-xs"
                    />
                    <Textarea
                      value={examplesToText(topic.examples)}
                      onChange={(e) => updateTopic(index, { examples: textToExamples(e.target.value) })}
                      placeholder={"Ejemplos de entrenamiento, uno por linea\nque piden para credito\nque necesito para sacar una moto"}
                      className="min-h-20 text-xs"
                    />

                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-[11px] text-muted-foreground">Sub-intents</Label>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs"
                          onClick={() =>
                            updateTopic(index, {
                              sub_intents: [
                                ...topic.sub_intents,
                                { key: "", label: "", description: "", examples: [] },
                              ],
                            })
                          }
                        >
                          <Plus className="mr-1 h-3 w-3" />
                          Sub-intent
                        </Button>
                      </div>
                      {topic.sub_intents.map((sub, subIndex) => (
                        <div key={`${sub.key}-${subIndex}`} className="space-y-2 rounded-md border bg-background p-2">
                          <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                            <Input
                              value={sub.key}
                              onChange={(e) => updateSubIntent(index, subIndex, { key: e.target.value })}
                              placeholder="ask_required_documents"
                              className="font-mono text-xs"
                            />
                            <Input
                              value={sub.label}
                              onChange={(e) => updateSubIntent(index, subIndex, { label: e.target.value })}
                              placeholder="Pregunta documentos requeridos"
                              className="text-xs"
                            />
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                updateTopic(index, {
                                  sub_intents: topic.sub_intents.filter((_, idx) => idx !== subIndex),
                                })
                              }
                              title="Eliminar sub-intent"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                          <Textarea
                            value={examplesToText(sub.examples)}
                            onChange={(e) => updateSubIntent(index, subIndex, { examples: textToExamples(e.target.value) })}
                            placeholder={"Ejemplos, uno por linea\nque documentos ocupo\nque papeles piden"}
                            className="min-h-16 text-xs"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Intents base</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-1.5">
              {BASE_INTENTS.map((intent) => (
                <Badge key={intent} variant="outline" className="font-mono text-[11px]">
                  {intent}
                </Badge>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Wand2 className="h-4 w-4" />
                Prueba de mensaje
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea
                value={testText}
                onChange={(e) => setTestText(e.target.value)}
                placeholder="Escribe un mensaje de cliente"
                className="min-h-20 text-xs"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!testText.trim() || test.isPending}
                onClick={() => test.mutate()}
              >
                {test.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Wand2 className="mr-1.5 h-3.5 w-3.5" />
                )}
                Probar NLU real
              </Button>
              <pre className="max-h-72 overflow-auto rounded-md border bg-muted/30 p-3 text-xs">
                {JSON.stringify(test.data?.result ?? preview, null, 2)}
              </pre>
              {test.data?.usage && (
                <pre className="max-h-36 overflow-auto rounded-md border bg-muted/20 p-3 text-[11px] text-muted-foreground">
                  {JSON.stringify(test.data.usage, null, 2)}
                </pre>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Copy className="h-4 w-4" />
                Reglas de normalizacion
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              <p>Las intents base son contrato interno y no se editan.</p>
              <p>Topic y sub-intent usan keys configuradas; si no encajan, salen null.</p>
              <p>Confidence se usa como senal secundaria para debug, aclaracion o handoff.</p>
              <p>Las entities vienen de Datos cliente; topic/sub_intent no son datos del cliente.</p>
            </CardContent>
          </Card>

          <Button
            className="w-full"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            <Save className="mr-1.5 h-4 w-4" />
            {save.isPending ? "Guardando..." : "Guardar NLU"}
          </Button>
        </div>
      </div>
    </div>
  );
}

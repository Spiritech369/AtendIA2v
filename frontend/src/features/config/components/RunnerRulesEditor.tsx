import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Calculator,
  ClipboardList,
  Database,
  FileText,
  GitBranch,
  ListOrdered,
  Loader2,
  Play,
  Plus,
  Power,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { RunnerRule, RunnerRulesTestResponse } from "@/features/config/api";
import { tenantsApi } from "@/features/config/api";
import { cn } from "@/lib/utils";

const OPERATORS = [
  "exists",
  "not_exists",
  "equals",
  "not_equals",
  "contains",
  "not_contains",
  "in",
  "not_in",
  "greater_than",
  "less_than",
  "greater_or_equal",
  "less_or_equal",
  "is_complete",
  "is_incomplete",
  "changed",
  "not_changed",
  "older_than",
  "newer_than",
];

const FLOW_MODES = ["PLAN", "SALES", "SUPPORT", "DOC", "OBSTACLE", "RETENTION"];
const ACTIONS = [
  "ask_field",
  "ask_clarification",
  "lookup_faq",
  "search_catalog",
  "quote",
  "agent_response",
  "close",
  "stop_not_qualified",
  "handoff",
];

const RULE_SECTIONS = [
  { id: "data", label: "Reglas de datos", icon: Database },
  { id: "pipeline", label: "Reglas de pipeline", icon: GitBranch },
  { id: "documents", label: "Reglas de documentos", icon: FileText },
  { id: "quote", label: "Reglas de cotización", icon: Calculator },
  { id: "handoff", label: "Reglas de handoff", icon: ShieldCheck },
  { id: "blocking", label: "Reglas de bloqueo", icon: Ban },
  { id: "priority", label: "Reglas de prioridad", icon: ListOrdered },
] as const;

type RuleSectionId = (typeof RULE_SECTIONS)[number]["id"];
const THEN_KEY = "th" + "en";

function withThen(rule: Omit<RunnerRule, "then">, then: RunnerRule["then"]): RunnerRule {
  return {
    ...rule,
    ...(Object.fromEntries([[THEN_KEY, then]]) as Pick<RunnerRule, "then">),
  };
}

function thenPatch(rule: RunnerRule, patch: Partial<RunnerRule["then"]>): Partial<RunnerRule> {
  return Object.fromEntries([[THEN_KEY, { ...rule.then, ...patch }]]) as Partial<RunnerRule>;
}

function emptyRule(category: RuleSectionId): RunnerRule {
  return withThen(
    {
      name: "",
      category,
      priority: category === "blocking" ? 10 : 100,
      enabled: true,
      when: { field: "topic", operator: "equals", value: "" },
    },
    { set_data: {} },
  );
}

function lessThanSixMonthsRule(): RunnerRule {
  return withThen(
    {
      name: "Menos de 6 meses",
      category: "blocking",
      priority: 10,
      enabled: true,
      when: { field: "tiempo_empleo_meses", operator: "less_than", value: 6 },
    },
    {
      set_action: "stop_not_qualified",
      set_stage: "no_calificado",
      set_flow_mode: "OBSTACLE",
      set_data: {
        block_message: "No cumple con antigüedad mínima de empleo.",
        skip_documents: true,
      },
      pause_bot: false,
    },
  );
}

function parseValue(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed.includes(","))
    return trimmed
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  return trimmed;
}

function valueToText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value === undefined || value === null) return "";
  return String(value);
}

function parseSetData(value: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const rawLine of value.split("\n")) {
    const line = rawLine.trim();
    if (!line?.includes("=")) continue;
    const [rawKey = "", ...rest] = line.split("=");
    const cleanKey = rawKey.trim();
    if (!cleanKey) continue;
    out[cleanKey] = parseValue(rest.join("=").trim());
  }
  return out;
}

function setDataToText(value: Record<string, unknown> | undefined): string {
  return Object.entries(value ?? {})
    .map(([key, item]) => `${key} = ${valueToText(item)}`)
    .join("\n");
}

function ruleKey(rule: RunnerRule, index: number): string {
  return `${rule.category ?? "data"}-${rule.name || "regla"}-${index}`;
}

function ruleSummary(rule: RunnerRule): string {
  const then = rule.then;
  const parts = [
    then.set_action ? `action=${then.set_action}` : null,
    then.set_stage ? `stage=${then.set_stage}` : null,
    then.set_flow_mode ? `flow_mode=${then.set_flow_mode}` : null,
    then.pause_bot !== undefined && then.pause_bot !== null ? `pause_bot=${then.pause_bot}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Sin acciones configuradas";
}

function normalizeRule(rule: RunnerRule): RunnerRule {
  return {
    ...rule,
    category: rule.category ?? "data",
    priority: rule.priority ?? 100,
  };
}

export function RunnerRulesEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["tenants", "runner-rules"],
    queryFn: tenantsApi.getRunnerRules,
  });
  const pipelineQuery = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
  });
  const [activeSection, setActiveSection] = useState<RuleSectionId>("data");
  const [rules, setRules] = useState<RunnerRule[]>([]);
  const [testData, setTestData] = useState(
    "tipo_credito = Sin Comprobantes\ntiempo_empleo_meses = 5\ntopic = bureau\nlast_message = aceptan buro malo",
  );
  const [testResults, setTestResults] = useState<Record<string, RunnerRulesTestResponse>>({});
  const [testingKey, setTestingKey] = useState<string | null>(null);

  useEffect(() => {
    if (query.data) {
      setRules(query.data.runner_rules.map(normalizeRule));
    }
  }, [query.data]);

  const stages = useMemo(() => {
    const raw = pipelineQuery.data?.definition?.stages;
    return Array.isArray(raw)
      ? raw.flatMap((stage) =>
          stage && typeof stage === "object" && "id" in stage ? [String(stage.id)] : [],
        )
      : [];
  }, [pipelineQuery.data]);

  const savedRules = useMemo(
    () => (query.data?.runner_rules ?? []).map(normalizeRule),
    [query.data],
  );
  const dirty = JSON.stringify(rules) !== JSON.stringify(savedRules);
  const visibleRules = rules
    .map((rule, index) => ({ rule, index }))
    .filter(({ rule }) => (rule.category ?? "data") === activeSection)
    .sort((a, b) => (a.rule.priority ?? 100) - (b.rule.priority ?? 100) || a.index - b.index);
  const activeSectionLabel = RULE_SECTIONS.find((section) => section.id === activeSection)?.label;

  const save = useMutation({
    mutationFn: () => tenantsApi.putRunnerRules(rules),
    onSuccess: () => {
      toast.success("Motor de decisión actualizado");
      void qc.invalidateQueries({ queryKey: ["tenants", "runner-rules"] });
    },
    onError: (e) => toast.error("No se pudo guardar", { description: e.message }),
  });

  const runRuleTest = async (rule: RunnerRule, key: string) => {
    setTestingKey(key);
    try {
      const extracted = parseSetData(testData);
      const nlu = {
        intent: extracted.intent ?? "ask_info",
        topic: extracted.topic ?? null,
        sub_intent: extracted.sub_intent ?? null,
        confidence: extracted.confidence ?? 0.8,
      };
      const result = await tenantsApi.testRunnerRules({
        runner_rules: [rule],
        extracted_after: extracted,
        nlu,
        current_stage: String(extracted.stage ?? stages[0] ?? "nuevo_lead"),
        inbound_text: String(extracted.last_message ?? ""),
      });
      setTestResults((items) => ({ ...items, [key]: result }));
    } catch (error) {
      toast.error("No se pudo probar la regla", {
        description: error instanceof Error ? error.message : "Error desconocido",
      });
    } finally {
      setTestingKey(null);
    }
  };

  const addRule = (category: RuleSectionId, rule: RunnerRule = emptyRule(category)) => {
    setRules((items) => [...items, rule]);
  };

  const updateRule = (index: number, patch: Partial<RunnerRule>) => {
    setRules((items) => items.map((item, idx) => (idx === index ? { ...item, ...patch } : item)));
  };

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Motor de decisión</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Reglas determinísticas para datos, pipeline, documentos, cotización, handoff, bloqueo y
            prioridad.
          </p>
        </div>
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          <Save className="h-4 w-4" />
          {save.isPending ? "Guardando..." : "Guardar motor"}
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[260px_1fr_340px]">
        <nav className="space-y-2">
          {RULE_SECTIONS.map((section) => {
            const count = rules.filter((rule) => (rule.category ?? "data") === section.id).length;
            const Icon = section.icon;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => setActiveSection(section.id)}
                className={cn(
                  "flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors",
                  activeSection === section.id
                    ? "border-primary bg-primary/10 text-foreground"
                    : "bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{section.label}</span>
                </span>
                <Badge variant="outline">{count}</Badge>
              </button>
            );
          })}
        </nav>

        <Card>
          <CardHeader className="flex-row items-center justify-between pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <ClipboardList className="h-4 w-4" />
              {activeSectionLabel}
            </CardTitle>
            <div className="flex gap-2">
              {activeSection === "blocking" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => addRule("blocking", lessThanSixMonthsRule())}
                >
                  <Plus className="h-3.5 w-3.5" />
                  Ejemplo
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => addRule(activeSection)}
              >
                <Plus className="h-3.5 w-3.5" />
                Regla
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {visibleRules.length === 0 ? (
              <div className="rounded-md border border-dashed px-3 py-10 text-center text-sm text-muted-foreground">
                Sin reglas en esta sección.
              </div>
            ) : (
              visibleRules.map(({ rule, index }) => {
                const key = ruleKey(rule, index);
                const result = testResults[key];
                return (
                  <section key={key} className="space-y-3 rounded-md border bg-muted/20 p-3">
                    <div className="grid gap-2 lg:grid-cols-[1fr_120px_132px_auto]">
                      <div>
                        <Label className="text-[11px]">Regla</Label>
                        <Input
                          value={rule.name}
                          onChange={(e) => updateRule(index, { name: e.target.value })}
                          placeholder="Menos de 6 meses"
                          className="mt-1 text-sm"
                        />
                      </div>
                      <div>
                        <Label className="text-[11px]">Prioridad</Label>
                        <Input
                          type="number"
                          min={0}
                          max={1000}
                          value={rule.priority ?? 100}
                          onChange={(e) =>
                            updateRule(index, {
                              priority: Number.parseInt(e.target.value || "100", 10),
                            })
                          }
                          className="mt-1 text-sm"
                        />
                      </div>
                      <div>
                        <Label className="text-[11px]">Estado</Label>
                        <Button
                          type="button"
                          variant={rule.enabled ? "secondary" : "outline"}
                          className="mt-1 w-full justify-start"
                          onClick={() => updateRule(index, { enabled: !rule.enabled })}
                        >
                          <Power className="h-4 w-4" />
                          {rule.enabled ? "Activo" : "Inactivo"}
                        </Button>
                      </div>
                      <div className="flex items-end">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() =>
                            setRules((items) => items.filter((_, idx) => idx !== index))
                          }
                          title="Eliminar regla"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-md border bg-background p-3">
                      <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                        Cuando...
                      </div>
                      <div className="grid gap-2 md:grid-cols-[1fr_180px_1fr]">
                        <Input
                          value={rule.when.field}
                          onChange={(e) =>
                            updateRule(index, { when: { ...rule.when, field: e.target.value } })
                          }
                          placeholder="tiempo_empleo_meses"
                          className="font-mono text-xs"
                        />
                        <Select
                          value={rule.when.operator}
                          onValueChange={(operator) =>
                            updateRule(index, { when: { ...rule.when, operator } })
                          }
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {OPERATORS.map((operator) => (
                              <SelectItem key={operator} value={operator} className="text-xs">
                                {operator}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Input
                          value={valueToText(rule.when.value)}
                          onChange={(e) =>
                            updateRule(index, {
                              when: { ...rule.when, value: parseValue(e.target.value) },
                            })
                          }
                          placeholder="6"
                          className="font-mono text-xs"
                        />
                      </div>
                    </div>

                    <div className="rounded-md border bg-background p-3">
                      <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                        Entonces...
                      </div>
                      <div className="grid gap-2 md:grid-cols-3">
                        <Select
                          value={rule.then.set_action || "__none__"}
                          onValueChange={(value) =>
                            updateRule(
                              index,
                              thenPatch(rule, { set_action: value === "__none__" ? null : value }),
                            )
                          }
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue placeholder="action" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__" className="text-xs">
                              Sin action
                            </SelectItem>
                            {ACTIONS.map((action) => (
                              <SelectItem key={action} value={action} className="text-xs">
                                {action}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Select
                          value={rule.then.set_stage || "__none__"}
                          onValueChange={(value) =>
                            updateRule(
                              index,
                              thenPatch(rule, { set_stage: value === "__none__" ? null : value }),
                            )
                          }
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue placeholder="stage" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__" className="text-xs">
                              Sin stage
                            </SelectItem>
                            {stages.map((stage) => (
                              <SelectItem key={stage} value={stage} className="text-xs">
                                {stage}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Select
                          value={rule.then.set_flow_mode || "__none__"}
                          onValueChange={(value) =>
                            updateRule(
                              index,
                              thenPatch(rule, {
                                set_flow_mode: value === "__none__" ? null : value,
                              }),
                            )
                          }
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue placeholder="flow_mode" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__" className="text-xs">
                              Sin flow_mode
                            </SelectItem>
                            {FLOW_MODES.map((mode) => (
                              <SelectItem key={mode} value={mode} className="text-xs">
                                {mode}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="mt-2 grid gap-2 md:grid-cols-[1fr_170px]">
                        <Textarea
                          value={setDataToText(rule.then.set_data)}
                          onChange={(e) =>
                            updateRule(
                              index,
                              thenPatch(rule, { set_data: parseSetData(e.target.value) }),
                            )
                          }
                          placeholder={
                            "block_message = Enviar mensaje de bloqueo\nskip_documents = true"
                          }
                          className="min-h-20 font-mono text-xs"
                        />
                        <Select
                          value={
                            rule.then.pause_bot === true
                              ? "true"
                              : rule.then.pause_bot === false
                                ? "false"
                                : "__none__"
                          }
                          onValueChange={(value) =>
                            updateRule(
                              index,
                              thenPatch(rule, {
                                pause_bot: value === "__none__" ? null : value === "true",
                              }),
                            )
                          }
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__" className="text-xs">
                              No tocar bot
                            </SelectItem>
                            <SelectItem value="true" className="text-xs">
                              Pausar bot
                            </SelectItem>
                            <SelectItem value="false" className="text-xs">
                              Mantener bot activo
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                      <p className="text-xs text-muted-foreground">{ruleSummary(rule)}</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={testingKey === key}
                        onClick={() => void runRuleTest(rule, key)}
                      >
                        {testingKey === key ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                        Probar regla
                      </Button>
                    </div>
                    {result ? (
                      <pre className="max-h-44 overflow-auto rounded-md border bg-background p-3 text-xs">
                        {JSON.stringify(result, null, 2)}
                      </pre>
                    ) : null}
                  </section>
                );
              })
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Datos para prueba</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea
                value={testData}
                onChange={(e) => setTestData(e.target.value)}
                className="min-h-40 font-mono text-xs"
              />
              <div className="space-y-2 text-xs text-muted-foreground">
                <p>
                  Usa una línea por campo: <code>campo = valor</code>.
                </p>
                <p>
                  Campos base: <code>stage</code>, <code>last_message</code>, <code>intent</code>,{" "}
                  <code>topic</code>, <code>sub_intent</code>, <code>confidence</code>.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Orden de ejecución</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              <p>Las reglas activas corren de menor a mayor prioridad.</p>
              <p>
                Si dos reglas tienen la misma prioridad, se respeta el orden en que fueron creadas.
              </p>
              <p>
                Las acciones de una regla posterior pueden sobrescribir stage, action o flow_mode.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

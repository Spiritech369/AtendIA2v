import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Gauge, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { type QosConfig, tenantsApi } from "@/features/config/api";

const DEFAULT_QOS: QosConfig = {
  enabled: false,
  debug_badges_enabled: true,
  fallback_on_timeout: false,
  pause_bot_on_budget_exceeded: false,
  response_slo_ms: 8000,
  nlu_timeout_ms: 3000,
  composer_timeout_ms: 5000,
  kb_timeout_ms: 2500,
  max_turn_cost_usd: 0.05,
  daily_ai_budget_usd: 25,
  max_messages_per_turn: 2,
  inbound_rate_limit_per_min: 60,
  outbound_rate_limit_per_min: 60,
  workflow_rate_limit_per_min: 120,
  dead_letter_after_attempts: 4,
};

type NumericKey = {
  [K in keyof QosConfig]: QosConfig[K] extends number ? K : never;
}[keyof QosConfig];

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  max,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value || 0))}
      />
    </div>
  );
}

function ToggleRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-md border p-3">
      <div>
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-muted-foreground">{description}</div>
      </div>
      <input
        type="checkbox"
        className="h-5 w-5 rounded border-input accent-primary"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </div>
  );
}

export function QosConfigEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["tenants", "qos-config"],
    queryFn: tenantsApi.getQosConfig,
  });
  const [draft, setDraft] = useState<QosConfig>(DEFAULT_QOS);

  useEffect(() => {
    if (query.data?.qos_config) setDraft({ ...DEFAULT_QOS, ...query.data.qos_config });
  }, [query.data]);

  const save = useMutation({
    mutationFn: () => tenantsApi.putQosConfig(draft),
    onSuccess: () => {
      toast.success("QoS guardado");
      void qc.invalidateQueries({ queryKey: ["tenants", "qos-config"] });
    },
    onError: (error) => toast.error("No se pudo guardar QoS", { description: error.message }),
  });

  const setBool = (key: keyof QosConfig) => (value: boolean) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const setNumber = (key: NumericKey) => (value: number) =>
    setDraft((current) => ({ ...current, [key]: value }));

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" />
            Quality of Service
          </CardTitle>
          <div className="text-xs text-muted-foreground">
            Políticas por cuenta para latencia, límites, fallback y visibilidad en debug.
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <ToggleRow
              title="Aplicar políticas QoS"
              description="Activa límites que pueden modificar comportamiento del bot."
              checked={draft.enabled}
              onChange={setBool("enabled")}
            />
            <ToggleRow
              title="Badges en debug"
              description="Muestra lento, costo alto, fallback o pausado en trazas."
              checked={draft.debug_badges_enabled}
              onChange={setBool("debug_badges_enabled")}
            />
            <ToggleRow
              title="Fallback por timeout"
              description="Si una llamada excede presupuesto, responde con fallback controlado."
              checked={draft.fallback_on_timeout}
              onChange={setBool("fallback_on_timeout")}
            />
            <ToggleRow
              title="Pausar por presupuesto"
              description="Si se supera presupuesto configurado, pausa automatizaciones del bot."
              checked={draft.pause_bot_on_budget_exceeded}
              onChange={setBool("pause_bot_on_budget_exceeded")}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gauge className="h-4 w-4" />
            Presupuestos de turno
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <NumberField
            label="SLO respuesta total (ms)"
            value={draft.response_slo_ms}
            min={1000}
            max={120000}
            onChange={setNumber("response_slo_ms")}
          />
          <NumberField
            label="Timeout NLU (ms)"
            value={draft.nlu_timeout_ms}
            min={500}
            max={60000}
            onChange={setNumber("nlu_timeout_ms")}
          />
          <NumberField
            label="Timeout Composer (ms)"
            value={draft.composer_timeout_ms}
            min={500}
            max={60000}
            onChange={setNumber("composer_timeout_ms")}
          />
          <NumberField
            label="Timeout KB/docs (ms)"
            value={draft.kb_timeout_ms}
            min={500}
            max={60000}
            onChange={setNumber("kb_timeout_ms")}
          />
          <NumberField
            label="Costo máximo por turno USD"
            value={draft.max_turn_cost_usd}
            step={0.001}
            max={100}
            onChange={setNumber("max_turn_cost_usd")}
          />
          <NumberField
            label="Presupuesto IA diario USD"
            value={draft.daily_ai_budget_usd}
            step={0.01}
            max={10000}
            onChange={setNumber("daily_ai_budget_usd")}
          />
          <NumberField
            label="Mensajes máximos por turno"
            value={draft.max_messages_per_turn}
            min={1}
            max={3}
            onChange={setNumber("max_messages_per_turn")}
          />
          <NumberField
            label="Intentos antes de DLQ"
            value={draft.dead_letter_after_attempts}
            min={1}
            max={20}
            onChange={setNumber("dead_letter_after_attempts")}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4" />
            Límites por minuto
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <NumberField
            label="Inbound"
            value={draft.inbound_rate_limit_per_min}
            min={1}
            max={10000}
            onChange={setNumber("inbound_rate_limit_per_min")}
          />
          <NumberField
            label="Outbound"
            value={draft.outbound_rate_limit_per_min}
            min={1}
            max={10000}
            onChange={setNumber("outbound_rate_limit_per_min")}
          />
          <NumberField
            label="Workflows"
            value={draft.workflow_rate_limit_per_min}
            min={1}
            max={10000}
            onChange={setNumber("workflow_rate_limit_per_min")}
          />
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "Guardando..." : "Guardar QoS"}
        </Button>
      </div>
    </div>
  );
}

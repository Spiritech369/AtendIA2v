import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Loader2, Plus, Power, Save, Trash2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { tenantsApi, type FollowupsConfig, type FollowupScheduleItem } from "@/features/config/api";

function kindForDelay(hours: number): string {
  if (hours === 3) return "3h_silence";
  if (hours === 12) return "12h_silence";
  return `silence_${hours}h`;
}

function emptyItem(): FollowupScheduleItem {
  return {
    kind: "silence_6h",
    delay_hours: 6,
    body: "Hola, ¿seguimos con tu tramite? Aqui estoy si necesitas ayuda.",
  };
}

function dateTimeLabel(iso: string): string {
  return new Intl.DateTimeFormat("es-MX", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function FollowupsConfigEditor() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["tenants", "followups-config"],
    queryFn: tenantsApi.getFollowupsConfig,
  });
  const [draft, setDraft] = useState<FollowupsConfig | null>(null);

  useEffect(() => {
    if (data?.followups_config) {
      setDraft(data.followups_config);
    }
  }, [data]);

  const stats = data?.stats ?? {};
  const hasPending = (stats.pending ?? 0) > 0;
  const dirty = useMemo(() => {
    if (!draft || !data?.followups_config) return false;
    return JSON.stringify(draft) !== JSON.stringify(data.followups_config);
  }, [draft, data]);

  const save = useMutation({
    mutationFn: tenantsApi.putFollowupsConfig,
    onSuccess: (next) => {
      queryClient.setQueryData(["tenants", "followups-config"], next);
      setDraft(next.followups_config);
      toast.success("Seguimientos guardados");
    },
    onError: (error: Error) => {
      toast.error("No se pudieron guardar", { description: error.message });
    },
  });

  const cancelPending = useMutation({
    mutationFn: tenantsApi.cancelPendingFollowups,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["tenants", "followups-config"] });
      toast.success(`${result.cancelled} seguimiento(s) cancelado(s)`);
    },
    onError: (error: Error) => {
      toast.error("No se pudieron cancelar", { description: error.message });
    },
  });

  if (isLoading || !draft) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4" />
            Seguimientos
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-36 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          No se pudo cargar la configuracion de seguimientos.
        </CardContent>
      </Card>
    );
  }

  function updateItem(index: number, patch: Partial<FollowupScheduleItem>) {
    setDraft((current) => {
      if (!current) return current;
      const schedule = current.schedule.map((item, i) => {
        if (i !== index) return item;
        const next = { ...item, ...patch };
        if (patch.delay_hours) next.kind = kindForDelay(patch.delay_hours);
        return next;
      });
      return { ...current, schedule };
    });
  }

  function removeItem(index: number) {
    setDraft((current) =>
      current ? { ...current, schedule: current.schedule.filter((_, i) => i !== index) } : current,
    );
  }

  function addItem() {
    setDraft((current) =>
      current && current.schedule.length < 5
        ? { ...current, schedule: [...current.schedule, emptyItem()] }
        : current,
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4" />
              Seguimientos automaticos
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={draft.enabled ? "default" : "secondary"}>
                {draft.enabled ? "Activos" : "Pausados"}
              </Badge>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setDraft({ ...draft, enabled: !draft.enabled })}
              >
                <Power className="mr-2 h-4 w-4" />
                {draft.enabled ? "Pausar" : "Activar"}
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!dirty || save.isPending}
                onClick={() => save.mutate(draft)}
              >
                {save.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                Guardar
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-4">
            {(["pending", "sent", "cancelled", "failed"] as const).map((key) => (
              <div key={key} className="rounded-md border px-3 py-2">
                <div className="text-xs text-muted-foreground">
                  {key === "pending"
                    ? "Pendientes"
                    : key === "sent"
                      ? "Enviados"
                      : key === "cancelled"
                        ? "Cancelados"
                        : "Fallidos"}
                </div>
                <div className="text-xl font-semibold">{stats[key] ?? 0}</div>
              </div>
            ))}
          </div>

          <Separator />

          <div className="space-y-3">
            {draft.schedule.map((item, index) => (
              <div key={`${item.kind}-${index}`} className="rounded-md border p-3">
                <div className="grid gap-3 lg:grid-cols-[140px_1fr_auto]">
                  <div className="space-y-2">
                    <Label>Horas</Label>
                    <Input
                      type="number"
                      min={1}
                      max={23}
                      value={item.delay_hours}
                      onChange={(event) =>
                        updateItem(index, {
                          delay_hours: Number.parseInt(event.target.value || "1", 10),
                        })
                      }
                    />
                    <Badge variant="outline">{item.kind}</Badge>
                  </div>
                  <div className="space-y-2">
                    <Label>Mensaje</Label>
                    <Textarea
                      className="min-h-24"
                      value={item.body}
                      onChange={(event) => updateItem(index, { body: event.target.value })}
                    />
                  </div>
                  <div className="flex items-start justify-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      disabled={draft.schedule.length <= 1}
                      onClick={() => removeItem(index)}
                      title="Quitar"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={draft.schedule.length >= 5}
              onClick={addItem}
            >
              <Plus className="mr-2 h-4 w-4" />
              Agregar seguimiento
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">Pendientes</CardTitle>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!hasPending || cancelPending.isPending}
              onClick={() => cancelPending.mutate()}
            >
              {cancelPending.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <XCircle className="mr-2 h-4 w-4" />
              )}
              Cancelar pendientes
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {data?.pending.length ? (
            <div className="divide-y rounded-md border">
              {data.pending.map((item) => (
                <div key={item.id} className="grid gap-2 px-3 py-2 text-sm sm:grid-cols-4">
                  <span className="font-medium">{item.phone_e164}</span>
                  <span className="text-muted-foreground">{item.customer_name ?? "Sin nombre"}</span>
                  <span>{item.kind}</span>
                  <span className="text-muted-foreground">{dateTimeLabel(item.run_at)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-md border border-dashed py-6 text-center text-sm text-muted-foreground">
              No hay seguimientos pendientes.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

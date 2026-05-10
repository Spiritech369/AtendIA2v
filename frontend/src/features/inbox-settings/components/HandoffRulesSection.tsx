import { ArrowDown, ArrowUp, Copy, GripVertical, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { HandoffRule, InboxConfig } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

const INTENT_STYLE: Record<string, string> = {
  ASK_PRICE:       "text-purple-700 bg-purple-50 dark:text-purple-300 dark:bg-purple-950/40",
  DOCS_MISSING:    "text-amber-700 bg-amber-50 dark:text-amber-300 dark:bg-amber-950/40",
  HUMAN_REQUESTED: "text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-950/40",
  STALE_24H:       "text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-950/40",
};

export function HandoffRulesSection({ draft, patchDraft, canEdit }: Props) {
  const rules = [...draft.handoff_rules].sort((a, b) => a.order - b.order);

  const update = (id: string, patch: Partial<HandoffRule>) => {
    patchDraft({
      handoff_rules: draft.handoff_rules.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    });
  };

  const move = (id: string, dir: -1 | 1) => {
    const sorted = [...rules];
    const idx = sorted.findIndex((r) => r.id === id);
    const target = idx + dir;
    if (target < 0 || target >= sorted.length) return;
    const a = sorted[idx]!;
    const b = sorted[target]!;
    patchDraft({
      handoff_rules: draft.handoff_rules.map((r) => {
        if (r.id === a.id) return { ...r, order: b.order };
        if (r.id === b.id) return { ...r, order: a.order };
        return r;
      }),
    });
  };

  const duplicate = (rule: HandoffRule) => {
    patchDraft({
      handoff_rules: [
        ...draft.handoff_rules,
        {
          ...rule,
          id: crypto.randomUUID(),
          intent: `${rule.intent}_COPIA`,
          order: draft.handoff_rules.length,
        },
      ],
    });
  };

  const remove = (id: string) => {
    patchDraft({ handoff_rules: draft.handoff_rules.filter((r) => r.id !== id) });
  };

  const add = () => {
    patchDraft({
      handoff_rules: [
        ...draft.handoff_rules,
        {
          id: crypto.randomUUID(),
          intent: "NUEVA_INTENCION",
          confidence: 80,
          action: "suggest_template",
          template: "",
          enabled: true,
          order: draft.handoff_rules.length,
        },
      ],
    });
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
        <strong>Nota:</strong> Estos ajustes configuran el motor IA. Actualmente son UI-only — la
        conexión al runner es una tarea separada.
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="text-sm">Reglas de handoff IA</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Cuándo la IA responde automáticamente y cuándo transfiere a un operador humano.
              </p>
            </div>
            {canEdit && (
              <Button variant="outline" size="sm" onClick={add} className="h-7 text-xs">
                <Plus className="mr-1 h-3 w-3" /> Nueva regla
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {rules.map((rule, idx) => (
            <div
              key={rule.id}
              className={cn(
                "rounded-lg border bg-card p-3 space-y-2 transition-opacity",
                !rule.enabled && "opacity-60",
              )}
            >
              {/* Top row */}
              <div className="flex items-center gap-2">
                {/* Order arrows */}
                <div className="flex flex-col gap-0.5 shrink-0 text-muted-foreground">
                  <button
                    type="button"
                    disabled={idx === 0 || !canEdit}
                    onClick={() => move(rule.id, -1)}
                    className="hover:text-foreground disabled:opacity-20"
                  >
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <GripVertical className="h-3 w-3 opacity-30" />
                  <button
                    type="button"
                    disabled={idx === rules.length - 1 || !canEdit}
                    onClick={() => move(rule.id, 1)}
                    className="hover:text-foreground disabled:opacity-20"
                  >
                    <ArrowDown className="h-3 w-3" />
                  </button>
                </div>

                {/* Intent badge */}
                <span
                  className={cn(
                    "shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold",
                    INTENT_STYLE[rule.intent] ?? "bg-muted text-foreground",
                  )}
                >
                  {rule.intent}
                </span>

                <span className="text-xs text-muted-foreground shrink-0">→</span>

                {/* Action */}
                <Input
                  value={rule.action}
                  onChange={(e) => update(rule.id, { action: e.target.value })}
                  disabled={!canEdit}
                  className="h-6 flex-1 text-xs"
                  placeholder="acción"
                />

                {/* Confidence bar + input */}
                <div className="flex items-center gap-1 shrink-0">
                  <div className="h-1.5 w-10 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${rule.confidence}%` }}
                    />
                  </div>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={rule.confidence}
                    onChange={(e) => update(rule.id, { confidence: Number(e.target.value) })}
                    disabled={!canEdit}
                    className="h-6 w-11 p-1 font-mono text-[10px]"
                  />
                  <span className="text-[9px] text-muted-foreground">%</span>
                </div>

                {/* Enabled toggle */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => update(rule.id, { enabled: !rule.enabled })}
                  className={cn(
                    "relative h-4 w-8 shrink-0 rounded-full transition-colors",
                    rule.enabled ? "bg-primary" : "bg-input",
                    !canEdit && "cursor-not-allowed",
                  )}
                  aria-label={rule.enabled ? "Desactivar regla" : "Activar regla"}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform",
                      rule.enabled ? "translate-x-4" : "translate-x-0.5",
                    )}
                  />
                </button>

                {/* Duplicate */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => duplicate(rule)}
                  title="Duplicar regla"
                  className="shrink-0 text-muted-foreground hover:text-foreground disabled:opacity-30"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>

                {/* Delete */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => remove(rule.id)}
                  title="Eliminar regla"
                  className="shrink-0 text-muted-foreground hover:text-destructive disabled:opacity-30"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Bottom row — intent + template */}
              <div className="flex items-center gap-2 pl-5">
                <span className="shrink-0 text-[9px] uppercase tracking-wider text-muted-foreground">
                  Intent
                </span>
                <Input
                  value={rule.intent}
                  onChange={(e) => update(rule.id, { intent: e.target.value.toUpperCase() })}
                  disabled={!canEdit}
                  className="h-6 w-40 font-mono text-[10px]"
                  placeholder="INTENT_NAME"
                />
                <span className="shrink-0 text-[9px] uppercase tracking-wider text-muted-foreground">
                  Plantilla
                </span>
                <Input
                  value={rule.template}
                  onChange={(e) => update(rule.id, { template: e.target.value })}
                  disabled={!canEdit}
                  className="h-6 flex-1 font-mono text-[10px]"
                  placeholder="nombre_plantilla (opcional)"
                />
              </div>
            </div>
          ))}

          {rules.length === 0 && (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Sin reglas. Agrega una para empezar.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

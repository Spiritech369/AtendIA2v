import { ArrowDown, ArrowUp, Eye, EyeOff, GripVertical, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { FilterChip, InboxConfig } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

export function FilterChipsSection({ draft, patchDraft, canEdit }: Props) {
  const chips = [...draft.filter_chips].sort((a, b) => a.order - b.order);

  const update = (id: string, patch: Partial<FilterChip>) => {
    patchDraft({
      filter_chips: draft.filter_chips.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    });
  };

  const move = (id: string, dir: -1 | 1) => {
    const sorted = [...chips];
    const idx = sorted.findIndex((c) => c.id === id);
    const target = idx + dir;
    if (target < 0 || target >= sorted.length) return;
    const a = sorted[idx]!;
    const b = sorted[target]!;
    const reordered = draft.filter_chips.map((c) => {
      if (c.id === a.id) return { ...c, order: b.order };
      if (c.id === b.id) return { ...c, order: a.order };
      return c;
    });
    patchDraft({ filter_chips: reordered });
  };

  const remove = (id: string) => {
    patchDraft({ filter_chips: draft.filter_chips.filter((c) => c.id !== id) });
  };

  const add = () => {
    const newChip: FilterChip = {
      id: crypto.randomUUID(),
      label: "Nuevo filtro",
      color: "#4f72f5",
      query: "",
      live_count: false,
      visible: true,
      order: chips.length,
    };
    patchDraft({ filter_chips: [...draft.filter_chips, newChip] });
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="text-sm">Chips de filtro</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Aparecen en la barra superior de la bandeja. Usa las flechas para reordenar.
              </p>
            </div>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
              {chips.filter((c) => c.visible).length} activos
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Live preview strip */}
          <div className="flex flex-wrap gap-1.5 rounded-lg border bg-muted/30 px-3 py-2">
            {chips
              .filter((c) => c.visible)
              .map((chip, i) => (
                <span
                  key={chip.id}
                  className="flex items-center gap-1 rounded-md px-2 py-0.5 text-[10.5px] font-medium"
                  style={{ background: `${chip.color}1a`, color: chip.color }}
                >
                  {chip.label}
                  {chip.live_count && (
                    <span
                      className="rounded px-1 text-[9px] font-bold text-white"
                      style={{ background: chip.color }}
                    >
                      {i === 0 ? "21" : Math.floor(Math.random() * 15) + 1}
                    </span>
                  )}
                </span>
              ))}
            {chips.filter((c) => c.visible).length === 0 && (
              <span className="text-[10px] text-muted-foreground">Sin chips visibles</span>
            )}
          </div>

          {/* Chip rows */}
          <div className="space-y-1.5">
            {chips.map((chip, idx) => (
              <div
                key={chip.id}
                className={cn(
                  "flex items-center gap-2 rounded-lg border bg-card p-2 transition-opacity",
                  !chip.visible && "opacity-50",
                )}
              >
                {/* Order arrows */}
                <div className="flex flex-col gap-0.5 text-muted-foreground">
                  <button
                    type="button"
                    disabled={idx === 0 || !canEdit}
                    onClick={() => move(chip.id, -1)}
                    className="p-0.5 hover:text-foreground disabled:opacity-20"
                    title="Subir"
                  >
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <GripVertical className="h-3 w-3 opacity-40" />
                  <button
                    type="button"
                    disabled={idx === chips.length - 1 || !canEdit}
                    onClick={() => move(chip.id, 1)}
                    className="p-0.5 hover:text-foreground disabled:opacity-20"
                    title="Bajar"
                  >
                    <ArrowDown className="h-3 w-3" />
                  </button>
                </div>

                {/* Color dot */}
                <div className="relative h-5 w-5 shrink-0">
                  <div
                    className="h-5 w-5 rounded-md border border-border/50"
                    style={{ background: chip.color }}
                  />
                  {canEdit && (
                    <input
                      type="color"
                      value={chip.color}
                      onChange={(e) => update(chip.id, { color: e.target.value })}
                      className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                      title="Cambiar color"
                    />
                  )}
                </div>

                {/* Label */}
                <Input
                  value={chip.label}
                  onChange={(e) => update(chip.id, { label: e.target.value })}
                  disabled={!canEdit}
                  className="h-7 w-36 shrink-0 text-xs"
                  placeholder="Nombre del filtro"
                />

                {/* Query */}
                <Input
                  value={chip.query}
                  onChange={(e) => update(chip.id, { query: e.target.value })}
                  disabled={!canEdit}
                  className="h-7 flex-1 font-mono text-[10px]"
                  placeholder="expresión de filtro…"
                />

                {/* Live count badge */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => update(chip.id, { live_count: !chip.live_count })}
                  title="Conteo en vivo"
                  className={cn(
                    "shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold border transition-colors",
                    chip.live_count
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/30",
                    !canEdit && "cursor-not-allowed",
                  )}
                >
                  LIVE
                </button>

                {/* Visibility toggle */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => update(chip.id, { visible: !chip.visible })}
                  title={chip.visible ? "Ocultar chip" : "Mostrar chip"}
                  className={cn(
                    "shrink-0 text-muted-foreground transition-colors hover:text-foreground",
                    !canEdit && "cursor-not-allowed",
                  )}
                >
                  {chip.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                </button>

                {/* Delete */}
                <button
                  type="button"
                  disabled={!canEdit}
                  onClick={() => remove(chip.id)}
                  title="Eliminar"
                  className={cn(
                    "shrink-0 text-muted-foreground transition-colors hover:text-destructive",
                    !canEdit && "cursor-not-allowed",
                  )}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>

          {canEdit && (
            <Button variant="outline" size="sm" onClick={add} className="w-full text-xs">
              <Plus className="mr-1 h-3 w-3" /> Agregar filtro
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

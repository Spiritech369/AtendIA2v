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
import { cn } from "@/lib/utils";
import type { InboxConfig } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

export function InboxLayoutSection({ draft, patchDraft, canEdit }: Props) {
  const { layout } = draft;
  const set = (patch: Partial<typeof layout>) =>
    patchDraft({ layout: { ...layout, ...patch } });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Diseño de bandeja</CardTitle>
          <p className="text-xs text-muted-foreground">
            Estructura de paneles visible para todos los operadores.
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Layout mode */}
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Modo de paneles</Label>
            <div className="grid grid-cols-2 gap-3">
              {(
                [
                  { value: true, label: "Tres paneles", desc: "Filtros · Lista · Chat", cols: [14, 40, 60] },
                  { value: false, label: "Dos paneles", desc: "Lista · Chat (sin rail)", cols: [40, 60] },
                ] as const
              ).map(({ value, label, desc, cols }) => (
                <button
                  key={String(value)}
                  type="button"
                  disabled={!canEdit}
                  onClick={() => set({ three_pane: value })}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors",
                    layout.three_pane === value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-muted-foreground/40",
                    !canEdit && "cursor-not-allowed opacity-60",
                  )}
                >
                  <p className="text-xs font-medium">{label}</p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">{desc}</p>
                  <div className="mt-2 flex h-4 gap-1">
                    {cols.map((w, i) => (
                      <div
                        key={i}
                        className="rounded-sm bg-muted-foreground/30"
                        style={{ width: w }}
                      />
                    ))}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Rail width */}
          <div className="flex items-center gap-3">
            <Label className="w-40 shrink-0 text-xs">Rail de filtros</Label>
            <Select
              value={layout.rail_width}
              onValueChange={(v) => set({ rail_width: v as "collapsed" | "expanded" })}
              disabled={!canEdit}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="expanded" className="text-xs">
                  Expandido — 200px
                </SelectItem>
                <SelectItem value="collapsed" className="text-xs">
                  Colapsado — 60px
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* List max width */}
          <div className="flex items-center gap-3">
            <Label className="w-40 shrink-0 text-xs">Lista máx. ancho</Label>
            <Input
              type="number"
              min={240}
              max={480}
              step={10}
              className="h-8 w-24 font-mono text-xs"
              value={layout.list_max_width}
              disabled={!canEdit}
              onChange={(e) => set({ list_max_width: Number(e.target.value) || 360 })}
            />
            <span className="text-xs text-muted-foreground">px</span>
          </div>

          {/* Composer density */}
          <div className="flex items-center gap-3">
            <Label className="w-40 shrink-0 text-xs">Densidad composer</Label>
            <Select
              value={layout.composer_density}
              onValueChange={(v) => set({ composer_density: v as "compact" | "comfortable" })}
              disabled={!canEdit}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="comfortable" className="text-xs">
                  Comfortable
                </SelectItem>
                <SelectItem value="compact" className="text-xs">
                  Compact
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Sticky composer */}
          <div className="flex items-center gap-3">
            <Label className="w-40 shrink-0 text-xs">Composer sticky</Label>
            <button
              type="button"
              disabled={!canEdit}
              onClick={() => set({ sticky_composer: !layout.sticky_composer })}
              className={cn(
                "relative h-5 w-9 rounded-full transition-colors",
                layout.sticky_composer ? "bg-primary" : "bg-input",
                !canEdit && "cursor-not-allowed opacity-60",
              )}
              aria-label={layout.sticky_composer ? "Desactivar sticky composer" : "Activar sticky composer"}
            >
              <span
                className={cn(
                  "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                  layout.sticky_composer ? "translate-x-4" : "translate-x-0.5",
                )}
              />
            </button>
            <span
              className={cn(
                "text-xs",
                layout.sticky_composer
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-muted-foreground",
              )}
            >
              {layout.sticky_composer ? "Activo" : "Inactivo"}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

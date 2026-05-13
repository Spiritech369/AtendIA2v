import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const MODE_MAP: Record<string, { label: string; classes: string }> = {
  PLAN: {
    label: "Planes",
    classes: "bg-blue-500/15 text-blue-700 border-blue-500/30",
  },
  SALES: {
    label: "Ventas",
    classes: "bg-emerald-500/15 text-emerald-700 border-emerald-500/30",
  },
  DOC: {
    label: "Documentos",
    classes: "bg-purple-500/15 text-purple-700 border-purple-500/30",
  },
  OBSTACLE: {
    label: "Obstáculo",
    classes: "bg-amber-500/15 text-amber-700 border-amber-500/30",
  },
  RETENTION: {
    label: "Retención",
    classes: "bg-rose-500/15 text-rose-700 border-rose-500/30",
  },
  SUPPORT: {
    label: "Soporte",
    classes: "bg-slate-500/15 text-slate-700 border-slate-500/30",
  },
};

export function FlowModeBadge({ mode }: { mode: string | null }) {
  if (!mode) {
    return <span className="text-muted-foreground">—</span>;
  }
  const entry = MODE_MAP[mode];
  if (!entry) {
    return (
      <Badge variant="outline" className="font-mono text-[10px]">
        {mode}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className={cn("font-medium", entry.classes)}>
      {entry.label}
    </Badge>
  );
}

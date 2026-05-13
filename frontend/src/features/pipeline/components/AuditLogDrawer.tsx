/**
 * M6 of the pipeline-automation editor plan.
 *
 * Slide-in panel showing pipeline-related audit events. Two flavours
 * combined by the backend:
 *
 *   - admin.pipeline.* events (pipeline.saved, pipeline.deleted) so
 *     operators see who saved or wiped the pipeline and when.
 *   - stage_entered / stage_exited events emitted by the runner every
 *     time a conversation moves — both FSM and auto_enter_rules
 *     transitions land here.
 *
 * The drawer is intentionally read-only. Editing the audit log would
 * defeat its purpose. Future work: filter by event type, scroll
 * pagination, deep-link to the conversation that moved.
 */
import { useQuery } from "@tanstack/react-query";
import { Clock, FileEdit, MoveRight, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { AuditLogEntry } from "@/features/config/api";
import { tenantsApi } from "@/features/config/api";

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (diffMs < 60_000) return "ahora";
  const min = Math.round(diffMs / 60_000);
  if (min < 60) return `hace ${min}m`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h}h`;
  const d = Math.round(h / 24);
  return `hace ${d}d`;
}

function EntryRow({ entry }: { entry: AuditLogEntry }) {
  const isAutoMove = entry.type === "stage_entered" || entry.type === "stage_exited";
  const isSave = entry.type === "admin.pipeline.saved";
  const isDelete = entry.type === "admin.pipeline.deleted";
  const Icon = isDelete
    ? Trash2
    : isSave
      ? FileEdit
      : isAutoMove
        ? MoveRight
        : Clock;
  const tone = isDelete
    ? "text-destructive"
    : isAutoMove
      ? "text-blue-500"
      : isSave
        ? "text-emerald-500"
        : "text-muted-foreground";

  return (
    <li className="flex gap-2.5 border-b py-2 last:border-b-0">
      <Icon className={`mt-0.5 size-3.5 shrink-0 ${tone}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">{describeAction(entry)}</span>
          <Badge
            variant="outline"
            className="px-1 py-0 font-mono text-[9px] text-muted-foreground"
          >
            {entry.type}
          </Badge>
        </div>
        <div className="mt-0.5 text-[10px] text-muted-foreground">
          {formatRelative(entry.occurred_at)}
          {entry.actor_user_id
            ? ` · usuario ${entry.actor_user_id.slice(0, 8)}`
            : entry.conversation_id
              ? ` · conv ${entry.conversation_id.slice(0, 8)}`
              : " · sistema"}
        </div>
        {Object.keys(entry.payload).length > 0 && (
          <pre className="mt-1 max-h-24 overflow-auto rounded bg-muted/40 px-1.5 py-1 font-mono text-[9px] leading-snug">
            {JSON.stringify(entry.payload, null, 2)}
          </pre>
        )}
      </div>
    </li>
  );
}

function describeAction(entry: AuditLogEntry): string {
  switch (entry.type) {
    case "admin.pipeline.saved": {
      const v = entry.payload.version;
      const n = entry.payload.stage_count;
      return `Pipeline guardado${typeof v === "number" ? ` (v${v})` : ""}${typeof n === "number" ? ` · ${n} etapas` : ""}`;
    }
    case "admin.pipeline.deleted":
      return "Pipeline eliminado (todas las versiones)";
    case "stage_entered":
      return `Conversación entró a ${stagePayload(entry.payload, "to")}`;
    case "stage_exited":
      return `Conversación salió de ${stagePayload(entry.payload, "from")}`;
    default:
      return entry.type;
  }
}

function stagePayload(payload: Record<string, unknown>, key: string): string {
  const v = payload[key];
  return typeof v === "string" && v.length > 0 ? v : "?";
}

export function AuditLogDrawer({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const query = useQuery({
    queryKey: ["pipeline", "audit-log"],
    queryFn: () => tenantsApi.getPipelineAuditLog({ limit: 50 }),
    enabled: open,
    staleTime: 30_000,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] flex-col">
        <SheetHeader>
          <SheetTitle>Historial</SheetTitle>
          <SheetDescription>
            Cambios al pipeline y movimientos de etapa, ordenados por más
            recientes primero.
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto pr-1">
          {query.isLoading && (
            <div className="space-y-2 pt-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}
          {query.isError && (
            <p className="pt-3 text-xs text-destructive">
              No se pudo cargar el historial. Intenta de nuevo.
            </p>
          )}
          {query.data && query.data.entries.length === 0 && (
            <p className="pt-3 text-xs text-muted-foreground">
              Aún no hay eventos. Aparecerán aquí cuando guardes el pipeline o
              cuando una conversación cambie de etapa.
            </p>
          )}
          {query.data && query.data.entries.length > 0 && (
            <ul>
              {query.data.entries.map((e) => (
                <EntryRow key={e.id} entry={e} />
              ))}
            </ul>
          )}
          {query.data?.has_more && (
            <p className="pb-2 pt-1 text-center text-[10px] text-muted-foreground">
              Hay más eventos — paginación próximamente.
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

import { CheckCircle2, Clock3, FileSearch, ShieldAlert, XCircle } from "lucide-react";
import type { ElementType } from "react";

import { Badge } from "@/components/ui/badge";
import {
  fieldStatusMeta,
  formatValue,
  type TenantFieldView,
} from "@/features/turn-traces/lib/universalTrace";
import { cn } from "@/lib/utils";

const STATUS_ICON: Record<TenantFieldView["status"], ElementType> = {
  validated: CheckCircle2,
  proposed: Clock3,
  needs_review: FileSearch,
  rejected: XCircle,
  blocked: ShieldAlert,
};

interface TenantFieldPanelProps {
  fields: TenantFieldView[];
  safeMode?: boolean;
  metadataMissing?: boolean;
}

export function TenantFieldPanel({
  fields,
  safeMode = false,
  metadataMissing = false,
}: TenantFieldPanelProps) {
  const grouped = groupFields(fields);

  if (fields.length === 0) {
    return (
      <section className="rounded-md border bg-muted/20 p-2.5">
        <PanelTitle safeMode={safeMode} metadataMissing />
        <div className="mt-2 text-xs text-muted-foreground">
          Sin metadata declarativa de campos para este tenant.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-md border bg-card p-2.5" aria-label="Campos del tenant">
      <PanelTitle safeMode={safeMode} metadataMissing={metadataMissing} />
      <div className="mt-2 space-y-2">
        {grouped.map(([group, groupFields]) => (
          <div key={group} className="space-y-1.5">
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {group}
            </div>
            <div className="grid grid-cols-1 gap-1.5">
              {groupFields.map((field) => (
                <TenantFieldRow key={field.key} field={field} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function PanelTitle({
  safeMode,
  metadataMissing,
}: {
  safeMode: boolean;
  metadataMissing: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="text-xs font-semibold">Campos del tenant</div>
      <div className="flex flex-wrap gap-1">
        {safeMode && (
          <Badge
            variant="outline"
            className="border-amber-500/40 bg-amber-500/10 text-[10px] text-amber-700"
          >
            safe_mode
          </Badge>
        )}
        {metadataMissing && (
          <Badge variant="outline" className="text-[10px]">
            metadata_missing
          </Badge>
        )}
      </div>
    </div>
  );
}

function TenantFieldRow({ field }: { field: TenantFieldView }) {
  const meta = fieldStatusMeta(field.status);
  const Icon = STATUS_ICON[field.status];
  return (
    <div className="rounded-md border bg-muted/20 px-2 py-1.5 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{field.label}</div>
          <div className="mt-0.5 break-words text-[12px] text-foreground/90">
            {formatValue(field.value)}
          </div>
        </div>
        <Badge variant="outline" className={cn("shrink-0 text-[10px]", meta.className)}>
          <Icon className="h-3 w-3" />
          {meta.label}
        </Badge>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
        {field.domainRole && <span>role: {field.domainRole}</span>}
        {field.source && <span>source: {field.source}</span>}
        {field.writer && <span>writer: {field.writer}</span>}
        {field.confidence != null && <span>confidence: {Math.round(field.confidence * 100)}%</span>}
        {field.lastTraceId && <span>trace: {field.lastTraceId}</span>}
        {field.evidenceRefs.length > 0 && <span>evidence: {field.evidenceRefs.join(", ")}</span>}
      </div>
    </div>
  );
}

function groupFields(fields: TenantFieldView[]): Array<[string, TenantFieldView[]]> {
  const grouped = new Map<string, TenantFieldView[]>();
  for (const field of fields) {
    const group = field.group || "general";
    grouped.set(group, [...(grouped.get(group) ?? []), field]);
  }
  return Array.from(grouped.entries());
}

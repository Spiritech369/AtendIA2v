import { WhatsAppStatusBadge } from "@/components/WhatsAppStatusBadge";
import { Separator } from "@/components/ui/separator";

interface Props {
  tenantId: string | null | undefined;
  compact: boolean;
}

/**
 * Sidebar header block: brand mark + tenant identifier + WhatsApp pulse.
 * In compact mode only the brand cube remains visible.
 */
export function SidebarHeader({ tenantId, compact }: Props) {
  return (
    <>
      <div className="flex h-14 shrink-0 items-center gap-2 px-4">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
          AI
        </span>
        {!compact && (
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">AtendIA</div>
            <div className="truncate text-[10px] text-muted-foreground">
              {tenantId ? `Tenant ${tenantId.slice(0, 8)}` : "Sin tenant"}
            </div>
          </div>
        )}
      </div>
      {!compact && (
        <div className="px-4 pb-3">
          <WhatsAppStatusBadge />
        </div>
      )}
      <Separator />
    </>
  );
}

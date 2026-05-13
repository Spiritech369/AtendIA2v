import { cn } from "@/lib/utils";

export type SidebarBadgeVariant = "default" | "destructive";

/**
 * Compact count chip rendered inside SidebarItem.
 * Hidden when value is 0 (no point yelling at the operator about nothing).
 * Caps at "99+" so it never breaks the row layout.
 */
export function SidebarBadge({
  value,
  variant = "default",
}: {
  value: number;
  variant?: SidebarBadgeVariant;
}) {
  if (value <= 0) return null;
  return (
    <span
      className={cn(
        "ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums",
        variant === "destructive" ? "bg-red-500/15 text-red-600" : "bg-primary/15 text-primary",
      )}
    >
      {value > 99 ? "99+" : value}
    </span>
  );
}

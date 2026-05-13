import { Link } from "@tanstack/react-router";

import type { NavItem } from "@/features/navigation/types";
import { cn } from "@/lib/utils";

import { SidebarBadge, type SidebarBadgeVariant } from "./SidebarBadge";

interface Props {
  item: NavItem;
  active: boolean;
  compact: boolean;
  badgeValue?: number;
  badgeVariant?: SidebarBadgeVariant;
}

/**
 * Single nav row. Wraps a TanStack Router `<Link>` so the router handles
 * client-side navigation. `aria-current="page"` set when active so screen
 * readers and keyboard users get the right cue.
 */
export function SidebarItem({
  item,
  active,
  compact,
  badgeValue,
  badgeVariant = "default",
}: Props) {
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      aria-current={active ? "page" : undefined}
      title={compact ? item.label : undefined}
      className={cn(
        "group/item relative flex items-center gap-3 rounded-md px-3 py-1.5 text-sm transition-colors",
        active
          ? "bg-primary/10 text-foreground font-medium"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-primary"
        />
      )}
      <Icon className="h-4 w-4 shrink-0" />
      {!compact && <span className="truncate">{item.label}</span>}
      {!compact && badgeValue !== undefined && (
        <SidebarBadge value={badgeValue} variant={badgeVariant} />
      )}
    </Link>
  );
}

/**
 * Helper used by SidebarGroup to compute whether a route matches the
 * current pathname. Exported so callers/tests can reuse the logic.
 */
export function isItemActive(item: NavItem, path: string): boolean {
  if (item.exactMatch) {
    if (path === item.to) return true;
    if (item.activeAlsoOn) {
      return item.activeAlsoOn.some((p) => path === p || path.startsWith(`${p}/`));
    }
    return false;
  }
  return path === item.to || path.startsWith(`${item.to}/`);
}

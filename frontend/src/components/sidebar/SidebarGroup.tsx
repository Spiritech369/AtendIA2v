import { ChevronDown } from "lucide-react";

import type { NavigationBadges } from "@/features/navigation/api";
import type { NavGroup } from "@/features/navigation/types";
import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/stores/sidebar-store";

import { isItemActive, SidebarItem } from "./SidebarItem";

interface Props {
  group: NavGroup;
  compact: boolean;
  activePath: string;
  badges: NavigationBadges | undefined;
}

/**
 * Group header (collapsible in expanded mode) + ordered items.
 * In compact mode the header is hidden; items render as a flat list of
 * icons so the sidebar still groups visually via spacing.
 */
export function SidebarGroup({ group, compact, activePath, badges }: Props) {
  const expanded = useSidebarStore((s) => s.isGroupExpanded(group.id));
  const toggle = useSidebarStore((s) => s.toggleGroup);

  return (
    <div className="px-2">
      {!compact && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => toggle(group.id)}
          className="flex w-full items-center justify-between rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground transition-colors hover:text-foreground"
        >
          <span>{group.label}</span>
          <ChevronDown
            className={cn(
              "h-3 w-3 transition-transform",
              !expanded && "-rotate-90",
            )}
          />
        </button>
      )}
      {(compact || expanded) && (
        <div className="mt-0.5 flex flex-col gap-0.5">
          {group.items.map((item) => {
            const value = item.badgeKey ? badges?.[item.badgeKey] : undefined;
            const isOverdueHandoff =
              item.id === "handoffs" && (badges?.handoffs_overdue ?? 0) > 0;
            return (
              <SidebarItem
                key={item.id}
                item={item}
                active={isItemActive(item, activePath)}
                compact={compact}
                badgeValue={value}
                badgeVariant={isOverdueHandoff ? "destructive" : "default"}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

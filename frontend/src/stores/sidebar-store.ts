import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SidebarState {
  compact: boolean;
  expandedGroups: Record<string, boolean>;
  toggleCompact: () => void;
  toggleGroup: (groupId: string) => void;
  isGroupExpanded: (groupId: string) => boolean;
}

/**
 * Persisted UI state for the sidebar:
 * - `compact`: icons-only mode (still navigable via tooltips).
 * - `expandedGroups`: per-group open/closed; defaults to open when key absent.
 *
 * Persisted to localStorage under `atendia.sidebar.v1`. Bump the suffix
 * if the shape changes incompatibly.
 */
export const useSidebarStore = create<SidebarState>()(
  persist(
    (set, get) => ({
      compact: false,
      expandedGroups: {},
      toggleCompact: () => set((s) => ({ compact: !s.compact })),
      toggleGroup: (groupId) =>
        set((s) => ({
          expandedGroups: {
            ...s.expandedGroups,
            [groupId]: !(s.expandedGroups[groupId] ?? true),
          },
        })),
      isGroupExpanded: (groupId) => get().expandedGroups[groupId] ?? true,
    }),
    {
      name: "atendia.sidebar.v1",
      partialize: (state) => ({
        compact: state.compact,
        expandedGroups: state.expandedGroups,
      }),
    },
  ),
);

import type { LucideIcon } from "lucide-react";

import type { Role } from "@/stores/auth";

export type BadgeKey =
  | "conversations_open"
  | "handoffs_open"
  | "appointments_today"
  | "ai_debug_warnings"
  | "unread_notifications";

export interface NavItem {
  id: string;
  label: string;
  to: string;
  icon: LucideIcon;
  roles: readonly Role[];
  badgeKey?: BadgeKey;
  /** Exact-path match only (e.g. "/" should not match every route). */
  exactMatch?: boolean;
  /** Extra path prefixes that also count as "active" (e.g. "/conversations" for "/"). */
  activeAlsoOn?: readonly string[];
}

export interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
}

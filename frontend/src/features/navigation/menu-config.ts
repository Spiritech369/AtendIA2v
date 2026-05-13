import {
  BarChart3,
  BookOpen,
  Bug,
  CalendarDays,
  Columns3,
  Database,
  FileText,
  LayoutDashboard,
  MessageCircle,
  Network,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";

import type { Role } from "@/stores/auth";

import type { NavGroup } from "./types";

const OPERATOR_PLUS: readonly Role[] = ["operator", "tenant_admin", "superadmin"];
const TENANT_ADMIN_PLUS: readonly Role[] = ["tenant_admin", "superadmin"];
const SUPERADMIN_ONLY: readonly Role[] = ["superadmin"];

export const NAV_GROUPS: NavGroup[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    items: [
      {
        id: "dashboard",
        label: "Dashboard",
        to: "/dashboard",
        icon: LayoutDashboard,
        roles: OPERATOR_PLUS,
      },
    ],
  },
  {
    id: "operacion",
    label: "Operación",
    items: [
      {
        id: "conversations",
        label: "Conversaciones",
        to: "/",
        icon: MessageCircle,
        roles: OPERATOR_PLUS,
        exactMatch: true,
        activeAlsoOn: ["/conversations"],
        badgeKey: "conversations_open",
      },
      {
        id: "handoffs",
        label: "Handoffs",
        to: "/handoffs",
        icon: ShieldCheck,
        roles: OPERATOR_PLUS,
        badgeKey: "handoffs_open",
      },
      {
        id: "pipeline",
        label: "Pipeline",
        to: "/pipeline",
        icon: Columns3,
        roles: OPERATOR_PLUS,
      },
      {
        id: "customers",
        label: "Clientes",
        to: "/customers",
        icon: Users,
        roles: OPERATOR_PLUS,
      },
      {
        id: "appointments",
        label: "Citas",
        to: "/appointments",
        icon: CalendarDays,
        roles: OPERATOR_PLUS,
        badgeKey: "appointments_today",
      },
    ],
  },
  {
    id: "ia",
    label: "Inteligencia IA",
    items: [
      {
        id: "agents",
        label: "Agentes IA",
        to: "/agents",
        icon: Sparkles,
        roles: TENANT_ADMIN_PLUS,
      },
      {
        id: "knowledge",
        label: "Conocimiento",
        to: "/knowledge",
        icon: BookOpen,
        roles: OPERATOR_PLUS,
      },
      {
        id: "turn-traces",
        label: "Debug de turnos",
        to: "/turn-traces",
        icon: Bug,
        roles: OPERATOR_PLUS,
        badgeKey: "ai_debug_warnings",
      },
    ],
  },
  {
    id: "automation",
    label: "Automatización",
    items: [
      {
        id: "workflows",
        label: "Workflows",
        to: "/workflows",
        icon: Network,
        roles: OPERATOR_PLUS,
      },
      {
        id: "inbox-settings",
        label: "Config. Bandeja",
        to: "/inbox-settings",
        icon: SlidersHorizontal,
        roles: TENANT_ADMIN_PLUS,
      },
    ],
  },
  {
    id: "metrics",
    label: "Medición",
    items: [
      {
        id: "analytics",
        label: "Analítica",
        to: "/analytics",
        icon: BarChart3,
        roles: OPERATOR_PLUS,
      },
      {
        id: "exports",
        label: "Exportar",
        to: "/exports",
        icon: Database,
        roles: OPERATOR_PLUS,
      },
    ],
  },
  {
    id: "admin",
    label: "Administración",
    items: [
      {
        id: "users",
        label: "Usuarios",
        to: "/users",
        icon: UserRound,
        roles: TENANT_ADMIN_PLUS,
      },
      {
        id: "config",
        label: "Configuración",
        to: "/config",
        icon: Settings,
        roles: TENANT_ADMIN_PLUS,
      },
      {
        id: "audit-log",
        label: "Auditoría",
        to: "/audit-log",
        icon: FileText,
        roles: SUPERADMIN_ONLY,
      },
    ],
  },
];

export function filterMenuByRole(
  groups: readonly NavGroup[],
  role: Role | null | undefined,
): NavGroup[] {
  if (!role) return [];
  return groups
    .map((g) => ({
      ...g,
      items: g.items.filter((it) => it.roles.includes(role)),
    }))
    .filter((g) => g.items.length > 0);
}

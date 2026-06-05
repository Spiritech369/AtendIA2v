import {
  BarChart3,
  BotMessageSquare,
  BookOpen,
  Boxes,
  Bug,
  CalendarDays,
  ClipboardCheck,
  Columns3,
  Database,
  FileText,
  ListChecks,
  LayoutDashboard,
  MessageCircle,
  Network,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TableProperties,
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
        capability: "route.dashboard",
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
        capability: "route.conversations",
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
        capability: "route.handoffs",
        badgeKey: "handoffs_open",
      },
      {
        id: "customers",
        label: "Clientes",
        to: "/customers",
        icon: Users,
        roles: OPERATOR_PLUS,
        capability: "route.customers",
      },
      {
        id: "appointments",
        label: "Citas",
        to: "/appointments",
        icon: CalendarDays,
        roles: OPERATOR_PLUS,
        capability: "route.appointments",
        badgeKey: "appointments_today",
      },
      {
        id: "catalog",
        label: "Catálogo",
        to: "/catalog",
        icon: Boxes,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.catalog",
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
        capability: "route.agents",
      },
      {
        id: "composer",
        label: "Composer IA",
        to: "/composer",
        icon: BotMessageSquare,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.composer",
      },
      {
        id: "customer-fields",
        label: "Datos cliente",
        to: "/customer-fields",
        icon: TableProperties,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.customer_fields",
      },
      {
        id: "pipeline",
        label: "Pipeline",
        to: "/pipeline",
        icon: Columns3,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.pipeline",
      },
      {
        id: "ai-requirements",
        label: "Expediente",
        to: "/expediente",
        icon: ClipboardCheck,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.expediente",
      },
      {
        id: "knowledge",
        label: "Conocimiento",
        to: "/knowledge",
        icon: BookOpen,
        roles: OPERATOR_PLUS,
        capability: "route.knowledge",
      },
      {
        id: "turn-traces",
        label: "Debug de turnos",
        to: "/turn-traces",
        icon: Bug,
        roles: OPERATOR_PLUS,
        capability: "route.turn_traces",
        badgeKey: "ai_debug_warnings",
      },
      {
        id: "config-linter",
        label: "Linter config",
        to: "/config-linter",
        icon: ListChecks,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.config_linter",
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
        capability: "route.workflows",
      },
      {
        id: "inbox-settings",
        label: "Config. Bandeja",
        to: "/inbox-settings",
        icon: SlidersHorizontal,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.inbox_settings",
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
        capability: "route.analytics",
      },
      {
        id: "exports",
        label: "Exportar",
        to: "/exports",
        icon: Database,
        roles: OPERATOR_PLUS,
        capability: "route.exports",
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
        capability: "route.users",
      },
      {
        id: "config",
        label: "Configuración",
        to: "/config",
        icon: Settings,
        roles: TENANT_ADMIN_PLUS,
        capability: "route.config",
      },
      {
        id: "audit-log",
        label: "Auditoría",
        to: "/audit-log",
        icon: FileText,
        roles: SUPERADMIN_ONLY,
        capability: "route.audit_log",
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

export function filterMenuByCapabilities(
  groups: readonly NavGroup[],
  role: Role | null | undefined,
  capabilities: readonly string[] | null | undefined,
): NavGroup[] {
  if (!role) return [];
  const capabilitySet = capabilities ? new Set(capabilities) : null;
  return groups
    .map((g) => ({
      ...g,
      items: g.items.filter((it) => {
        if (!capabilitySet) return it.roles.includes(role);
        return it.capability ? capabilitySet.has(it.capability) : it.roles.includes(role);
      }),
    }))
    .filter((g) => g.items.length > 0);
}

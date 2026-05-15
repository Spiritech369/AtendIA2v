# Sidebar reagrupado con badges — diseño

**Fecha:** 2026-05-13
**Branch:** `claude/beautiful-mirzakhani-55368f`
**Autor:** Claude + zpiritech369@gmail.com

Reorganizar el sidebar actual (lista plana de 14 ítems) en 6 grupos
colapsables con badges dinámicos por módulo, modo compacto icon-only,
drawer mobile, y un solo endpoint backend nuevo para counts. Cero
infra nueva más allá de eso.

## Estado actual

- `frontend/src/components/AppShell.tsx:51-145` renderiza un `<aside>`
  con `NAV_ITEMS` (lista plana, 14 entradas). Filtrado básico
  `tenantAdminOnly`/`superadminOnly`. Sin grupos, sin badges, sin
  collapse, sin mobile drawer.
- `WhatsAppStatusBadge.tsx` polling 10s a `/api/v1/channel/status`.
- `NotificationsDropdown` (dentro de AppShell header) polling 30s a
  `/api/v1/notifications`.
- Endpoints de counts dispersos: `/dashboard/summary` para
  conversaciones activas, `/handoffs` para handoffs, etc.

## Filtrado del spec original

El prompt pidió WebSocket nuevo, tenant switcher, role taxonomy nueva,
varios endpoints. Lo que de verdad mueve la aguja:

- **Reagrupación + filtrado por rol**: barata, alto impacto.
- **Badges dinámicos**: requiere un endpoint nuevo agregado.
- **Compact mode + localStorage**: barata, mejora UX.
- **Mobile drawer**: barata con `Sheet` de shadcn.
- **WhatsApp status + tenant name en el sidebar header**: barata,
  reusa el componente existente.

Lo descartado:

- **Tenant switcher**: no hay `tenant_memberships` cross. Punch list.
- **WebSocket nuevo**: el patrón polling 30s es lo que el sistema usa.
- **`/api/me`, `/api/workspace/status`, `/api/navigation/menu`** nuevos:
  ya existen `/auth/me`, `/channel/status`. Menú vive en cliente — más
  simple, mismo resultado.
- **Roles operator/supervisor/admin/owner**: proyecto usa
  `operator/tenant_admin/superadmin` (+ supervisor/sales_agent/
  ai_reviewer/manager reservados). Sin renombrar, sólo mapear.

## Mapa de grupos

| Grupo | Ítem | Ruta | Roles | Badge |
|---|---|---|---|---|
| Dashboard | Dashboard | `/dashboard` | operator+ | — |
| Operación | Conversaciones | `/` | operator+ | `conversations_open` |
| | Handoffs | `/handoffs` | operator+ | `handoffs_open` (rojo si `handoffs_overdue>0`) |
| | Pipeline | `/pipeline` | operator+ | — |
| | Clientes | `/customers` | operator+ | — |
| | Citas | `/appointments` | operator+ | `appointments_today` |
| Inteligencia IA | Agentes IA | `/agents` | tenant_admin+ | — |
| | Conocimiento | `/knowledge` | operator+ | — |
| | Debug turnos | `/turn-traces` | operator+ | `ai_debug_warnings` |
| Automatización | Workflows | `/workflows` | operator+ | — |
| | Config. Bandeja | `/inbox-settings` | tenant_admin+ | — |
| Medición | Analítica | `/analytics` | operator+ | — |
| | Exportar | `/exports` | operator+ | — |
| Administración | Usuarios | `/users` | tenant_admin+ | — |
| | Configuración | `/config` | tenant_admin+ | — |
| | Auditoría | `/audit-log` | superadmin | — |

## Backend: nuevo endpoint

`GET /api/v1/navigation/badges`:

```python
class NavigationBadges(BaseModel):
    conversations_open: int
    handoffs_open: int
    handoffs_overdue: int
    appointments_today: int
    ai_debug_warnings: int
    unread_notifications: int
```

Lógica:
- `conversations_open`: `SELECT COUNT(*) FROM conversations WHERE
  tenant_id=? AND status IN ('open','in_progress') AND deleted_at IS
  NULL`. (Confirmar valores reales del enum status; si el modelo usa
  otra columna, ajustar.)
- `handoffs_open`: `SELECT COUNT(*) FROM human_handoffs WHERE
  tenant_id=? AND status IN ('open','assigned')`.
- `handoffs_overdue`: subset con `sla_due_at < now() at time zone 'utc'`.
- `appointments_today`: `Appointment.scheduled_at::date = today AND
  status IN ('scheduled','confirmed','pending')` con tz del tenant.
- `ai_debug_warnings`: `SELECT COUNT(*) FROM turn_traces WHERE
  tenant_id=? AND errors IS NOT NULL AND created_at >= now()-interval '24 hours'`.
- `unread_notifications`: per-user, `WHERE user_id=? AND read=false`.

5 counts paralelos (asyncio.gather) + 1 user-scoped.

Polling cada 30s desde el frontend. Sin SSE/WS — alineado al patrón
existente de notifications/channel.

## Frontend

```
src/components/sidebar/
  AppSidebar.tsx          # contenedor desktop + drawer mobile
  SidebarHeader.tsx       # logo + nombre tenant + WhatsAppStatusBadge
  SidebarGroup.tsx        # header colapsable + lista de ítems
  SidebarItem.tsx         # Link con icono + label + badge
  SidebarBadge.tsx        # chip de conteo
  SidebarFooter.tsx       # user card + role + logout + compact toggle
src/features/navigation/
  menu-config.ts          # NAV_GROUPS tipado declarativo
  api.ts                  # navigationApi.getBadges()
  hooks.ts                # useNavBadges()
  types.ts
src/stores/
  sidebar-store.ts        # Zustand con persist: compact, expandedGroups
```

`AppShell.tsx` queda como wrapper: `<AppSidebar />` + `<header>` (sólo
NotificationsDropdown y user dropdown como están) + `<main>`. El
sidebar absorbe el WhatsApp status y el tenant name del header viejo.

### Tipos clave

```ts
type Role = "operator" | "tenant_admin" | "superadmin" | "supervisor" | "manager" | "sales_agent" | "ai_reviewer";

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
  exactMatch?: boolean; // true for "/" so it doesn't match every route
}

export interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
}
```

### Detección de ruta activa

Para cada ítem:
- `exactMatch=true` (Conversaciones `/`): `path === to`.
- `exactMatch=false` (default): `path === to || path.startsWith(to + "/")`.
- Conversaciones también debe estar activa en `/conversations/:id` —
  arreglar con regla extra: `to === "/" && path.startsWith("/conversations")`.

### Sidebar store

```ts
interface SidebarState {
  compact: boolean;
  expandedGroups: Record<string, boolean>; // groupId → true (default true)
  toggleCompact: () => void;
  toggleGroup: (groupId: string) => void;
}
```

Persisted con `zustand/middleware/persist` a `localStorage` (key
`atendia.sidebar.v1`).

### Mobile drawer

Hook `useMediaQuery("(max-width: 767px)")`. Cuando es mobile:
- Sidebar oculto por default.
- Botón hamburger en AppShell header (móvil).
- Al click abre `Sheet` (radix) con el `<AppSidebar>` adentro.
- `aria-expanded` y `aria-controls` correctos.

### Estados visuales

- **Active**: `bg-primary/10`, `border-l-2 border-primary`, label en
  `font-medium`.
- **Hover**: `bg-muted`.
- **Badge default**: chip `bg-primary text-primary-foreground` con count.
- **Badge destructive**: `bg-red-500/10 text-red-600` cuando hay
  overdue (sólo handoffs por ahora).
- **Compact**: width `w-14`, sólo icon centrado; label en
  `<Tooltip>` shadcn (radix) al hover.
- **Loading**: skeleton de los grupos hasta que la sesión resuelva.
- **Error de badges**: chips ocultos, sidebar funcional.

## Tests

### Backend
- `core/tests/api/test_navigation_badges.py`:
  - Seed: tenant con 3 conversaciones open + 1 closed → `conversations_open=3`.
  - 2 handoffs status='open' + 1 'resolved' → `handoffs_open=2`.
  - 1 handoff con `sla_due_at` pasado → `handoffs_overdue=1`.
  - 2 citas para hoy en estado scheduled → `appointments_today=2`.
  - 1 turn_trace con `errors != null` en últimas 24h → `ai_debug_warnings=1`.
  - 3 notifications, 2 unread → `unread_notifications=2`.
- Test tenant scope: tenant A no ve counts de tenant B.
- Test RBAC: operator obtiene 200 (los badges son operator-visible).

### Frontend
- `menu-config.test.ts`:
  - `filterMenuByRole("operator")` excluye agents/users/audit-log/inbox-settings/config.
  - `filterMenuByRole("tenant_admin")` incluye agents/users/inbox-settings/config, excluye audit-log.
  - `filterMenuByRole("superadmin")` incluye todo.
- `sidebar-store.test.ts`:
  - `toggleCompact` flippea.
  - `toggleGroup("operacion")` flippea ese grupo.
  - Persist via localStorage.
- `useNavBadges.test.ts`:
  - Fetch successful → counts disponibles.
  - Fetch error → counts undefined, no throw.
- `SidebarItem.test.tsx`:
  - Active state: `aria-current="page"` cuando ruta coincide.
  - `exactMatch` para `/`.
  - Badge se renderiza si `badgeKey` y `value>0`.
  - Badge variante destructive si prop dado.
- `SidebarGroup.test.tsx`:
  - Click en header colapsa.
  - `aria-expanded` correcto.
  - Filtrado de items por rol antes de render.

## YAGNI

- Sin tenant switcher.
- Sin SSE/WS nuevo.
- Sin endpoint `/api/navigation/menu`.
- Sin role rename.
- Sin breadcrumbs.
- Sin search global en sidebar.
- Sin pinned items o quick links.

## Criterios de éxito

- 6 grupos visibles con sus ítems filtrados por rol.
- Badges aparecen y se actualizan cada 30s.
- Click en header de grupo colapsa/expande; preferencia persiste.
- Modo compacto disponible via toggle en footer; persiste.
- En mobile (<768px), sidebar abre como drawer.
- `aria-current="page"` correcto sobre el ítem activo.
- Conversaciones (`/`) sigue activo cuando se navega a `/conversations/:id`.
- WhatsApp status visible en sidebar header.
- Tests backend (8+) y frontend (10+) verdes.
- `tsc --noEmit` y `biome check` limpios en archivos tocados.

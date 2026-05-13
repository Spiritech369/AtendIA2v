import { redirect } from "@tanstack/react-router";

import type { Role } from "@/stores/auth";
import { useAuthStore } from "@/stores/auth";

/**
 * Route guard for use in `beforeLoad`. Throws a redirect if:
 * - the user is not authenticated → `/login`
 * - the user's role is not in `allowed` → `/`
 *
 * Chains with the auth-group's session check; safe to use on any
 * `/(auth)/*` route:
 *
 * ```ts
 * export const Route = createFileRoute("/(auth)/users")({
 *   beforeLoad: requireRole(["tenant_admin", "superadmin"]),
 *   component: UsersPage,
 * });
 * ```
 */
export function requireRole(allowed: readonly Role[]) {
  return async () => {
    const state = useAuthStore.getState();
    const user = state.user ?? (await state.fetchMe());
    if (!user) throw redirect({ to: "/login" });
    if (!allowed.includes(user.role)) throw redirect({ to: "/" });
  };
}

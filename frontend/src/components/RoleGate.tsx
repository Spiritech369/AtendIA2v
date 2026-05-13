import type { ReactNode } from "react";

import type { Role } from "@/stores/auth";
import { useAuthStore } from "@/stores/auth";

/**
 * Conditionally render children based on the current user's role.
 * Use inside pages everyone can see, where one section/button still
 * needs admin gating (the API also enforces this — the gate is purely
 * for UX clarity).
 */
export function RoleGate({
  roles,
  children,
  fallback = null,
}: {
  roles: readonly Role[];
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const role = useAuthStore((s) => s.user?.role);
  if (!role || !roles.includes(role)) return <>{fallback}</>;
  return <>{children}</>;
}

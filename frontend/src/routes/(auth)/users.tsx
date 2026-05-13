import { createFileRoute } from "@tanstack/react-router";

import { UsersPage } from "@/features/users/components/UsersPage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/users")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: UsersPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { UsersPage } from "@/features/users/components/UsersPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/users")({
  beforeLoad: requireCapability("route.users", ["tenant_admin", "superadmin"]),
  component: UsersPage,
});

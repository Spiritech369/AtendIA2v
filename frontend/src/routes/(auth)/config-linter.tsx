import { createFileRoute } from "@tanstack/react-router";

import { ConfigLinterPage } from "@/features/config-linter/components/ConfigLinterPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/config-linter")({
  beforeLoad: requireCapability("route.config_linter", ["tenant_admin", "superadmin"]),
  component: ConfigLinterPage,
});

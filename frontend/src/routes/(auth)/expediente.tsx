import { createFileRoute } from "@tanstack/react-router";

import { ExpedientePage } from "@/features/expediente/components/ExpedientePage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/expediente")({
  beforeLoad: requireCapability("route.expediente", ["tenant_admin", "superadmin"]),
  component: ExpedientePage,
});

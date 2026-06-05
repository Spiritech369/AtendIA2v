import { createFileRoute } from "@tanstack/react-router";

import { CatalogPage } from "@/features/catalog/components/CatalogPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/catalog")({
  beforeLoad: requireCapability("route.catalog", ["tenant_admin", "superadmin"]),
  component: CatalogPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { CatalogPage } from "@/features/catalog/components/CatalogPage";

export const Route = createFileRoute("/(auth)/catalog")({
  component: CatalogPage,
});

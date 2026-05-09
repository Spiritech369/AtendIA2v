import { createFileRoute } from "@tanstack/react-router";

import { ClientsPage } from "@/features/customers/components/ClientsPage";

export const Route = createFileRoute("/(auth)/customers")({
  component: () => <ClientsPage />,
});

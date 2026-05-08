import { createFileRoute } from "@tanstack/react-router";

import { CustomerSearch } from "@/features/customers/components/CustomerSearch";

export const Route = createFileRoute("/(auth)/customers")({
  component: () => (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Clientes</h1>
      <CustomerSearch />
    </div>
  ),
});

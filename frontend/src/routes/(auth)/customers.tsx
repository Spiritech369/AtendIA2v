import { Outlet, createFileRoute, useLocation } from "@tanstack/react-router";

import { ClientsPage } from "@/features/customers/components/ClientsPage";

export const Route = createFileRoute("/(auth)/customers")({
  component: CustomersRoute,
});

function CustomersRoute() {
  const location = useLocation();
  if (location.pathname === "/customers" || location.pathname === "/customers/") {
    return <ClientsPage />;
  }
  return <Outlet />;
}

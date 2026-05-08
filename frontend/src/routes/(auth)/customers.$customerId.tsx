import { createFileRoute } from "@tanstack/react-router";

import { CustomerDetail } from "@/features/customers/components/CustomerDetail";

export const Route = createFileRoute("/(auth)/customers/$customerId")({
  component: CustomerDetailPage,
});

function CustomerDetailPage() {
  const { customerId } = Route.useParams();
  return <CustomerDetail customerId={customerId} />;
}

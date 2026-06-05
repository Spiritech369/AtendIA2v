import { createFileRoute } from "@tanstack/react-router";

import { CustomerFieldsEditor } from "@/features/config/components/CustomerFieldsEditor";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/customer-fields")({
  beforeLoad: requireCapability("route.customer_fields", ["tenant_admin", "superadmin"]),
  component: CustomerFieldsPage,
});

function CustomerFieldsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Datos cliente</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Campos que Inteligencia IA puede extraer, recordar y usar para reglas por cuenta.
        </p>
      </div>
      <CustomerFieldsEditor />
    </div>
  );
}

import { createFileRoute } from "@tanstack/react-router";

import { AuditLogPage } from "@/features/audit-log/AuditLogPage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/audit-log")({
  beforeLoad: requireRole(["superadmin"]),
  component: AuditLogPage,
});

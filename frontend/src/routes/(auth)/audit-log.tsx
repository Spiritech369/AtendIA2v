import { createFileRoute } from "@tanstack/react-router";

import { AuditLogPage } from "@/features/audit-log/AuditLogPage";

export const Route = createFileRoute("/(auth)/audit-log")({
  component: AuditLogPage,
});

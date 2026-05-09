import { createFileRoute } from "@tanstack/react-router";

import { AppointmentsPage } from "@/features/appointments/components/AppointmentsPage";

export const Route = createFileRoute("/(auth)/appointments")({
  component: AppointmentsPage,
});

import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/(auth)/conversations")({
  beforeLoad: () => {
    throw redirect({ to: "/" });
  },
});

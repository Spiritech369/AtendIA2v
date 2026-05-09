import { createRootRoute, Outlet } from "@tanstack/react-router";

import { RouteErrorFallback } from "@/components/RouteErrorFallback";
import { Toaster } from "@/components/ui/sonner";

export const Route = createRootRoute({
  component: () => (
    <>
      <Outlet />
      <Toaster richColors position="top-right" />
    </>
  ),
  // Without this, any render exception anywhere in the tree blanks the
  // whole page silently. RouteErrorFallback shows the actual message.
  errorComponent: ({ error, reset }) => (
    <>
      <RouteErrorFallback error={error} reset={reset} />
      <Toaster richColors position="top-right" />
    </>
  ),
});

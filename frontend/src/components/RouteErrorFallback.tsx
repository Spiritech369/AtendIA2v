import { useRouter } from "@tanstack/react-router";
import { AlertOctagon, Home, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  error: Error;
  reset?: () => void;
}

/**
 * Last-resort error UI. Without this, a render exception anywhere in the
 * tree (including a Pydantic validation array reaching JSX) blanks the
 * whole page silently — the operator sees a white screen with no clue
 * what to do.
 *
 * Mounted on the root route and the (auth) group via TanStack Router's
 * ``errorComponent`` so the surrounding shell stays visible when
 * possible.
 *
 * The error message has already been flattened by the axios response
 * interceptor (``api-client.ts``) so Pydantic 422 arrays render as a
 * single readable string instead of crashing.
 */
export function RouteErrorFallback({ error, reset }: Props) {
  const router = useRouter();
  const message = typeof error?.message === "string"
    ? error.message
    : "Error desconocido";
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertOctagon className="h-5 w-5 text-destructive" />
            Algo falló al renderizar esta vista
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <pre className="whitespace-pre-wrap break-words rounded-md border bg-muted/50 p-3 text-xs">
            {message}
          </pre>
          {error?.stack && (
            <details className="text-[11px] text-muted-foreground">
              <summary className="cursor-pointer">Stack</summary>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words">
                {error.stack}
              </pre>
            </details>
          )}
          <p className="text-xs text-muted-foreground">
            Esta pantalla aparece en lugar del crash silencioso. Si vuelve
            a pasar, copia el mensaje y revisa las pestañas Network +
            Console del navegador.
          </p>
          <div className="flex gap-2">
            <Button
              variant="default"
              size="sm"
              onClick={() => {
                if (reset) reset();
                else router.invalidate();
              }}
            >
              <RotateCcw className="mr-2 h-3 w-3" /> Reintentar
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.navigate({ to: "/" })}
            >
              <Home className="mr-2 h-3 w-3" /> Inicio
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

import { Check, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useAcceptFieldSuggestion,
  useFieldSuggestions,
  useRejectFieldSuggestion,
} from "@/features/conversations/hooks/useFieldSuggestions";

const FIELD_LABELS: Record<string, string> = {
  marca: "Marca",
  modelo_interes: "Producto",
  plan_credito: "Plan de crédito",
  tipo_credito: "Tipo de crédito",
  city: "Ubicación",
  estimated_value: "Valor estimado",
  antiguedad_laboral_meses: "Antigüedad laboral (meses)",
};

/**
 * Shows pending NLU-derived suggestions for a customer above the
 * `Datos de contacto` grid. Renders nothing when there are zero
 * pending — keeps the contact panel quiet by default.
 */
export function FieldSuggestionsPanel({ customerId }: { customerId: string }) {
  const query = useFieldSuggestions(customerId);
  const accept = useAcceptFieldSuggestion(customerId);
  const reject = useRejectFieldSuggestion(customerId);

  if (!query.data || query.data.length === 0) return null;

  return (
    <div className="px-3 py-3 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-blue-600">
        <Sparkles className="h-3 w-3" />
        Sugerencias de IA ({query.data.length})
      </div>
      <div className="space-y-1.5">
        {query.data.map((s) => {
          const label = FIELD_LABELS[s.key] ?? s.key.replace(/_/g, " ");
          const confidencePct = Math.round(Number(s.confidence) * 100);
          return (
            <div
              key={s.id}
              className="rounded-md border border-blue-500/20 bg-blue-500/5 p-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium">{label}</div>
                  <div className="truncate font-mono text-[11px] text-blue-700">
                    {s.suggested_value}
                  </div>
                </div>
                <span className="shrink-0 rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 tabular-nums">
                  {confidencePct}%
                </span>
              </div>
              {s.evidence_text && (
                <div className="mt-1 line-clamp-2 text-[10px] italic text-muted-foreground">
                  «{s.evidence_text}»
                </div>
              )}
              <div className="mt-1.5 flex gap-1">
                <Button
                  size="sm"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => accept.mutate(s.id)}
                  disabled={accept.isPending}
                >
                  <Check className="mr-1 h-3 w-3" /> Aceptar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[10px]"
                  onClick={() => reject.mutate(s.id)}
                  disabled={reject.isPending}
                >
                  <X className="mr-1 h-3 w-3" /> Rechazar
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

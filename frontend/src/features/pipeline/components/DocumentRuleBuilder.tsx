/**
 * M4 of the pipeline-automation editor plan.
 *
 * A specialized UI on top of the generic RuleBuilder for the most
 * common "Papelería completa"-style rule: "this stage activates when
 * these N documents are all status=ok". The operator picks documents
 * from a checklist; we generate a normal AutoEnterRulesDraft underneath
 * (with `equals "ok"` conditions per selected doc) so the M3 evaluator
 * needs zero special-casing.
 *
 * Visible alongside RuleBuilder — operators pick whichever maps better
 * to their mental model. The shape on the wire is identical.
 */
import { FileCheck2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type {
  AutoEnterRulesDraft,
  ConditionDraft,
} from "./PipelineEditor";

// ── Document catalog ──────────────────────────────────────────────────
// Each entry corresponds to a `customer.attrs[DOC_KEY]` dict the AI
// Field Extraction sprint writes when a document is uploaded. The .status
// sub-field is the canonical path the evaluator reads.

export const DOCUMENT_CATALOG: ReadonlyArray<{
  key: string;
  label: string;
  hint?: string;
}> = [
  { key: "DOCS_INE", label: "INE", hint: "Identificación oficial" },
  {
    key: "DOCS_COMPROBANTE_DOMICILIO",
    label: "Comprobante de domicilio",
    hint: "Recibo CFE / agua / teléfono",
  },
  {
    key: "DOCS_ESTADOS_CUENTA",
    label: "Estados de cuenta",
    hint: "3 últimos meses",
  },
  {
    key: "DOCS_RECIBOS_NOMINA",
    label: "Recibos de nómina",
    hint: "Aplica para crédito nómina",
  },
  {
    key: "DOCS_RESOLUCION_IMSS",
    label: "Resolución IMSS",
    hint: "Aplica si trabajador IMSS",
  },
];

// We treat a stage's `auto_enter_rules` as "doc-mode-shaped" when every
// condition is `DOCS_<KEY>.status equals "ok"` AND there are no other
// kinds of conditions. Detecting this lets us pre-fill the checklist
// from a previously-saved rule without forcing the operator to
// rebuild from scratch.
const DOC_STATUS_RE = /^(DOCS_[A-Z_]+)\.status$/;

function deriveSelectedDocs(rules: AutoEnterRulesDraft | undefined): Set<string> | null {
  if (!rules || rules.conditions.length === 0) return null;
  const docs = new Set<string>();
  for (const c of rules.conditions) {
    const match = c.field.match(DOC_STATUS_RE);
    if (!match) return null; // mixed rule, leave doc-mode untouched
    if (c.operator !== "equals" || c.value !== "ok") return null;
    docs.add(match[1]!);
  }
  return docs;
}

function buildDocConditions(selectedKeys: Iterable<string>): ConditionDraft[] {
  return Array.from(selectedKeys).map((key) => ({
    field: `${key}.status`,
    operator: "equals" as const,
    value: "ok",
  }));
}

// ── Component ─────────────────────────────────────────────────────────

export function DocumentRuleBuilder({
  stageLabel,
  rules,
  onChange,
  disabled,
}: {
  stageLabel: string;
  rules: AutoEnterRulesDraft | undefined;
  onChange: (next: AutoEnterRulesDraft | undefined) => void;
  disabled?: boolean;
}) {
  const selected = deriveSelectedDocs(rules);
  const docMode = selected !== null; // rules-shape match for doc-only conditions
  const enabled = rules?.enabled === true;

  const toggleDoc = (key: string) => {
    const current = new Set(selected ?? []);
    if (current.has(key)) current.delete(key);
    else current.add(key);
    if (current.size === 0) {
      // Empty set + enabled would fail backend validation. Collapse rules
      // to undefined so we don't accidentally ship "enabled:true,
      // conditions:[]".
      onChange(undefined);
      return;
    }
    onChange({
      enabled: enabled || true, // turning on a doc auto-activates the rule
      match: "all",
      conditions: buildDocConditions(current),
    });
  };

  // If the stage already has a non-doc rule, the doc UI is read-only
  // (showing 0 docs selected). The operator should use the generic
  // RuleBuilder instead. We surface that with a hint.
  if (rules && rules.conditions.length > 0 && !docMode) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
        <p className="font-medium text-foreground">
          Reglas personalizadas activas
        </p>
        <p className="mt-1">
          Esta etapa tiene condiciones que no son sólo documentos. Edítalas
          en "Reglas de auto-entrada".
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <FileCheck2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
        <div>
          <p className="text-xs font-semibold">Documentos requeridos</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Marca los documentos que deben quedar en{" "}
            <code className="rounded bg-muted px-1 text-[10px]">status = ok</code>{" "}
            para que la conversación entre a "{stageLabel}".
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {DOCUMENT_CATALOG.map((doc) => {
          const isChecked = selected?.has(doc.key) ?? false;
          return (
            <button
              key={doc.key}
              type="button"
              onClick={() => toggleDoc(doc.key)}
              disabled={disabled}
              aria-pressed={isChecked}
              className={cn(
                "flex items-start gap-2 rounded-md border px-2.5 py-2 text-left text-[11px] transition",
                isChecked
                  ? "border-emerald-500/40 bg-emerald-500/5"
                  : "border-border bg-background hover:bg-muted/40",
                disabled && "cursor-not-allowed opacity-50",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded border",
                  isChecked
                    ? "border-emerald-500 bg-emerald-500 text-white"
                    : "border-input bg-background",
                )}
                aria-hidden
              >
                {isChecked ? "✓" : ""}
              </span>
              <span className="flex-1">
                <span className="block font-medium text-foreground">
                  {doc.label}
                </span>
                {doc.hint && (
                  <span className="block text-[10px] text-muted-foreground">
                    {doc.hint}
                  </span>
                )}
                <span className="mt-1 block font-mono text-[9px] text-muted-foreground">
                  {doc.key}.status
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {selected && selected.size > 0 && (
        <div className="flex items-center justify-between rounded-md border bg-muted/30 px-2.5 py-1.5 text-[11px]">
          <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Resumen
          </Label>
          <span className="font-medium">{selected.size} documento(s) requeridos</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[10px] text-destructive hover:bg-destructive/10"
            onClick={() => onChange(undefined)}
            disabled={disabled}
          >
            Limpiar
          </Button>
        </div>
      )}
    </div>
  );
}

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
// The catalog is now tenant-configurable and lives inside
// `pipeline.definition.documents_catalog`. The shape of each entry is
// what the operator authors in the Pipeline editor's "Catálogo de
// documentos" section, and `<DocumentRuleBuilder>` receives the
// current draft's catalog as a prop. Checking a document still writes
// a `DOCS_<KEY>.status equals "ok"` condition into the stage's
// auto_enter_rules — that contract is unchanged so existing pipelines
// keep working.

export interface DocumentCatalogEntry {
  key: string;
  label: string;
  hint?: string;
}

// We treat a stage's `auto_enter_rules` as "doc-mode-shaped" when every
// condition is `DOCS_<KEY>.status equals "ok"` AND there are no other
// kinds of conditions. Detecting this lets us pre-fill the checklist
// from a previously-saved rule without forcing the operator to
// rebuild from scratch.
const DOC_STATUS_RE = /^(DOCS_[A-Z_]+)\.status$/;

// Two doc-rule shapes the operator can author through this UI:
//   * "all_validated" — every selected doc must have status=ok
//     (match=all, operator=equals "ok"). Use this for stages like
//     "Papelería completa" where uploads must be reviewed.
//   * "any_arrived"   — any selected doc has any status value at all
//     (match=any, operator=exists). Use this for stages like
//     "Documentos pendientes" where the trigger is "the customer
//     started uploading".
export type DocRuleMode = "all_validated" | "any_arrived";

function deriveDocRule(
  rules: AutoEnterRulesDraft | undefined,
): { mode: DocRuleMode; docs: Set<string> } | null {
  if (!rules || rules.conditions.length === 0) return null;
  // Sniff the mode from the first condition's operator. Then require
  // every condition to be consistent — mixed shapes fall through to
  // the generic RuleBuilder.
  const first = rules.conditions[0]!;
  if (first.operator !== "equals" && first.operator !== "exists") return null;
  const mode: DocRuleMode =
    first.operator === "equals" ? "all_validated" : "any_arrived";
  const docs = new Set<string>();
  for (const c of rules.conditions) {
    const match = c.field.match(DOC_STATUS_RE);
    if (!match) return null;
    if (mode === "all_validated") {
      if (c.operator !== "equals" || c.value !== "ok") return null;
    } else {
      if (c.operator !== "exists") return null;
    }
    docs.add(match[1]!);
  }
  return { mode, docs };
}

function buildDocConditions(
  selectedKeys: Iterable<string>,
  mode: DocRuleMode,
): ConditionDraft[] {
  return Array.from(selectedKeys).map((key) =>
    mode === "all_validated"
      ? { field: `${key}.status`, operator: "equals" as const, value: "ok" }
      : { field: `${key}.status`, operator: "exists" as const },
  );
}

// ── Component ─────────────────────────────────────────────────────────

export function DocumentRuleBuilder({
  stageLabel,
  rules,
  catalog,
  onChange,
  disabled,
}: {
  stageLabel: string;
  rules: AutoEnterRulesDraft | undefined;
  catalog: ReadonlyArray<DocumentCatalogEntry>;
  onChange: (next: AutoEnterRulesDraft | undefined) => void;
  disabled?: boolean;
}) {
  const parsed = deriveDocRule(rules);
  const docMode = parsed !== null;
  const mode: DocRuleMode = parsed?.mode ?? "all_validated";
  const selected = parsed?.docs ?? null;
  const enabled = rules?.enabled === true;

  const writeRule = (
    nextMode: DocRuleMode,
    nextSelected: Set<string>,
  ) => {
    if (nextSelected.size === 0) {
      onChange(undefined);
      return;
    }
    onChange({
      enabled: enabled || true,
      match: nextMode === "all_validated" ? "all" : "any",
      conditions: buildDocConditions(nextSelected, nextMode),
    });
  };

  const toggleDoc = (key: string) => {
    const current = new Set(selected ?? []);
    if (current.has(key)) current.delete(key);
    else current.add(key);
    writeRule(mode, current);
  };

  const setMode = (nextMode: DocRuleMode) => {
    if (nextMode === mode) return;
    writeRule(nextMode, new Set(selected ?? []));
  };

  // If the stage already has a non-doc rule, the doc UI is read-only.
  // The operator should use the generic RuleBuilder instead.
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
            Marca los documentos que disparan la entrada a "{stageLabel}".
          </p>
        </div>
      </div>

      {/* Mode picker: the same checklist generates two different rule
          shapes depending on whether the operator wants "any doc
          arrived" or "all docs validated". */}
      <div className="grid grid-cols-2 gap-1.5">
        <button
          type="button"
          onClick={() => setMode("any_arrived")}
          disabled={disabled}
          aria-pressed={mode === "any_arrived"}
          className={cn(
            "rounded-md border px-2 py-1.5 text-left text-[11px] transition",
            mode === "any_arrived"
              ? "border-amber-500/40 bg-amber-500/5"
              : "border-border bg-background hover:bg-muted/40",
            disabled && "cursor-not-allowed opacity-50",
          )}
        >
          <span className="block font-medium text-foreground">
            Cualquier doc llegó
          </span>
          <span className="block text-[10px] text-muted-foreground">
            Dispara cuando llegue cualquiera de los seleccionados, sin
            importar si ya está validado.
          </span>
        </button>
        <button
          type="button"
          onClick={() => setMode("all_validated")}
          disabled={disabled}
          aria-pressed={mode === "all_validated"}
          className={cn(
            "rounded-md border px-2 py-1.5 text-left text-[11px] transition",
            mode === "all_validated"
              ? "border-emerald-500/40 bg-emerald-500/5"
              : "border-border bg-background hover:bg-muted/40",
            disabled && "cursor-not-allowed opacity-50",
          )}
        >
          <span className="block font-medium text-foreground">
            Todos validados
          </span>
          <span className="block text-[10px] text-muted-foreground">
            Dispara cuando los seleccionados tengan{" "}
            <code className="rounded bg-muted px-1 text-[9px]">status = ok</code>.
          </span>
        </button>
      </div>
      {catalog.length === 0 && (
        <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
          No hay documentos en el catálogo. Defínelos arriba en "Catálogo
          de documentos" para que aparezcan aquí.
        </p>
      )}
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {catalog.map((doc) => {
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

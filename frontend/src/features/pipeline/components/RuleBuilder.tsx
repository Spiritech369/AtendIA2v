/**
 * M2 of the pipeline-automation editor plan.
 *
 * Lets an operator declare *when* a conversation should auto-move into a
 * stage. The shape of the data is pinned by the backend Condition /
 * AutoEnterRules contract in
 * `core/atendia/contracts/pipeline_definition.py`; we keep the same
 * operator names, the same value-required-or-not rules, and the same
 * dot-separated field-path regex. Anything we accept here that the
 * backend would reject is a bug — the validator in PipelineEditor blocks
 * Save against the same rules.
 *
 * Components are co-located in this single file because they're tightly
 * coupled (the operator type drives whether ValueInput renders at all,
 * the field catalog drives FieldSelector suggestions, etc) and that
 * makes the test target obvious.
 */
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import type {
  AutoEnterRulesDraft,
  ConditionDraft,
  RuleOperator,
} from "./PipelineEditor";
import {
  OPERATORS_NEEDING_LIST,
  OPERATORS_WITHOUT_VALUE,
} from "./PipelineEditor";

// ── Static catalogs ────────────────────────────────────────────────────
// Open question #1 from the plan doc lands on "static for now, dynamic
// later". The list comes from the user's spec; document fields use the
// DOCS_* uppercase convention the AI Field Extraction sprint already
// emits into customer.attrs.

export const FIELD_CATALOG: ReadonlyArray<{ id: string; label: string; group: string }> = [
  // Identity
  { id: "nombre", label: "Nombre del cliente", group: "Identidad" },
  { id: "telefono", label: "Teléfono", group: "Identidad" },

  // Sales-funnel fields (interest, credit shape)
  { id: "modelo_interes", label: "Modelo de interés", group: "Ventas" },
  { id: "plan_credito", label: "Plan de crédito", group: "Ventas" },
  { id: "tipo_credito", label: "Tipo de crédito", group: "Ventas" },
  { id: "tipo_enganche", label: "Tipo de enganche", group: "Ventas" },
  { id: "enganche_confirmado", label: "Enganche confirmado", group: "Ventas" },
  { id: "solicitud_sistema_status", label: "Estatus en sistema", group: "Ventas" },

  // Document statuses (canonical path: DOCS_KEY.status)
  { id: "DOCS_INE.status", label: "INE — status", group: "Documentos" },
  { id: "DOCS_COMPROBANTE_DOMICILIO.status", label: "Comprobante domicilio — status", group: "Documentos" },
  { id: "DOCS_ESTADOS_CUENTA.status", label: "Estados de cuenta — status", group: "Documentos" },
  { id: "DOCS_RECIBOS_NOMINA.status", label: "Recibos de nómina — status", group: "Documentos" },
  { id: "DOCS_RESOLUCION_IMSS.status", label: "Resolución IMSS — status", group: "Documentos" },
];

export const OPERATOR_LABELS: Record<RuleOperator, string> = {
  exists: "existe",
  not_exists: "no existe",
  equals: "es igual a",
  not_equals: "es distinto de",
  contains: "contiene",
  greater_than: "es mayor que",
  less_than: "es menor que",
  in: "está en",
  not_in: "no está en",
};

const ALL_OPERATORS: RuleOperator[] = [
  "exists",
  "not_exists",
  "equals",
  "not_equals",
  "contains",
  "greater_than",
  "less_than",
  "in",
  "not_in",
];

// Document-status enum from the user's spec. Used as suggestions when the
// operator is equals/not_equals/in/not_in and the field path is a DOCS_*
// status. The list is just hints — operators can still type anything.
export const DOC_STATUS_VALUES = [
  "missing",
  "received",
  "pending_review",
  "ok",
  "rejected",
  "expired",
  "unreadable",
];

const FIELD_DATALIST_ID = "rule-field-catalog";

// ── FieldSelector ──────────────────────────────────────────────────────
// HTML5 <datalist> gives us suggestion-with-free-text without a heavier
// combobox dependency. Operators can still type a custom field (e.g. a
// field added recently that hasn't been backfilled into the static
// catalog).
export function FieldSelector({
  value,
  onChange,
  disabled,
  invalid,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  invalid?: boolean;
}) {
  return (
    <Input
      list={FIELD_DATALIST_ID}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="modelo_interes"
      className={cn(
        "h-8 flex-1 font-mono text-xs",
        invalid && "border-destructive focus-visible:ring-destructive/40",
      )}
      disabled={disabled}
      aria-invalid={invalid || undefined}
    />
  );
}

// One <datalist> mounted once per RuleBuilder serves every FieldSelector
// inside. Cheap to render, dramatically cleaner DOM than per-row.
function FieldDatalist() {
  return (
    <datalist id={FIELD_DATALIST_ID}>
      {FIELD_CATALOG.map((f) => (
        <option key={f.id} value={f.id}>
          {f.label}
        </option>
      ))}
    </datalist>
  );
}

// ── OperatorSelector ──────────────────────────────────────────────────
export function OperatorSelector({
  value,
  onChange,
  disabled,
}: {
  value: RuleOperator;
  onChange: (next: RuleOperator) => void;
  disabled?: boolean;
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => onChange(v as RuleOperator)}
      disabled={disabled}
    >
      <SelectTrigger size="sm" className="h-8 w-[8.5rem] text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ALL_OPERATORS.map((op) => (
          <SelectItem key={op} value={op} className="text-xs">
            {OPERATOR_LABELS[op]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ── ValueInput ─────────────────────────────────────────────────────────
// Renders nothing for presence operators. For list operators, we keep
// the raw typed string in the draft (otherwise "ok," gets parsed to
// ["ok"], rendered back as "ok", and the typed comma is silently eaten
// mid-edit). PipelineEditor.serialise parses string → list at save time,
// so the on-wire shape stays a real array.
export function ValueInput({
  operator,
  value,
  onChange,
  disabled,
  invalid,
}: {
  operator: RuleOperator;
  value: ConditionDraft["value"];
  onChange: (next: ConditionDraft["value"]) => void;
  disabled?: boolean;
  invalid?: boolean;
}) {
  if (OPERATORS_WITHOUT_VALUE.has(operator)) {
    return (
      <div className="flex h-8 flex-1 items-center px-2 text-[11px] text-muted-foreground">
        — (sin valor)
      </div>
    );
  }

  const isList = OPERATORS_NEEDING_LIST.has(operator);
  // Pre-existing list value (e.g. from a loaded pipeline) is rendered as a
  // joined string; subsequent edits stay as raw string until save.
  const stringValue = Array.isArray(value) ? value.join(", ") : (value ?? "");
  return (
    <Input
      value={stringValue}
      onChange={(e) => onChange(e.target.value)}
      placeholder={isList ? "ok, pending_review" : "ok"}
      className={cn(
        "h-8 flex-1 text-xs",
        invalid && "border-destructive focus-visible:ring-destructive/40",
      )}
      disabled={disabled}
      aria-invalid={invalid || undefined}
    />
  );
}

// ── RulePreview ────────────────────────────────────────────────────────
// Renders a single human-readable sentence: "Cuando *modelo_interes*
// existe **y** *plan_credito* existe". The bold/italic markers are just
// styling — we render with proper elements below.
export function RulePreview({ rules }: { rules: AutoEnterRulesDraft | undefined }) {
  if (!rules || !rules.enabled || rules.conditions.length === 0) {
    return (
      <p className="text-[11px] italic text-muted-foreground">
        (Sin reglas activas)
      </p>
    );
  }
  const joiner = rules.match === "all" ? " y " : " o ";
  return (
    <p className="text-[11px] leading-relaxed text-foreground">
      <span className="text-muted-foreground">Auto-entrar cuando </span>
      {rules.conditions.map((c, i) => (
        <span key={i}>
          {i > 0 && <span className="text-muted-foreground">{joiner}</span>}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
            {c.field || "?"}
          </code>{" "}
          <span className="text-muted-foreground">
            {OPERATOR_LABELS[c.operator]}
          </span>
          {!OPERATORS_WITHOUT_VALUE.has(c.operator) && (
            <>
              {" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
                {OPERATORS_NEEDING_LIST.has(c.operator)
                  ? Array.isArray(c.value)
                    ? c.value.join(", ") || "?"
                    : c.value || "?"
                  : c.value || "?"}
              </code>
            </>
          )}
        </span>
      ))}
    </p>
  );
}

// ── ConditionRow ───────────────────────────────────────────────────────
function ConditionRow({
  condition,
  onChange,
  onRemove,
  disabled,
  fieldInvalid,
  valueInvalid,
}: {
  condition: ConditionDraft;
  onChange: (patch: Partial<ConditionDraft>) => void;
  onRemove: () => void;
  disabled?: boolean;
  fieldInvalid?: boolean;
  valueInvalid?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <FieldSelector
        value={condition.field}
        onChange={(v) => onChange({ field: v })}
        disabled={disabled}
        invalid={fieldInvalid}
      />
      <OperatorSelector
        value={condition.operator}
        onChange={(op) => {
          // Switching operator may invalidate the existing value; clear it
          // for safety so the operator re-enters intentionally. Presence
          // ops drop value entirely.
          if (OPERATORS_WITHOUT_VALUE.has(op)) {
            onChange({ operator: op, value: undefined });
          } else if (OPERATORS_NEEDING_LIST.has(op)) {
            onChange({ operator: op, value: [] });
          } else {
            onChange({ operator: op, value: "" });
          }
        }}
        disabled={disabled}
      />
      <ValueInput
        operator={condition.operator}
        value={condition.value}
        onChange={(v) => onChange({ value: v })}
        disabled={disabled}
        invalid={valueInvalid}
      />
      <Button
        variant="ghost"
        size="icon"
        onClick={onRemove}
        disabled={disabled}
        className="h-8 w-8 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
        title="Eliminar condición"
        type="button"
      >
        <Trash2 className="size-3.5" />
      </Button>
    </div>
  );
}

// ── RuleBuilder (host) ─────────────────────────────────────────────────
export function RuleBuilder({
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
  // Normalise: an "off and empty" state is represented as undefined on the
  // wire so save payloads don't carry empty rule blocks. The UI keeps a
  // local shape with safe defaults regardless.
  const effective: AutoEnterRulesDraft = rules ?? {
    enabled: false,
    match: "all",
    conditions: [],
  };

  const updateRules = (patch: Partial<AutoEnterRulesDraft>) => {
    const merged: AutoEnterRulesDraft = { ...effective, ...patch };
    // If toggled off with no conditions, collapse back to undefined so the
    // wire payload stays clean.
    if (!merged.enabled && merged.conditions.length === 0) {
      onChange(undefined);
      return;
    }
    onChange(merged);
  };

  const addCondition = () => {
    updateRules({
      conditions: [
        ...effective.conditions,
        { field: "", operator: "exists" },
      ],
    });
  };

  const updateCondition = (idx: number, patch: Partial<ConditionDraft>) => {
    updateRules({
      conditions: effective.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    });
  };

  const removeCondition = (idx: number) => {
    updateRules({
      conditions: effective.conditions.filter((_, i) => i !== idx),
    });
  };

  return (
    <div className="space-y-3">
      <FieldDatalist />

      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold">Reglas de auto-entrada</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Mover automáticamente a "{stageLabel}" cuando se cumplan estas condiciones.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={effective.enabled}
          onClick={() => updateRules({ enabled: !effective.enabled })}
          disabled={disabled}
          className={cn(
            "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            effective.enabled ? "bg-primary" : "bg-muted",
            disabled && "cursor-not-allowed opacity-50",
          )}
        >
          <span
            className={cn(
              "pointer-events-none inline-block size-4 rounded-full bg-white shadow-lg transition-transform",
              effective.enabled ? "translate-x-4" : "translate-x-0",
            )}
          />
        </button>
      </div>

      {effective.enabled && (
        <>
          <div className="flex items-center gap-2">
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Coincidencia
            </Label>
            <Select
              value={effective.match}
              onValueChange={(v) => updateRules({ match: v === "any" ? "any" : "all" })}
              disabled={disabled}
            >
              <SelectTrigger size="sm" className="h-7 w-32 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-xs">
                  Todas (AND)
                </SelectItem>
                <SelectItem value="any" className="text-xs">
                  Cualquiera (OR)
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            {effective.conditions.map((c, idx) => (
              <ConditionRow
                key={idx}
                condition={c}
                onChange={(patch) => updateCondition(idx, patch)}
                onRemove={() => removeCondition(idx)}
                disabled={disabled}
              />
            ))}
            {effective.conditions.length === 0 && (
              <p className="rounded-md border border-dashed border-border px-3 py-2 text-[11px] text-muted-foreground">
                Sin condiciones — agrega al menos una para activar la regla.
              </p>
            )}
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 w-full text-xs"
            onClick={addCondition}
            disabled={disabled}
          >
            <Plus className="mr-1 size-3" /> Agregar condición
          </Button>

          <div className="rounded-md border bg-muted/30 px-3 py-2">
            <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              Vista previa
            </p>
            <RulePreview rules={effective} />
          </div>
        </>
      )}
    </div>
  );
}

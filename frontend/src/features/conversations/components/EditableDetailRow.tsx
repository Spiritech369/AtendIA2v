/**
 * EditableDetailRow — DetailRow card with inline edit/save/delete.
 *
 * Used by ContactDetailGridSection for every editable card in the
 * "Datos de contacto" grid. Stays read-only when `editable=false`
 * (e.g. phone). Calls `onSave(null)` when the user clears the value.
 */
import { Check, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface EditableDetailRowOption {
  value: string;
  label: string;
}

export interface EditableDetailRowProps {
  label: string;
  value: string | null | undefined;
  icon?: React.ComponentType<{ className?: string }>;
  editable: boolean;
  deletable: boolean;
  inputType?: "text" | "number" | "email" | "select";
  options?: EditableDetailRowOption[];
  placeholder?: string;
  validate?: (raw: string) => string | null;
  onSave: (newValue: string | null) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
}

export function EditableDetailRow({
  label,
  value,
  icon: Icon,
  editable,
  deletable,
  inputType = "text",
  options,
  placeholder = "Sin dato",
  validate,
  onSave,
  onDelete,
}: EditableDetailRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(value ?? "");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(value ?? "");
      setError(null);
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [editing, value]);

  async function save() {
    const trimmed = draft.trim();
    if (validate) {
      const err = validate(trimmed);
      if (err) {
        setError(err);
        return;
      }
    }
    await onSave(trimmed === "" ? null : trimmed);
    setEditing(false);
  }

  function cancel() {
    setEditing(false);
    setError(null);
  }

  return (
    <div className="group min-w-0 rounded-md border border-border bg-muted/30 px-2 py-1.5">
      <div className="flex items-center justify-between gap-1 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1">
          {Icon && <Icon className="h-3 w-3 shrink-0" />}
          <span>{label}</span>
        </div>
        {editable && !editing && !confirmDelete && (
          <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <button
              type="button"
              aria-label={`Editar ${label}`}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground"
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3 w-3" />
            </button>
            {deletable && onDelete && (
              <button
                type="button"
                aria-label={`Eliminar ${label}`}
                className="rounded p-0.5 text-muted-foreground hover:text-destructive"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <div className="mt-1 space-y-1">
          {inputType === "select" ? (
            <select
              ref={inputRef as React.RefObject<HTMLSelectElement>}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void save();
                }
                if (e.key === "Escape") cancel();
              }}
              className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs"
            >
              <option value="" disabled>
                {placeholder}
              </option>
              {(options ?? []).map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          ) : (
            <Input
              ref={inputRef as React.RefObject<HTMLInputElement>}
              type={inputType}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void save();
                }
                if (e.key === "Escape") cancel();
              }}
              className="h-7 text-xs"
              placeholder={placeholder}
            />
          )}
          {error && <p className="text-[10px] text-destructive">{error}</p>}
          <div className="flex gap-1">
            <Button
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={() => void save()}
            >
              <Check className="mr-1 h-3 w-3" /> Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[11px]"
              onClick={cancel}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <div
          className={cn(
            "mt-0.5 truncate text-[11px] font-medium",
            !value && "text-muted-foreground italic",
          )}
        >
          {value || placeholder}
        </div>
      )}

      {confirmDelete && onDelete && (
        <div className="mt-1 flex items-center gap-1 rounded bg-destructive/10 px-1.5 py-1 text-[11px]">
          <span className="flex-1">¿Eliminar este campo?</span>
          <Button
            size="sm"
            variant="destructive"
            className="h-5 px-1.5 text-[10px]"
            onClick={async () => {
              await onDelete();
              setConfirmDelete(false);
            }}
          >
            Confirmar
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-5 px-1.5 text-[10px]"
            onClick={() => setConfirmDelete(false)}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  );
}

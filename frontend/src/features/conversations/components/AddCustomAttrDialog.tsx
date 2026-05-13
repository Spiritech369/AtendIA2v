/**
 * AddCustomAttrDialog — modal para agregar un campo ad-hoc al
 * customer.attrs (no a la tabla tenant-wide de custom fields).
 *
 * Auto-slugifica `key` desde `label` hasta que el usuario edita la
 * key manualmente; a partir de ahí respeta su input.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export type CustomAttrFieldType = "text" | "number" | "date" | "boolean";

export interface CustomAttrPayload {
  key: string;
  label: string;
  field_type: CustomAttrFieldType;
  value: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: CustomAttrPayload) => void;
}

export function slugify(input: string): string {
  return input
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function AddCustomAttrDialog({ open, onClose, onSubmit }: Props) {
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [fieldType, setFieldType] = useState<CustomAttrFieldType>("text");
  const [value, setValue] = useState("");

  function handleLabelChange(next: string) {
    setLabel(next);
    if (!keyTouched) setKey(slugify(next));
  }

  function handleKeyChange(next: string) {
    setKey(next);
    setKeyTouched(true);
  }

  function reset() {
    setLabel("");
    setKey("");
    setKeyTouched(false);
    setFieldType("text");
    setValue("");
  }

  function handleSave() {
    if (!key.trim() || !value.trim()) return;
    onSubmit({
      key: key.trim(),
      label: label.trim() || key,
      field_type: fieldType,
      value: value.trim(),
    });
    reset();
    onClose();
  }

  function handleClose() {
    reset();
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Agregar campo personalizado</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="custom-attr-label">Etiqueta</Label>
            <Input
              id="custom-attr-label"
              value={label}
              onChange={(e) => handleLabelChange(e.target.value)}
              placeholder="Ej. Color favorito"
            />
          </div>
          <div>
            <Label htmlFor="custom-attr-key">Clave</Label>
            <Input
              id="custom-attr-key"
              value={key}
              onChange={(e) => handleKeyChange(e.target.value)}
              placeholder="color_favorito"
              className="font-mono text-xs"
            />
          </div>
          <div>
            <Label htmlFor="custom-attr-type">Tipo</Label>
            <select
              id="custom-attr-type"
              value={fieldType}
              onChange={(e) => setFieldType(e.target.value as CustomAttrFieldType)}
              className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="text">Texto</option>
              <option value="number">Número</option>
              <option value="date">Fecha</option>
              <option value="boolean">Sí/No</option>
            </select>
          </div>
          <div>
            <Label htmlFor="custom-attr-value">Valor</Label>
            <Input
              id="custom-attr-value"
              type={
                fieldType === "number"
                  ? "number"
                  : fieldType === "date"
                    ? "date"
                    : "text"
              }
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={handleClose}>
            Cancelar
          </Button>
          <Button
            onClick={handleSave}
            disabled={!key.trim() || !value.trim()}
          >
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

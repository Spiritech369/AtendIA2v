import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Calendar,
  ChevronRight,
  FileCheck,
  FileText,
  Hash,
  List,
  ListChecks,
  Plus,
  Save,
  Search,
  Sparkles,
  ToggleLeft,
  Trash2,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  type FieldDefinition,
  type FieldDefinitionType,
  fieldsApi,
} from "@/features/customers/api";
import { knowledgeApi } from "@/features/knowledge/api";
import { cn } from "@/lib/utils";

const FIELD_TYPES: Array<{ value: FieldDefinitionType; label: string }> = [
  { value: "text", label: "Texto" },
  { value: "select", label: "Lista" },
  { value: "number", label: "Numero" },
  { value: "date", label: "Fecha" },
  { value: "checkbox", label: "Si/No" },
  { value: "multiselect", label: "Lista multiple" },
  { value: "document", label: "Documento" },
];

interface FieldDraft {
  label: string;
  field_type: FieldDefinitionType;
  optionsText: string;
  instructionsText: string;
  ordering: string;
}

interface ReferenceToken {
  token: string;
  label: string;
  description: string;
  icon: "document" | "faq";
}

const choiceTypes = new Set<FieldDefinitionType>(["select", "multiselect"]);
const ALL_TYPES = "__all__";
const REFERENCE_PATTERN = /#(?:document|documento|catalogo|catalog|faq|kb)\.[A-Za-z0-9_.-]+/i;
const premiumCard =
  "rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-white/10 dark:bg-[#0E1424]/90 dark:shadow-2xl dark:shadow-black/20";
const premiumInput =
  "h-9 rounded-lg border-slate-200 bg-white text-xs text-slate-950 placeholder:text-slate-400 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-100 dark:placeholder:text-slate-500";
const premiumTextarea =
  "min-h-28 rounded-lg border-slate-200 bg-white text-xs text-slate-950 placeholder:text-slate-400 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-100 dark:placeholder:text-slate-500";
const primaryButton =
  "bg-blue-600 text-white shadow-sm shadow-blue-600/20 hover:bg-blue-700 dark:bg-blue-500 dark:shadow-blue-950/40 dark:hover:bg-blue-400";

function slugifyKey(label: string): string {
  return label
    .trim()
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .replace(/^[^A-Z]+/, "");
}

function normalizeKeyInput(value: string): string {
  return value
    .trim()
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Z0-9_]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[^A-Z]+/, "");
}

function optionsToText(definition: FieldDefinition): string {
  const raw = definition.field_options as { choices?: unknown; options?: unknown } | null;
  const choices = Array.isArray(raw?.choices)
    ? raw?.choices
    : Array.isArray(raw?.options)
      ? raw?.options
      : [];
  return choices.filter((v): v is string => typeof v === "string").join(", ");
}

function instructionsToText(definition: FieldDefinition): string {
  const raw = definition.field_options ?? {};
  for (const key of ["instructions", "extraction_instructions", "behavior", "how_to_extract"]) {
    const value = raw[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

function fieldOptionsFromDraft(
  draft: Pick<FieldDraft, "field_type" | "optionsText" | "instructionsText">,
): Record<string, unknown> | null {
  const options: Record<string, unknown> = {};
  if (choiceTypes.has(draft.field_type)) {
    const choices = draft.optionsText
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    options.choices = choices;
  }
  if (draft.field_type === "document") {
    options.choices = ["missing", "ok", "rejected"];
    options.is_document_status = true;
  }
  const instructions = draft.instructionsText.trim();
  if (instructions) options.instructions = instructions;
  return Object.keys(options).length ? options : null;
}

function draftFromDefinition(definition: FieldDefinition): FieldDraft {
  return {
    label: definition.label,
    field_type: definition.field_type as FieldDefinitionType,
    optionsText: optionsToText(definition),
    instructionsText: instructionsToText(definition),
    ordering: String(definition.ordering ?? 0),
  };
}

function renderReferenceHighlights(text: string, knownTokens: Map<string, ReferenceToken>) {
  const pattern = /(#(?:document|documento|catalogo|catalog|faq|kb)\.[A-Za-z0-9_.-]+)/gi;
  const parts: Array<{ id: string; text: string; token?: ReferenceToken; isReference?: boolean }> =
    [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const value = match[0];
    const index = match.index ?? 0;
    if (index > cursor) {
      parts.push({ id: `text-${cursor}-${index}`, text: text.slice(cursor, index) });
    }
    parts.push({
      id: `ref-${index}-${index + value.length}`,
      text: value,
      token: knownTokens.get(value.toLowerCase()),
      isReference: true,
    });
    cursor = index + value.length;
  }
  if (cursor < text.length) {
    parts.push({ id: `text-${cursor}-${text.length}`, text: text.slice(cursor) });
  }
  return parts;
}

function fieldTypeLabel(type: FieldDefinitionType | string): string {
  return FIELD_TYPES.find((item) => item.value === type)?.label ?? String(type);
}

function isDraftDirty(definition: FieldDefinition, draft: FieldDraft): boolean {
  return (
    draft.label !== definition.label ||
    draft.field_type !== definition.field_type ||
    draft.optionsText !== optionsToText(definition) ||
    draft.instructionsText !== instructionsToText(definition) ||
    Number.parseInt(draft.ordering, 10) !== definition.ordering
  );
}

function FieldTypeIcon({
  type,
  className,
}: {
  type: FieldDefinitionType | string;
  className?: string;
}) {
  const iconClass = cn("size-4", className);
  if (type === "select") return <List className={iconClass} />;
  if (type === "multiselect") return <ListChecks className={iconClass} />;
  if (type === "number") return <Hash className={iconClass} />;
  if (type === "date") return <Calendar className={iconClass} />;
  if (type === "checkbox") return <ToggleLeft className={iconClass} />;
  if (type === "document") return <FileCheck className={iconClass} />;
  return <FileText className={iconClass} />;
}

function FieldTypeBadge({ type }: { type: FieldDefinitionType | string }) {
  const tone =
    type === "select"
      ? "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-400/20 dark:bg-violet-500/10 dark:text-violet-200"
      : type === "multiselect"
        ? "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-400/20 dark:bg-fuchsia-500/10 dark:text-fuchsia-200"
        : type === "number"
          ? "border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-500/10 dark:text-cyan-200"
          : type === "date"
            ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200"
            : type === "checkbox"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-500/10 dark:text-emerald-200"
              : type === "document"
                ? "border-teal-200 bg-teal-50 text-teal-700 dark:border-teal-400/20 dark:bg-teal-500/10 dark:text-teal-200"
                : "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-400/20 dark:bg-blue-500/10 dark:text-blue-200";
  return (
    <Badge variant="outline" className={cn("gap-1.5 px-2 py-0.5 text-[11px]", tone)}>
      <FieldTypeIcon type={type} className="size-3" />
      {fieldTypeLabel(type)}
    </Badge>
  );
}

function FieldStats({
  total,
  documents,
  aiFields,
  kbReferences,
}: {
  total: number;
  documents: number;
  aiFields: number;
  kbReferences: number;
}) {
  const stats = [
    { label: "Total campos", value: total, detail: "en orden de lectura", icon: ListChecks },
    { label: "Documentos", value: documents, detail: "estatus validables", icon: FileCheck },
    { label: "Campos IA", value: aiFields, detail: "con instrucciones", icon: Sparkles },
    { label: "Referencias KB", value: kbReferences, detail: "con tokens activos", icon: BookOpen },
  ];
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {stats.map((stat) => (
        <div key={stat.label} className={cn(premiumCard, "px-4 py-3")}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {stat.label}
              </div>
              <div className="mt-1 text-2xl font-semibold text-slate-950 dark:text-slate-100">
                {stat.value}
              </div>
              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-500">
                {stat.detail}
              </div>
            </div>
            <div className="flex size-10 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-600 dark:border-blue-400/10 dark:bg-blue-500/10 dark:text-cyan-300">
              <stat.icon className="size-4" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function FieldSearchToolbar({
  search,
  onSearchChange,
  typeFilter,
  onTypeFilterChange,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  typeFilter: string;
  onTypeFilterChange: (value: string) => void;
}) {
  return (
    <div className={cn(premiumCard, "p-3")}>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Buscar por nombre o clave tecnica"
            className={cn(premiumInput, "pl-9")}
          />
        </div>
        <Select value={typeFilter} onValueChange={onTypeFilterChange}>
          <SelectTrigger className={premiumInput}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TYPES} className="text-xs">
              Todos los tipos
            </SelectItem>
            {FIELD_TYPES.map((type) => (
              <SelectItem key={type.value} value={type.value} className="text-xs">
                {type.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

function CreateFieldPanel({
  newLabel,
  newKey,
  newKeyPreview,
  newType,
  newOptions,
  newInstructions,
  isPending,
  onLabelChange,
  onKeyChange,
  onTypeChange,
  onOptionsChange,
  onInstructionsChange,
  onCreate,
  instructionRef,
  referencePicker,
  referencePreview,
}: {
  newLabel: string;
  newKey: string;
  newKeyPreview: string;
  newType: FieldDefinitionType;
  newOptions: string;
  newInstructions: string;
  isPending: boolean;
  onLabelChange: (value: string) => void;
  onKeyChange: (value: string) => void;
  onTypeChange: (value: FieldDefinitionType) => void;
  onOptionsChange: (value: string) => void;
  onInstructionsChange: (value: string) => void;
  onCreate: () => void;
  instructionRef: (node: HTMLTextAreaElement | null) => void;
  referencePicker: ReactNode;
  referencePreview: ReactNode;
}) {
  return (
    <div className={cn(premiumCard, "overflow-hidden dark:ring-1 dark:ring-blue-500/10")}>
      <div className="border-b border-slate-100 px-5 py-4 dark:border-white/5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950 dark:text-slate-100">
              Crear nuevo dato
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Define que dato puede recordar la IA y como debe leerlo.
            </p>
          </div>
          <Badge
            variant="outline"
            className="border-blue-200 bg-blue-50 font-mono text-[11px] text-blue-700 dark:border-blue-400/20 dark:bg-blue-500/10 dark:text-cyan-200"
          >
            {newKeyPreview || "CLAVE_TECNICA"}
          </Badge>
        </div>
      </div>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)_220px]">
          <div className="space-y-1.5">
            <Label className="text-[11px] text-slate-600 dark:text-slate-300">Nombre visible</Label>
            <Input
              value={newLabel}
              onChange={(event) => onLabelChange(event.target.value)}
              placeholder="Ej. INE frente"
              className={premiumInput}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[11px] text-slate-600 dark:text-slate-300">Clave tecnica</Label>
            <Input
              value={newKey}
              onChange={(event) => onKeyChange(event.target.value)}
              placeholder="INE_FRENTE"
              className={cn(premiumInput, "font-mono")}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[11px] text-slate-600 dark:text-slate-300">Tipo de campo</Label>
            <Select
              value={newType}
              onValueChange={(value) => onTypeChange(value as FieldDefinitionType)}
            >
              <SelectTrigger className={premiumInput}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FIELD_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value} className="text-xs">
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {choiceTypes.has(newType) && (
          <div className="space-y-1.5">
            <Label className="text-[11px] text-slate-600 dark:text-slate-300">Opciones</Label>
            <Input
              value={newOptions}
              onChange={(event) => onOptionsChange(event.target.value)}
              placeholder="aprobado, pendiente"
              className={premiumInput}
            />
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          <div className="space-y-1.5">
            <Label className="text-[11px] text-slate-600 dark:text-slate-300">
              Instrucciones IA
            </Label>
            <Textarea
              ref={instructionRef}
              value={newInstructions}
              onChange={(event) => onInstructionsChange(event.target.value)}
              placeholder="Como debe detectar, validar o pedir este dato."
              className={premiumTextarea}
            />
            {referencePreview}
          </div>
          <div className="space-y-1.5">
            <Label className="text-[11px] text-slate-600 dark:text-slate-300">Referencias KB</Label>
            {referencePicker}
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            className={cn("h-9 rounded-lg px-4", primaryButton)}
            disabled={!newLabel.trim() || isPending}
            onClick={onCreate}
          >
            <Plus className="mr-1 size-3.5" />
            Agregar dato
          </Button>
        </div>
      </div>
    </div>
  );
}

function FieldRow({
  definition,
  draft,
  index,
  dirty,
  active,
  onClick,
}: {
  definition: FieldDefinition;
  draft: FieldDraft;
  index: number;
  dirty: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group flex w-full items-center gap-3 border-b border-slate-100 px-4 py-3 text-left transition last:border-b-0 hover:bg-slate-50 dark:border-white/5 dark:hover:bg-white/[0.04]",
        active &&
          "bg-blue-50/70 dark:bg-blue-500/10 dark:ring-1 dark:ring-inset dark:ring-blue-400/20",
      )}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-xs font-semibold text-slate-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-300">
        {index + 1}
      </div>
      <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-600 dark:border-blue-400/10 dark:bg-blue-500/10 dark:text-cyan-300">
        <FieldTypeIcon type={draft.field_type} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-950 dark:text-slate-100">
          {draft.label || definition.label}
        </div>
        <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500 dark:text-slate-500">
          {definition.key}
        </div>
      </div>

      <div className="hidden shrink-0 sm:block">
        <FieldTypeBadge type={draft.field_type} />
      </div>

      {dirty && (
        <Badge
          variant="outline"
          className="shrink-0 border-amber-200 bg-amber-50 text-[11px] text-amber-700 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200"
        >
          Sin guardar
        </Badge>
      )}

      <ChevronRight className="size-4 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-blue-600 dark:text-slate-600 dark:group-hover:text-cyan-300" />
    </button>
  );
}

function FieldEditorDrawer({
  definition,
  draft,
  dirty,
  updatePending,
  removePending,
  onClose,
  onPatch,
  onSave,
  onDelete,
  instructionRef,
  referencePicker,
  referencePreview,
}: {
  definition: FieldDefinition;
  draft: FieldDraft;
  dirty: boolean;
  updatePending: boolean;
  removePending: boolean;
  onClose: () => void;
  onPatch: (patch: Partial<FieldDraft>) => void;
  onSave: () => void;
  onDelete: () => void;
  instructionRef: (node: HTMLTextAreaElement | null) => void;
  referencePicker: ReactNode;
  referencePreview: ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        className="absolute inset-0 bg-slate-950/45 backdrop-blur-sm dark:bg-black/60"
        onClick={onClose}
        aria-label="Cerrar editor"
      />

      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col overflow-hidden border-l border-slate-200 bg-white shadow-2xl dark:border-white/10 dark:bg-[#0B1020]">
        <div className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-5 py-4 backdrop-blur dark:border-white/10 dark:bg-[#0B1020]/95">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-slate-100">
                Editar dato del cliente
                {dirty && (
                  <Badge
                    variant="outline"
                    className="border-amber-200 bg-amber-50 text-[11px] text-amber-700 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200"
                  >
                    Sin guardar
                  </Badge>
                )}
              </div>
              <div className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
                {draft.label || definition.label}
              </div>
              <div className="mt-1 truncate font-mono text-[11px] text-slate-400 dark:text-slate-500">
                {definition.key}
              </div>
            </div>

            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              <X className="mr-1 size-3.5" />
              Cerrar
            </Button>
          </div>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          <div className={cn(premiumCard, "p-4 shadow-none dark:shadow-none")}>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">
                  Nombre visible
                </Label>
                <Input
                  value={draft.label}
                  onChange={(event) => onPatch({ label: event.target.value })}
                  className={premiumInput}
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">
                  Clave tecnica
                </Label>
                <Input
                  value={normalizeKeyInput(definition.key)}
                  disabled
                  className={cn(premiumInput, "font-mono opacity-80")}
                  title="La clave no cambia para no romper reglas existentes"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">
                  Tipo de campo
                </Label>
                <Select
                  value={draft.field_type}
                  onValueChange={(value) => onPatch({ field_type: value as FieldDefinitionType })}
                >
                  <SelectTrigger className={premiumInput}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FIELD_TYPES.map((type) => (
                      <SelectItem key={type.value} value={type.value} className="text-xs">
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">Orden</Label>
                <Input
                  type="number"
                  value={draft.ordering}
                  onChange={(event) => onPatch({ ordering: event.target.value })}
                  className={premiumInput}
                />
              </div>
            </div>

            {choiceTypes.has(draft.field_type) && (
              <div className="mt-3 space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">Opciones</Label>
                <Input
                  value={draft.optionsText}
                  onChange={(event) => onPatch({ optionsText: event.target.value })}
                  placeholder="valor_a, valor_b"
                  className={premiumInput}
                />
              </div>
            )}
          </div>

          <div className={cn(premiumCard, "p-4 shadow-none dark:shadow-none")}>
            <div className="space-y-1.5">
              <Label className="text-[11px] text-slate-600 dark:text-slate-300">
                Instrucciones IA
              </Label>
              <Textarea
                ref={instructionRef}
                value={draft.instructionsText}
                onChange={(event) => onPatch({ instructionsText: event.target.value })}
                placeholder="Como debe detectar, validar o pedir este dato"
                className="min-h-44 rounded-lg border-slate-200 bg-white text-xs text-slate-950 placeholder:text-slate-400 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-100 dark:placeholder:text-slate-500"
              />
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(240px,0.85fr)_minmax(0,1fr)]">
              <div className="space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">
                  Referencias KB
                </Label>
                {referencePicker}
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px] text-slate-600 dark:text-slate-300">
                  Vista previa
                </Label>
                {referencePreview || (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-6 text-center text-xs text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
                    Sin referencias detectadas todavia.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="sticky bottom-0 flex items-center justify-between border-t border-slate-200 bg-white/95 px-5 py-4 backdrop-blur dark:border-white/10 dark:bg-[#0B1020]/95">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-slate-500 hover:text-destructive dark:text-slate-400"
            disabled={removePending}
            onClick={onDelete}
          >
            <Trash2 className="mr-1 size-3.5" />
            Eliminar campo
          </Button>

          <Button
            type="button"
            size="sm"
            className={cn("rounded-lg px-4", primaryButton)}
            disabled={!dirty || updatePending}
            onClick={onSave}
          >
            <Save className="mr-1 size-3.5" />
            Guardar cambios
          </Button>
        </div>
      </div>
    </div>
  );
}

export function CustomerFieldsEditor() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["field-definitions"],
    queryFn: fieldsApi.listDefinitions,
  });
  const docsQuery = useQuery({
    queryKey: ["knowledge", "documents", "customer-field-references"],
    queryFn: knowledgeApi.listDocuments,
  });
  const faqsQuery = useQuery({
    queryKey: ["knowledge", "faqs", "customer-field-references"],
    queryFn: knowledgeApi.listFaqs,
  });

  const [drafts, setDrafts] = useState<Record<string, FieldDraft>>({});
  const [newLabel, setNewLabel] = useState("");
  const [newKey, setNewKey] = useState("");
  const [newType, setNewType] = useState<FieldDefinitionType>("text");
  const [newOptions, setNewOptions] = useState("");
  const [newInstructions, setNewInstructions] = useState("");
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState(ALL_TYPES);
  const instructionRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});

  useEffect(() => {
    if (!query.data) return;
    setDrafts(
      Object.fromEntries(
        query.data.map((definition) => [definition.id, draftFromDefinition(definition)]),
      ),
    );
  }, [query.data]);

  const existingKeys = useMemo(
    () => new Set((query.data ?? []).map((definition) => definition.key.toUpperCase())),
    [query.data],
  );
  const sortedDefinitions = useMemo(
    () => [...(query.data ?? [])].sort((a, b) => (a.ordering ?? 0) - (b.ordering ?? 0)),
    [query.data],
  );
  const selectedDefinition = useMemo(
    () => sortedDefinitions.find((definition) => definition.id === selectedDefinitionId) ?? null,
    [sortedDefinitions, selectedDefinitionId],
  );
  const selectedDraft = selectedDefinition
    ? (drafts[selectedDefinition.id] ?? draftFromDefinition(selectedDefinition))
    : null;
  const newKeyPreview = normalizeKeyInput(newKey) || slugifyKey(newLabel);
  const fieldStats = useMemo(() => {
    let documents = 0;
    let aiFields = 0;
    let kbReferences = 0;
    for (const definition of sortedDefinitions) {
      const draft = drafts[definition.id] ?? draftFromDefinition(definition);
      if (draft.field_type === "document") documents += 1;
      if (draft.instructionsText.trim()) aiFields += 1;
      if (REFERENCE_PATTERN.test(draft.instructionsText)) kbReferences += 1;
    }
    return {
      total: sortedDefinitions.length,
      documents,
      aiFields,
      kbReferences,
    };
  }, [drafts, sortedDefinitions]);
  const filteredDefinitions = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return sortedDefinitions.filter((definition) => {
      const draft = drafts[definition.id] ?? draftFromDefinition(definition);
      const matchesType = typeFilter === ALL_TYPES || draft.field_type === typeFilter;
      const matchesSearch =
        !needle ||
        draft.label.toLowerCase().includes(needle) ||
        definition.label.toLowerCase().includes(needle) ||
        definition.key.toLowerCase().includes(needle);
      return matchesType && matchesSearch;
    });
  }, [drafts, search, sortedDefinitions, typeFilter]);
  const referenceTokens = useMemo<ReferenceToken[]>(() => {
    const documents =
      docsQuery.data?.slice(0, 30).map((document) => ({
        token: `#document.${document.filename.replace(/\s+/g, "_")}`,
        label: document.filename,
        description: `Documento KB (${document.status}, ${document.fragment_count} chunks)`,
        icon: "document" as const,
      })) ?? [];
    const faqs =
      faqsQuery.data?.slice(0, 20).map((faq) => ({
        token: `#faq.${faq.id}`,
        label: faq.question,
        description: "FAQ de Knowledge Base",
        icon: "faq" as const,
      })) ?? [];
    return [...documents, ...faqs];
  }, [docsQuery.data, faqsQuery.data]);
  const knownReferenceTokens = useMemo(
    () => new Map(referenceTokens.map((token) => [token.token.toLowerCase(), token])),
    [referenceTokens],
  );

  const create = useMutation({
    mutationFn: () => {
      const key = normalizeKeyInput(newKey) || slugifyKey(newLabel);
      if (!key) throw new Error("Define una clave tecnica");
      if (existingKeys.has(key.toUpperCase())) throw new Error("Esa clave ya existe");
      return fieldsApi.createDefinition({
        key,
        label: newLabel.trim(),
        field_type: newType,
        field_options: fieldOptionsFromDraft({
          field_type: newType,
          optionsText: newOptions,
          instructionsText: newInstructions,
        }),
        ordering: (query.data?.length ?? 0) + 1,
      });
    },
    onSuccess: () => {
      toast.success("Dato del cliente creado");
      setNewLabel("");
      setNewKey("");
      setNewType("text");
      setNewOptions("");
      setNewInstructions("");
      void qc.invalidateQueries({ queryKey: ["field-definitions"] });
    },
    onError: (e) => toast.error("No se pudo crear", { description: e.message }),
  });

  const update = useMutation({
    mutationFn: ({ definition, draft }: { definition: FieldDefinition; draft: FieldDraft }) =>
      fieldsApi.updateDefinition(definition.id, {
        label: draft.label.trim(),
        field_type: draft.field_type,
        field_options: fieldOptionsFromDraft(draft),
        ordering: Number.parseInt(draft.ordering, 10) || 0,
      }),
    onSuccess: () => {
      toast.success("Dato del cliente actualizado");
      void qc.invalidateQueries({ queryKey: ["field-definitions"] });
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: e.message }),
  });

  const remove = useMutation({
    mutationFn: (definition: FieldDefinition) => fieldsApi.deleteDefinition(definition.id),
    onSuccess: () => {
      toast.success("Dato del cliente eliminado");
      void qc.invalidateQueries({ queryKey: ["field-definitions"] });
    },
    onError: (e) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  const updateDraft = (id: string, patch: Partial<FieldDraft>) => {
    const definition = sortedDefinitions.find((item) => item.id === id);
    setDrafts((prev) => ({
      ...prev,
      [id]: {
        ...(prev[id] ?? (definition ? draftFromDefinition(definition) : {})),
        ...patch,
      } as FieldDraft,
    }));
  };

  const insertReferenceToken = (target: "new" | string, token: string) => {
    const textarea = instructionRefs.current[target];
    if (target === "new") {
      const cursor = textarea?.selectionStart ?? newInstructions.length;
      const next = `${newInstructions.slice(0, cursor)}${token}${newInstructions.slice(cursor)}`;
      setNewInstructions(next);
      requestAnimationFrame(() => {
        textarea?.focus();
        textarea?.setSelectionRange(cursor + token.length, cursor + token.length);
      });
      return;
    }
    const definition = sortedDefinitions.find((item) => item.id === target);
    const current =
      drafts[target]?.instructionsText ??
      (definition ? draftFromDefinition(definition).instructionsText : "");
    const cursor = textarea?.selectionStart ?? current.length;
    const next = `${current.slice(0, cursor)}${token}${current.slice(cursor)}`;
    updateDraft(target, { instructionsText: next });
    requestAnimationFrame(() => {
      textarea?.focus();
      textarea?.setSelectionRange(cursor + token.length, cursor + token.length);
    });
  };

  const ReferencePicker = ({ target }: { target: "new" | string }) => (
    <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-2 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-slate-600 dark:text-slate-300">
          Referencias KB
        </span>
        <span className="text-[10px] text-slate-500 dark:text-slate-500">Click para insertar</span>
      </div>
      <div className="flex max-h-32 flex-wrap gap-1.5 overflow-auto">
        {referenceTokens.length ? (
          referenceTokens.map((token) => (
            <button
              key={`${target}-${token.token}`}
              type="button"
              className="inline-flex max-w-full items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-left text-[11px] text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-300 dark:hover:border-cyan-400/30 dark:hover:bg-cyan-500/10"
              title={`${token.token}\n${token.description}`}
              onClick={() => insertReferenceToken(target, token.token)}
            >
              {token.icon === "document" ? (
                <FileText className="size-3 shrink-0 text-amber-600" />
              ) : (
                <BookOpen className="size-3 shrink-0 text-cyan-600" />
              )}
              <span className="truncate">{token.label}</span>
            </button>
          ))
        ) : (
          <span className="text-[11px] text-slate-500 dark:text-slate-400">
            Sube documentos o FAQs en Knowledge Base para referenciarlos.
          </span>
        )}
      </div>
    </div>
  );

  const ReferencePreview = ({ text }: { text: string }) => {
    const parts = renderReferenceHighlights(text, knownReferenceTokens);
    if (!parts.some((part) => part.isReference)) return null;
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-2 text-[11px] leading-relaxed text-slate-700 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300">
        <div className="mb-1 font-medium text-slate-500 dark:text-slate-400">
          Referencias detectadas
        </div>
        <div className="whitespace-pre-wrap break-words">
          {parts.map((part) =>
            part.isReference ? (
              <Badge
                key={part.id}
                variant="outline"
                className="mx-0.5 border-blue-200 bg-blue-50 align-baseline font-mono text-[10px] text-blue-700 dark:border-cyan-400/20 dark:bg-cyan-500/10 dark:text-cyan-200"
                title={part.token?.description ?? "Referencia KB"}
              >
                {part.text}
              </Badge>
            ) : (
              <span key={part.id}>{part.text}</span>
            ),
          )}
        </div>
      </div>
    );
  };

  if (query.isLoading) {
    return (
      <section className="min-h-screen bg-slate-50 px-6 py-6 text-slate-950 dark:bg-[#070A12] dark:text-slate-100">
        <div className="mx-auto max-w-7xl space-y-4">
          <Skeleton className="h-24 w-full rounded-2xl" />
          <div className="grid gap-3 md:grid-cols-4">
            <Skeleton className="h-28 rounded-2xl" />
            <Skeleton className="h-28 rounded-2xl" />
            <Skeleton className="h-28 rounded-2xl" />
            <Skeleton className="h-28 rounded-2xl" />
          </div>
          <Skeleton className="h-96 w-full rounded-2xl" />
        </div>
      </section>
    );
  }

  const selectedDirty =
    selectedDefinition && selectedDraft ? isDraftDirty(selectedDefinition, selectedDraft) : false;

  return (
    <section className="min-h-screen bg-slate-50 px-6 py-6 text-slate-950 dark:bg-[#070A12] dark:text-slate-100">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="overflow-hidden rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm dark:border-white/10 dark:bg-[#0E1424]/90 dark:shadow-2xl dark:shadow-black/20">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <Badge
                variant="outline"
                className="mb-3 border-blue-200 bg-blue-50 text-[11px] text-blue-700 dark:border-cyan-400/20 dark:bg-cyan-500/10 dark:text-cyan-200"
              >
                Configuracion IA
              </Badge>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-100">
                Datos del cliente
              </h1>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                Campos que la IA puede extraer, recordar y usar en reglas por cuenta.
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-400">
              <Sparkles className="size-4 text-blue-600 dark:text-cyan-300" />
              Orden visual por{" "}
              <span className="font-mono text-slate-700 dark:text-slate-200">ordering</span>
            </div>
          </div>
        </header>

        <FieldStats
          total={fieldStats.total}
          documents={fieldStats.documents}
          aiFields={fieldStats.aiFields}
          kbReferences={fieldStats.kbReferences}
        />

        <CreateFieldPanel
          newLabel={newLabel}
          newKey={newKey}
          newKeyPreview={newKeyPreview}
          newType={newType}
          newOptions={newOptions}
          newInstructions={newInstructions}
          isPending={create.isPending}
          onLabelChange={(value) => {
            setNewLabel(value);
            if (!newKey) setNewKey(slugifyKey(value));
          }}
          onKeyChange={(value) => setNewKey(normalizeKeyInput(value))}
          onTypeChange={setNewType}
          onOptionsChange={setNewOptions}
          onInstructionsChange={setNewInstructions}
          onCreate={() => create.mutate()}
          instructionRef={(node) => {
            instructionRefs.current.new = node;
          }}
          referencePicker={<ReferencePicker target="new" />}
          referencePreview={<ReferencePreview text={newInstructions} />}
        />

        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-950 dark:text-slate-100">
                Datos creados
              </h2>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Da click en un dato para editarlo. La lista sigue el orden en que la IA los lee.
              </p>
            </div>
            <Badge
              variant="outline"
              className="border-slate-200 bg-white text-xs text-slate-600 dark:border-white/10 dark:bg-white/[0.04] dark:text-slate-300"
            >
              {filteredDefinitions.length} de {sortedDefinitions.length} campos
            </Badge>
          </div>

          <FieldSearchToolbar
            search={search}
            onSearchChange={setSearch}
            typeFilter={typeFilter}
            onTypeFilterChange={setTypeFilter}
          />

          <div className={cn(premiumCard, "overflow-hidden")}>
            {filteredDefinitions.length ? (
              filteredDefinitions.map((definition) => {
                const originalIndex = sortedDefinitions.findIndex(
                  (item) => item.id === definition.id,
                );
                const draft = drafts[definition.id] ?? draftFromDefinition(definition);
                const dirty = isDraftDirty(definition, draft);
                return (
                  <FieldRow
                    key={definition.id}
                    definition={definition}
                    draft={draft}
                    index={originalIndex}
                    dirty={dirty}
                    active={definition.id === selectedDefinitionId}
                    onClick={() => setSelectedDefinitionId(definition.id)}
                  />
                );
              })
            ) : (
              <div className="px-4 py-12 text-center">
                <div className="mx-auto flex size-12 items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 text-slate-400 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-500">
                  <Search className="size-5" />
                </div>
                <div className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
                  No hay datos para mostrar
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Ajusta la busqueda o crea un nuevo dato para este tenant.
                </div>
              </div>
            )}
          </div>
        </div>

        {selectedDefinition && selectedDraft && (
          <FieldEditorDrawer
            definition={selectedDefinition}
            draft={selectedDraft}
            dirty={Boolean(selectedDirty)}
            updatePending={update.isPending}
            removePending={remove.isPending}
            onClose={() => setSelectedDefinitionId(null)}
            onPatch={(patch) => updateDraft(selectedDefinition.id, patch)}
            onSave={() =>
              update.mutate({
                definition: selectedDefinition,
                draft: selectedDraft,
              })
            }
            onDelete={() => {
              if (window.confirm(`Eliminar el campo "${selectedDefinition.label}"?`)) {
                remove.mutate(selectedDefinition);
                setSelectedDefinitionId(null);
              }
            }}
            instructionRef={(node) => {
              instructionRefs.current[selectedDefinition.id] = node;
            }}
            referencePicker={<ReferencePicker target={selectedDefinition.id} />}
            referencePreview={<ReferencePreview text={selectedDraft.instructionsText} />}
          />
        )}
      </div>
    </section>
  );
}

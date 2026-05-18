import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

const FIELD_TYPES: Array<{ value: FieldDefinitionType; label: string }> = [
  { value: "text", label: "Texto" },
  { value: "select", label: "Lista" },
  { value: "number", label: "Numero" },
  { value: "date", label: "Fecha" },
  { value: "checkbox", label: "Si/No" },
  { value: "multiselect", label: "Lista multiple" },
];

interface FieldDraft {
  label: string;
  field_type: FieldDefinitionType;
  optionsText: string;
  instructionsText: string;
  aliasesText: string;
  ordering: string;
}

interface ReferenceToken {
  token: string;
  label: string;
  description: string;
  icon: "document" | "faq";
}

const choiceTypes = new Set<FieldDefinitionType>(["select", "multiselect"]);

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

function aliasesToText(definition: FieldDefinition): string {
  const raw = definition.field_options ?? {};
  const aliases = raw.option_aliases ?? raw.aliases ?? raw.map;
  if (!aliases || typeof aliases !== "object" || Array.isArray(aliases)) return "";
  return Object.entries(aliases)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
}

function aliasesFromText(text: string): Record<string, string> | null {
  const entries = text
    .split(/[,\n]/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const match = chunk.match(/^(.+?)(?:=>|=|:)(.+)$/);
      if (!match) return null;
      const key = match[1]?.trim() ?? "";
      const value = match[2]?.trim() ?? "";
      return [key, value] as const;
    })
    .filter((entry): entry is readonly [string, string] => !!entry && !!entry[0] && !!entry[1]);
  return entries.length ? Object.fromEntries(entries) : null;
}

function fieldOptionsFromDraft(
  draft: Pick<FieldDraft, "field_type" | "optionsText" | "instructionsText" | "aliasesText">,
): Record<string, unknown> | null {
  const options: Record<string, unknown> = {};
  if (choiceTypes.has(draft.field_type)) {
    const choices = draft.optionsText
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    options.choices = choices;
  }
  const instructions = draft.instructionsText.trim();
  if (instructions) options.instructions = instructions;
  const aliases = aliasesFromText(draft.aliasesText);
  if (aliases) options.option_aliases = aliases;
  return Object.keys(options).length ? options : null;
}

function draftFromDefinition(definition: FieldDefinition): FieldDraft {
  return {
    label: definition.label,
    field_type: definition.field_type as FieldDefinitionType,
    optionsText: optionsToText(definition),
    instructionsText: instructionsToText(definition),
    aliasesText: aliasesToText(definition),
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
  const [newAliases, setNewAliases] = useState("");
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
          aliasesText: newAliases,
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
      setNewAliases("");
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
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } as FieldDraft }));
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
    const current = drafts[target]?.instructionsText ?? "";
    const cursor = textarea?.selectionStart ?? current.length;
    const next = `${current.slice(0, cursor)}${token}${current.slice(cursor)}`;
    updateDraft(target, { instructionsText: next });
    requestAnimationFrame(() => {
      textarea?.focus();
      textarea?.setSelectionRange(cursor + token.length, cursor + token.length);
    });
  };

  const ReferencePicker = ({ target }: { target: "new" | string }) => (
    <div className="rounded-md border bg-muted/20 p-2">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-muted-foreground">Referencias KB</span>
        <span className="text-[10px] text-muted-foreground">Click para insertar</span>
      </div>
      <div className="flex max-h-24 flex-wrap gap-1 overflow-auto">
        {referenceTokens.length ? (
          referenceTokens.map((token) => (
            <button
              key={`${target}-${token.token}`}
              type="button"
              className="inline-flex max-w-full items-center gap-1 rounded-md border bg-background px-2 py-1 text-left text-[11px] hover:bg-muted"
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
          <span className="text-[11px] text-muted-foreground">
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
      <div className="rounded-md border bg-muted/20 p-2 text-[11px] leading-relaxed">
        <div className="mb-1 font-medium text-muted-foreground">Referencias detectadas</div>
        <div className="whitespace-pre-wrap break-words">
          {parts.map((part) =>
            part.isReference ? (
              <Badge
                key={part.id}
                variant="outline"
                className="mx-0.5 align-baseline font-mono text-[10px]"
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

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Datos del cliente</CardTitle>
        <div className="text-xs text-muted-foreground">
          Estos campos aparecen en Conversaciones y como campos disponibles en reglas del Pipeline.
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 rounded-md border border-dashed bg-muted/20 p-3 md:grid-cols-[1fr_0.8fr_0.7fr_1fr_auto]">
          <div className="space-y-1">
            <Label className="text-[11px]">Nombre visible</Label>
            <Input
              value={newLabel}
              onChange={(e) => {
                const next = e.target.value;
                setNewLabel(next);
                if (!newKey) setNewKey(slugifyKey(next));
              }}
              placeholder="Ej. INE frente"
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px]">Clave</Label>
            <Input
              value={newKey}
              onChange={(e) => setNewKey(normalizeKeyInput(e.target.value))}
              placeholder="INE_FRENTE"
              className="h-8 font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px]">Tipo</Label>
            <Select
              value={newType}
              onValueChange={(value) => setNewType(value as FieldDefinitionType)}
            >
              <SelectTrigger className="h-8 text-xs">
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
          <div className="space-y-1">
            <Label className="text-[11px]">Opciones</Label>
            <Input
              value={newOptions}
              onChange={(e) => setNewOptions(e.target.value)}
              placeholder="aprobado, pendiente"
              className="h-8 text-xs"
              disabled={!choiceTypes.has(newType)}
            />
          </div>
          <div className="flex items-end">
            <Button
              type="button"
              size="sm"
              className="h-8"
              disabled={!newLabel.trim() || create.isPending}
              onClick={() => create.mutate()}
            >
              <Plus className="mr-1 size-3.5" />
              Agregar
            </Button>
          </div>
          <div className="space-y-1 md:col-span-2">
            <Label className="text-[11px]">Instrucciones IA</Label>
            <Textarea
              ref={(node) => {
                instructionRefs.current.new = node;
              }}
              value={newInstructions}
              onChange={(e) => setNewInstructions(e.target.value)}
              placeholder="Ej. Valida contra #document.CATALOGO_MODELOS2026.json y guarda solo el valor canonico."
              className="min-h-16 text-xs"
            />
            <ReferencePicker target="new" />
            <ReferencePreview text={newInstructions} />
          </div>
          <div className="space-y-1 md:col-span-3">
            <Label className="text-[11px]">Mapeo / alias</Label>
            <Textarea
              value={newAliases}
              onChange={(e) => setNewAliases(e.target.value)}
              placeholder="1=Nomina tarjeta, 2=Nomina recibos"
              className="min-h-16 font-mono text-xs"
            />
          </div>
        </div>

        <div className="space-y-2">
          {query.data?.length ? (
            query.data.map((definition) => {
              const draft = drafts[definition.id] ?? draftFromDefinition(definition);
              const dirty =
                draft.label !== definition.label ||
                draft.field_type !== definition.field_type ||
                draft.optionsText !== optionsToText(definition) ||
                draft.instructionsText !== instructionsToText(definition) ||
                draft.aliasesText !== aliasesToText(definition) ||
                Number.parseInt(draft.ordering, 10) !== definition.ordering;
              return (
                <div
                  key={definition.id}
                  className="grid gap-2 rounded-md border bg-background p-3 md:grid-cols-[1fr_0.8fr_0.7fr_1fr_4rem_auto_auto]"
                >
                  <div className="space-y-1">
                    <Label className="text-[11px]">Nombre visible</Label>
                    <Input
                      value={draft.label}
                      onChange={(e) => updateDraft(definition.id, { label: e.target.value })}
                      className="h-8 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[11px]">Clave</Label>
                    <Input
                      value={normalizeKeyInput(definition.key)}
                      className="h-8 font-mono text-xs"
                      disabled
                      title="La clave no cambia para no romper reglas existentes"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[11px]">Tipo</Label>
                    <Select
                      value={draft.field_type}
                      onValueChange={(value) =>
                        updateDraft(definition.id, { field_type: value as FieldDefinitionType })
                      }
                    >
                      <SelectTrigger className="h-8 text-xs">
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
                  <div className="space-y-1">
                    <Label className="text-[11px]">Opciones</Label>
                    <Input
                      value={draft.optionsText}
                      onChange={(e) => updateDraft(definition.id, { optionsText: e.target.value })}
                      placeholder="valor_a, valor_b"
                      className="h-8 text-xs"
                      disabled={!choiceTypes.has(draft.field_type)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[11px]">Orden</Label>
                    <Input
                      type="number"
                      value={draft.ordering}
                      onChange={(e) => updateDraft(definition.id, { ordering: e.target.value })}
                      className="h-8 text-xs"
                    />
                  </div>
                  <div className="flex items-end">
                    <Button
                      type="button"
                      variant={dirty ? "default" : "outline"}
                      size="icon"
                      className="h-8 w-8"
                      disabled={!dirty || update.isPending}
                      onClick={() => update.mutate({ definition, draft })}
                      aria-label="Guardar dato"
                    >
                      <Save className="size-3.5" />
                    </Button>
                  </div>
                  <div className="flex items-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(definition)}
                      aria-label="Eliminar dato"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                  <div className="space-y-1 md:col-span-3">
                    <Label className="text-[11px]">Instrucciones IA</Label>
                    <Textarea
                      ref={(node) => {
                        instructionRefs.current[definition.id] = node;
                      }}
                      value={draft.instructionsText}
                      onChange={(e) =>
                        updateDraft(definition.id, { instructionsText: e.target.value })
                      }
                      placeholder="Como debe detectar o pedir este dato"
                      className="min-h-16 text-xs"
                    />
                    <ReferencePicker target={definition.id} />
                    <ReferencePreview text={draft.instructionsText} />
                  </div>
                  <div className="space-y-1 md:col-span-4">
                    <Label className="text-[11px]">Mapeo / alias</Label>
                    <Textarea
                      value={draft.aliasesText}
                      onChange={(e) => updateDraft(definition.id, { aliasesText: e.target.value })}
                      placeholder="1=opcion uno, 2=opcion dos"
                      className="min-h-16 font-mono text-xs"
                    />
                  </div>
                </div>
              );
            })
          ) : (
            <div className="rounded-md border border-dashed px-3 py-6 text-center text-xs text-muted-foreground">
              Aun no hay datos configurados para este tenant.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

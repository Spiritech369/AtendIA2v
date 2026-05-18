import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Bot,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Eye,
  FileCheck,
  Files,
  FileText,
  Info,
  ListChecks,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { tenantsApi } from "@/features/config/api";
import { fieldsApi } from "@/features/customers/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

type DocumentSpec = {
  key: string;
  label: string;
  hint: string;
};

type ExpedienteDraft = {
  docs_plan_field: string;
  docs_per_plan: Record<string, string[]>;
  documents_catalog: DocumentSpec[];
  vision_doc_mapping: Record<string, string[]>;
};

const DOC_KEY_RE = /^DOCS_[A-Z][A-Z0-9_]*$/;
const VISION_CATEGORIES = [
  "ine",
  "comprobante",
  "recibo_nomina",
  "estado_cuenta",
  "constancia_sat",
  "factura",
  "imss",
] as const;
type VisionCategory = (typeof VISION_CATEGORIES)[number];

const VISION_LABELS: Record<VisionCategory, string> = {
  ine: "INE",
  comprobante: "Comprobante",
  recibo_nomina: "Recibo nomina",
  estado_cuenta: "Estado cuenta",
  constancia_sat: "Constancia SAT",
  factura: "Factura",
  imss: "IMSS",
};
const PLAN_FIELD_KEYS = new Set(["CREDITO_TIPO", "TIPO_CREDITO", "PLAN_CREDITO"]);

function parseStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function parseDraft(definition: Record<string, unknown> | undefined): ExpedienteDraft {
  const def = definition ?? {};
  const catalog: DocumentSpec[] = Array.isArray(def.documents_catalog)
    ? def.documents_catalog.flatMap((item) => {
        if (typeof item !== "object" || item === null) return [];
        const raw = item as Record<string, unknown>;
        if (typeof raw.key !== "string" || typeof raw.label !== "string") return [];
        return [
          {
            key: raw.key,
            label: raw.label,
            hint: typeof raw.hint === "string" ? raw.hint : "",
          },
        ];
      })
    : [];

  const docsByPlan: Record<string, string[]> = {};
  if (typeof def.docs_per_plan === "object" && def.docs_per_plan !== null) {
    for (const [plan, docs] of Object.entries(def.docs_per_plan as Record<string, unknown>)) {
      docsByPlan[plan] = parseStringList(docs);
    }
  }

  const visionMapping: Record<string, string[]> = {};
  if (typeof def.vision_doc_mapping === "object" && def.vision_doc_mapping !== null) {
    for (const [category, docs] of Object.entries(
      def.vision_doc_mapping as Record<string, unknown>,
    )) {
      if ((VISION_CATEGORIES as readonly string[]).includes(category)) {
        visionMapping[category] = parseStringList(docs).filter((key) => DOC_KEY_RE.test(key));
      }
    }
  }

  return {
    docs_plan_field: typeof def.docs_plan_field === "string" ? def.docs_plan_field : "plan_credito",
    docs_per_plan: docsByPlan,
    documents_catalog: catalog,
    vision_doc_mapping: visionMapping,
  };
}

function deriveDocKey(label: string): string {
  const clean = label
    .trim()
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/^DOCS[_\s]?/i, "")
    .replace(/[^A-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_");
  return clean ? `DOCS_${clean}` : "";
}

function normalizeDocKeyInput(value: string): string {
  return deriveDocKey(value);
}

function normalizeTechnicalKey(value: string): string {
  return value
    .trim()
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_");
}

function choicesFromFieldOptions(options: Record<string, unknown> | null): string[] {
  const raw = options?.choices ?? options?.options;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function serialiseExpediente(draft: ExpedienteDraft): Record<string, unknown> {
  const mapping: Record<string, string[]> = {};
  for (const [category, docs] of Object.entries(draft.vision_doc_mapping)) {
    const clean = docs.filter((key) => DOC_KEY_RE.test(key));
    if (clean.length > 0) mapping[category] = clean;
  }
  return {
    docs_plan_field: draft.docs_plan_field.trim() || "plan_credito",
    documents_catalog: draft.documents_catalog.map((doc) => ({
      key: doc.key,
      label: doc.label.trim(),
      ...(doc.hint.trim() ? { hint: doc.hint.trim() } : {}),
    })),
    docs_per_plan: draft.docs_per_plan,
    vision_doc_mapping: mapping,
  };
}

function validateDraft(draft: ExpedienteDraft): string | null {
  const docKeys = new Set<string>();
  for (const doc of draft.documents_catalog) {
    if (!DOC_KEY_RE.test(doc.key)) return `Documento invalido: ${doc.key}`;
    if (!doc.label.trim()) return `El documento ${doc.key} no tiene nombre.`;
    if (docKeys.has(doc.key)) return `Documento duplicado: ${doc.key}`;
    docKeys.add(doc.key);
  }
  if (!draft.docs_plan_field.trim()) return "Selecciona el campo que define los casos.";

  for (const [plan, docs] of Object.entries(draft.docs_per_plan)) {
    if (!plan.trim()) return "Hay un plan sin nombre.";
    for (const key of docs) {
      if (!docKeys.has(key)) return `${plan} usa un documento que ya no existe: ${key}`;
    }
  }

  for (const [category, docs] of Object.entries(draft.vision_doc_mapping)) {
    if (!(VISION_CATEGORIES as readonly string[]).includes(category)) {
      return `Categoria Vision invalida: ${category}`;
    }
    for (const key of docs) {
      if (!docKeys.has(key))
        return `Vision ${category} apunta a un documento que ya no existe: ${key}`;
    }
  }

  return null;
}

function expedienteFingerprint(value: ExpedienteDraft | null): string {
  if (!value) return "";
  return JSON.stringify(serialiseExpediente(value));
}

export function ExpedientePage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const canEdit = user?.role === "tenant_admin" || user?.role === "superadmin";

  const query = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });
  const customerFields = useQuery({
    queryKey: ["field-definitions", "expediente-doc-keys"],
    queryFn: fieldsApi.listDefinitions,
    enabled: canEdit,
    retry: false,
  });

  const [draft, setDraft] = useState<ExpedienteDraft | null>(null);
  const [newDocLabel, setNewDocLabel] = useState("");
  const [newDocKey, setNewDocKey] = useState("");
  const [newDocHint, setNewDocHint] = useState("");
  const [newPlanName, setNewPlanName] = useState("");

  useEffect(() => {
    if (query.data?.definition) {
      setDraft(parseDraft(query.data.definition));
    }
  }, [query.data?.definition]);

  const savedDraft = useMemo(() => parseDraft(query.data?.definition), [query.data?.definition]);
  const dirty = useMemo(
    () => draft !== null && expedienteFingerprint(draft) !== expedienteFingerprint(savedDraft),
    [draft, savedDraft],
  );
  const docKeyPreview = newDocKey.trim()
    ? normalizeDocKeyInput(newDocKey)
    : deriveDocKey(newDocLabel);
  const docKeyExists = Boolean(
    docKeyPreview && draft?.documents_catalog.some((doc) => doc.key === docKeyPreview),
  );
  const customerDocFieldOptions = useMemo(
    () =>
      (customerFields.data ?? [])
        .map((field) => ({ ...field, docKey: normalizeTechnicalKey(field.key) }))
        .filter((field) => DOC_KEY_RE.test(field.docKey))
        .filter((field) => !draft?.documents_catalog.some((doc) => doc.key === field.docKey))
        .sort((a, b) => a.docKey.localeCompare(b.docKey)),
    [customerFields.data, draft?.documents_catalog],
  );
  const planField = useMemo(
    () =>
      (customerFields.data ?? []).find(
        (field) =>
          normalizeTechnicalKey(field.key) === normalizeTechnicalKey(draft?.docs_plan_field ?? ""),
      ) ??
      (customerFields.data ?? []).find((field) =>
        PLAN_FIELD_KEYS.has(normalizeTechnicalKey(field.key)),
      ),
    [customerFields.data, draft?.docs_plan_field],
  );
  const selectedPlanFieldKey = draft?.docs_plan_field || planField?.key || "plan_credito";
  const planFieldChoices = useMemo(
    () =>
      planField
        ? choicesFromFieldOptions(planField.field_options).filter(
            (choice) => !draft?.docs_per_plan[choice],
          )
        : [],
    [draft?.docs_per_plan, planField],
  );
  const validationError = draft ? validateDraft(draft) : null;
  const planCount = draft ? Object.keys(draft.docs_per_plan).length : 0;
  const mappedVisionCount = draft
    ? Object.values(draft.vision_doc_mapping).reduce((sum, docs) => sum + docs.length, 0)
    : 0;
  const visionCategoryCount = draft
    ? Object.values(draft.vision_doc_mapping).filter((docs) => docs.length > 0).length
    : 0;
  const configWarnings = useMemo(() => {
    if (!draft) return [];
    const warnings: string[] = [];
    if (!draft.docs_plan_field.trim()) warnings.push("Falta seleccionar el campo del cliente.");
    if (draft.documents_catalog.length === 0) warnings.push("No hay documentos en catalogo.");
    if (Object.keys(draft.docs_per_plan).length === 0) warnings.push("No hay casos configurados.");
    if (mappedVisionCount === 0) warnings.push("Vision esta en modo manual.");
    return warnings;
  }, [draft, mappedVisionCount]);
  const docUsage = useMemo(() => {
    const usage: Record<string, { plans: number; vision: number }> = {};
    if (!draft) return usage;
    for (const doc of draft.documents_catalog) usage[doc.key] = { plans: 0, vision: 0 };
    for (const docs of Object.values(draft.docs_per_plan)) {
      for (const docKey of docs) {
        if (usage[docKey]) usage[docKey].plans += 1;
      }
    }
    for (const docs of Object.values(draft.vision_doc_mapping)) {
      for (const docKey of docs) {
        if (usage[docKey]) usage[docKey].vision += 1;
      }
    }
    return usage;
  }, [draft]);

  const save = useMutation({
    mutationFn: async () => {
      if (!draft || !query.data?.definition) throw new Error("No hay expediente cargado.");
      const error = validateDraft(draft);
      if (error) throw new Error(error);
      const nextDefinition = {
        ...query.data.definition,
        ...serialiseExpediente(draft),
      };
      return tenantsApi.putPipeline(nextDefinition);
    },
    onSuccess: (response) => {
      queryClient.setQueryData(["tenants", "pipeline"], response);
      void queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      toast.success(`Expediente guardado (v${response.version})`);
    },
    onError: (error: Error) => {
      toast.error("No se pudo guardar Expediente", { description: error.message });
    },
  });

  function addDocument() {
    const label = newDocLabel.trim();
    const key = newDocKey.trim() ? normalizeDocKeyInput(newDocKey) : deriveDocKey(label);
    if (!draft || !label || !key || docKeyExists) return;
    setDraft({
      ...draft,
      documents_catalog: [...draft.documents_catalog, { key, label, hint: newDocHint.trim() }],
    });
    setNewDocLabel("");
    setNewDocKey("");
    setNewDocHint("");
  }

  function updateDocument(index: number, patch: Partial<DocumentSpec>) {
    setDraft((current) =>
      current
        ? {
            ...current,
            documents_catalog: current.documents_catalog.map((doc, i) =>
              i === index ? { ...doc, ...patch } : doc,
            ),
          }
        : current,
    );
  }

  function removeDocument(key: string) {
    setDraft((current) => {
      if (!current) return current;
      const docs_per_plan = Object.fromEntries(
        Object.entries(current.docs_per_plan).map(([plan, docs]) => [
          plan,
          docs.filter((docKey) => docKey !== key),
        ]),
      ) as Record<string, string[]>;
      const visionEntries = Object.entries(current.vision_doc_mapping).flatMap(
        ([category, docs]) => {
          const nextDocs = docs.filter((docKey) => docKey !== key);
          return nextDocs.length > 0 ? [[category, nextDocs] as const] : [];
        },
      );
      const vision_doc_mapping = Object.fromEntries(visionEntries) as Record<string, string[]>;
      return {
        ...current,
        documents_catalog: current.documents_catalog.filter((doc) => doc.key !== key),
        docs_per_plan,
        vision_doc_mapping,
      };
    });
  }

  function addPlan() {
    const plan = newPlanName.trim();
    if (!draft || !plan || draft.docs_per_plan[plan]) return;
    setDraft({
      ...draft,
      docs_per_plan: { ...draft.docs_per_plan, [plan]: [] },
    });
    setNewPlanName("");
  }

  function renamePlan(currentPlan: string, nextRaw: string) {
    const nextPlan = nextRaw.trim();
    if (!draft || !nextPlan || nextPlan === currentPlan) return;
    if (draft.docs_per_plan[nextPlan]) {
      toast.error("Ya existe ese plan");
      return;
    }
    const nextMap: Record<string, string[]> = {};
    for (const [plan, docs] of Object.entries(draft.docs_per_plan)) {
      nextMap[plan === currentPlan ? nextPlan : plan] = docs;
    }
    setDraft({ ...draft, docs_per_plan: nextMap });
  }

  function removePlan(plan: string) {
    setDraft((current) => {
      if (!current) return current;
      const docs_per_plan = { ...current.docs_per_plan };
      delete docs_per_plan[plan];
      return { ...current, docs_per_plan };
    });
  }

  function togglePlanDoc(plan: string, docKey: string) {
    setDraft((current) => {
      if (!current) return current;
      const currentDocs = current.docs_per_plan[plan] ?? [];
      const nextDocs = currentDocs.includes(docKey)
        ? currentDocs.filter((key) => key !== docKey)
        : [...currentDocs, docKey];
      return {
        ...current,
        docs_per_plan: { ...current.docs_per_plan, [plan]: nextDocs },
      };
    });
  }

  function toggleVisionDoc(category: VisionCategory, docKey: string) {
    setDraft((current) => {
      if (!current) return current;
      const currentDocs = current.vision_doc_mapping[category] ?? [];
      const nextDocs = currentDocs.includes(docKey)
        ? currentDocs.filter((key) => key !== docKey)
        : [...currentDocs, docKey];
      const vision_doc_mapping = { ...current.vision_doc_mapping };
      if (nextDocs.length === 0) delete vision_doc_mapping[category];
      else vision_doc_mapping[category] = nextDocs;
      return { ...current, vision_doc_mapping };
    });
  }

  function moveVisionDoc(category: VisionCategory, index: number, delta: -1 | 1) {
    setDraft((current) => {
      if (!current) return current;
      const docs = [...(current.vision_doc_mapping[category] ?? [])];
      const target = index + delta;
      if (target < 0 || target >= docs.length) return current;
      [docs[index], docs[target]] = [docs[target] as string, docs[index] as string];
      return {
        ...current,
        vision_doc_mapping: { ...current.vision_doc_mapping, [category]: docs },
      };
    });
  }

  if (query.isLoading || !draft) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-24 w-full" />
        <div className="grid gap-4 xl:grid-cols-[0.9fr_1.25fr_0.95fr]">
          <Skeleton className="h-96 w-full" />
          <Skeleton className="h-96 w-full" />
          <Skeleton className="h-96 w-full" />
        </div>
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="rounded-md border bg-card p-6 text-sm text-muted-foreground">
        No se pudo cargar el pipeline activo para editar Expediente.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="sticky top-0 z-10 -mx-1 rounded-md border bg-background/95 px-1 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <ClipboardCheck className="h-5 w-5" />
              Expediente
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Matriz de documentos, reglas por caso y lectura automatica de Vision.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={dirty ? "default" : "secondary"}>
              {dirty ? "Cambios sin guardar" : "Sin cambios"}
            </Badge>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!dirty || save.isPending}
              onClick={() => setDraft(savedDraft)}
            >
              <RotateCcw className="h-4 w-4" />
              Revertir
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!canEdit || !dirty || Boolean(validationError) || save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Guardar
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <Metric
          icon={Files}
          label="Catalogo"
          value={draft.documents_catalog.length}
          detail="documentos"
        />
        <Metric icon={ListChecks} label="Casos" value={planCount} detail="planes activos" />
        <Metric icon={Eye} label="Vision" value={mappedVisionCount} detail="mapeos automaticos" />
      </div>

      <ConfigStatus
        fieldKey={selectedPlanFieldKey}
        fieldLabel={planField?.label}
        planNames={Object.keys(draft.docs_per_plan)}
        documentCount={draft.documents_catalog.length}
        mappedVisionCount={mappedVisionCount}
        visionCategoryCount={visionCategoryCount}
        warnings={configWarnings}
      />

      {validationError && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{validationError}</span>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.82fr)_minmax(0,1.6fr)]">
        <section className="rounded-lg border bg-card xl:sticky xl:top-24 xl:max-h-[calc(100vh-7rem)] xl:overflow-auto">
          <SectionHeader
            icon={FileText}
            title="Catalogo de documentos"
            count={draft.documents_catalog.length}
          />
          <div className="space-y-3 p-4 pt-0">
            {canEdit && (
              <div className="rounded-md border bg-muted/20 p-3">
                <div className="space-y-2">
                  <div>
                    <Label className="text-xs">Nombre</Label>
                    <Input
                      value={newDocLabel}
                      onChange={(event) => setNewDocLabel(event.target.value)}
                      placeholder="INE - frente"
                      className="h-8"
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && newDocLabel.trim() && !docKeyExists) {
                          event.preventDefault();
                          addDocument();
                        }
                      }}
                    />
                  </div>
                  <div>
                    <Label className="text-xs">ID tecnico</Label>
                    <Input
                      value={newDocKey}
                      onChange={(event) => setNewDocKey(event.target.value)}
                      onBlur={() => setNewDocKey((value) => normalizeDocKeyInput(value))}
                      placeholder="DOCS_INE_FRENTE"
                      className="h-8 font-mono text-xs"
                    />
                    <p
                      className={cn(
                        "mt-1 text-xs",
                        docKeyExists || (docKeyPreview && !DOC_KEY_RE.test(docKeyPreview))
                          ? "text-destructive"
                          : "text-muted-foreground",
                      )}
                    >
                      {docKeyPreview ? (
                        <>
                          Se guardara como <code>{docKeyPreview}</code>
                          {docKeyExists ? " y ya existe" : ""}
                        </>
                      ) : (
                        "Puedes pegar aqui el ID creado en Datos del cliente."
                      )}
                    </p>
                    {customerDocFieldOptions.length > 0 && (
                      <div className="mt-2 flex max-h-20 flex-wrap gap-1 overflow-auto">
                        {customerDocFieldOptions.slice(0, 8).map((field) => (
                          <button
                            key={field.id}
                            type="button"
                            className="rounded-full border border-dashed px-2 py-1 text-[11px] font-mono hover:bg-muted"
                            title={field.label}
                            onClick={() => {
                              setNewDocKey(field.docKey);
                              if (!newDocLabel.trim()) setNewDocLabel(field.label);
                            }}
                          >
                            {field.docKey}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div>
                    <Label className="text-xs">Nota</Label>
                    <Input
                      value={newDocHint}
                      onChange={(event) => setNewDocHint(event.target.value)}
                      placeholder="Vigente, legible, sin recortar"
                      className="h-8"
                    />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full"
                    disabled={
                      !newDocLabel.trim() ||
                      !docKeyPreview ||
                      !DOC_KEY_RE.test(docKeyPreview) ||
                      docKeyExists
                    }
                    onClick={addDocument}
                  >
                    <Plus className="h-4 w-4" />
                    Agregar
                  </Button>
                </div>
              </div>
            )}

            <div className="space-y-2">
              {draft.documents_catalog.map((doc, index) => (
                <div key={doc.key} className="rounded-md border bg-background p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <code className="block truncate text-xs text-muted-foreground">
                        {doc.key}
                      </code>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
                          {docUsage[doc.key]?.plans ?? 0} casos
                        </Badge>
                        <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
                          {docUsage[doc.key]?.vision ?? 0} Vision
                        </Badge>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      disabled={!canEdit}
                      onClick={() => removeDocument(doc.key)}
                      aria-label={`Eliminar ${doc.label}`}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </div>
                  <div className="space-y-2">
                    <Input
                      value={doc.label}
                      disabled={!canEdit}
                      onChange={(event) => updateDocument(index, { label: event.target.value })}
                      className="h-8"
                    />
                    <Input
                      value={doc.hint}
                      disabled={!canEdit}
                      onChange={(event) => updateDocument(index, { hint: event.target.value })}
                      placeholder="Nota opcional"
                      className="h-8 text-xs"
                    />
                  </div>
                </div>
              ))}
              {draft.documents_catalog.length === 0 && (
                <EmptyState icon={FileText} text="Sin documentos configurados." />
              )}
            </div>
          </div>
        </section>

        <section className="rounded-lg border bg-card">
          <Tabs defaultValue="cases" className="gap-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b p-4">
              <div>
                <h2 className="flex items-center gap-2 text-base font-semibold">
                  <Bot className="h-4 w-4" />
                  Reglas del expediente
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Que documentos pide cada valor del campo configurado y que reconoce Vision.
                </p>
              </div>
              <TabsList>
                <TabsTrigger value="cases">
                  <FileCheck className="h-4 w-4" />
                  Casos
                </TabsTrigger>
                <TabsTrigger value="vision">
                  <Eye className="h-4 w-4" />
                  Vision
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="cases" className="space-y-3 p-4">
              {canEdit && (
                <div className="grid gap-2 rounded-md border bg-muted/20 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
                  <div>
                    <Label className="text-xs">Campo que define el caso</Label>
                    <Select
                      value={selectedPlanFieldKey}
                      onValueChange={(value) =>
                        setDraft((current) =>
                          current ? { ...current, docs_plan_field: value } : current,
                        )
                      }
                    >
                      <SelectTrigger className="h-8 font-mono text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {customerFields.data?.map((field) => (
                          <SelectItem key={field.id} value={field.key} className="text-xs">
                            {normalizeTechnicalKey(field.key)} - {field.label}
                          </SelectItem>
                        ))}
                        {(!customerFields.data?.length ||
                          !customerFields.data.some(
                            (field) => field.key === selectedPlanFieldKey,
                          )) && (
                          <SelectItem value={selectedPlanFieldKey} className="text-xs">
                            {normalizeTechnicalKey(selectedPlanFieldKey)}
                          </SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                  <p className="self-end text-[11px] text-muted-foreground">
                    Cada caso debe llamarse igual que un valor posible de{" "}
                    <code>{normalizeTechnicalKey(selectedPlanFieldKey)}</code>. Ejemplo: si el
                    cliente tiene ese campo en <code>Nomina recibos</code>, se aplican los
                    documentos del caso <code>Nomina recibos</code>.
                  </p>
                </div>
              )}

              {canEdit && (
                <div className="flex items-end gap-2 rounded-md border border-dashed bg-muted/20 p-3">
                  <div className="flex-1">
                    <Label className="text-xs">
                      Nuevo caso / valor de {planField?.label ?? "credito"}
                    </Label>
                    <Input
                      value={newPlanName}
                      onChange={(event) => setNewPlanName(event.target.value)}
                      placeholder="Nomina recibos"
                      className="h-8"
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && newPlanName.trim()) {
                          event.preventDefault();
                          addPlan();
                        }
                      }}
                    />
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Debe coincidir con el valor que ya tenga el cliente en{" "}
                      <code>{normalizeTechnicalKey(selectedPlanFieldKey)}</code>.
                    </p>
                    {planFieldChoices.length > 0 && (
                      <div className="mt-2 flex max-h-20 flex-wrap gap-1 overflow-auto">
                        {planFieldChoices.slice(0, 10).map((choice) => (
                          <button
                            key={choice}
                            type="button"
                            className="rounded-full border border-dashed px-2 py-1 text-[11px] hover:bg-muted"
                            onClick={() => setNewPlanName(choice)}
                          >
                            {choice}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={addPlan}>
                    <Plus className="h-4 w-4" />
                    Agregar
                  </Button>
                </div>
              )}

              <div className="space-y-3">
                {Object.entries(draft.docs_per_plan).map(([plan, docs]) => (
                  <div key={plan} className="rounded-md border bg-background p-3">
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                      <Input
                        defaultValue={plan}
                        disabled={!canEdit}
                        className="h-8 min-w-48 flex-1 text-xs"
                        onBlur={(event) => renamePlan(plan, event.currentTarget.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                        }}
                      />
                      <Badge variant="outline" className="font-mono">
                        {normalizeTechnicalKey(selectedPlanFieldKey)}
                      </Badge>
                      <Badge variant={docs.length ? "default" : "secondary"}>
                        {docs.length} docs
                      </Badge>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        disabled={!canEdit}
                        onClick={() => removePlan(plan)}
                        aria-label={`Eliminar ${plan}`}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {draft.documents_catalog.map((doc) => {
                        const checked = docs.includes(doc.key);
                        return (
                          <button
                            key={doc.key}
                            type="button"
                            disabled={!canEdit}
                            aria-pressed={checked}
                            onClick={() => togglePlanDoc(plan, doc.key)}
                            className={cn(
                              "min-h-16 rounded-md border px-3 py-2 text-left text-xs transition",
                              checked
                                ? "border-emerald-500/50 bg-emerald-500/10"
                                : "border-border hover:bg-muted/40",
                              !canEdit && "cursor-not-allowed opacity-60",
                            )}
                          >
                            <span className="flex items-start gap-2">
                              <span
                                className={cn(
                                  "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                                  checked
                                    ? "border-emerald-600 bg-emerald-600 text-white"
                                    : "border-input bg-background",
                                )}
                              >
                                {checked ? <Check className="h-3 w-3" /> : null}
                              </span>
                              <span className="min-w-0">
                                <span className="block truncate font-medium">{doc.label}</span>
                                <span className="block truncate font-mono text-[10px] text-muted-foreground">
                                  {doc.key}
                                </span>
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
                {planCount === 0 && <EmptyState icon={FileCheck} text="Sin casos configurados." />}
              </div>
            </TabsContent>

            <TabsContent value="vision" className="space-y-3 p-4">
              {VISION_CATEGORIES.map((category) => {
                const docs = draft.vision_doc_mapping[category] ?? [];
                return (
                  <div key={category} className="rounded-md border bg-background p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium">{VISION_LABELS[category]}</div>
                        <code className="text-xs text-muted-foreground">{category}</code>
                      </div>
                      <Badge variant={docs.length ? "default" : "secondary"}>
                        {docs.length ? `${docs.length} doc` : "Manual"}
                      </Badge>
                    </div>

                    {docs.length > 0 && (
                      <div className="mb-2 space-y-1.5">
                        {docs.map((docKey, index) => {
                          const doc = draft.documents_catalog.find((item) => item.key === docKey);
                          return (
                            <div
                              key={docKey}
                              className="flex items-center gap-2 rounded-md border bg-muted/20 px-2 py-1.5 text-xs"
                            >
                              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                              <span className="min-w-0 flex-1 truncate">
                                {doc?.label ?? docKey}
                                {category === "ine" && (
                                  <span className="ml-2 text-[10px] text-muted-foreground">
                                    {index === 0
                                      ? "frente"
                                      : index === 1
                                        ? "reverso"
                                        : `lado ${index + 1}`}
                                  </span>
                                )}
                              </span>
                              {canEdit && (
                                <div className="flex items-center gap-1">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-xs"
                                    disabled={index === 0}
                                    onClick={() => moveVisionDoc(category, index, -1)}
                                  >
                                    <ArrowUp className="h-3 w-3" />
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-xs"
                                    disabled={index === docs.length - 1}
                                    onClick={() => moveVisionDoc(category, index, 1)}
                                  >
                                    <ArrowDown className="h-3 w-3" />
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-xs"
                                    onClick={() => toggleVisionDoc(category, docKey)}
                                  >
                                    <X className="h-3 w-3 text-destructive" />
                                  </Button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {canEdit && (
                      <div className="flex flex-wrap gap-1.5">
                        {draft.documents_catalog
                          .filter((doc) => !docs.includes(doc.key))
                          .map((doc) => (
                            <button
                              type="button"
                              key={doc.key}
                              className="rounded-full border border-dashed px-2 py-1 text-xs hover:bg-muted"
                              onClick={() => toggleVisionDoc(category, doc.key)}
                            >
                              + {doc.label}
                            </button>
                          ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </TabsContent>
          </Tabs>
        </section>
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof FileText;
  label: string;
  value: number;
  detail: string;
}) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-semibold">{value}</span>
        <span className="text-xs text-muted-foreground">{detail}</span>
      </div>
    </div>
  );
}

function ConfigStatus({
  fieldKey,
  fieldLabel,
  planNames,
  documentCount,
  mappedVisionCount,
  visionCategoryCount,
  warnings,
}: {
  fieldKey: string;
  fieldLabel?: string;
  planNames: string[];
  documentCount: number;
  mappedVisionCount: number;
  visionCategoryCount: number;
  warnings: string[];
}) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <ClipboardCheck className="h-4 w-4" />
            Estado de configuracion
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Este expediente usa este campo, estos casos, estos docs y esta Vision.
          </p>
        </div>
        <Badge variant={warnings.length === 0 ? "default" : "secondary"}>
          {warnings.length === 0 ? "Listo para validar" : `${warnings.length} aviso`}
        </Badge>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-4">
        <StatusBlock
          label="Campo cliente"
          value={normalizeTechnicalKey(fieldKey)}
          detail={fieldLabel ?? "Campo configurable del cliente"}
        />
        <StatusBlock
          label="Casos"
          value={`${planNames.length}`}
          detail={planNames.length ? planNames.slice(0, 3).join(", ") : "Sin casos"}
        />
        <StatusBlock
          label="Documentos"
          value={`${documentCount}`}
          detail="catalogo que pide el bot"
        />
        <StatusBlock
          label="Vision"
          value={`${mappedVisionCount}`}
          detail={`${visionCategoryCount} categorias automaticas`}
        />
      </div>

      {warnings.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {warnings.map((warning) => (
            <Badge key={warning} variant="outline" className="gap-1 text-xs">
              <Info className="h-3 w-3" />
              {warning}
            </Badge>
          ))}
        </div>
      )}
    </section>
  );
}

function StatusBlock({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="min-w-0 rounded-md border bg-muted/20 px-3 py-2">
      <div className="text-[11px] font-medium uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 truncate font-mono text-sm font-semibold">{value}</div>
      <div className="mt-1 truncate text-xs text-muted-foreground">{detail}</div>
    </div>
  );
}

function SectionHeader({
  icon: Icon,
  title,
  count,
}: {
  icon: typeof FileText;
  title: string;
  count: number;
}) {
  return (
    <div className="flex items-center justify-between gap-3 p-4">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <Icon className="h-4 w-4" />
        {title}
      </h2>
      <Badge variant="outline">{count}</Badge>
    </div>
  );
}

function EmptyState({ icon: Icon, text }: { icon: typeof FileText; text: string }) {
  return (
    <div className="flex min-h-28 flex-col items-center justify-center rounded-md border border-dashed bg-muted/20 p-4 text-center text-sm text-muted-foreground">
      <Icon className="mb-2 h-5 w-5" />
      {text}
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Download, RotateCcw, Send, Sparkles, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  type KnowledgeTestResponse,
  knowledgeApi,
} from "@/features/knowledge/api";
import { extractErrorDetail } from "@/lib/error-detail";

// Surfaces a 429 from the backend (KB cooldown / rate limit) with a useful
// toast instead of the generic axios error. Falls through to extractErrorDetail
// for everything else so Pydantic 422 arrays don't leak into JSX.
function explain429(err: unknown, fallback: string): string {
  const e = err as { response?: { status?: number } };
  if (e?.response?.status === 429) {
    return extractErrorDetail(err, "Demasiadas solicitudes — espera un momento.");
  }
  return extractErrorDetail(err, fallback);
}

export function KnowledgeBasePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Base de conocimiento</h1>
        <p className="text-sm text-muted-foreground">FAQs, articulos, documentos y prueba de respuestas.</p>
      </div>
      <Tabs defaultValue="catalog">
        <TabsList>
          <TabsTrigger value="catalog">Articulos</TabsTrigger>
          <TabsTrigger value="faqs">FAQs</TabsTrigger>
          <TabsTrigger value="documents">Documentos</TabsTrigger>
          <TabsTrigger value="test">Probar</TabsTrigger>
        </TabsList>
        <TabsContent value="catalog" className="mt-4">
          <CatalogTab />
        </TabsContent>
        <TabsContent value="faqs" className="mt-4">
          <FAQsTab />
        </TabsContent>
        <TabsContent value="documents" className="mt-4">
          <DocumentsTab />
        </TabsContent>
        <TabsContent value="test" className="mt-4">
          <TestTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function FAQsTab() {
  const qc = useQueryClient();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const list = useQuery({ queryKey: ["knowledge", "faqs"], queryFn: knowledgeApi.listFaqs });
  const create = useMutation({
    mutationFn: knowledgeApi.createFaq,
    onSuccess: () => {
      setQuestion("");
      setAnswer("");
      void qc.invalidateQueries({ queryKey: ["knowledge", "faqs"] });
    },
  });
  const remove = useMutation({
    mutationFn: knowledgeApi.deleteFaq,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge", "faqs"] }),
  });
  return (
    <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>Nueva FAQ</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Pregunta" />
          <Textarea value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Respuesta" rows={5} />
          <Button onClick={() => create.mutate({ question, answer, tags: [] })}>Crear</Button>
        </CardContent>
      </Card>
      <div className="space-y-2">
        {list.data?.map((faq) => (
          <Card key={faq.id}>
            <CardContent className="flex items-start justify-between gap-3 p-4">
              <div>
                <div className="font-medium">{faq.question}</div>
                <p className="mt-1 text-sm text-muted-foreground">{faq.answer}</p>
              </div>
              <Button size="icon" variant="ghost" onClick={() => remove.mutate(faq.id)} aria-label="Eliminar FAQ">
                <Trash2 className="h-4 w-4" />
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function CatalogTab() {
  const qc = useQueryClient();
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const list = useQuery({ queryKey: ["knowledge", "catalog"], queryFn: knowledgeApi.listCatalog });
  const create = useMutation({
    mutationFn: knowledgeApi.createCatalog,
    onSuccess: () => {
      setSku("");
      setName("");
      setCategory("");
      void qc.invalidateQueries({ queryKey: ["knowledge", "catalog"] });
    },
  });
  const remove = useMutation({
    mutationFn: knowledgeApi.deleteCatalog,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge", "catalog"] }),
  });
  return (
    <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>Nuevo articulo</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input value={sku} onChange={(e) => setSku(e.target.value)} placeholder="SKU" />
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nombre" />
          <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Categoria" />
          <Button onClick={() => create.mutate({ sku, name, category: category || null, attrs: {}, tags: [] })}>
            Crear
          </Button>
        </CardContent>
      </Card>
      <div className="space-y-2">
        {list.data?.map((item) => (
          <Card key={item.id}>
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <div className="font-medium">{item.name}</div>
                <div className="text-xs text-muted-foreground">{item.sku}</div>
              </div>
              <div className="flex items-center gap-2">
                {item.category && <Badge variant="outline">{item.category}</Badge>}
                <Button size="icon" variant="ghost" onClick={() => remove.mutate(item.id)} aria-label="Eliminar item de catálogo">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function DocumentsTab() {
  const qc = useQueryClient();
  const [category, setCategory] = useState("");
  const list = useQuery({
    queryKey: ["knowledge", "documents"],
    queryFn: knowledgeApi.listDocuments,
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "processing") ? 3000 : false,
  });
  const upload = useMutation({
    mutationFn: ({ file, category }: { file: File; category: string }) =>
      knowledgeApi.uploadDocument(file, category),
    onSuccess: () => {
      toast.success("Documento recibido");
      void qc.invalidateQueries({ queryKey: ["knowledge", "documents"] });
    },
    onError: (err) => {
      toast.error(explain429(err, "No se pudo subir el documento."));
    },
  });
  const remove = useMutation({
    mutationFn: knowledgeApi.deleteDocument,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge", "documents"] }),
  });
  const retry = useMutation({
    mutationFn: knowledgeApi.retryDocument,
    onSuccess: () => {
      toast.success("Reintento encolado");
      void qc.invalidateQueries({ queryKey: ["knowledge", "documents"] });
    },
    onError: (err) => {
      toast.error(explain429(err, "No se pudo reintentar."));
    },
  });
  const reindex = useMutation({
    mutationFn: knowledgeApi.reindex,
    onSuccess: (data) => {
      toast.success(`Reindexado encolado: ${data.queued} documentos`);
      void qc.invalidateQueries({ queryKey: ["knowledge", "documents"] });
    },
    onError: (err) => {
      toast.error(
        explain429(err, "No se pudo encolar el reindexado.") +
          " (Cooldown 5 min entre reindexados)",
      );
    },
  });
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div>
            <Label>Categoria</Label>
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-56"
            />
          </div>
          <Button variant="outline" asChild>
            <label>
              <Upload className="mr-2 h-4 w-4" /> Subir documento
              <input
                className="hidden"
                type="file"
                accept=".pdf,.docx,.xlsx,.csv,.txt"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) upload.mutate({ file, category });
                }}
              />
            </label>
          </Button>
          <Button
            variant="secondary"
            disabled={reindex.isPending}
            onClick={() => reindex.mutate()}
          >
            Reindexar
          </Button>
        </CardContent>
      </Card>
      <div className="space-y-2">
        {list.data?.map((doc) => (
          <Card key={doc.id}>
            <CardContent className="flex items-center justify-between gap-3 p-4">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium" title={doc.filename}>
                  {doc.filename}
                </div>
                <div className="text-xs text-muted-foreground">
                  {doc.fragment_count} fragmentos
                  {doc.category ? ` · ${doc.category}` : ""}
                </div>
                {doc.error_message && (
                  <div className="mt-1 flex items-start gap-1 text-xs text-destructive">
                    <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                    <span className="break-words">{doc.error_message}</span>
                  </div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge
                  variant={
                    doc.status === "indexed"
                      ? "default"
                      : doc.status === "error"
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {doc.status}
                </Badge>
                <Button
                  size="icon"
                  variant="ghost"
                  asChild
                  title="Descargar original"
                >
                  <a href={knowledgeApi.downloadDocumentUrl(doc.id)} download>
                    <Download className="h-4 w-4" />
                  </a>
                </Button>
                {doc.status === "error" && (
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Reintentar indexado"
                    aria-label="Reintentar indexado"
                    onClick={() => retry.mutate(doc.id)}
                    disabled={retry.isPending}
                  >
                    <RotateCcw className="h-4 w-4" />
                  </Button>
                )}
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => remove.mutate(doc.id)}
                  aria-label="Eliminar documento"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function TestTab() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<KnowledgeTestResponse | null>(null);
  const run = useMutation({
    mutationFn: knowledgeApi.test,
    onSuccess: setResult,
    onError: (err) => {
      toast.error(explain429(err, "No se pudo ejecutar la prueba."));
    },
  });
  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Pregunta de prueba"
            onKeyDown={(e) => {
              if (e.key === "Enter" && query.trim()) run.mutate(query);
            }}
          />
          <Button
            onClick={() => run.mutate(query)}
            disabled={!query.trim() || run.isPending}
          >
            <Send className="mr-2 h-4 w-4" /> Probar
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Límite: 10 consultas por minuto por tenant.
        </p>
        {result && (
          <div className="space-y-3">
            <ModeBanner mode={result.mode} />
            <div className="rounded-md border p-3 text-sm whitespace-pre-wrap">
              {result.answer}
            </div>
            {result.sources.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">
                  Fuentes consultadas ({result.sources.length})
                </div>
                {result.sources.map((source) => (
                  <div
                    key={`${source.type}-${source.id}`}
                    className="rounded-md border p-3 text-xs text-muted-foreground"
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <Badge variant="outline">{source.type}</Badge>
                      <span className="text-[10px] text-muted-foreground">
                        score: {source.score.toFixed(3)}
                      </span>
                    </div>
                    <p className="line-clamp-4 text-foreground/80">{source.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ModeBanner({ mode }: { mode: KnowledgeTestResponse["mode"] }) {
  // ``llm`` = the answer was synthesised by gpt-4o-mini against the sources.
  // ``sources_only`` = degraded mode, the operator must read the source
  // cards. ``empty`` = nothing relevant found in the knowledge base.
  if (mode === "llm") {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200">
        <Sparkles className="h-3 w-3" /> Respuesta generada con gpt-4o-mini
        sobre las fuentes.
      </div>
    );
  }
  if (mode === "sources_only") {
    return (
      <div className="flex items-start gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
        <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
        <span>
          OpenAI no disponible. Lee las tarjetas de fuente directamente
          antes de responder al cliente.
        </span>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-muted bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
      No se encontraron fuentes relevantes.
    </div>
  );
}

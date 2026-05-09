import { api } from "@/lib/api-client";

export interface FAQItem {
  id: string;
  question: string;
  answer: string;
  tags: string[];
}

export interface CatalogItem {
  id: string;
  sku: string;
  name: string;
  attrs: Record<string, unknown>;
  category: string | null;
  tags: string[];
  use_count: number;
  active: boolean;
}

export interface DocumentItem {
  id: string;
  filename: string;
  category: string | null;
  status: string;
  fragment_count: number;
  error_message: string | null;
  created_at: string;
}

export interface KnowledgeSource {
  type: string;
  id: string;
  text: string;
  score: number;
}

export interface KnowledgeTestResponse {
  answer: string;
  // ``llm`` = synthesised by gpt-4o-mini; ``sources_only`` = degraded
  // (no key or LLM call failed); ``empty`` = no relevant sources.
  mode: "llm" | "sources_only" | "empty";
  sources: KnowledgeSource[];
}

export const knowledgeApi = {
  listFaqs: async () => (await api.get<FAQItem[]>("/knowledge/faqs")).data,
  createFaq: async (body: { question: string; answer: string; tags: string[] }) =>
    (await api.post<FAQItem>("/knowledge/faqs", body)).data,
  deleteFaq: async (id: string) => api.delete(`/knowledge/faqs/${id}`),
  listCatalog: async () => (await api.get<CatalogItem[]>("/knowledge/catalog")).data,
  createCatalog: async (body: {
    sku: string;
    name: string;
    attrs: Record<string, unknown>;
    category?: string | null;
    tags: string[];
  }) => (await api.post<CatalogItem>("/knowledge/catalog", body)).data,
  deleteCatalog: async (id: string) => api.delete(`/knowledge/catalog/${id}`),
  listDocuments: async () => (await api.get<DocumentItem[]>("/knowledge/documents")).data,
  uploadDocument: async (file: File, category?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (category) form.append("category", category);
    return (
      await api.post<DocumentItem>("/knowledge/documents/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
    ).data;
  },
  deleteDocument: async (id: string) => api.delete(`/knowledge/documents/${id}`),
  retryDocument: async (id: string) =>
    (await api.post<DocumentItem>(`/knowledge/documents/${id}/retry`)).data,
  // Returns the raw bytes; the caller turns it into a download. We use blob
  // response type so binary content (PDF/DOCX/...) round-trips intact.
  downloadDocumentUrl: (id: string) => `/api/v1/knowledge/documents/${id}/download`,
  test: async (query: string) =>
    (await api.post<KnowledgeTestResponse>("/knowledge/test", { query })).data,
  reindex: async () => (await api.post<{ queued: number }>("/knowledge/reindex")).data,
};

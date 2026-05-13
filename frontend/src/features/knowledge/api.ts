import { z } from "zod";
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

const statusSchema = z.enum(["good", "warning", "critical"]);
const severitySchema = z.enum(["low", "medium", "high", "critical"]);

const healthMetricSchema = z.object({
  key: z.string(),
  label: z.string(),
  score: z.number(),
  status: statusSchema,
  tooltip: z.string(),
  trend: z.number(),
});

export const knowledgeHealthSchema = z.object({
  overall_score: z.number(),
  label: z.string(),
  status: statusSchema,
  change_vs_yesterday: z.number(),
  metrics: z.array(healthMetricSchema),
  updated_at: z.string(),
});

export const healthHistoryPointSchema = z.object({
  date: z.string(),
  overall_score: z.number(),
  retrieval_quality_score: z.number(),
  answer_confidence_score: z.number(),
});

export const riskFindingSchema = z.object({
  id: z.string(),
  category: z.string(),
  title: z.string(),
  description: z.string(),
  severity: severitySchema,
  affected_sources: z.number(),
  affected_conversations: z.number(),
  recommended_action: z.string(),
  quick_action_type: z.string(),
});

export const riskResponseSchema = z.object({
  items: z.array(riskFindingSchema),
  updated_at: z.string(),
});

export const knowledgeCommandItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  source_type: z.string(),
  collection: z.string(),
  retrieval_score: z.number(),
  status: z.string(),
  freshness: z.string(),
  freshness_days: z.number(),
  conflicts: z.number(),
  last_used_at: z.string(),
  risk_level: severitySchema,
  owner: z.string(),
});

export const knowledgeItemsResponseSchema = z.object({
  items: z.array(knowledgeCommandItemSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
});

export const unansweredQuestionSchema = z.object({
  id: z.string(),
  question: z.string(),
  frequency: z.number(),
  trend_percent: z.number(),
  funnel_stage: z.string(),
  last_seen_at: z.string(),
  suggested_action: z.string(),
});

export const unansweredQuestionsResponseSchema = z.object({
  items: z.array(unansweredQuestionSchema),
  total: z.number(),
});

export const funnelStageSchema = z.object({
  id: z.string(),
  label: z.string(),
  coverage_percent: z.number(),
  confidence_average: z.number(),
  unanswered_count: z.number(),
  conflict_count: z.number(),
  highest_risk_source: z.string(),
  status: statusSchema,
});

export const funnelCoverageResponseSchema = z.object({
  stages: z.array(funnelStageSchema),
});

export const bottomActionCardSchema = z.object({
  id: z.string(),
  title: z.string(),
  value: z.string(),
  trend: z.string(),
  cta: z.string(),
  status: statusSchema,
  sparkline: z.array(z.number()),
});

export const dashboardCardsResponseSchema = z.object({
  items: z.array(bottomActionCardSchema),
});

export const retrievedChunkSchema = z.object({
  id: z.string(),
  source_name: z.string(),
  page_number: z.number(),
  preview: z.string(),
  retrieval_score: z.number(),
  freshness_status: z.string(),
  warnings: z.array(z.string()),
});

export const simulationResponseSchema = z.object({
  id: z.string(),
  agent: z.string(),
  model: z.string(),
  user_message: z.string(),
  prompt_preview: z.string(),
  retrieved_chunks: z.array(retrievedChunkSchema),
  confidence_score: z.number(),
  coverage_score: z.number(),
  risk_flags: z.array(z.string()),
  answer: z.string(),
  source_summary: z.string(),
  mode: z.enum(["mock", "llm", "sources_only"]),
});

export const chunkImpactSchema = z.object({
  chunk_id: z.string(),
  source_document: z.string(),
  page_number: z.number(),
  chunk_text: z.string(),
  embedding_status: z.string(),
  retrieval_score: z.number(),
  used_in_answers_week: z.number(),
  affected_active_conversations: z.number(),
  affected_funnel_stages: z.array(z.string()),
  risk_level: severitySchema,
  related_conflicts: z.array(z.string()),
  last_edited_by: z.string(),
  last_indexed_at: z.string(),
});

export const conflictsResponseSchema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      severity: severitySchema,
      sources: z.array(z.string()),
      status: z.string(),
      recommended_resolution: z.string(),
    }),
  ),
  total: z.number(),
});

export const auditLogsResponseSchema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      action: z.string(),
      actor: z.string(),
      target: z.string(),
      created_at: z.string(),
    }),
  ),
});

export type KnowledgeHealth = z.infer<typeof knowledgeHealthSchema>;
export type KnowledgeHealthMetric = z.infer<typeof healthMetricSchema>;
export type HealthHistoryPoint = z.infer<typeof healthHistoryPointSchema>;
export type RiskFinding = z.infer<typeof riskFindingSchema>;
export type KnowledgeCommandItem = z.infer<typeof knowledgeCommandItemSchema>;
export type UnansweredQuestion = z.infer<typeof unansweredQuestionSchema>;
export type FunnelStage = z.infer<typeof funnelStageSchema>;
export type BottomActionCard = z.infer<typeof bottomActionCardSchema>;
export type RetrievedChunk = z.infer<typeof retrievedChunkSchema>;
export type SimulationResponse = z.infer<typeof simulationResponseSchema>;
export type ChunkImpact = z.infer<typeof chunkImpactSchema>;

export interface KnowledgeItemsParams {
  q?: string;
  collection?: string;
  status?: string;
  risk?: string;
  page?: number;
  page_size?: number;
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
    return (await api.post<DocumentItem>("/knowledge/documents/upload", form)).data;
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
  getHealth: async () => knowledgeHealthSchema.parse((await api.get("/knowledge/health")).data),
  getHealthHistory: async () =>
    z.array(healthHistoryPointSchema).parse((await api.get("/knowledge/health/history")).data),
  listRisks: async () => riskResponseSchema.parse((await api.get("/knowledge/risks")).data),
  resolveRisk: async (id: string) => (await api.post(`/knowledge/risks/${id}/resolve`)).data,
  listItems: async (params: KnowledgeItemsParams = {}) =>
    knowledgeItemsResponseSchema.parse((await api.get("/knowledge/items", { params })).data),
  publishItem: async (id: string) => (await api.post(`/knowledge/items/${id}/publish`)).data,
  archiveItem: async (id: string) => (await api.post(`/knowledge/items/${id}/archive`)).data,
  reindexItem: async (id: string) => (await api.post(`/knowledge/items/${id}/reindex`)).data,
  listUnansweredQuestions: async () =>
    unansweredQuestionsResponseSchema.parse(
      (await api.get("/knowledge/unanswered-questions")).data,
    ),
  createFaqFromQuestion: async (id: string) =>
    (await api.post(`/knowledge/unanswered-questions/${id}/create-faq`)).data,
  ignoreQuestion: async (id: string) =>
    (await api.post(`/knowledge/unanswered-questions/${id}/ignore`)).data,
  escalateQuestion: async (id: string) =>
    (await api.post(`/knowledge/unanswered-questions/${id}/escalate`)).data,
  getFunnelCoverage: async () =>
    funnelCoverageResponseSchema.parse((await api.get("/knowledge/funnel-coverage")).data),
  getDashboardCards: async () =>
    dashboardCardsResponseSchema.parse((await api.get("/knowledge/dashboard-cards")).data),
  simulate: async (body: { message: string; agent: string; model: string }) =>
    simulationResponseSchema.parse((await api.post("/knowledge/simulate", body)).data),
  markSimulationCorrect: async (id: string) =>
    (await api.post(`/knowledge/simulate/${id}/mark-correct`)).data,
  markSimulationIncomplete: async (id: string) =>
    (await api.post(`/knowledge/simulate/${id}/mark-incomplete`)).data,
  markSimulationIncorrect: async (id: string) =>
    (await api.post(`/knowledge/simulate/${id}/mark-incorrect`)).data,
  createFaqFromSimulation: async (id: string) =>
    (await api.post(`/knowledge/simulate/${id}/create-faq`)).data,
  blockSimulationAnswer: async (id: string) =>
    (await api.post(`/knowledge/simulate/${id}/block-answer`)).data,
  getChunkImpact: async (id: string) =>
    chunkImpactSchema.parse((await api.get(`/knowledge/chunks/${id}/impact`)).data),
  disableChunk: async (id: string) => (await api.post(`/knowledge/chunks/${id}/disable`)).data,
  splitChunk: async (id: string) => (await api.post(`/knowledge/chunks/${id}/split`)).data,
  mergeChunk: async (id: string) => (await api.post(`/knowledge/chunks/${id}/merge`)).data,
  prioritizeChunk: async (id: string) =>
    (await api.post(`/knowledge/chunks/${id}/prioritize`)).data,
  reindexChunk: async (id: string) => (await api.post(`/knowledge/chunks/${id}/reindex`)).data,
  listConflicts: async () =>
    conflictsResponseSchema.parse((await api.get("/knowledge/conflicts")).data),
  resolveConflict: async (id: string) =>
    (await api.post(`/knowledge/conflicts/${id}/resolve`)).data,
  listAuditLogs: async () =>
    auditLogsResponseSchema.parse((await api.get("/knowledge/audit-logs")).data),
};

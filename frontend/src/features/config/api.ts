import { api } from "@/lib/api-client";
import type { InboxConfig } from "@/features/inbox-settings/types";

export interface PipelineResponse {
  version: number;
  definition: Record<string, unknown>;
  active: boolean;
  created_at: string;
}

export interface BrandFactsResponse {
  brand_facts: Record<string, string>;
}

export interface ToneResponse {
  voice: Record<string, unknown>;
}

export interface TimezoneResponse {
  timezone: string;
}

export interface WhatsAppDetails {
  phone_number: string | null;
  business_name: string | null;
  phone_number_id: string | null;
  business_id: string | null;
  verify_token: string | null;
  webhook_path: string;
  last_webhook_at: string | null;
  circuit_breaker_open: boolean;
}

export interface AIProviderInfo {
  nlu_provider: string;
  nlu_model: string;
  composer_provider: string;
  composer_model: string;
  has_openai_key: boolean;
}

export const tenantsApi = {
  getPipeline: async () => (await api.get<PipelineResponse>("/tenants/pipeline")).data,
  putPipeline: async (definition: Record<string, unknown>) =>
    (await api.put<PipelineResponse>("/tenants/pipeline", { definition })).data,
  getBrandFacts: async () => (await api.get<BrandFactsResponse>("/tenants/brand-facts")).data,
  putBrandFacts: async (brand_facts: Record<string, string>) =>
    (await api.put<BrandFactsResponse>("/tenants/brand-facts", { brand_facts })).data,
  getTone: async () => (await api.get<ToneResponse>("/tenants/tone")).data,
  putTone: async (voice: Record<string, unknown>) =>
    (await api.put<ToneResponse>("/tenants/tone", { voice })).data,
  getTimezone: async () => (await api.get<TimezoneResponse>("/tenants/timezone")).data,
  putTimezone: async (timezone: string) =>
    (await api.put<TimezoneResponse>("/tenants/timezone", { timezone })).data,
};

export const inboxConfigApi = {
  get: async (): Promise<InboxConfig> => {
    const r = await api.get<{ inbox_config: InboxConfig }>("/tenants/inbox-config");
    return r.data.inbox_config;
  },
  put: async (inbox_config: InboxConfig): Promise<InboxConfig> => {
    const r = await api.put<{ inbox_config: InboxConfig }>("/tenants/inbox-config", { inbox_config });
    return r.data.inbox_config;
  },
};

export const integrationsApi = {
  getWhatsAppDetails: async () =>
    (await api.get<WhatsAppDetails>("/integrations/whatsapp/details")).data,
  getAIProvider: async () =>
    (await api.get<AIProviderInfo>("/integrations/ai-provider")).data,
};

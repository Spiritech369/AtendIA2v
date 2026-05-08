import { api } from "@/lib/api-client";

export interface FunnelResponse {
  total_conversations: number;
  quoted: number;
  plan_assigned: number;
  papeleria_completa: number;
}

export interface CostDayPoint {
  day: string;
  nlu_usd: string;
  composer_usd: string;
  tool_usd: string;
  vision_usd: string;
  total_usd: string;
}

export interface CostResponse {
  points: CostDayPoint[];
}

export interface VolumeBucket {
  hour: number;
  inbound: number;
  outbound: number;
}

export interface VolumeResponse {
  buckets: VolumeBucket[];
}

export const analyticsApi = {
  funnel: async (params: { from?: string; to?: string } = {}) =>
    (await api.get<FunnelResponse>("/analytics/funnel", { params })).data,
  cost: async (params: { from?: string; to?: string } = {}) =>
    (await api.get<CostResponse>("/analytics/cost", { params })).data,
  volume: async (params: { from?: string; to?: string } = {}) =>
    (await api.get<VolumeResponse>("/analytics/volume", { params })).data,
};

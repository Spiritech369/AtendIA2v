import { api } from "@/lib/api-client";

export interface FeatureFlags {
  show_nyi_controls: boolean;
  demo_mode: boolean;
  mock_knowledge_model: boolean;
}

export interface TenantCapabilities {
  schema_version: string;
  tenant_id: string;
  feature_flags: FeatureFlags;
  limits: {
    max_pipeline_stages: number;
    max_workflow_nodes: number;
  };
  current_user: {
    id: string;
    role: string;
    capabilities: string[];
  };
}

export interface ProductConfigSchema {
  schema_version: string;
  roles_available: string[];
  pipeline_modes_available: string[];
  actions_available: string[];
  rule_operators_available: string[];
  handoff_reasons_available: string[];
  feature_flags: FeatureFlags;
  limits: {
    max_pipeline_stages: number;
    max_workflow_nodes: number;
  };
}

export const capabilitiesApi = {
  getProductSchema: async (): Promise<ProductConfigSchema> => {
    const { data } = await api.get<ProductConfigSchema>("/product-config/schema");
    return data;
  },
  getTenantCapabilities: async (tenantId: string): Promise<TenantCapabilities> => {
    const { data } = await api.get<TenantCapabilities>(`/tenants/${tenantId}/capabilities`);
    return data;
  },
};

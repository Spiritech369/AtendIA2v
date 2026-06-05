import { create } from "zustand";

import { capabilitiesApi, type TenantCapabilities } from "@/features/capabilities/api";

interface CapabilitiesState {
  tenantId: string | null;
  capabilities: TenantCapabilities | null;
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
}

interface CapabilitiesActions {
  fetchForTenant: (tenantId: string) => Promise<TenantCapabilities | null>;
  reset: () => void;
  hasCapability: (capability: string) => boolean;
  hasFeatureFlag: (flag: keyof TenantCapabilities["feature_flags"]) => boolean;
}

const initialState: CapabilitiesState = {
  tenantId: null,
  capabilities: null,
  status: "idle",
  error: null,
};

export const useCapabilitiesStore = create<CapabilitiesState & CapabilitiesActions>(
  (set, get) => ({
    ...initialState,

    async fetchForTenant(tenantId) {
      const state = get();
      if (state.tenantId === tenantId && state.capabilities) {
        return state.capabilities;
      }
      set({ tenantId, status: "loading", error: null });
      try {
        const capabilities = await capabilitiesApi.getTenantCapabilities(tenantId);
        set({ tenantId, capabilities, status: "ready", error: null });
        return capabilities;
      } catch (error) {
        set({
          tenantId,
          capabilities: null,
          status: "error",
          error: error instanceof Error ? error.message : "No se pudieron cargar capabilities",
        });
        return null;
      }
    },

    reset() {
      set(initialState);
    },

    hasCapability(capability) {
      return (
        get().capabilities?.current_user.capabilities.includes(capability) ??
        false
      );
    },

    hasFeatureFlag(flag) {
      return get().capabilities?.feature_flags[flag] === true;
    },
  }),
);

import { create } from "zustand";

import { api } from "@/lib/api-client";

export type Role = "operator" | "tenant_admin" | "superadmin";

export interface AuthUser {
  id: string;
  tenant_id: string | null;
  role: Role;
  email: string;
}

interface AuthState {
  user: AuthUser | null;
  /** undefined = not yet checked, null = checked-and-anonymous, AuthUser = logged in. */
  status: "idle" | "loading" | "authenticated" | "anonymous";
  csrf: string | null;
}

interface AuthActions {
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  fetchMe: () => Promise<AuthUser | null>;
}

export const useAuthStore = create<AuthState & AuthActions>((set) => ({
  user: null,
  status: "idle",
  csrf: null,

  async login(email, password) {
    set({ status: "loading" });
    const { data } = await api.post<{ csrf_token: string; user: AuthUser }>("/auth/login", {
      email,
      password,
    });
    set({ user: data.user, csrf: data.csrf_token, status: "authenticated" });
    return data.user;
  },

  async logout() {
    try {
      await api.post("/auth/logout");
    } finally {
      set({ user: null, csrf: null, status: "anonymous" });
    }
  },

  async fetchMe() {
    set((s) => (s.status === "idle" ? { ...s, status: "loading" } : s));
    try {
      const { data } = await api.get<AuthUser>("/auth/me");
      set({ user: data, status: "authenticated" });
      return data;
    } catch {
      set({ user: null, status: "anonymous" });
      return null;
    }
  },
}));

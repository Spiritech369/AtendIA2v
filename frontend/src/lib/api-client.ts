import axios, { type AxiosError, type AxiosInstance } from "axios";

import { extractErrorDetail } from "@/lib/error-detail";

/**
 * Axios instance for the operator dashboard.
 *
 * - `withCredentials: true` so the httpOnly `atendia_session` cookie is
 *   sent on every request.
 * - Request interceptor reads `atendia_csrf` cookie (set by /auth/login)
 *   and echoes it in `X-CSRF-Token` for unsafe methods. Backend's CSRF
 *   middleware compares the two.
 * - Response interceptor: on 401, redirect to /login. Rewrites
 *   ``error.message`` so Pydantic 422 arrays and HTTPException details
 *   reach React as clean strings — without this, every
 *   ``toast.error(..., { description: e.message })`` call site risks
 *   "Objects are not valid as a React child".
 */
export const api: AxiosInstance = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match?.[1] ?? null;
}

api.interceptors.request.use((config) => {
  const csrf = readCookie("atendia_csrf");
  if (csrf && config.headers) {
    config.headers["X-CSRF-Token"] = csrf;
  }
  if (config.data instanceof FormData && config.headers) {
    delete config.headers["Content-Type"];
  }
  return config;
});

api.interceptors.response.use(undefined, (err: AxiosError) => {
  if (err.response?.status === 401) {
    // Avoid redirect loop while already on login page
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.assign("/login");
    }
  }
  // Replace ``err.message`` with a flattened detail string. Mutating instead
  // of wrapping keeps existing callers (``toast.error("...", { description:
  // e.message })``) working without changes.
  const flat = extractErrorDetail(err, err.message);
  if (flat && flat !== err.message) {
    err.message = flat;
  }
  return Promise.reject(err);
});

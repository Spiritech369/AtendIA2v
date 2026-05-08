import axios, { type AxiosError, type AxiosInstance } from "axios";

/**
 * Axios instance for the operator dashboard.
 *
 * - `withCredentials: true` so the httpOnly `atendia_session` cookie is
 *   sent on every request.
 * - Request interceptor reads `atendia_csrf` cookie (set by /auth/login)
 *   and echoes it in `X-CSRF-Token` for unsafe methods. Backend's CSRF
 *   middleware compares the two.
 * - Response interceptor: on 401, redirect to /login. On 403 with detail
 *   "csrf...", same — the CSRF token rotated and we need a fresh login.
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
  return config;
});

api.interceptors.response.use(undefined, (err: AxiosError) => {
  if (err.response?.status === 401) {
    // Avoid redirect loop while already on login page
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.assign("/login");
    }
  }
  return Promise.reject(err);
});

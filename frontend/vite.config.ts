import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const isDockerDev = process.env.BACKEND_URL?.includes("backend") ?? false;

// https://vite.dev/config/
// NOTE: tanstackRouter MUST come before react() so the route tree is
// generated before the React plugin processes the imports.
export default defineConfig({
  plugins: [
    ...(isDockerDev ? [] : [tanstackRouter({ target: "react", autoCodeSplitting: true })]),
    tailwindcss(),
    react(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Honor a PORT env var when set so Vite binds where a parent harness
    // (preview sandbox, supervisor, etc.) expects it.
    ...(process.env.PORT
      ? { port: Number(process.env.PORT), strictPort: true }
      : {}),
    proxy: {
      // En Docker → BACKEND_URL=http://backend:8001 (desde docker-compose)
      // Local sin Docker → fallback a localhost:8001
      "/api": process.env.BACKEND_URL ?? "http://localhost:8001",
      "/ws": { target: process.env.BACKEND_WS_URL ?? "ws://localhost:8001", ws: true },
    },
    // Docker Desktop + Windows bind-mounts can emit transient EIO errors
    // from /app and crash Vite's watcher, leaving the browser on a blank
    // page. In Docker we keep the dev server stable and restart the
    // frontend container manually after code changes.
    watch: isDockerDev
      ? { ignored: ["**/*"], ignoreInitial: true }
      : { usePolling: true, interval: 300 },
  },
});

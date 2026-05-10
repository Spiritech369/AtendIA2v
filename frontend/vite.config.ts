import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
// NOTE: tanstackRouter MUST come before react() so the route tree is
// generated before the React plugin processes the imports.
export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), tailwindcss(), react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // En Docker → BACKEND_URL=http://backend:8001 (desde docker-compose)
      // Local sin Docker → fallback a localhost:8001
      "/api": process.env.BACKEND_URL ?? "http://localhost:8001",
      "/ws": { target: process.env.BACKEND_WS_URL ?? "ws://localhost:8001", ws: true },
    },
    // Windows + Docker bind-mounts don't emit inotify events reliably.
    // Polling ensures HMR works without manual container restarts.
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
});

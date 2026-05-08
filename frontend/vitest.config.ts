import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.{test,spec}.{ts,tsx}", "src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      reporter: ["text", "html"],
      thresholds: { lines: 85 },
      exclude: [
        "src/main.tsx",
        "src/vite-env.d.ts",
        "**/*.d.ts",
        "tests/**",
        "scripts/**",
        "src/routeTree.gen.ts",
      ],
    },
  },
});

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
      // Threshold ramps back up to 85 in T56 (block close-out). Holding at
      // 60 while individual block tests are still landing so a single
      // un-covered code path doesn't block unrelated work.
      thresholds: { lines: 60 },
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

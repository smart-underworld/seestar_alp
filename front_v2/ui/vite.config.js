import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5433,
    proxy: {
      "/api": "http://localhost:5432",
      "/ws": {
        target: "ws://localhost:5432",
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    globals: true,
    include: ["src/**/*.test.{ts,js}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,svelte}"],
      exclude: ["src/main.ts", "src/App.svelte"],
      thresholds: {
        lines: 85,
        statements: 85,
        branches: 65,
        functions: 14,
      },
    },
  },
});

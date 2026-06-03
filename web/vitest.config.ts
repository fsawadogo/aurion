import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Vitest config for the Aurion web portal.
 *
 * jsdom environment so React Testing Library can mount components
 * with a DOM. Path alias `@/*` mirrors the `tsconfig.json` baseUrl so
 * test imports look identical to the production code.
 *
 * Tests live under `web/tests/**` so they're co-located with the
 * project without being mixed into the component tree.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.spec.{ts,tsx}"],
    css: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});

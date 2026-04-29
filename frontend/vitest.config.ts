import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import path from "node:path"

// Vitest config for Next.js 16 + React 19.
// We avoid `next/jest` because that adapter still lags behind Next 16's
// internal Turbopack pipeline; vitest + @vitejs/plugin-react gives us a
// stable JSX transform without pulling SWC binaries that Next manages.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./__tests__/setup.ts"],
    include: ["__tests__/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
})

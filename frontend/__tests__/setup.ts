import "@testing-library/jest-dom/vitest"
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

// RTL doesn't auto-cleanup when `globals: false`, so we wire it up here.
afterEach(() => {
  cleanup()
})

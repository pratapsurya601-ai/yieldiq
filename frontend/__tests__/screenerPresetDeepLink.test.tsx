/**
 * Screener page — preset deep-link regression tests.
 *
 * Pins the P1 fix for the bug where clicking a Quant Picks tile on
 * /home navigated to `/screener?preset=<key>` but the screener page
 * ignored the param and rendered the empty preset picker. Users had to
 * pick the preset a second time.
 *
 * Three scenarios:
 *   1. No `?preset=` query param  → empty picker is shown (current path).
 *   2. `?preset=high_quality`     → preset auto-applies, ResultsTable
 *                                    renders (NOT the picker).
 *   3. `?preset=buffett` alias    → resolves to `high_quality` preset
 *                                    via the alias map.
 *
 * Mocks: next/navigation (router + searchParams), next/link, and the
 * default axios `api` instance (no real network calls during render).
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

// Mutable holder so each test can swap the query string before render.
let currentSearch = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/screener",
  useSearchParams: () => currentSearch,
}))

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string
    children: React.ReactNode
  } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

// Stub the default axios `api` instance so the page can mount without
// hitting the network. Different endpoints get different responses:
//   - /screener/fields  → schema (so FilterBuilder can render)
//   - /screener/query   → 1-stock result payload
vi.mock("@/lib/api", () => {
  const getMock = vi.fn(async (url: string) => {
    if (url.includes("/screener/fields")) {
      return {
        data: {
          fields: [
            { key: "roe", label: "ROE", type: "numeric", unit: "%" },
            { key: "de_ratio", label: "D/E", type: "numeric" },
          ],
          sortable: ["roe", "de_ratio"],
        },
      }
    }
    if (url.includes("/screener/query")) {
      return {
        data: {
          results: [
            {
              ticker: "TCS.NS",
              roe: 42,
              de_ratio: 0.1,
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        },
      }
    }
    return { data: {} }
  })
  return {
    default: { get: getMock, post: vi.fn() },
    BUILD_ID: "test",
  }
})

import ScreenerPage from "@/app/(app)/screener/page"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  currentSearch = new URLSearchParams()
})

describe("ScreenerPage preset deep-link", () => {
  it("renders the empty preset picker when no ?preset= query param is present", async () => {
    currentSearch = new URLSearchParams()
    renderWithClient(<ScreenerPage />)

    // Empty-state copy is the "Start with a preset" heading. If the page
    // had auto-run a preset we would see ResultsTable / FilterBuilder
    // chrome instead.
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /start with a preset/i }),
      ).toBeInTheDocument()
    })
  })

  it("auto-applies the preset when ?preset=high_quality is on the URL", async () => {
    currentSearch = new URLSearchParams("preset=high_quality")
    renderWithClient(<ScreenerPage />)

    // The empty-state picker heading MUST NOT be on screen — applyPreset
    // sets `hasRun=true` which routes the render to FilterBuilder + the
    // ResultsTable, not the preset picker grid.
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: /start with a preset/i }),
      ).not.toBeInTheDocument()
    })

    // FilterBuilder renders a "Filters" heading once a preset is loaded.
    expect(screen.getByRole("heading", { name: /^filters$/i })).toBeInTheDocument()
  })

  it("honors the buffett alias by mapping ?preset=buffett to the high_quality preset", async () => {
    currentSearch = new URLSearchParams("preset=buffett")
    renderWithClient(<ScreenerPage />)

    // Same end-state as the direct-match test — picker hidden, results
    // chrome rendered. If the alias map ever drops the `buffett` entry,
    // this test fails and the regression is caught before merge.
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: /start with a preset/i }),
      ).not.toBeInTheDocument()
    })

    expect(screen.getByRole("heading", { name: /^filters$/i })).toBeInTheDocument()
  })
})

/**
 * Portfolio page motion wiring smoke test.
 *
 * Pins the integration of the motion primitives library on the
 * portfolio holdings + watchlist + alerts surfaces. Specifically:
 *   1. The holdings list is wrapped in a <RevealStagger> — emits
 *      `data-anim="reveal-stagger"` on its outer container.
 *   2. The KPI tiles (Invested / Winners / Losers) use <NumberFlip>
 *      for their numeric values — emits `data-motion="number-flip"`.
 *   3. The Reset-holdings button is wrapped in <PressScale> — emits
 *      `data-motion="press-scale"`.
 *
 * Why a wiring test rather than animation behavior? The motion
 * components own their reduced-motion + timing logic; we test those
 * inside the motion package. This test exists to catch a regression
 * where someone unwraps a primitive while refactoring this page.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

let currentSearch = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/portfolio",
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

// Mock the api surfaces the portfolio page calls so the page can render
// without hitting the network. Provides one populated holding so the
// holdings-list path renders (RevealStagger + NumberFlip).
vi.mock("@/lib/api", () => ({
  getHoldingsLive: vi.fn(async () => ({
    holdings: [
      {
        ticker: "TCS.NS",
        display_ticker: "TCS",
        company_name: "Tata Consultancy",
        sector: "IT",
        quantity: 10,
        entry_price: 3500,
        current_price: 4000,
        invested_value: 35000,
        current_value: 40000,
        pnl_abs: 5000,
        pnl_pct: 14.3,
        fair_value: 4200,
        mos_pct: 5,
        account_label: "default",
        as_of: null,
      },
    ],
    summary: {
      total_invested: 35000,
      total_current_value: 40000,
      total_pnl_abs: 5000,
      total_pnl_pct: 14.3,
      winners: 1,
      losers: 0,
      count: 1,
    },
    sample_portfolio: null,
  })),
  getPortfolioHealth: vi.fn(async () => ({
    score: 0,
    grade: "",
    summary: "",
    issues: [],
    strengths: [],
  })),
  getWatchlist: vi.fn(async () => []),
  removeFromWatchlist: vi.fn(),
  getAlerts: vi.fn(async () => []),
  deleteAlert: vi.fn(),
  resetHoldings: vi.fn(),
  getBandShifts: vi.fn(async () => ({ alerts: [] })),
  getFVHistoryBatch: vi.fn(async () => ({})),
}))

// Heavy children mocked out to keep the test focused on the page shell.
vi.mock("@/components/portfolio/PortfolioSumOfPartsCard", () => ({
  default: () => null,
}))
vi.mock("@/components/portfolio/PortfolioReturnsStrip", () => ({
  default: () => null,
}))
vi.mock("@/components/portfolio/HoldingSparkline", () => ({
  default: () => null,
}))
vi.mock("@/components/portfolio/PortfolioPrism", () => ({
  default: () => null,
}))
vi.mock("@/components/portfolio/HealthScore", () => ({
  default: () => null,
}))
vi.mock("@/components/portfolio/HealthDashboard", () => ({
  BelowFairValueBanner: () => null,
}))
vi.mock("@/components/portfolio/UpdatesFeed", () => ({
  default: () => null,
}))
vi.mock("@/components/portfolio/SamplePortfolioView", () => ({
  default: () => null,
  SAMPLE_DISMISSED_KEY: "sample-dismissed",
}))
vi.mock("@/components/watchlist/WatchlistRanking", () => ({
  WatchlistRanking: () => null,
}))
vi.mock("@/components/ModelDisclaimer", () => ({
  default: () => null,
}))

import PortfolioPage from "@/app/(app)/portfolio/page"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  currentSearch = new URLSearchParams()
})

describe("Portfolio page motion wiring", () => {
  it("wraps the holdings list in RevealStagger and Reset button in PressScale", async () => {
    const { container } = renderWithClient(<PortfolioPage />)

    await waitFor(() => {
      // The holdings <section> renders a RevealStagger wrapper around
      // the holding cards.
      expect(
        container.querySelectorAll("[data-anim='reveal-stagger']").length,
      ).toBeGreaterThan(0)
    })

    // Reset-holdings button (and the import link) are wrapped in PressScale.
    expect(
      container.querySelectorAll("[data-motion='press-scale']").length,
    ).toBeGreaterThan(0)
  })

  it("renders NumberFlip on the KPI tiles (Invested / Winners / Losers)", async () => {
    const { container } = renderWithClient(<PortfolioPage />)

    await waitFor(() => {
      // At least three NumberFlip instances render — one each for the
      // gradient header value (Total Value) and the three KPI tiles.
      expect(
        container.querySelectorAll("[data-motion='number-flip']").length,
      ).toBeGreaterThanOrEqual(3)
    })
  })
})

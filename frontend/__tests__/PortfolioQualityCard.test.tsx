/**
 * PortfolioQualityCard — at-a-glance "quality posture" panel on /home.
 *
 * Pins the four render states the feat/home-quality-card PR ships:
 *
 *   1. Loading  — skeleton renders before holdings + summaries resolve.
 *   2. Empty    — user with zero holdings sees the CTA card pointing
 *                 to /search (no aggregate row, no per-position table).
 *   3. Single   — user with one holding renders aggregate + 1 row.
 *   4. Multi    — user with three holdings renders aggregate (means
 *                 across all three) + 3 rows, and each row carries a
 *                 traffic-light triple + an /analysis/{T} link.
 *
 * Bonus: the SEBI vocabulary smoke test — the card must not introduce
 * advisory copy (the home-page check_sebi_words.py CI pass owns the
 * static lint, but a runtime DOM scan catches dynamic strings the
 * static lint can't see).
 *
 * Mocks: `@/lib/api` for hermetic network isolation, and
 * `@/store/authStore` so the component thinks the user is logged in
 * (the query is gated on `!!token`).
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getHoldingsLive: vi.fn(),
  getStockSummary: vi.fn(),
}))

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (state: { token: string | null }) => unknown) =>
    selector({ token: "test-jwt" }),
}))

import { getHoldingsLive, getStockSummary } from "@/lib/api"
import PortfolioQualityCard from "@/components/home/v2/PortfolioQualityCard"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// Minimal LiveHolding stubs — the card only reads ticker, display_ticker,
// and sector. The full type has ~20 more fields used by PortfolioPanel.
function liveHolding(display: string, ticker?: string) {
  return {
    ticker: ticker ?? `${display}.NS`,
    display_ticker: display,
    company_name: display,
    sector: "Financial Services",
    entry_price: 1000,
    quantity: 10,
    account_label: "demat",
    current_price: 1100,
    invested_value: 10000,
    current_value: 11000,
    pnl_abs: 1000,
    pnl_pct: 10,
    day_change_abs: 50,
    day_change_pct: 0.5,
    fair_value: 1200,
    mos_pct: 9,
    verdict: "Fairly Valued",
    score: 70,
    saved_at: "2026-06-01T00:00:00Z",
    notes: "",
  }
}

// Minimal StockSummary stubs — the card reads only score / mos /
// piotroski / confidence / moat, but the type has ~30 more fields the
// fair-value page consumes. We cast on the mock.mockResolvedValue side.
function stockSummary(
  ticker: string,
  o: { score: number; mos: number; piotroski: number; confidence: number; moat: string },
) {
  return {
    ticker,
    company_name: ticker,
    sector: "Financial Services",
    industry: "Bank",
    exchange: "NSE",
    currency: "INR",
    fair_value: 1200,
    current_price: 1000,
    mos: o.mos,
    verdict: "Fairly Valued",
    score: o.score,
    grade: "B",
    moat: o.moat,
    piotroski: o.piotroski,
    bear_case: 900,
    base_case: 1200,
    bull_case: 1500,
    wacc: 0.1,
    confidence: o.confidence,
    roe: null,
    de_ratio: null,
    roce: null,
    debt_ebitda: null,
    interest_coverage: null,
    current_ratio: null,
    asset_turnover: null,
    revenue_cagr_3y: null,
    revenue_cagr_5y: null,
    ev_ebitda: null,
    market_cap: 1_000_000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: null,
  }
}

beforeEach(() => {
  vi.mocked(getHoldingsLive).mockReset()
  vi.mocked(getStockSummary).mockReset()
})

describe("PortfolioQualityCard", () => {
  it("renders the skeleton before the holdings call resolves (loading state)", () => {
    vi.mocked(getHoldingsLive).mockReturnValue(new Promise(() => {}))
    const { container } = renderWithClient(<PortfolioQualityCard />)
    expect(
      container.querySelector("[data-testid='quality-card-loading-skeleton']"),
    ).not.toBeNull()
  })

  it("renders the empty-state CTA for a user with zero holdings", async () => {
    vi.mocked(getHoldingsLive).mockResolvedValue({
      holdings: [],
      summary: {
        total_invested: 0,
        total_current_value: 0,
        total_pnl_abs: 0,
        total_pnl_pct: 0,
        winners: 0,
        losers: 0,
        count: 0,
      },
    })
    const { container } = renderWithClient(<PortfolioQualityCard />)
    await waitFor(() => {
      expect(container.querySelector("[data-testid='quality-card-empty']")).not.toBeNull()
    })
    // Copy + CTA target.
    expect(container.textContent).toContain(
      "Add stocks to your portfolio to see quality signals",
    )
    const link = container.querySelector("a[href='/search']")
    expect(link).not.toBeNull()
    // No aggregate row, no rows.
    expect(container.querySelector("[data-testid='quality-card-aggregate']")).toBeNull()
    expect(container.querySelector("[data-testid='quality-card-row']")).toBeNull()
  })

  it("renders aggregate + 1 row when the user has a single holding", async () => {
    vi.mocked(getHoldingsLive).mockResolvedValue({
      holdings: [liveHolding("ITC")],
      summary: {
        total_invested: 10000,
        total_current_value: 11000,
        total_pnl_abs: 1000,
        total_pnl_pct: 10,
        winners: 1,
        losers: 0,
        count: 1,
      },
    })
    vi.mocked(getStockSummary).mockResolvedValue(
      stockSummary("ITC", {
        score: 72,
        mos: 45,
        piotroski: 8,
        confidence: 88,
        moat: "Wide",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      }) as any,
    )
    const { container } = renderWithClient(<PortfolioQualityCard />)
    await waitFor(() => {
      expect(screen.getAllByTestId("quality-card-row").length).toBe(1)
    })
    // Aggregate tiles — for a single holding the means equal the per-row
    // values, so we can pin the rendered text.
    const agg = container.querySelector("[data-testid='quality-card-aggregate']")
    expect(agg).not.toBeNull()
    expect(agg!.textContent).toContain("72/100")
    // True (Buffett) MoS = (1 - price/FV)*100 = (1 - 1000/1200)*100 = 16.667% → "+16.7%"
    // fixture: fair_value=1200, current_price=1000 (already set in stockSummary helper defaults)
    expect(agg!.textContent).toContain("+16.7%")
    expect(agg!.textContent).toContain("8.0/9")
    expect(agg!.textContent).toContain("88%")
    // Moat distribution: 1W, 0N, 0—
    expect(agg!.textContent).toMatch(/1W/)
    // Per-row link target.
    const link = container.querySelector("[data-testid='quality-card-row-link']")
    expect(link!.getAttribute("href")).toBe("/analysis/ITC")
    // Traffic lights render (3 dots).
    expect(container.querySelectorAll("[data-testid='quality-traffic-lights'] span").length).toBe(
      3,
    )
  })

  it("renders aggregate (means across 3) + 3 rows for a 3-holding portfolio", async () => {
    vi.mocked(getHoldingsLive).mockResolvedValue({
      holdings: [
        liveHolding("ITC"),
        liveHolding("HDFCBANK"),
        liveHolding("RELIANCE"),
      ],
      summary: {
        total_invested: 30000,
        total_current_value: 33000,
        total_pnl_abs: 3000,
        total_pnl_pct: 10,
        winners: 3,
        losers: 0,
        count: 3,
      },
    })
    // Per-ticker summaries — values chosen so the means are easy to
    // verify: avg score = (72+50+65)/3 = 62.33, avg piotroski =
    // (7+6+8)/3 = 7.0, moat mix = 2W + 1N + 0—.
    const byTicker: Record<string, ReturnType<typeof stockSummary>> = {
      ITC: stockSummary("ITC", {
        score: 72, mos: 50, piotroski: 7, confidence: 88, moat: "Wide",
      }),
      HDFCBANK: stockSummary("HDFCBANK", {
        score: 50, mos: 25, piotroski: 6, confidence: 90, moat: "Wide",
      }),
      RELIANCE: stockSummary("RELIANCE", {
        score: 65, mos: 18, piotroski: 8, confidence: 75, moat: "Narrow",
      }),
    }
    vi.mocked(getStockSummary).mockImplementation(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      async (ticker: string) => byTicker[ticker] as any,
    )
    const { container } = renderWithClient(<PortfolioQualityCard />)
    await waitFor(() => {
      expect(screen.getAllByTestId("quality-card-row").length).toBe(3)
    })
    const agg = container.querySelector("[data-testid='quality-card-aggregate']")!
    // 62.33 → toFixed(0) = "62"
    expect(agg.textContent).toContain("62/100")
    // 7.0 / 9
    expect(agg.textContent).toContain("7.0/9")
    // Moat mix: 2W · 1N · 0—
    expect(agg.textContent).toMatch(/2W/)
    expect(agg.textContent).toMatch(/1N/)
    // Each row links to the correct analysis page.
    const links = container.querySelectorAll("[data-testid='quality-card-row-link']")
    expect(links.length).toBe(3)
    expect(links[0].getAttribute("href")).toBe("/analysis/ITC")
    expect(links[1].getAttribute("href")).toBe("/analysis/HDFCBANK")
    expect(links[2].getAttribute("href")).toBe("/analysis/RELIANCE")
    // 3 rows × 3 traffic-light dots = 9 dots total.
    const allDots = container.querySelectorAll(
      "[data-testid='quality-traffic-lights'] span",
    )
    expect(allDots.length).toBe(9)
  })

  it("does not introduce SEBI-banned advisory copy in the rendered DOM", async () => {
    vi.mocked(getHoldingsLive).mockResolvedValue({
      holdings: [liveHolding("ITC")],
      summary: {
        total_invested: 10000,
        total_current_value: 11000,
        total_pnl_abs: 1000,
        total_pnl_pct: 10,
        winners: 1,
        losers: 0,
        count: 1,
      },
    })
    vi.mocked(getStockSummary).mockResolvedValue(
      stockSummary("ITC", {
        score: 72, mos: 45, piotroski: 8, confidence: 88, moat: "Wide",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      }) as any,
    )
    const { container } = renderWithClient(<PortfolioQualityCard />)
    await waitFor(() => {
      expect(screen.getAllByTestId("quality-card-row").length).toBe(1)
    })
    const text = (container.textContent || "").toLowerCase()
    // The card must not contain any advisory framing. // sebi-allow: recommendation
    expect(text).not.toContain("buy")
    expect(text).not.toContain("sell")
    expect(text).not.toContain("recommend") // sebi-allow: recommend
    expect(text).not.toContain("accumulate") // sebi-allow: accumulate
    expect(text).not.toContain("strong")
    expect(text).not.toContain("weak") // sebi-allow: weak
  })
})

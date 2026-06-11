/**
 * AnalysisSectionEmptyStates (2026-06-11) — P0 regression suite.
 *
 * Brief: the analysis page renders the section header + caption from
 * NumberedSectionHeader / CollapsibleSection unconditionally, then
 * mounts the panel component as the body. When a panel returns null
 * (no data ingested yet, anon user, transient 5xx) the header is left
 * orphaned and the user sees "EARNINGS CALLS · Management commentary
 * from the latest call." with nothing below the divider.
 *
 * These tests pin the contract: every panel that is referenced from
 * AnalysisBody's `summarySectionMap` MUST render some body content
 * (loading skeleton, empty-state copy, or real data) when the
 * upstream returns no rows. They are NOT allowed to return null.
 *
 * One pin per affected panel — fail-fast on regression.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import EarningsCallsWidget from "@/components/analysis/EarningsCallsWidget"
import ConcallsPanel from "@/components/analysis/ConcallsPanel"
import NewsWidget from "@/components/analysis/NewsWidget"
import BullsBearsPanel from "@/components/analysis/BullsBearsPanel"
import ReverseDcfPanel from "@/components/analysis/ReverseDcfPanel"
import CompoundedGrowthPanel from "@/components/analysis/CompoundedGrowthPanel"
import MemoryLane from "@/components/analysis/MemoryLane"
import FinancialsChartPanel from "@/components/analysis/FinancialsChartPanel"
import DividendBarChart from "@/components/analysis/DividendBarChart"
import { useAuthStore } from "@/store/authStore"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/** Install a fetch mock that returns `body` for any URL containing
 *  `match`, and 404 for everything else. */
function installFetchEmpty(matches: Array<{ match: string; body: unknown; status?: number }>) {
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    for (const m of matches) {
      if (u.includes(m.match)) {
        return new Response(JSON.stringify(m.body), { status: m.status ?? 200 })
      }
    }
    return new Response("not found", { status: 404 })
  })
  // @ts-expect-error — installing a jsdom fetch stub
  globalThis.fetch = fetchMock
  return fetchMock
}

beforeEach(() => {
  useAuthStore.setState({
    token: null,
    userId: null,
    email: null,
    tier: "free",
  } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("AnalysisSectionEmptyStates — orphan-header regression suite", () => {
  it("EarningsCallsWidget renders an empty-state card when the transcripts endpoint returns zero items", async () => {
    installFetchEmpty([
      {
        match: "/transcripts/POWERGRID",
        body: { ticker: "POWERGRID", count: 0, transcripts: [] },
      },
    ])
    const { container } = renderWithClient(<EarningsCallsWidget ticker="POWERGRID" />)
    await waitFor(() => {
      expect(screen.getByTestId("earnings-calls-empty")).toBeInTheDocument()
    })
    // Body MUST have non-whitespace content (no orphan-header).
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("ConcallsPanel renders an empty-state card when the concall library is empty", async () => {
    installFetchEmpty([
      {
        match: "/public/concalls/POWERGRID",
        body: { ticker: "POWERGRID", count: 0, concalls: [] },
      },
    ])
    const { container } = renderWithClient(<ConcallsPanel ticker="POWERGRID" />)
    await waitFor(() => {
      expect(screen.getByTestId("concalls-panel-empty")).toBeInTheDocument()
    })
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("NewsWidget renders an empty-state card when no items are ingested", async () => {
    installFetchEmpty([
      {
        match: "/public/news/POWERGRID",
        body: { ticker: "POWERGRID", count: 0, items: [] },
      },
    ])
    const { container } = renderWithClient(<NewsWidget ticker="POWERGRID" />)
    await waitFor(() => {
      expect(screen.getByTestId("news-widget-empty")).toBeInTheDocument()
    })
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("BullsBearsPanel renders an empty-state card when both sides are missing", () => {
    const { container } = renderWithClient(
      <BullsBearsPanel bulls={null} bears={null} updated={null} />,
    )
    expect(screen.getByTestId("bulls-bears-empty")).toBeInTheDocument()
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("ReverseDcfPanel renders an empty-state card when the endpoint has no payload", async () => {
    installFetchEmpty([
      // 404 covers the null-payload branch (fetchReverseDcf returns null).
    ])
    const { container } = renderWithClient(<ReverseDcfPanel ticker="POWERGRID" />)
    await waitFor(() => {
      expect(screen.getByTestId("reverse-dcf-empty")).toBeInTheDocument()
    })
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("CompoundedGrowthPanel renders an empty-state card when the panel data is null", async () => {
    installFetchEmpty([
      {
        match: "/public/stock-summary/POWERGRID",
        body: { ticker: "POWERGRID", compounded_growth: null },
      },
    ])
    const { container } = renderWithClient(<CompoundedGrowthPanel ticker="POWERGRID" />)
    await waitFor(() => {
      expect(screen.getByTestId("compounded-growth-empty")).toBeInTheDocument()
    })
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("MemoryLane renders a sign-in CTA for anonymous users (never null)", () => {
    const { container } = renderWithClient(
      <MemoryLane ticker="POWERGRID" companyName="Power Grid Corporation of India Ltd." />,
    )
    expect(screen.getByTestId("memory-lane-signin-cta")).toBeInTheDocument()
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("FinancialsChartPanel renders an empty-state card when no FY rows come back", async () => {
    // Mock the axios-backed `getFinancials` to return a payload with
    // empty income / cash_flow arrays — mirrors a freshly-added ticker
    // (or a between-CACHE_VERSION recompute window) where the BSE XBRL
    // backfill hasn't populated the financials_history rows yet.
    const apiMod = await import("@/lib/api")
    vi.spyOn(apiMod, "getFinancials").mockResolvedValue({
      ticker: "POWERGRID",
      period: "annual",
      currency: "INR",
      currency_unit: "Cr",
      income: [],
      cash_flow: [],
      balance_sheet: [],
      has_quarterly: false,
      data_source: "yfinance_fallback",
      tier_limited: false,
    } as unknown as Awaited<ReturnType<typeof apiMod.getFinancials>>)
    const { container } = renderWithClient(
      <FinancialsChartPanel
        ticker="POWERGRID"
        currency="INR"
        sector="Utilities"
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId("financials-chart-empty")).toBeInTheDocument()
    })
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it("DividendBarChart renders an empty-state card with known-payer copy when has_dividends=true but fy_history is empty", () => {
    // POWERGRID-shape — has_dividends true and a current yield, but
    // the per-FY DPS series hasn't been backfilled yet.
    const { container } = renderWithClient(
      <DividendBarChart
        dividend={{
          has_dividends: true,
          ticker: "POWERGRID",
          message: "",
          current_yield_pct: 5.4,
          payout_ratio_pct: 60,
          five_yr_avg_yield: 5.1,
          dividend_rate_per_share: 12,
          last_dividend_value: 3,
          next_ex_date: null,
          next_ex_days: null,
          consecutive_years: 18,
          fy_history: [],
          coverage_ratio: 1.5,
          sustainability: "strong",
          sustainability_reason: "covered by FCF",
        }}
        currency="INR"
        ticker="POWERGRID"
      />,
    )
    expect(screen.getByTestId("dividend-bar-chart-empty")).toBeInTheDocument()
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
    // Known-payer phrasing — re-uses the existing chip data instead of
    // claiming the stock pays no dividends.
    expect(container.textContent ?? "").toMatch(/backfill/i)
  })

  it("DividendBarChart renders an empty-state card with non-payer copy when there is no dividend payload", () => {
    const { container } = renderWithClient(
      <DividendBarChart dividend={null} currency="INR" ticker="WIPRO" />,
    )
    expect(screen.getByTestId("dividend-bar-chart-empty")).toBeInTheDocument()
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
    expect(container.textContent ?? "").toMatch(/No dividend history/i)
  })

  it("MemoryLane renders a welcome card for authed users with no prior visit", async () => {
    useAuthStore.setState({
      token: "fake-jwt-token",
      userId: "user-alice",
      email: "alice@example.com",
      tier: "free",
    } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
    // 204 status causes Response constructor to throw — bypass by
    // returning a 200 with an empty-shape payload that triggers the
    // !first_visited_at branch (same end-state as a 204).
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes("/me/memory-lane/POWERGRID")) {
        return new Response(
          JSON.stringify({
            ticker: "POWERGRID",
            ticker_bare: "POWERGRID",
            first_visited_at: null,
            last_visited_at: null,
            days_ago: 0,
            visit_count: 0,
            price_at_first_visit: null,
            fair_value_at_first_visit: null,
            verdict_at_first_visit: null,
            current_price: null,
            current_fair_value: null,
            current_verdict: null,
            price_delta_pct: null,
            fv_delta_pct: null,
            hypothetical_10k_value: null,
            user_note: null,
          }),
          { status: 200 },
        )
      }
      return new Response("not found", { status: 404 })
    })
    // @ts-expect-error — installing a jsdom fetch stub
    globalThis.fetch = fetchMock

    const { container } = renderWithClient(
      <MemoryLane ticker="POWERGRID" companyName="Power Grid Corporation of India Ltd." />,
    )
    await waitFor(() => {
      expect(screen.getByTestId("memory-lane-welcome")).toBeInTheDocument()
    })
    expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })
})

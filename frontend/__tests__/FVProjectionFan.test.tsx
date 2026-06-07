/**
 * FVProjectionFan smoke tests.
 *
 * Pins:
 *   1. Renders the three endpoint chips (Bull / Base / Bear) with the
 *      passed scenario values.
 *   2. Computes implied 5y CAGR correctly from current price → base IV.
 *   3. "Show numbers" toggle reveals the legacy 3-card table view.
 *   4. Empty state when no current price and no history.
 *   5. Merged actual-price series sources from chart-data (daily_prices)
 *      when available — see PR fix(analysis): 5Y projection actual-price
 *      line reads daily_prices, not fair_value_history.
 *   6. Falls back to fv-history's price column when chart-data errors.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

// Mock the API module before importing the component so the useQuery
// hooks see the mocked implementations.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    getChartData: vi.fn(),
    getFVHistory: vi.fn(),
  }
})

import FVProjectionFan from "@/components/analysis/FVProjectionFan"
import { getChartData, getFVHistory } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const SCENARIOS = {
  bear: { iv: 918, mos_pct: 19.7 },
  base: { iv: 1102, mos_pct: 43.7 },
  bull: { iv: 1469, mos_pct: 91.6 },
}

describe("FVProjectionFan", () => {
  beforeEach(() => {
    vi.mocked(getChartData).mockReset()
    vi.mocked(getFVHistory).mockReset()
  })

  it("renders the three endpoint chips with their CAGR", () => {
    renderWithClient(
      <FVProjectionFan
        ticker="HDFCBANK.NS"
        currency="INR"
        currentPrice={767}
        scenarios={SCENARIOS}
        historyOverride={[]}
      />,
    )
    // Each scenario row carries label + values; assert by label.
    expect(screen.getByText("Bull")).toBeInTheDocument()
    expect(screen.getByText("Base")).toBeInTheDocument()
    expect(screen.getByText("Bear")).toBeInTheDocument()
    // Implied 5y CAGR: (1102/767)^(1/5)-1 = ~7.5%
    expect(screen.getByText(/7\.5% \(base\)/)).toBeInTheDocument()
  })

  it("toggles the legacy numeric scenario view", () => {
    renderWithClient(
      <FVProjectionFan
        ticker="HDFCBANK.NS"
        currency="INR"
        currentPrice={767}
        scenarios={SCENARIOS}
        historyOverride={[]}
      />,
    )
    const toggle = screen.getByRole("button", { name: /show numbers/i })
    fireEvent.click(toggle)
    expect(screen.getByText(/Hide numbers/i)).toBeInTheDocument()
    // Three "case" cards appear.
    expect(screen.getAllByText(/case/i).length).toBeGreaterThanOrEqual(3)
  })

  it("renders an empty placeholder when neither price nor history exists", () => {
    renderWithClient(
      <FVProjectionFan
        ticker="HDFCBANK.NS"
        currency="INR"
        currentPrice={0}
        scenarios={SCENARIOS}
        historyOverride={[]}
      />,
    )
    expect(screen.getByText(/No price history available/i)).toBeInTheDocument()
  })

  it("merges chart-data daily_prices into the actual-price series", async () => {
    // Synthesise 14 months of daily closes so the bucketed series
    // covers at least the -12m window the X-axis exposes.
    const now = Date.now()
    const oneDay = 24 * 3600 * 1000
    const prices = Array.from({ length: 14 * 30 }, (_, i) => {
      const d = new Date(now - (14 * 30 - i) * oneDay)
      return {
        date: d.toISOString().slice(0, 10),
        price: 700 + Math.sin(i / 10) * 50,
      }
    })
    vi.mocked(getChartData).mockResolvedValue({ prices })
    // fv-history returns only 30d (the bug we're fixing). Without
    // chart-data, this would give the chart only ~1 bucket.
    vi.mocked(getFVHistory).mockResolvedValue({
      ticker: "HDFCBANK.NS",
      has_data: true,
      tier: "pro",
      tier_limited: false,
      years_returned: 2,
      data: prices.slice(-30).map((p) => ({
        date: p.date,
        fair_value: 1000,
        price: p.price,
        mos_pct: 0,
        verdict: null,
      })),
      summary: {
        has_data: true,
        data_start_date: prices[0].date,
        total_points: 30,
        pct_undervalued: 50,
        pct_overvalued: 50,
      },
    })

    renderWithClient(
      <FVProjectionFan
        ticker="HDFCBANK.NS"
        currency="INR"
        currentPrice={767}
        scenarios={SCENARIOS}
      />,
    )
    // Both endpoints invoked (parallel fetch — order not asserted).
    await waitFor(() => expect(getChartData).toHaveBeenCalledWith("HDFCBANK.NS", "1y"))
    expect(getFVHistory).toHaveBeenCalledWith("HDFCBANK.NS", 2)
    // Chart renders (no empty / error placeholder). The merged series
    // produces multiple SVG line paths inside the recharts container.
    await waitFor(() => {
      expect(
        screen.queryByText(/No price history available/i),
      ).not.toBeInTheDocument()
    })
  })

  it("still renders the chart when chart-data fails (fallback to fv-history)", async () => {
    vi.mocked(getChartData).mockRejectedValue(new Error("network error"))
    const now = Date.now()
    const oneDay = 24 * 3600 * 1000
    vi.mocked(getFVHistory).mockResolvedValue({
      ticker: "HDFCBANK.NS",
      has_data: true,
      tier: "free",
      tier_limited: true,
      years_returned: 1,
      data: Array.from({ length: 60 }, (_, i) => ({
        date: new Date(now - (60 - i) * oneDay).toISOString().slice(0, 10),
        fair_value: 1000,
        price: 700 + i,
        mos_pct: 0,
        verdict: null,
      })),
      summary: {
        has_data: true,
        data_start_date: null,
        total_points: 60,
        pct_undervalued: 50,
        pct_overvalued: 50,
      },
    })

    renderWithClient(
      <FVProjectionFan
        ticker="HDFCBANK.NS"
        currency="INR"
        currentPrice={767}
        scenarios={SCENARIOS}
      />,
    )
    // Chips render regardless; the fallback path keeps the chart alive.
    await waitFor(() => {
      expect(
        screen.queryByText(/No price history available/i),
      ).not.toBeInTheDocument()
    })
    expect(screen.getByText("Bull")).toBeInTheDocument()
  })
})

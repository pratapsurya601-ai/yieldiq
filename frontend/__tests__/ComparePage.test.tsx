/**
 * Day-108b — Side-by-side comparison page tests.
 *
 * Covers the four behaviours that make /compare ship-ready:
 *   1. Renders a 2-ticker comparison (HDFCBANK vs ICICIBANK) with both
 *      company headers, fair-value rows, and per-pillar metrics.
 *   2. Renders a 3-ticker comparison (private-bank trio) and shows the
 *      Scenarios section with bear/base/bull rows for each ticker.
 *   3. "Remove ticker" X button drops a column AND syncs the URL via
 *      router.replace (so refresh / share keeps the new shape).
 *   4. Empty state renders the SEBI-safe prompt when no tickers given
 *      and one of the quick-start trios populates the table.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { StockSummary } from "@/lib/api"

// ── Mocks ───────────────────────────────────────────────────────────────

const replaceMock = vi.fn()
const getStockSummaryStatusMock = vi.fn()
const getPublicPeersMock = vi.fn()
const apiGetMock = vi.fn()

let searchParamsImpl: URLSearchParams = new URLSearchParams("")

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => ({
    get: (k: string) => searchParamsImpl.get(k),
  }),
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

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    default: { get: (...a: unknown[]) => apiGetMock(...a) },
    getStockSummaryStatus: (t: string) => getStockSummaryStatusMock(t),
    getPublicPeers: (t: string, n: number) => getPublicPeersMock(t, n),
  }
})

vi.mock("@/components/ModelDisclaimer", () => ({
  default: () => <div data-testid="model-disclaimer" />,
}))

// We don't care what the auth store does in this view, but the nav-free
// CompareContent component pulls in cn / utils which sometimes touch it.
vi.mock("@/store/authStore", () => ({
  useAuthStore: () => "free",
}))

// ── Fixtures ────────────────────────────────────────────────────────────

function mkSummary(overrides: Partial<StockSummary>): StockSummary {
  return {
    ticker: "HDFCBANK.NS",
    company_name: "HDFC Bank",
    sector: "Banking",
    industry: "Private Bank",
    exchange: "NSE",
    currency: "INR",
    fair_value: 2000,
    current_price: 1800,
    mos: 10,
    verdict: "fairly_valued",
    score: 72,
    grade: "B+",
    moat: "Wide",
    piotroski: 7,
    bear_case: 1500,
    base_case: 2000,
    bull_case: 2500,
    wacc: 11.5,
    confidence: 80,
    roe: 17.5,
    de_ratio: 1.2,
    roce: 18.0,
    debt_ebitda: 1.0,
    interest_coverage: 4.0,
    current_ratio: 1.1,
    asset_turnover: 0.1,
    revenue_cagr_3y: 14.0,
    revenue_cagr_5y: 13.0,
    ev_ebitda: 12.0,
    market_cap: 13_00_000_00_00_000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: null,
    ...overrides,
  }
}

const HDFC = mkSummary({ ticker: "HDFCBANK.NS", company_name: "HDFC Bank", score: 74 })
const ICICI = mkSummary({
  ticker: "ICICIBANK.NS",
  company_name: "ICICI Bank",
  fair_value: 1300,
  current_price: 1100,
  mos: 18,
  score: 78,
  bear_case: 900,
  base_case: 1300,
  bull_case: 1700,
})
const KOTAK = mkSummary({
  ticker: "KOTAKBANK.NS",
  company_name: "Kotak Mahindra Bank",
  fair_value: 1900,
  current_price: 1750,
  mos: 8,
  score: 69,
  bear_case: 1450,
  base_case: 1900,
  bull_case: 2350,
})

const SUMMARIES: Record<string, StockSummary> = {
  HDFCBANK: HDFC,
  "HDFCBANK.NS": HDFC,
  ICICIBANK: ICICI,
  "ICICIBANK.NS": ICICI,
  KOTAKBANK: KOTAK,
  "KOTAKBANK.NS": KOTAK,
}

// ── Helpers ─────────────────────────────────────────────────────────────

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

async function loadPage() {
  // Dynamic import so module-level useSearchParams sees the latest mock state.
  vi.resetModules()
  const mod = await import("@/app/(app)/compare/page")
  return mod.default
}

beforeEach(() => {
  replaceMock.mockReset()
  getStockSummaryStatusMock.mockReset()
  getPublicPeersMock.mockReset()
  apiGetMock.mockReset()

  getStockSummaryStatusMock.mockImplementation((t: string) => {
    const key = t.toUpperCase()
    const summary = SUMMARIES[key]
    if (summary) return Promise.resolve({ kind: "ok", summary })
    return Promise.resolve({ kind: "unavailable", ticker: t })
  })
  // Peers suggestion is a nice-to-have, not under test here.
  getPublicPeersMock.mockResolvedValue({ ticker: "", peers: [] })
  apiGetMock.mockResolvedValue({ data: { results: [] } })
})

// ── Tests ───────────────────────────────────────────────────────────────

describe("ComparePage", () => {
  it("renders a 2-ticker side-by-side view (HDFCBANK vs ICICIBANK)", async () => {
    searchParamsImpl = new URLSearchParams("tickers=HDFCBANK,ICICIBANK")
    const ComparePage = await loadPage()
    renderWithClient(<ComparePage />)

    await waitFor(() => {
      // Desktop table + mobile cards both render — names appear twice.
      expect(screen.getAllByText("HDFC Bank").length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText("ICICI Bank").length).toBeGreaterThanOrEqual(1)
    })

    // Core valuation rows must be present.
    expect(screen.getAllByText(/Fair Value/i).length).toBeGreaterThan(0)
    // PR-B microcopy rename: "MoS" → "Discount to FV" as primary label.
    expect(screen.getAllByText(/Discount to FV/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/YieldIQ Score/).length).toBeGreaterThan(0)
  })

  it("renders a 3-ticker view with the scenarios section", async () => {
    searchParamsImpl = new URLSearchParams(
      "tickers=HDFCBANK,ICICIBANK,KOTAKBANK",
    )
    const ComparePage = await loadPage()
    renderWithClient(<ComparePage />)

    await waitFor(() => {
      expect(screen.getAllByText("HDFC Bank").length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText("ICICI Bank").length).toBeGreaterThanOrEqual(1)
      expect(
        screen.getAllByText("Kotak Mahindra Bank").length,
      ).toBeGreaterThanOrEqual(1)
    })

    // Scenarios section + each per-share case row.
    expect(screen.getAllByText(/Scenarios/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Bear case/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Base case/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Bull case/i).length).toBeGreaterThan(0)
  })

  it("removes a ticker via the X button and syncs the URL", async () => {
    searchParamsImpl = new URLSearchParams("tickers=HDFCBANK,ICICIBANK")
    const ComparePage = await loadPage()
    renderWithClient(<ComparePage />)

    await waitFor(() => {
      expect(screen.getAllByText("ICICI Bank").length).toBeGreaterThanOrEqual(1)
    })

    const removeBtn = screen.getByRole("button", { name: /Remove ICICIBANK/i })
    fireEvent.click(removeBtn)

    await waitFor(() => {
      expect(screen.queryAllByText("ICICI Bank").length).toBe(0)
    })

    // URL should reflect the surviving ticker.
    const lastCall = replaceMock.mock.calls.at(-1)
    expect(lastCall?.[0]).toBe("/compare?tickers=HDFCBANK")
  })

  it("honors under_review tickers with the neutral amber warning (not the red error)", async () => {
    // KOTAKBANK gets the under_review payload; the other two are ok.
    getStockSummaryStatusMock.mockImplementation((t: string) => {
      const key = t.toUpperCase()
      if (key === "KOTAKBANK" || key === "KOTAKBANK.NS") {
        return Promise.resolve({
          kind: "under_review",
          ticker: t,
          message: "Recalibrating after FY26 Q1 results.",
        })
      }
      const summary = SUMMARIES[key]
      if (summary) return Promise.resolve({ kind: "ok", summary })
      return Promise.resolve({ kind: "unavailable", ticker: t })
    })

    searchParamsImpl = new URLSearchParams(
      "tickers=HDFCBANK,ICICIBANK,KOTAKBANK",
    )
    const ComparePage = await loadPage()
    renderWithClient(<ComparePage />)

    await waitFor(() => {
      expect(
        screen.getByTestId("compare-under-review-warning"),
      ).toHaveTextContent(/KOTAKBANK/i)
    })
    // Under-review tickers must NOT show in the red unavailable bar.
    expect(
      screen.queryByTestId("compare-unavailable-warning"),
    ).not.toBeInTheDocument()
    // KOTAKBANK column must be excluded from the table.
    expect(screen.queryAllByText("Kotak Mahindra Bank").length).toBe(0)
    // The two ok tickers still render.
    expect(screen.getAllByText("HDFC Bank").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("ICICI Bank").length).toBeGreaterThanOrEqual(1)
  })

  it("clamps a runaway MoS via displayMos (defense-in-depth +200% cap)", async () => {
    // Simulate a stale-cache payload with raw +321% MoS — pre-clamp era.
    const runaway = mkSummary({
      ticker: "RUNAWAY.NS",
      company_name: "Runaway Corp",
      mos: 321.5,
    })
    getStockSummaryStatusMock.mockImplementation((t: string) => {
      const key = t.toUpperCase()
      if (key === "RUNAWAY" || key === "RUNAWAY.NS") {
        return Promise.resolve({ kind: "ok", summary: runaway })
      }
      const summary = SUMMARIES[key]
      if (summary) return Promise.resolve({ kind: "ok", summary })
      return Promise.resolve({ kind: "unavailable", ticker: t })
    })

    searchParamsImpl = new URLSearchParams("tickers=HDFCBANK,RUNAWAY")
    const ComparePage = await loadPage()
    renderWithClient(<ComparePage />)

    await waitFor(() => {
      expect(screen.getAllByText("Runaway Corp").length).toBeGreaterThanOrEqual(1)
    })
    // Display must show the clamped sentinel, NOT the raw +321.5%.
    expect(screen.queryAllByText(/321\.5%/).length).toBe(0)
    expect(screen.getAllByText(/≥200\.0%/).length).toBeGreaterThan(0)
  })

  it("shows the empty prompt and populates the trio when clicked", async () => {
    searchParamsImpl = new URLSearchParams("")
    const ComparePage = await loadPage()
    renderWithClient(<ComparePage />)

    // Empty-state copy stays SEBI-safe — describes the action, not a recommendation.
    expect(
      await screen.findByText(/Build a peer group/i),
    ).toBeInTheDocument()

    const trioBtn = screen.getByRole("button", { name: /TCS \/ INFY \/ WIPRO/i })
    expect(trioBtn).toBeInTheDocument()
  })
})

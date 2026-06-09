/**
 * ValuationHistoryPanel smoke tests.
 *
 * Pins:
 *   1. Renders the chart when ≥12 observations are present.
 *   2. Renders the empty-state copy when <12 observations are present.
 *   3. Stats chips reflect the mocked response values verbatim.
 *   4. Caveats list renders every backend caveat + the locked footnote.
 *   5. Loading skeleton appears while the query is in flight.
 *   6. Error state with retry button when the API rejects.
 *   7. No SEBI-banned words leak into rendered DOM.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    getValuationHistoryBacktest: vi.fn(),
  }
})

// ResizeObserver is not implemented in jsdom — Recharts needs it.
class _RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).ResizeObserver = _RO

import ValuationHistoryPanel from "@/components/analysis/ValuationHistoryPanel"
import { getValuationHistoryBacktest } from "@/lib/api"
import type { ValuationHistoryBacktestResponse } from "@/types/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/** Build a synthetic backtest payload with `n` rows. Helper kept tiny. */
function makePayloadImpl(n: number): ValuationHistoryBacktestResponse {
  const series = Array.from({ length: n }, (_, i) => {
    const d = new Date(2024, 0, 1 + i * 30)
    const fair_value = 100
    // Oscillate the price around FV with one ~25% dive around i=6..10.
    const price =
      i >= 6 && i <= 10 ? 75 + (i - 6) * 1.0 : 100 + ((i % 4) - 2) * 5
    const deviation_pct = ((price - fair_value) / fair_value) * 100
    return {
      date: d.toISOString().slice(0, 10),
      price,
      fair_value,
      deviation_pct: Number(deviation_pct.toFixed(2)),
    }
  })
  return {
    ticker: "RELIANCE.NS",
    as_of: new Date().toISOString().slice(0, 10),
    history_window_months: Math.max(1, Math.round((n * 30) / 30.4375)),
    series,
    stats: {
      n_observations: n,
      n_signal_events: 1,
      signal_threshold_pct: 20,
      median_holding_days: 90,
      median_realized_pct: 18.5,
      median_abs_error_pct: 11.2,
      pct_within_10: 0.52,
      pct_within_20: 0.83,
    },
    caveats: [
      `N=${n} observations over ${Math.round((n * 30) / 30.4375)} months.`,
      "Excluded 3 quarantined observation(s).",
    ],
  }
}

function makeSparsePayload(n: number): ValuationHistoryBacktestResponse {
  const series = Array.from({ length: n }, (_, i) => {
    const d = new Date(2024, 0, 1 + i * 30)
    return {
      date: d.toISOString().slice(0, 10),
      price: 95 + i,
      fair_value: 100,
      deviation_pct: ((95 + i - 100) / 100) * 100,
    }
  })
  return {
    ticker: "NEWCO.NS",
    as_of: new Date().toISOString().slice(0, 10),
    history_window_months: Math.max(1, Math.round((n * 30) / 30.4375)),
    series,
    stats: null,
    caveats: [
      `Insufficient history — ${n} observation(s); calibration stats need at least 12 months.`,
      `N=${n} observations over ${Math.round((n * 30) / 30.4375)} months.`,
    ],
  }
}

describe("ValuationHistoryPanel", () => {
  beforeEach(() => {
    vi.mocked(getValuationHistoryBacktest).mockReset()
  })

  it("renders the chart and stats chips when data has ≥12 observations", async () => {
    vi.mocked(getValuationHistoryBacktest).mockResolvedValue(
      makePayloadImpl(24),
    )
    renderWithClient(
      <ValuationHistoryPanel ticker="RELIANCE.NS" currency="INR" />,
    )
    await waitFor(() =>
      expect(screen.getByTestId("valuation-history-chart")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("stats-chip-observations")).toHaveTextContent(
      "24",
    )
    expect(screen.getByTestId("stats-chip-median-error")).toHaveTextContent(
      "11.2%",
    )
    expect(screen.getByTestId("stats-chip-within-20")).toHaveTextContent("83%")
    expect(screen.getByTestId("stats-chip-threshold")).toHaveTextContent("-20%")
  })

  it("renders an empty state when fewer than 12 observations are available", async () => {
    vi.mocked(getValuationHistoryBacktest).mockResolvedValue(
      makeSparsePayload(5),
    )
    renderWithClient(
      <ValuationHistoryPanel ticker="NEWCO.NS" currency="INR" />,
    )
    await waitFor(() =>
      expect(screen.getByTestId("valuation-history-empty")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Not enough history yet/i)).toBeInTheDocument()
    // Stats chip row is hidden when stats is null.
    expect(
      screen.queryByTestId("stats-chip-observations"),
    ).not.toBeInTheDocument()
  })

  it("renders every caveat plus the locked SEBI footnote", async () => {
    vi.mocked(getValuationHistoryBacktest).mockResolvedValue(
      makePayloadImpl(24),
    )
    renderWithClient(
      <ValuationHistoryPanel ticker="RELIANCE.NS" currency="INR" />,
    )
    await waitFor(() =>
      expect(screen.getByTestId("valuation-history-chart")).toBeInTheDocument(),
    )
    // Both backend caveats rendered.
    expect(screen.getByTestId("valuation-history-caveat-0")).toHaveTextContent(
      /N=24 observations/,
    )
    expect(screen.getByTestId("valuation-history-caveat-1")).toHaveTextContent(
      /Excluded 3 quarantined/,
    )
    // The locked footnote is always present.
    expect(
      screen.getByText(/Past calibration is a description of model behavior/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Not investment advice/i)).toBeInTheDocument()
  })

  it("renders the loading skeleton while the query is in flight", () => {
    // Never-resolving promise to keep the query loading.
    vi.mocked(getValuationHistoryBacktest).mockReturnValue(
      new Promise(() => {
        /* hangs forever for the test */
      }),
    )
    renderWithClient(
      <ValuationHistoryPanel ticker="RELIANCE.NS" currency="INR" />,
    )
    expect(
      screen.getByTestId("valuation-history-skeleton"),
    ).toBeInTheDocument()
  })

  it("renders an error state with a retry button when the API rejects", async () => {
    vi.mocked(getValuationHistoryBacktest).mockRejectedValue(
      new Error("boom"),
    )
    renderWithClient(
      <ValuationHistoryPanel ticker="RELIANCE.NS" currency="INR" />,
    )
    await waitFor(() =>
      expect(
        screen.getByTestId("valuation-history-error"),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/Try again/i)).toBeInTheDocument()
    // Clicking refetches — re-arm the mock with success and assert
    // the chart eventually mounts.
    vi.mocked(getValuationHistoryBacktest).mockResolvedValue(
      makePayloadImpl(24),
    )
    fireEvent.click(screen.getByText(/Try again/i))
    await waitFor(() =>
      expect(screen.getByTestId("valuation-history-chart")).toBeInTheDocument(),
    )
  })

  it("does not leak SEBI-banned vocabulary into rendered DOM", async () => {
    vi.mocked(getValuationHistoryBacktest).mockResolvedValue(
      makePayloadImpl(24),
    )
    const { container } = renderWithClient(
      <ValuationHistoryPanel ticker="RELIANCE.NS" currency="INR" />,
    )
    await waitFor(() =>
      expect(screen.getByTestId("valuation-history-chart")).toBeInTheDocument(),
    )
    const text = (container.textContent ?? "").toLowerCase()
    // Banned-vocabulary list mirrors scripts/check_sebi_words.py.
    // Each literal is tagged with sebi-allow so the lint accepts the
    // fixture words here — they are test inputs, not user-facing copy.
    /* sebi-allow: buy, sell, hold, recommend, outperform, underperform, accumulate, expensive, cheap, attractive, poor, strong, weak, appears, concern, strength, weakness, investable, investability, should */
    const banned = ["buy", "sell", "hold", "recommend", "outperform", "underperform", "accumulate", "expensive", "cheap", "attractive", "poor", "strong", "weak", "appears", "concern", "strength", "weakness", "investable", "investability", "should"] /* sebi-allow: buy, sell, hold, recommend, outperform, underperform, accumulate, expensive, cheap, attractive, poor, strong, weak, appears, concern, strength, weakness, investable, investability, should */
    for (const w of banned) {
      const re = new RegExp(`\\b${w}\\b`, "i")
      expect(text).not.toMatch(re)
    }
  })
})

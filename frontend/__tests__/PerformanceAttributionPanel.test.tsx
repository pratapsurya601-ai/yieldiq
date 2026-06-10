/**
 * PerformanceAttributionPanel smoke tests.
 *
 * Pins these behaviours (v_performance_attribution_2026_06_10):
 *   1. Loading -> placeholder; never blank slot.
 *   2. Empty (total_verdicts_tracked === 0) -> empty placeholder
 *      with a neutral microcopy, not a chart.
 *   3. Populated -> headline includes the rounded avg alpha vs
 *      Nifty and total verdicts; best/worst callouts render.
 *   4. Rolling track-record array renders the sparkline container.
 *   5. SEBI vocab discipline: the rendered DOM must not contain
 *      any banned token. The BANNED array is built from fragments
 *      at runtime (see CLAUDE.md rule #5) so the diff-only sebi-lint
 *      scanner does not fire on this test file.
 */
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

const getVerdictAttributionMock = vi.fn()

vi.mock("@/lib/api", () => ({
  getVerdictAttribution: (...a: unknown[]) => getVerdictAttributionMock(...a),
}))

import PerformanceAttributionPanel from "@/components/analysis/PerformanceAttributionPanel"
import type { VerdictAttributionSummary } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const POPULATED: VerdictAttributionSummary = {
  ticker: "RELIANCE",
  total_verdicts_tracked: 3,
  direction_correct_pct: 66.67,
  avg_alpha_vs_nifty_pct: 8.5,
  median_alpha_vs_nifty_pct: 7.0,
  best_verdict: {
    ticker: "RELIANCE",
    period_start: "2025-01-01",
    period_end: "2025-04-01",
    verdict_at_start: "undervalued",
    fv_at_start: 1500,
    price_at_start: 1000,
    price_at_end: 1400,
    actual_return_pct: 40,
    nifty_return_pct: 5,
    sector_return_pct: 5,
    alpha_vs_nifty: 35,
    alpha_vs_sector: 35,
    verdict_proven_correct: true,
  },
  worst_verdict: {
    ticker: "RELIANCE",
    period_start: "2025-04-02",
    period_end: "2025-07-02",
    verdict_at_start: "undervalued",
    fv_at_start: 1500,
    price_at_start: 1000,
    price_at_end: 950,
    actual_return_pct: -5,
    nifty_return_pct: 10,
    sector_return_pct: 10,
    alpha_vs_nifty: -15,
    alpha_vs_sector: -15,
    verdict_proven_correct: false,
  },
  rolling_30d_track_record: [
    { bucket_end: "2025-03-01", verdict_count: 1, mean_alpha_vs_nifty_pct: 12, direction_correct_pct: 100 },
    { bucket_end: "2025-04-01", verdict_count: 2, mean_alpha_vs_nifty_pct: 6, direction_correct_pct: 50 },
    { bucket_end: "2025-06-30", verdict_count: 1, mean_alpha_vs_nifty_pct: -3, direction_correct_pct: 0 },
  ],
}

const EMPTY: VerdictAttributionSummary = {
  ticker: "RELIANCE",
  total_verdicts_tracked: 0,
  direction_correct_pct: 0,
  avg_alpha_vs_nifty_pct: 0,
  median_alpha_vs_nifty_pct: 0,
  best_verdict: null,
  worst_verdict: null,
  rolling_30d_track_record: [],
}

beforeEach(() => {
  getVerdictAttributionMock.mockReset()
})

describe("PerformanceAttributionPanel", () => {
  it("renders the loading placeholder while the query is in flight", () => {
    getVerdictAttributionMock.mockReturnValue(new Promise(() => { /* never resolves */ }))
    renderWithClient(<PerformanceAttributionPanel ticker="RELIANCE" />)
    expect(screen.getByTestId("performance-attribution-panel")).toBeInTheDocument()
  })

  it("renders the empty placeholder when no verdicts are tracked", async () => {
    getVerdictAttributionMock.mockResolvedValue(EMPTY)
    renderWithClient(<PerformanceAttributionPanel ticker="RELIANCE" />)
    await waitFor(() => {
      expect(screen.getByText(/Not enough verdict history/i)).toBeInTheDocument()
    })
    expect(screen.queryByTestId("rolling-track-record")).not.toBeInTheDocument()
  })

  it("renders headline + best/worst callouts when populated", async () => {
    getVerdictAttributionMock.mockResolvedValue(POPULATED)
    renderWithClient(<PerformanceAttributionPanel ticker="RELIANCE" />)

    await waitFor(() => {
      expect(screen.getByTestId("attribution-headline")).toBeInTheDocument()
    })
    const headline = screen.getByTestId("attribution-headline")
    expect(headline.textContent).toMatch(/\+8\.5%/)
    expect(headline.textContent).toMatch(/3 verdicts/)

    const callouts = screen.getAllByTestId("verdict-callout")
    expect(callouts).toHaveLength(2)
    // Best callout — positive alpha (+35%)
    expect(callouts[0].textContent).toMatch(/\+35\.0%/)
    // Worst callout — negative alpha (-15%)
    expect(callouts[1].textContent).toMatch(/-15\.0%/)
  })

  it("renders the rolling track-record sparkline when buckets exist", async () => {
    getVerdictAttributionMock.mockResolvedValue(POPULATED)
    renderWithClient(<PerformanceAttributionPanel ticker="RELIANCE" />)
    await waitFor(() => {
      expect(screen.getByTestId("rolling-track-record")).toBeInTheDocument()
    })
  })

  it("does not leak any SEBI-banned token in the rendered DOM", async () => {
    getVerdictAttributionMock.mockResolvedValue(POPULATED)
    const { container } = renderWithClient(
      <PerformanceAttributionPanel ticker="RELIANCE" />,
    )
    await waitFor(() => {
      expect(screen.getByTestId("attribution-headline")).toBeInTheDocument()
    })
    // Build the banned list from fragments at runtime so the file is
    // safe under scripts/check_sebi_words.py --diff-only.
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "out" + "perform",
      "under" + "perform",
      "stro" + "ng",
      "we" + "ak",
      "che" + "ap",
      "expens" + "ive",
      "attract" + "ive",
      "recomm" + "end",
    ]
    const haystack = (container.textContent || "").toLowerCase()
    for (const word of BANNED) {
      expect(haystack.includes(word)).toBe(false)
    }
  })
})

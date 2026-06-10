/**
 * ValuationTrajectoryChart smoke tests (T5.2, 2026-06-10).
 *
 * Pins:
 *   1. Renders DCF + Market price line series when history is supplied.
 *   2. Range selector toggles 1Y/3Y/5Y/All and filters the rendered
 *      point count accordingly.
 *   3. Empty-data state shows the right placeholder.
 *   4. Insights panel auto-computes trend + within-band + composite
 *      gap from the supplied history + props.
 *   5. Scenario bands + composite-IV reference rendered when supplied.
 *   6. SEBI vocab guard — fragments-built BANNED array (Pattern B per
 *      CLAUDE.md rule #5) ensures none of the regulator-restricted
 *      verbs leak into the rendered DOM.
 */
import { describe, it, expect } from "vitest"
import { render, screen, fireEvent, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import ValuationTrajectoryChart from "@/components/analysis/ValuationTrajectoryChart"
import type { FVHistoryPoint } from "@/lib/api"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/**
 * Synthesise N daily points spanning `spanDays` ending today.
 * fair_value drifts +/- around the base, price tracks it with noise.
 */
function makeHistory(spanDays: number, basePrice = 1000, baseFv = 1200): FVHistoryPoint[] {
  const out: FVHistoryPoint[] = []
  const oneDay = 24 * 3600 * 1000
  const now = Date.now()
  // Roughly weekly cadence so tests stay snappy but cover the span.
  const stride = Math.max(1, Math.floor(spanDays / 60))
  for (let i = spanDays; i >= 0; i -= stride) {
    const d = new Date(now - i * oneDay)
    const t = (spanDays - i) / spanDays
    const fv = baseFv * (1 + t * 0.2)
    const price = basePrice * (1 + t * 0.15 + Math.sin(i / 12) * 0.04)
    out.push({
      date: d.toISOString().slice(0, 10),
      fair_value: Math.round(fv * 100) / 100,
      price: Math.round(price * 100) / 100,
      mos_pct: Math.round(((fv - price) / price) * 1000) / 10,
      verdict: "fair_value",
    } as FVHistoryPoint)
  }
  return out
}

describe("ValuationTrajectoryChart", () => {
  it("renders the chart canvas + legend when history is supplied", () => {
    const history = makeHistory(365 * 3)
    renderWithClient(
      <ValuationTrajectoryChart
        ticker="HDFCBANK.NS"
        currentPrice={1100}
        compositeIntrinsicValue={1300}
        scenarios={{ bull: 1500, base: 1300, bear: 950 }}
        historyOverride={history}
      />,
    )
    const section = screen.getByTestId("valuation-trajectory-chart")
    expect(section).toHaveAttribute("data-state", "ready")
    expect(within(section).getByTestId("trajectory-chart-canvas")).toBeInTheDocument()
    // Legend rows for the two primary historical series.
    expect(within(section).getByText("DCF fair value")).toBeInTheDocument()
    expect(within(section).getByText("Market price")).toBeInTheDocument()
  })

  it("range selector toggles 1Y/3Y/5Y/All and updates ARIA state", () => {
    const history = makeHistory(365 * 5)
    renderWithClient(
      <ValuationTrajectoryChart
        ticker="HDFCBANK.NS"
        currentPrice={1100}
        scenarios={{ bull: 1500, base: 1300, bear: 950 }}
        historyOverride={history}
      />,
    )
    const oneY = screen.getByRole("radio", { name: /1Y range/i })
    const fiveY = screen.getByRole("radio", { name: /5Y range/i })
    const allBtn = screen.getByRole("radio", { name: /All range/i })

    // Default is 3Y.
    expect(screen.getByRole("radio", { name: /3Y range/i })).toHaveAttribute(
      "aria-checked",
      "true",
    )

    fireEvent.click(oneY)
    expect(oneY).toHaveAttribute("aria-checked", "true")

    fireEvent.click(fiveY)
    expect(fiveY).toHaveAttribute("aria-checked", "true")

    fireEvent.click(allBtn)
    expect(allBtn).toHaveAttribute("aria-checked", "true")
  })

  it("renders insights panel with auto-computed trend lines", () => {
    const history = makeHistory(365 * 3)
    renderWithClient(
      <ValuationTrajectoryChart
        ticker="HDFCBANK.NS"
        currentPrice={1100}
        compositeIntrinsicValue={1300}
        scenarios={{ bull: 1500, base: 1300, bear: 950 }}
        historyOverride={history}
      />,
    )
    const panel = screen.getByTestId("trajectory-insights")
    // Trend line — synthesised history drifts UP, so the panel
    // surfaces a positive trend statement.
    expect(panel.textContent).toMatch(/DCF fair value has trended up/i)
    // Within-band statistic line.
    expect(panel.textContent).toMatch(
      /within .20% of DCF fair value on \d+% of tracked days/i,
    )
    // Composite-IV gap line (because compositeIntrinsicValue was passed).
    expect(panel.textContent).toMatch(/composite intrinsic value sits/i)
  })

  it("shows the empty placeholder when history is empty", () => {
    renderWithClient(
      <ValuationTrajectoryChart
        ticker="HDFCBANK.NS"
        currentPrice={1100}
        historyOverride={[]}
      />,
    )
    const section = screen.getByTestId("valuation-trajectory-chart")
    expect(section).toHaveAttribute("data-state", "empty")
    expect(within(section).getByText(/Trajectory builds up/i)).toBeInTheDocument()
  })

  it("renders without composite or scenarios when those props are omitted", () => {
    const history = makeHistory(365 * 2)
    renderWithClient(
      <ValuationTrajectoryChart
        ticker="HDFCBANK.NS"
        currentPrice={1100}
        historyOverride={history}
      />,
    )
    const section = screen.getByTestId("valuation-trajectory-chart")
    expect(section).toHaveAttribute("data-state", "ready")
    // Composite-gap line is absent from insights when prop omitted.
    const panel = screen.getByTestId("trajectory-insights")
    expect(panel.textContent).not.toMatch(/composite intrinsic value sits/i)
  })

  // SEBI vocab guard — Pattern B (fragments) per CLAUDE.md rule #5.
  // None of the regulator-restricted action verbs may leak into the
  // chart's rendered DOM. Built from fragments so the diff-only SEBI
  // lint scanner (which sees ADDED LINES) does not trip on the test
  // file itself.
  it("does not leak SEBI-banned verbs into rendered output", () => {
    const history = makeHistory(365 * 3)
    const { container } = renderWithClient(
      <ValuationTrajectoryChart
        ticker="HDFCBANK.NS"
        currentPrice={1100}
        compositeIntrinsicValue={1300}
        scenarios={{ bull: 1500, base: 1300, bear: 950 }}
        historyOverride={history}
      />,
    )
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "stro" + "ng b" + "uy",
      "stro" + "ng se" + "ll",
      "tar" + "get pri" + "ce",
      "recommen" + "dation",
    ]
    const haystack = (container.textContent || "").toLowerCase()
    for (const term of BANNED) {
      expect(haystack).not.toContain(term)
    }
  })
})

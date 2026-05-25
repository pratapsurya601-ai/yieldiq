/**
 * FVProjectionFan smoke tests.
 *
 * Pins:
 *   1. Renders the three endpoint chips (Bull / Base / Bear) with the
 *      passed scenario values.
 *   2. Computes implied 5y CAGR correctly from current price → base IV.
 *   3. "Show numbers" toggle reveals the legacy 3-card table view.
 *   4. Empty state when no current price and no history.
 */
import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import FVProjectionFan from "@/components/analysis/FVProjectionFan"

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
})

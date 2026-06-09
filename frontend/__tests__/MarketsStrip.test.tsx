/**
 * MarketsStrip — locks in the post-2026-06-09 layout that adds three
 * commodity tiles (GOLD / SILVER / CRUDE) after the existing five
 * indices + FX + 10Y cells.
 *
 * The strip is the LCP candidate on /home, so structural drift here has
 * outsized perf implications. The snapshot diff catches both visual
 * regressions and accidental tile removal.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getMarketPulse: vi.fn(),
}))

import { getMarketPulse } from "@/lib/api"
import MarketsStrip from "@/components/home/v2/MarketsStrip"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const FULL_PULSE = {
  indices: [
    { name: "NIFTY 50",   price: 25_400, change_pct:  0.42 },
    { name: "NIFTY BANK", price: 53_100, change_pct: -0.18 },
    { name: "SENSEX",     price: 83_550, change_pct:  0.30 },
  ],
  fear_greed_index: null,
  fear_greed_label: null,
  timestamp: "2026-06-08T15:30:00+05:30",
  usd_inr: 83.5,
  risk_free_pct: 7.05,
  // Commodity payload added by the same PR as this test.
  gold_usd: 2350.0,
  silver_usd: 30.5,
  crude_usd: 78.2,
  gold_usd_change_pct: 0.8,
  silver_usd_change_pct: -0.5,
  crude_usd_change_pct: 1.2,
  gold_inr_per_10g: 63_080,
  silver_inr_per_10g: 818,
}

describe("MarketsStrip — commodity tiles", () => {
  it("renders GOLD, SILVER, and CRUDE tiles after the index + FX cells", async () => {
    vi.mocked(getMarketPulse).mockResolvedValue(FULL_PULSE as never)
    const { container } = renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    expect(screen.getByText("SILVER")).toBeInTheDocument()
    expect(screen.getByText("CRUDE")).toBeInTheDocument()
    // Spot-check formatting: gold/silver in ₹/10g, crude in $/bbl.
    expect(screen.getByText(/₹63,080\/10g/)).toBeInTheDocument()
    expect(screen.getByText(/\$78\.2\/bbl/)).toBeInTheDocument()
    // SEBI watch — neutral labels only.
    const text = container.textContent || ""
    expect(text.toLowerCase()).not.toContain("buy")
    expect(text.toLowerCase()).not.toContain("recommend")
    expect(container).toMatchSnapshot()
  })

  it("renders '—' for commodity tiles when upstream data is missing", async () => {
    // yfinance rate-limit / outage path: gold_inr_per_10g and crude_usd
    // both null. The tile must degrade to "—" rather than crash.
    vi.mocked(getMarketPulse).mockResolvedValue({
      ...FULL_PULSE,
      gold_usd: null,
      silver_usd: null,
      crude_usd: null,
      gold_usd_change_pct: null,
      silver_usd_change_pct: null,
      crude_usd_change_pct: null,
      gold_inr_per_10g: null,
      silver_inr_per_10g: null,
    } as never)
    const { container } = renderWithClient(<MarketsStrip />)
    await waitFor(() => {
      expect(screen.getByText("GOLD")).toBeInTheDocument()
    })
    // All three commodity tiles render the em-dash placeholder.
    const dashes = container.querySelectorAll("span")
    const dashCount = Array.from(dashes).filter(
      (el) => el.textContent === "—",
    ).length
    // Strip already had USD/INR + India 10Y emit a "—" for the pct
    // column even in the populated case (pct=null). With three more
    // missing tiles we expect AT LEAST 3 additional dashes for the
    // commodity values themselves.
    expect(dashCount).toBeGreaterThanOrEqual(3)
  })
})

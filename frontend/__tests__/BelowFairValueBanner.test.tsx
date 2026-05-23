/**
 * UX #130 (2026-05-23) — BelowFairValueBanner threshold.
 *
 * The banner and the backend Health-card strengths line both render
 * "{N} holdings below our model fair value" and MUST agree. Both now
 * count rows where `mos_pct > 0`. The matching backend assertion lives
 * in `backend/tests/test_below_fv_count_alignment.py`.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { BelowFairValueBanner } from "@/components/portfolio/HealthDashboard"
import type { LiveHolding } from "@/lib/api"

function h(ticker: string, mos: number, fv: number | null = 120): LiveHolding {
  return {
    ticker,
    display_ticker: ticker.replace(".NS", ""),
    company_name: ticker,
    sector: "Financial Services",
    entry_price: 100,
    quantity: 10,
    account_label: "default",
    current_price: 100,
    invested_value: 1000,
    current_value: 1000,
    pnl_abs: 0,
    pnl_pct: 0,
    day_change_abs: null,
    day_change_pct: null,
    fair_value: fv,
    mos_pct: mos,
    verdict: "fairly_valued",
    score: 60,
    saved_at: "",
    notes: "",
  }
}

describe("BelowFairValueBanner", () => {
  it("counts every holding with mos_pct > 0 (matches backend undervalued_count)", () => {
    const holdings = [
      h("A.NS", 25),    // counts
      h("B.NS", 10),    // counts
      h("C.NS", 2),     // counts (was excluded at the old 15% threshold)
      h("D.NS", 0.5),   // counts (was excluded at the old 15% threshold)
      h("E.NS", 0),     // EXCLUDED — exactly at FV
      h("F.NS", -3),    // EXCLUDED — above FV
    ]
    render(<BelowFairValueBanner holdings={holdings} />)
    expect(
      screen.getByText(/4 holdings trading below our model fair value/i),
    ).toBeInTheDocument()
  })

  it("singularises for a single holding", () => {
    render(<BelowFairValueBanner holdings={[h("A.NS", 12)]} />)
    expect(
      screen.getByText(/1 holding trading below our model fair value/i),
    ).toBeInTheDocument()
  })

  it("renders nothing when no holdings are below fair value", () => {
    const { container } = render(
      <BelowFairValueBanner holdings={[h("A.NS", -5), h("B.NS", 0)]} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("skips holdings whose fair value isn't known", () => {
    const holdings = [
      h("A.NS", 50, null), // no FV → skipped
      h("B.NS", 12, 110),  // counts
    ]
    render(<BelowFairValueBanner holdings={holdings} />)
    expect(
      screen.getByText(/1 holding trading below our model fair value/i),
    ).toBeInTheDocument()
  })
})

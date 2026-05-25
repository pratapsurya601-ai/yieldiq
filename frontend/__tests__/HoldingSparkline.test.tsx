/**
 * HoldingSparkline (P0 #5, 2026-05-25).
 *
 * Render-state assertions only — Recharts SVG output is intentionally
 * stripped of axes/tooltips so there's nothing to interrogate beyond
 * the wrapper. The skeleton + empty-state branches are the bits that
 * matter for users on cold workers / brand-new portfolios.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import HoldingSparkline from "@/components/portfolio/HoldingSparkline"
import type { FVHistoryPoint } from "@/lib/api"

describe("HoldingSparkline", () => {
  it("renders the loading skeleton when loading=true", () => {
    render(<HoldingSparkline data={undefined} loading />)
    expect(screen.getByTestId("sparkline-skeleton")).toBeInTheDocument()
  })

  it("renders the empty placeholder when data is missing", () => {
    render(<HoldingSparkline data={undefined} />)
    expect(screen.getByTestId("sparkline-empty")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("renders the empty placeholder when data has fewer than 2 points", () => {
    const one: FVHistoryPoint[] = [{ date: "2025-06-01", price: 100, fair_value: 110, mos_pct: 10, verdict: "undervalued" }]
    render(<HoldingSparkline data={one} />)
    expect(screen.getByTestId("sparkline-empty")).toBeInTheDocument()
  })

  it("renders the chart wrapper when data has 2+ points", () => {
    const series: FVHistoryPoint[] = [
      { date: "2025-06-01", price: 100, fair_value: 110, mos_pct: 10, verdict: "undervalued" },
      { date: "2025-06-02", price: 101, fair_value: 111, mos_pct: 9.9, verdict: "undervalued" },
      { date: "2025-06-03", price: 99, fair_value: 112, mos_pct: 13.1, verdict: "undervalued" },
    ]
    render(<HoldingSparkline data={series} />)
    expect(screen.getByTestId("sparkline")).toBeInTheDocument()
    expect(screen.queryByTestId("sparkline-empty")).not.toBeInTheDocument()
  })
})

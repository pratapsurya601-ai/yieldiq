/**
 * Day-108c (2026-05-23) — Sector landing page tests.
 *
 * Pure-component tests (cover SectorTable directly + the empty-state
 * branch). The full page is a server component that fetches data
 * from the backend; that surface is exercised end-to-end by the
 * backend pytest test_day108c_sector_pages.
 */
import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import SectorTable from "@/app/(marketing)/sector/[slug]/SectorTable"

type Row = Parameters<typeof SectorTable>[0]["rows"][number]

const ROWS: Row[] = [
  {
    ticker: "TCS.NS", name: "TCS",
    score: 72, verdict: "fairly_valued",
    fv: 4200, price: 3850, mos_pct: 9.1,
    pe_ratio: 28, roe: 45, fv_to_price: 1.0909,
  },
  {
    ticker: "INFY.NS", name: "Infosys",
    score: 68, verdict: "undervalued",
    fv: 1800, price: 1600, mos_pct: 12.5,
    pe_ratio: 24, roe: 31, fv_to_price: 1.125,
  },
  {
    ticker: "TECHM.NS", name: "Tech Mahindra",
    score: 55, verdict: "overvalued",
    fv: 1600, price: 1700, mos_pct: -5.8,
    pe_ratio: 30, roe: 11, fv_to_price: 0.94,
  },
]

describe("SectorTable", () => {
  it("renders one row per cohort ticker with the bare symbol", () => {
    render(<SectorTable rows={ROWS} />)
    expect(screen.getByText("TCS")).toBeInTheDocument()
    expect(screen.getByText("INFY")).toBeInTheDocument()
    expect(screen.getByText("TECHM")).toBeInTheDocument()
    // Verdict badges visible
    expect(screen.getByText("Undervalued")).toBeInTheDocument()
    expect(screen.getByText("Overvalued")).toBeInTheDocument()
  })

  it("toggles sort order when the Score header is clicked", () => {
    render(<SectorTable rows={ROWS} />)
    // Default: sorted by score desc → TCS(72) first row, TECHM(55) last
    let bodyRows = screen.getAllByRole("row").slice(1) // skip header
    expect(bodyRows[0]).toHaveTextContent("TCS")
    expect(bodyRows[bodyRows.length - 1]).toHaveTextContent("TECHM")

    // Click Score header → ascending → TECHM first, TCS last
    fireEvent.click(screen.getByRole("button", { name: /Score/i }))
    bodyRows = screen.getAllByRole("row").slice(1)
    expect(bodyRows[0]).toHaveTextContent("TECHM")
    expect(bodyRows[bodyRows.length - 1]).toHaveTextContent("TCS")
  })

  it("shows the empty-state message when given no rows", () => {
    render(<SectorTable rows={[]} />)
    expect(
      screen.getByText(/No cached analyses for this cohort yet/i),
    ).toBeInTheDocument()
  })
})

/**
 * IndexDashboardClient — markets index dashboard surface
 * (NIFTY 50 / NIFTY BANK / NIFTY IT / SENSEX share this component).
 *
 * Coverage:
 *
 *   (1) Renders constituent rows with the documented columns when the
 *       backend ships populated data.
 *   (2) Default sort is MoS desc (Bug 2 spec): the most-undervalued
 *       constituent lands in row 1.
 *   (3) Empty-state copy renders when stocks=[], so the cache-cold
 *       fallback still hangs together visually.
 *   (4) SEBI-vocab DOM regression — the rendered DOM contains none of
 *       the banned advisory tokens. Per root CLAUDE.md rule #5, the
 *       banned array is built from string fragments at runtime so the
 *       diff-only sebi-lint check (which scans added LINES, not
 *       runtime values) doesn't false-positive on the test file.
 *   (5) Sector chip strip renders when the dataset has multiple
 *       sectors and toggles ``sectorFilter`` on click.
 */
import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import React from "react"

import IndexDashboardClient from "@/app/(marketing)/nifty50/IndexDashboardClient"

// ── Test data ────────────────────────────────────────────────────

const MULTI_SECTOR_DATA = {
  index_id: "nifty50",
  index_name: "Nifty 50 Valuation Dashboard",
  description: "All 50 Nifty 50 stocks ranked by DCF fair value",
  total_stocks: 50,
  available_stocks: 4,
  stocks: [
    {
      ticker: "RELIANCE.NS",
      display_ticker: "RELIANCE",
      company_name: "Reliance Industries Ltd",
      sector: "Energy",
      current_price: 1450,
      fair_value: 1800,
      mos: 24.1,
      verdict: "undervalued",
      score: 78,
      grade: "B",
      moat: "wide",
      market_cap: 9.8e12,
    },
    {
      ticker: "TCS.NS",
      display_ticker: "TCS",
      company_name: "Tata Consultancy Services Ltd",
      sector: "Information Technology",
      current_price: 3900,
      fair_value: 5200,
      mos: 33.3,
      verdict: "undervalued",
      score: 85,
      grade: "A",
      moat: "wide",
      market_cap: 1.4e13,
    },
    {
      ticker: "HDFCBANK.NS",
      display_ticker: "HDFCBANK",
      company_name: "HDFC Bank Ltd",
      sector: "Financial Services",
      current_price: 1700,
      fair_value: 1750,
      mos: 2.9,
      verdict: "fairly_valued",
      score: 80,
      grade: "A",
      moat: "narrow",
      market_cap: 1.3e13,
    },
    {
      ticker: "ITC.NS",
      display_ticker: "ITC",
      company_name: "ITC Ltd",
      sector: "FMCG",
      current_price: 450,
      fair_value: 380,
      mos: -15.6,
      verdict: "overvalued",
      score: 65,
      grade: "C",
      moat: "wide",
      market_cap: 5.6e12,
    },
  ],
  summary: {
    undervalued: 2,
    fairly_valued: 1,
    overvalued: 1,
    most_undervalued: {
      ticker: "TCS.NS",
      display_ticker: "TCS",
      company_name: "Tata Consultancy Services Ltd",
      sector: "Information Technology",
      current_price: 3900,
      fair_value: 5200,
      mos: 33.3,
      verdict: "undervalued",
      score: 85,
      grade: "A",
      moat: "wide",
      market_cap: 1.4e13,
    },
    most_overvalued: {
      ticker: "ITC.NS",
      display_ticker: "ITC",
      company_name: "ITC Ltd",
      sector: "FMCG",
      current_price: 450,
      fair_value: 380,
      mos: -15.6,
      verdict: "overvalued",
      score: 65,
      grade: "C",
      moat: "wide",
      market_cap: 5.6e12,
    },
  },
}

const EMPTY_DATA = {
  index_id: "nifty50",
  index_name: "Nifty 50 Valuation Dashboard",
  description: "All 50 Nifty 50 stocks ranked by DCF fair value",
  total_stocks: 50,
  available_stocks: 0,
  stocks: [],
  summary: {
    undervalued: 0,
    fairly_valued: 0,
    overvalued: 0,
    most_undervalued: null,
    most_overvalued: null,
  },
}

// ── Tests ────────────────────────────────────────────────────────

describe("IndexDashboardClient — populated rendering", () => {
  it("renders all constituent rows with the documented columns", () => {
    render(<IndexDashboardClient data={MULTI_SECTOR_DATA as never} />)
    // Each ticker shows up as its display string.
    expect(screen.getByText("RELIANCE")).toBeInTheDocument()
    expect(screen.getByText("TCS")).toBeInTheDocument()
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument()
    expect(screen.getByText("ITC")).toBeInTheDocument()
    // Sector breakdown chip strip renders (4 sectors).
    expect(screen.getByTestId("sector-chip-strip")).toBeInTheDocument()
  })

  it("default sort places the highest-MoS row at the top (Bug 2 spec)", () => {
    // TCS has the highest MoS (33.3); it must render in row 1 when the
    // default sort is MoS desc.
    const { container } = render(
      <IndexDashboardClient data={MULTI_SECTOR_DATA as never} />,
    )
    const tbody = container.querySelector("tbody")
    const firstRow = tbody?.querySelector("tr")
    expect(firstRow?.textContent).toContain("TCS")
  })

  it("sector chip toggles the filter on click", () => {
    render(<IndexDashboardClient data={MULTI_SECTOR_DATA as never} />)
    // After clicking the Energy chip, only RELIANCE must remain.
    const energyChip = screen.getByText(/Energy/)
    fireEvent.click(energyChip)
    expect(screen.getByText("RELIANCE")).toBeInTheDocument()
    expect(screen.queryByText("TCS")).not.toBeInTheDocument()
  })
})

describe("IndexDashboardClient — empty-state fallback", () => {
  it("renders the empty-state copy when stocks=[] (cache-cold path)", () => {
    render(<IndexDashboardClient data={EMPTY_DATA as never} />)
    // The empty-state row carries a static heading describing the
    // snapshot rather than fake data.
    expect(
      screen.getByText(/Nifty 50 fair-value snapshot/i),
    ).toBeInTheDocument()
  })
})

describe("IndexDashboardClient — SEBI vocab guard", () => {
  it("renders zero banned advisory tokens in the DOM", () => {
    // Pattern B (per root CLAUDE.md rule #5): build the banned array
    // from fragments at runtime so the diff-only sebi-lint scan, which
    // reads ADDED LINES regardless of whether they live in code,
    // strings, comments, or test fixtures, never sees the literal
    // tokens. The runtime assertion is identical.
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "outp" + "erform",
      "underp" + "erform",
      "accum" + "ulate",
      "che" + "ap",
      "expens" + "ive",
      "attra" + "ctive",
      "po" + "or",
      "stro" + "ng",
      "we" + "ak",
      "reco" + "mmend",
      "recommen" + "dation",
      "investa" + "ble",
      "investabi" + "lity",
      "appe" + "ars",
      "sho" + "uld",
      "conc" + "ern",
      "stren" + "gth",
      "wea" + "kness",
    ]

    const { container } = render(
      <IndexDashboardClient data={MULTI_SECTOR_DATA as never} />,
    )
    const text = (container.textContent || "").toLowerCase()
    for (const token of BANNED) {
      const re = new RegExp(`\\b${token}\\b`, "i")
      expect(text.match(re)).toBeNull()
    }
  })
})

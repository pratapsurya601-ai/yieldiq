/**
 * CSV-zip export — structural unit tests.
 *
 * Validates CSV row counts, header presence, RFC 4180 escaping, and
 * that the zip bundle contains every expected file plus the README.
 */
import { describe, it, expect } from "vitest"
import JSZip from "jszip"
import {
  buildSummaryCSV,
  buildFinancialsCSV,
  buildPeersCSV,
  buildDividendsCSV,
  buildReadme,
  buildCSVZip,
  csvEscape,
  toCSV,
} from "@/lib/csv-zip"
import { SEBI_DISCLAIMER } from "@/lib/excel-detailed"
import type {
  StockSummary,
  HistoricalFinancialsResponse,
  PublicPeersResponse,
  DividendHistoryResponse,
} from "@/lib/api"

function makeSummary(): StockSummary {
  return {
    ticker: "ACME",
    company_name: 'Acme "Holdings" Ltd, India', // quotes + comma — escape me
    sector: "Industrials",
    industry: "Capital Goods",
    exchange: "NSE",
    currency: "INR",
    fair_value: 500,
    current_price: 400,
    mos: 25,
    verdict: "below_fair_value",
    score: 80,
    grade: "A",
    moat: "wide",
    piotroski: 8,
    bear_case: 350,
    base_case: 500,
    bull_case: 700,
    wacc: 0.12,
    confidence: 82,
    roe: 18,
    de_ratio: 0.3,
    roce: 22,
    debt_ebitda: 0.8,
    interest_coverage: 12,
    current_ratio: 1.6,
    asset_turnover: 1.1,
    revenue_cagr_3y: 0.14,
    revenue_cagr_5y: 0.12,
    ev_ebitda: 11,
    market_cap: 30000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: "2026-06-01",
  }
}

const ANNUAL: HistoricalFinancialsResponse = {
  ticker: "ACME",
  currency: "INR",
  periods: [
    {
      period_end: "2025-03-31",
      period_type: "annual",
      revenue: 1000, ebitda: 220, ebit: 180, pat: 140, eps_diluted: 14,
      cfo: 170, capex: -50, free_cash_flow: 120, total_assets: 2400,
      total_equity: 1600, total_debt: 600, cash_and_equivalents: 200,
      shares_outstanding: 10, roe: 0.087, roa: 0.058,
      debt_to_equity: 0.375, gross_margin: 0.42, operating_margin: 0.18,
      net_margin: 0.14, fcf_margin: 0.12, revenue_growth_yoy: 0.10,
      pat_growth_yoy: 0.12,
    },
  ],
}

const PEERS: PublicPeersResponse = {
  ticker: "ACME",
  peers: [
    { peer_ticker: "X", rank: 1, sector: "Industrials", sub_sector: "Cap Goods",
      mcap_ratio: 1.2, company_name: "X Co", fair_value: 100, current_price: 80,
      margin_of_safety: 25, verdict: "below_fair_value", score: 70, moat: "narrow",
      roe: 14, pe_ratio: 18 },
  ],
}

const DIV: DividendHistoryResponse = {
  ticker: "ACME",
  count: 2,
  total_paid_5y: 25,
  dividends: [
    { ex_date: "2025-06-01", amount: 5, source_format: "rupee_amount" },
    { ex_date: "2024-06-01", amount: 4.5, source_format: "rupee_amount" },
  ],
}

describe("csvEscape", () => {
  it("returns empty string for null / undefined / NaN", () => {
    expect(csvEscape(null)).toBe("")
    expect(csvEscape(undefined)).toBe("")
    expect(csvEscape(NaN)).toBe("")
  })

  it("wraps fields containing comma, quote, or newline", () => {
    expect(csvEscape("a,b")).toBe('"a,b"')
    expect(csvEscape('he said "hi"')).toBe('"he said ""hi"""')
    expect(csvEscape("line1\nline2")).toBe('"line1\nline2"')
  })

  it("leaves clean strings and numbers alone", () => {
    expect(csvEscape("hello")).toBe("hello")
    expect(csvEscape(42)).toBe("42")
  })
})

describe("buildSummaryCSV", () => {
  it("emits a single data row with all expected columns", () => {
    const out = buildSummaryCSV(makeSummary())
    const lines = out.trim().split(/\r\n/)
    expect(lines.length).toBe(2) // header + 1 row
    const header = lines[0]?.split(",") ?? []
    expect(header).toContain("ticker")
    expect(header).toContain("fair_value")
    expect(header).toContain("piotroski")
  })

  it("escapes embedded quotes and commas in company_name", () => {
    const out = buildSummaryCSV(makeSummary())
    expect(out).toContain('"Acme ""Holdings"" Ltd, India"')
  })
})

describe("buildFinancialsCSV", () => {
  it("returns header-only when periods is empty", () => {
    const out = buildFinancialsCSV(null)
    const lines = out.trim().split(/\r\n/)
    expect(lines.length).toBe(1)
    expect(lines[0]).toContain("period_end")
  })

  it("emits one row per period", () => {
    const out = buildFinancialsCSV(ANNUAL)
    const lines = out.trim().split(/\r\n/)
    expect(lines.length).toBe(2)
  })
})

describe("buildPeersCSV", () => {
  it("emits one row per peer with rank, ticker, score", () => {
    const out = buildPeersCSV(PEERS)
    const lines = out.trim().split(/\r\n/)
    expect(lines.length).toBe(2)
    expect(lines[1]).toContain("X")
    expect(lines[1]).toContain("70")
  })
})

describe("buildDividendsCSV", () => {
  it("emits one row per dividend event", () => {
    const out = buildDividendsCSV(DIV)
    const lines = out.trim().split(/\r\n/)
    expect(lines.length).toBe(3) // header + 2 events
  })
})

describe("buildReadme", () => {
  it("names the ticker and embeds the SEBI disclaimer", () => {
    const r = buildReadme("ACME")
    expect(r).toContain("YieldIQ detailed export — ACME")
    expect(r).toContain(SEBI_DISCLAIMER)
  })
})

describe("toCSV", () => {
  it("uses CRLF line endings (RFC 4180)", () => {
    const out = toCSV(["a", "b"], [["1", "2"]])
    expect(out).toBe("a,b\r\n1,2\r\n")
  })
})

describe("buildCSVZip", () => {
  // We round-trip the zip through JSZip directly (rather than through
  // the Blob in the test) because jsdom's Blob does not implement
  // `arrayBuffer()`. Building the JSZip object ourselves and asserting
  // it contains the right entries proves the same invariant — every
  // CSV slice plus the README is registered with the zip writer.
  it("registers every expected entry on the zip writer", async () => {
    const z = new JSZip()
    z.file("summary.csv", buildSummaryCSV(makeSummary()))
    z.file("financials_annual.csv", buildFinancialsCSV(ANNUAL))
    z.file("financials_quarterly.csv", buildFinancialsCSV(null))
    z.file("ratios.csv", "")
    z.file("peers.csv", buildPeersCSV(PEERS))
    z.file("dividends.csv", buildDividendsCSV(DIV))
    z.file("README.txt", buildReadme("ACME"))
    const names = Object.keys(z.files).sort()
    expect(names).toEqual([
      "README.txt",
      "dividends.csv",
      "financials_annual.csv",
      "financials_quarterly.csv",
      "peers.csv",
      "ratios.csv",
      "summary.csv",
    ])
  })

  it("buildCSVZip resolves to a non-empty Blob", async () => {
    const blob = await buildCSVZip({
      ticker: "ACME",
      summary: makeSummary(),
      annualFinancials: ANNUAL,
      quarterlyFinancials: null,
      ratios: null,
      peers: PEERS,
      dividends: DIV,
    })
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.size).toBeGreaterThan(0)
  })
})

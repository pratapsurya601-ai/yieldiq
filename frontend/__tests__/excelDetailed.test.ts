/**
 * Detailed Excel export — structural unit tests.
 *
 * Asserts the workbook has the expected 10 sheets, that the DCF Model
 * sheet contains formula cells (so editing assumptions actually
 * recomputes downstream values in Excel, rather than being hardcoded),
 * and that the Cover sheet carries the SEBI disclaimer.
 */
import { describe, it, expect } from "vitest"
import * as XLSX from "xlsx"
import {
  buildDetailedWorkbook,
  SEBI_DISCLAIMER,
  type DetailedExcelBundle,
} from "@/lib/excel-detailed"
import type { StockSummary, HistoricalFinancialsResponse } from "@/lib/api"

function makeSummary(overrides: Partial<StockSummary> = {}): StockSummary {
  return {
    ticker: "TEST",
    company_name: "Test Industries Ltd",
    sector: "Materials",
    industry: "Cement",
    exchange: "NSE",
    currency: "INR",
    fair_value: 1200,
    current_price: 1000,
    mos: 20,
    verdict: "below_fair_value",
    score: 72,
    grade: "B+",
    moat: "narrow",
    piotroski: 7,
    bear_case: 900,
    base_case: 1200,
    bull_case: 1500,
    wacc: 0.115,
    confidence: 78,
    roe: 16.4,
    de_ratio: 0.42,
    roce: 19.1,
    debt_ebitda: 1.1,
    interest_coverage: 8.2,
    current_ratio: 1.4,
    asset_turnover: 0.9,
    revenue_cagr_3y: 0.12,
    revenue_cagr_5y: 0.10,
    ev_ebitda: 14.2,
    market_cap: 45000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: "2026-06-01",
    ...overrides,
  }
}

function makeAnnual(): HistoricalFinancialsResponse {
  return {
    ticker: "TEST",
    currency: "INR",
    periods: [
      {
        period_end: "2025-03-31",
        period_type: "annual",
        revenue: 5000,
        ebitda: 1100,
        ebit: 900,
        pat: 700,
        eps_diluted: 35,
        cfo: 850,
        capex: -200,
        free_cash_flow: 650,
        total_assets: 12000,
        total_equity: 8000,
        total_debt: 3000,
        cash_and_equivalents: 800,
        shares_outstanding: 20,
        roe: 0.087,
        roa: 0.058,
        debt_to_equity: 0.375,
        gross_margin: 0.42,
        operating_margin: 0.18,
        net_margin: 0.14,
        fcf_margin: 0.13,
        revenue_growth_yoy: 0.11,
        pat_growth_yoy: 0.18,
      },
      {
        period_end: "2024-03-31",
        period_type: "annual",
        revenue: 4500,
        ebitda: 950,
        ebit: 780,
        pat: 590,
        eps_diluted: 29,
        cfo: 720,
        capex: -180,
        free_cash_flow: 540,
        total_assets: 11000,
        total_equity: 7400,
        total_debt: 2800,
        cash_and_equivalents: 700,
        shares_outstanding: 20,
        roe: 0.080,
        roa: 0.054,
        debt_to_equity: 0.378,
        gross_margin: 0.41,
        operating_margin: 0.17,
        net_margin: 0.13,
        fcf_margin: 0.12,
        revenue_growth_yoy: 0.09,
        pat_growth_yoy: 0.12,
      },
    ],
  }
}

const EMPTY_BUNDLE: DetailedExcelBundle = {
  ticker: "TEST",
  summary: makeSummary(),
  annualFinancials: makeAnnual(),
  quarterlyFinancials: null,
  ratios: null,
  peers: null,
  dividends: null,
}

describe("buildDetailedWorkbook", () => {
  it("emits exactly the 10 named sheets in order", () => {
    const wb = buildDetailedWorkbook(EMPTY_BUNDLE)
    expect(wb.SheetNames).toEqual([
      "Cover",
      "Valuation Summary",
      "DCF Model",
      "Financials Annual",
      "Financials Quarterly",
      "Ratios 10y",
      "Peers",
      "Dividend History",
      "Quality & Moat",
      "Methodology",
    ])
  })

  it("DCF Model uses Excel FORMULAS for WACC, projected FCF, terminal, and equity value", () => {
    const wb = buildDetailedWorkbook(EMPTY_BUNDLE)
    const ws = wb.Sheets["DCF Model"]
    // WACC build
    expect(ws.B14.f).toMatch(/\+\s*B7\*B6/)         // cost of equity = Rf + Beta*ERP
    expect(ws.B15.f).toMatch(/B8\s*\*\s*\(1\s*-\s*B9/) // after-tax kd
    expect(ws.B16.f).toMatch(/B10\*B15\s*\+\s*\(1-B10\)\*B14/) // WACC
    // FCF projection chain
    expect(ws.B19.f).toBe("B2*(1+B3/100)")
    expect(ws.B23.f).toBe("B22*(1+B3/100)")
    // Discount factor
    expect(ws.C19.f).toContain("POWER(1+B$16/100, A19)")
    // Terminal value
    expect(ws.B25.f).toContain("B23*(1+B4/100)/((B16-B4)/100)")
    // Sum of PVs + per-share
    expect(ws.B27.f).toBe("SUM(D19:D23)+B26")
    expect(ws.B28.f).toBe("B27/B11")
  })

  it("Cover sheet carries the SEBI disclaimer string verbatim", () => {
    const wb = buildDetailedWorkbook(EMPTY_BUNDLE)
    const ws = wb.Sheets.Cover
    // The disclaimer is the last populated row, at the merged cell A29.
    const aoa = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1 })
    // Find the row containing the disclaimer
    const flat = aoa.map((r) => (Array.isArray(r) ? r.join(" ") : "")).join("\n")
    expect(flat).toContain(SEBI_DISCLAIMER)
  })

  it("does not include any banned SEBI vocabulary in the sheet text", () => {
    const wb = buildDetailedWorkbook(EMPTY_BUNDLE)
    // sebi-allow: buy, sell, outperform, underperform, expensive, cheap, undervalued, overvalued, attractive, investable
    // sebi-allow: buy, sell, outperform, underperform, expensive, cheap, undervalued, overvalued, attractive, investable
    const banned = [
      // sebi-allow: buy, sell, outperform, underperform, expensive, cheap
      "buy", "sell", "outperform", "underperform", "expensive", "cheap",
      // sebi-allow: undervalued, overvalued, attractive, investable
      "undervalued", "overvalued", "attractive", "investable",
    ]
    // Concatenate all string cells across all sheets and scan for
    // banned words at word boundaries. We allow the verdict field
    // (e.g. "below_fair_value") because that's an engine-allow-listed
    // token, not free-form copy.
    for (const name of wb.SheetNames) {
      if (name === "Cover" || name === "Valuation Summary") {
        // skip — verdict label may appear; scanned only across pure
        // free-text sheets:
        continue
      }
      const ws = wb.Sheets[name]
      const aoa = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1 })
      for (const row of aoa) {
        if (!Array.isArray(row)) continue
        for (const cell of row) {
          if (typeof cell !== "string") continue
          for (const word of banned) {
            const re = new RegExp(`\\b${word}\\b`, "i")
            expect(re.test(cell)).toBe(false)
          }
        }
      }
    }
  })

  it("Annual Financials sheet writes the year column as text (no comma separators)", () => {
    const wb = buildDetailedWorkbook(EMPTY_BUNDLE)
    const ws = wb.Sheets["Financials Annual"]
    expect(ws.A2.t).toBe("s")
    expect(ws.A2.v).toBe("2024")
  })
})

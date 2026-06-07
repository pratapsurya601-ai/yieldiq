/**
 * Sensitivity matrix + PDF builder invariants.
 *
 * These guard the page-2 additions (WACC build-up + 5x5 sensitivity matrix):
 *   1. The centre cell of the 5x5 matrix MUST exactly equal `fair_value`
 *      to within INR 1. The PDF page is rendered against this expectation
 *      and a drift here means the displayed centre value would disagree
 *      with the scorecard.
 *   2. The matrix must be monotone:
 *        - higher WACC -> lower IV (rows decrease top-to-bottom for fixed g)
 *        - higher g    -> higher IV (cols increase left-to-right for fixed W)
 *      A failure here points at a sign/formula bug in the closed-form DCF
 *      approximation that drives the off-diagonal cells.
 *   3. buildPDFReport must not throw on a minimal bundle.
 */
import { describe, it, expect } from "vitest"
import { buildPDFReport, buildSensitivityMatrix, type PDFBundle } from "@/lib/pdf-report"
import type { StockSummary } from "@/lib/api"

function makeSummary(overrides: Partial<StockSummary> = {}): StockSummary {
  return {
    ticker: "TEST",
    company_name: "Test Co Ltd",
    sector: "Tech",
    industry: "Software",
    exchange: "NSE",
    currency: "INR",
    fair_value: 1500,
    current_price: 1200,
    mos: 25,
    verdict: "undervalued",
    score: 72,
    grade: "B+",
    moat: "Narrow",
    piotroski: 7,
    bear_case: 1100,
    base_case: 1500,
    bull_case: 1900,
    wacc: 0.12,
    confidence: 0.78,
    roe: 18.2,
    de_ratio: 0.4,
    roce: 22.1,
    debt_ebitda: 1.1,
    interest_coverage: 12,
    current_ratio: 1.8,
    asset_turnover: 0.9,
    revenue_cagr_3y: 0.12,
    revenue_cagr_5y: 0.14,
    ev_ebitda: 14.5,
    market_cap: 250000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: null,
    ...overrides,
  } as StockSummary
}

describe("buildSensitivityMatrix", () => {
  it("centre cell equals fair_value within INR 1", () => {
    const s = makeSummary()
    const m = buildSensitivityMatrix(s, 0.04)
    const centre = m.values[2]?.[2]
    expect(centre).not.toBeNull()
    expect(Math.abs((centre ?? 0) - s.fair_value)).toBeLessThan(1)
  })

  it("is monotone: higher WACC -> lower IV at fixed growth", () => {
    const s = makeSummary()
    const m = buildSensitivityMatrix(s, 0.04)
    for (let c = 0; c < 5; c++) {
      for (let r = 0; r < 4; r++) {
        const hi = m.values[r]?.[c]
        const lo = m.values[r + 1]?.[c]
        if (hi == null || lo == null) continue
        expect(hi).toBeGreaterThan(lo)
      }
    }
  })

  it("is monotone: higher terminal growth -> higher IV at fixed WACC", () => {
    const s = makeSummary()
    const m = buildSensitivityMatrix(s, 0.04)
    for (let r = 0; r < 5; r++) {
      for (let c = 0; c < 4; c++) {
        const lo = m.values[r]?.[c]
        const hi = m.values[r]?.[c + 1]
        if (lo == null || hi == null) continue
        expect(hi).toBeGreaterThan(lo)
      }
    }
  })

  it("handles W <= g gracefully by emitting null cells", () => {
    // Force a tiny base WACC so positive g offsets push some cells to W <= g.
    const s = makeSummary({ wacc: 0.05 })
    const m = buildSensitivityMatrix(s, 0.04)
    // At W = 0.05 - 0.02 = 0.03 and g = 0.04 + 0.02 = 0.06, W < g -> null.
    expect(m.values[0]?.[4]).toBeNull()
  })
})

describe("buildPDFReport", () => {
  it("renders 5 pages and does not throw on a minimal bundle", () => {
    const bundle: PDFBundle = {
      ticker: "TEST",
      summary: makeSummary(),
      annualFinancials: null,
      ratios: null,
      peers: null,
    }
    const doc = buildPDFReport(bundle)
    expect(doc.getNumberOfPages()).toBe(5)
  })
})

/**
 * PDF export — structural unit tests.
 *
 * jsPDF runs fine under jsdom (it uses ArrayBuffer + standard fonts,
 * no canvas dependency for the output we generate). We assert page
 * count, page size, and that the underlying PDF byte stream contains
 * the ticker so we know the renderer actually wrote text.
 */
import { describe, it, expect } from "vitest"
import { buildPDFReport, type PDFBundle } from "@/lib/pdf-report"
import type {
  StockSummary,
  HistoricalFinancialsResponse,
  PublicPeersResponse,
} from "@/lib/api"

function summary(): StockSummary {
  return {
    ticker: "RELIANCE",
    company_name: "Reliance Industries",
    sector: "Energy",
    industry: "Oil & Gas",
    exchange: "NSE",
    currency: "INR",
    fair_value: 3000,
    current_price: 2500,
    mos: 20,
    verdict: "below_fair_value",
    score: 78,
    grade: "A-",
    moat: "narrow",
    piotroski: 7,
    bear_case: 2200,
    base_case: 3000,
    bull_case: 3700,
    wacc: 0.11,
    confidence: 80,
    roe: 14,
    de_ratio: 0.5,
    roce: 16,
    debt_ebitda: 1.5,
    interest_coverage: 6,
    current_ratio: 1.2,
    asset_turnover: 0.8,
    revenue_cagr_3y: 0.12,
    revenue_cagr_5y: 0.10,
    ev_ebitda: 12,
    market_cap: 1800000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: "2026-06-01",
  }
}

const ANNUAL: HistoricalFinancialsResponse = {
  ticker: "RELIANCE",
  currency: "INR",
  periods: [
    {
      period_end: "2025-03-31", period_type: "annual",
      revenue: 100000, ebitda: 20000, ebit: 16000, pat: 12000,
      eps_diluted: 80, cfo: 18000, capex: -5000, free_cash_flow: 13000,
      total_assets: 500000, total_equity: 300000, total_debt: 150000,
      cash_and_equivalents: 20000, shares_outstanding: 150,
      roe: 0.1, roa: 0.05, debt_to_equity: 0.5,
      gross_margin: 0.4, operating_margin: 0.16, net_margin: 0.12,
      fcf_margin: 0.13, revenue_growth_yoy: 0.1, pat_growth_yoy: 0.12,
    },
    {
      period_end: "2024-03-31", period_type: "annual",
      revenue: 90000, ebitda: 18000, ebit: 14000, pat: 10500,
      eps_diluted: 70, cfo: 16000, capex: -4500, free_cash_flow: 11500,
      total_assets: 470000, total_equity: 280000, total_debt: 145000,
      cash_and_equivalents: 18000, shares_outstanding: 150,
      roe: 0.094, roa: 0.045, debt_to_equity: 0.518,
      gross_margin: 0.38, operating_margin: 0.155, net_margin: 0.117,
      fcf_margin: 0.13, revenue_growth_yoy: 0.08, pat_growth_yoy: 0.10,
    },
  ],
}

const PEERS: PublicPeersResponse = {
  ticker: "RELIANCE",
  peers: [
    { peer_ticker: "ONGC", rank: 1, sector: "Energy", sub_sector: "Oil & Gas",
      mcap_ratio: 0.4, company_name: "ONGC", fair_value: 250, current_price: 220,
      margin_of_safety: 14, verdict: "below_fair_value", score: 65, moat: "narrow",
      roe: 12, pe_ratio: 8 },
  ],
}

const BUNDLE: PDFBundle = {
  ticker: "RELIANCE",
  summary: summary(),
  annualFinancials: ANNUAL,
  ratios: null,
  peers: PEERS,
}

describe("buildPDFReport", () => {
  it("produces a 3-page A4 document", () => {
    const doc = buildPDFReport(BUNDLE)
    expect(doc.getNumberOfPages()).toBe(3)
    const w = doc.internal.pageSize.getWidth()
    const h = doc.internal.pageSize.getHeight()
    // A4 in points: 595 x 842 (jsPDF default at pt unit)
    expect(Math.round(w)).toBe(595)
    expect(Math.round(h)).toBe(842)
  })

  it("emits a non-empty PDF stream containing the ticker", () => {
    const doc = buildPDFReport(BUNDLE)
    const out = doc.output("arraybuffer")
    expect(out.byteLength).toBeGreaterThan(1000) // sanity floor
    // Decode the stream and check for the ticker. We use latin1 because
    // PDF text streams are byte-level; jsPDF's default font is WinAnsi,
    // so straight ASCII characters in the ticker land verbatim in the
    // content stream.
    const txt = new TextDecoder("latin1").decode(out)
    expect(txt).toContain("RELIANCE")
  })

  it("renders without throwing when financials and peers are null", () => {
    const minimal: PDFBundle = {
      ticker: "EMPTY",
      summary: summary(),
      annualFinancials: null,
      ratios: null,
      peers: null,
    }
    expect(() => buildPDFReport(minimal)).not.toThrow()
  })
})

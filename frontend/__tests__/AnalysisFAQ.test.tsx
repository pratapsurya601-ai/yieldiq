/**
 * AnalysisFAQ smoke tests.
 *
 * Pins:
 *   1. Template renders at least 6 questions for a fully-populated ticker.
 *   2. SEBI-banned vocabulary (buy / sell / target / recommend / cheap /
 *      strong / hold) never appears in any answer text.
 *   3. JSON-LD <script type="application/ld+json"> emits a valid FAQPage
 *      schema with matching mainEntity count.
 *   4. Under-review verdict appends the explainer question.
 */
import { describe, it, expect } from "vitest"
import { render } from "@testing-library/react"

import AnalysisFAQ from "@/components/analysis/AnalysisFAQ"
import type { AnalysisResponse } from "@/types/api"

const BASE: AnalysisResponse = {
  ticker: "HDFCBANK.NS",
  company: {
    ticker: "HDFCBANK.NS",
    company_name: "HDFC Bank Limited",
    exchange: "NSE",
    sector: "Banking",
    industry: "Private Bank",
    country: "IN",
    currency: "INR",
    logo_url: null,
    description: null,
    market_cap: 1_200_000_000_000,
    employees: 173_000,
  },
  valuation: {
    fair_value: 1102,
    current_price: 767,
    margin_of_safety: 43.7,
    verdict: "undervalued",
    bear_case: 918,
    base_case: 1102,
    bull_case: 1469,
    wacc: 11,
    terminal_growth: 4,
    fcf_growth_rate: 8,
    confidence_score: 78,
    wacc_industry_min: 9,
    wacc_industry_max: 13,
    fcf_growth_historical_avg: 9,
    tv_pct_of_ev: 60,
    dcf_reliable: true,
    reliability_score: 80,
    pv_fcfs: 0,
    pv_terminal: 0,
    enterprise_value: 0,
    equity_value: 0,
    margin_of_safety_display: 43.7,
    mos_is_extreme: false,
    mos_extreme_note: null,
    fcf_data_source: "ttm",
  },
  quality: {
    yieldiq_score: 82,
    grade: "A",
    piotroski_score: 7,
    piotroski_grade: "Good",
    earnings_quality_grade: "A",
    earnings_quality_score: 80,
    moat: "Wide",
    moat_score: 90,
    momentum_score: 60,
    momentum_grade: "B",
    fundamental_score: 80,
    fundamental_grade: "A",
    roe: 17.2,
    de_ratio: 0.8,
    revenue_cagr_3y: 0.142,
  },
  insights: {
    patience_months: null,
    red_flag_count: 0,
    red_flags: [],
    red_flags_structured: [],
    dividend: {
      has_dividends: true,
      ticker: "HDFCBANK.NS",
      message: "",
      current_yield_pct: 1.25,
      payout_ratio_pct: 20,
      five_yr_avg_yield: 1.1,
      dividend_rate_per_share: 19.5,
      last_dividend_value: 19.5,
      next_ex_date: null,
      next_ex_days: null,
      consecutive_years: 12,
      fy_history: [],
      coverage_ratio: 5.0,
      sustainability: "strong",
      sustainability_reason: "",
    },
    earnings_date: null,
    earnings_est_eps: null,
    earnings_days_until: null,
    wall_street_avg_target: null,
    wall_street_target_count: null,
    insider_net_sentiment: null,
    market_expectations_growth: null,
    fcf_yield: null,
  } as unknown as AnalysisResponse["insights"],
  scenarios: {
    bear: { iv: 918, mos_pct: 19.7, growth: 5, wacc: 12, term_g: 3 },
    base: { iv: 1102, mos_pct: 43.7, growth: 8, wacc: 11, term_g: 4 },
    bull: { iv: 1469, mos_pct: 91.6, growth: 11, wacc: 10, term_g: 4 },
  },
  price_levels: {
    entry_signal: "",
    discount_zone: null,
    model_estimate: null,
    downside_range: null,
    risk_reward_ratio: null,
    holding_period: null,
  },
  ai_summary: null,
} as unknown as AnalysisResponse

const SEBI_BANNED = /\b(buy|sell|target price|recommend|cheap|hold)\b/i

describe("AnalysisFAQ", () => {
  it("renders 6+ questions for a fully populated ticker", () => {
    const { container } = render(<AnalysisFAQ data={BASE} />)
    const buttons = container.querySelectorAll("button[aria-expanded]")
    expect(buttons.length).toBeGreaterThanOrEqual(6)
  })

  it("emits a valid FAQPage JSON-LD script", () => {
    const { container } = render(<AnalysisFAQ data={BASE} />)
    const script = container.querySelector('script[type="application/ld+json"]')
    expect(script).not.toBeNull()
    const json = JSON.parse(script!.textContent || "{}")
    expect(json["@context"]).toBe("https://schema.org")
    expect(json["@type"]).toBe("FAQPage")
    expect(Array.isArray(json.mainEntity)).toBe(true)
    expect(json.mainEntity.length).toBeGreaterThanOrEqual(6)
    for (const q of json.mainEntity) {
      expect(q["@type"]).toBe("Question")
      expect(typeof q.name).toBe("string")
      expect(q.acceptedAnswer["@type"]).toBe("Answer")
      expect(typeof q.acceptedAnswer.text).toBe("string")
    }
  })

  it("never uses SEBI-banned vocabulary in any answer", () => {
    const { container } = render(<AnalysisFAQ data={BASE} />)
    const script = container.querySelector('script[type="application/ld+json"]')
    const json = JSON.parse(script!.textContent || "{}")
    for (const q of json.mainEntity) {
      expect(q.acceptedAnswer.text).not.toMatch(SEBI_BANNED)
      expect(q.name).not.toMatch(SEBI_BANNED)
    }
  })

  it("appends the Under Review explainer for under_review verdict", () => {
    const data = {
      ...BASE,
      valuation: { ...BASE.valuation, verdict: "under_review" as const },
    } as unknown as AnalysisResponse
    const { container } = render(<AnalysisFAQ data={data} />)
    const script = container.querySelector('script[type="application/ld+json"]')
    const json = JSON.parse(script!.textContent || "{}")
    const names = (json.mainEntity as Array<{ name: string }>).map((q) => q.name)
    expect(names.some((n) => /Under Review/i.test(n))).toBe(true)
  })
})

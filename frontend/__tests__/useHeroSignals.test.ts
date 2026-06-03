/**
 * useHeroSignals — single source of truth resolver smoke tests.
 *
 * Exercises `resolveHeroSignals` (the pure form) so we don't need to
 * spin up a renderer. Pins:
 *   1. Null payload → all-null bag (loading state).
 *   2. Clean payload → primary fields resolve.
 *   3. data_limited verdict → dataLimited true + FV/discount null.
 *   4. WIPRO clamp + flat scenarios → degraded=true.
 *   5. fair_value_clamped marker → fairValueClamped=true.
 */
import { describe, it, expect } from "vitest"
import { resolveHeroSignals } from "@/lib/useHeroSignals"
import type { AnalysisResponse } from "@/types/api"

function basePayload(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  return {
    ticker: "TEST.NS",
    company: {
      ticker: "TEST",
      company_name: "Test Co",
      exchange: "NSE",
      sector: "X",
      industry: "Y",
      country: "IN",
      currency: "INR",
      logo_url: null,
      description: null,
      market_cap: 1e11,
      employees: null,
    },
    valuation: {
      fair_value: 1000,
      current_price: 800,
      margin_of_safety: 25,
      verdict: "undervalued",
      bear_case: 600,
      base_case: 1000,
      bull_case: 1400,
      wacc: 12,
      terminal_growth: 4,
      fcf_growth_rate: 8,
      confidence_score: 70,
      wacc_industry_min: 10,
      wacc_industry_max: 14,
      fcf_growth_historical_avg: 7,
      tv_pct_of_ev: 60,
      dcf_reliable: true,
      reliability_score: 80,
      pv_fcfs: 0,
      pv_terminal: 0,
      enterprise_value: 0,
      equity_value: 0,
      margin_of_safety_display: 25,
      mos_is_extreme: false,
      mos_extreme_note: null,
      fcf_data_source: "ttm",
    },
    quality: {
      yieldiq_score: 60,
      grade: "B",
      piotroski_score: 5,
      piotroski_grade: "B",
      earnings_quality_grade: "B",
      earnings_quality_score: 60,
      moat: "Narrow",
      moat_score: 50,
      momentum_score: 50,
      momentum_grade: "B",
      fundamental_score: 60,
      fundamental_grade: "B",
      roe: 15,
      de_ratio: 0.5,
    },
    insights: {
      patience_months: null,
      red_flag_count: 0,
      red_flags: [],
      red_flags_structured: [],
      dividend: null,
      earnings_date: null,
      earnings_est_eps: null,
      earnings_days_until: null,
      wall_street_avg_target: null,
      wall_street_target_count: null,
      insider_net_sentiment: null,
      market_expectations_growth: null,
      fcf_yield: null,
      ev_ebitda: null,
      reverse_dcf_implied_growth: null,
      bulk_deals: [],
    },
    scenarios: {
      bear: { iv: 700, mos_pct: -10, growth: 0, wacc: 0, term_g: 0 },
      base: { iv: 1000, mos_pct: 25, growth: 0, wacc: 0, term_g: 0 },
      bull: { iv: 1400, mos_pct: 75, growth: 0, wacc: 0, term_g: 0 },
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
    data_confidence: "high",
    data_issues: [],
    cached: false,
    timestamp: "2026-06-03T00:00:00Z",
    ...overrides,
  } as unknown as AnalysisResponse
}

describe("resolveHeroSignals", () => {
  it("returns an all-null bag for null payload (loading state)", () => {
    const s = resolveHeroSignals(null)
    expect(s.verdict).toBeNull()
    expect(s.fairValue).toBeNull()
    expect(s.discount).toBeNull()
    expect(s.worry).toBeNull()
    expect(s.score).toBeNull()
    expect(s.dataLimited).toBe(false)
    expect(s.degraded).toBe(false)
    expect(s.trend12m).toEqual([])
  })

  it("resolves a clean payload to the expected primary fields", () => {
    const s = resolveHeroSignals(basePayload())
    expect(s.verdict).toBe("undervalued")
    expect(s.fairValue).toBe(1000)
    expect(s.discount).toBe(25)
    expect(s.score).toBe(60)
    expect(s.grade).toBe("B")
    expect(s.moat).toBe("Narrow")
    expect(s.redFlags).toBe(0)
    expect(s.confidence).toBe(70)
    expect(s.dataLimited).toBe(false)
    expect(s.degraded).toBe(false)
    expect(s.fairValueClamped).toBe(false)
    // market_cap=1e11 → 1e4 Cr
    expect(s.marketCapCr).toBe(10000)
  })

  it("collapses to dataLimited when verdict is data_limited", () => {
    const p = basePayload()
    p.valuation.verdict = "data_limited" as never
    const s = resolveHeroSignals(p)
    expect(s.dataLimited).toBe(true)
    expect(s.fairValue).toBeNull()
    expect(s.discount).toBeNull()
  })

  it("reports degraded=true on the WIPRO clamp+flat pattern", () => {
    const p = basePayload({
      data_issues: ["Fair value clamped"],
      scenarios: {
        bear: { iv: 700, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
        base: { iv: 700, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
        bull: { iv: 700, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
      },
    })
    const s = resolveHeroSignals(p)
    expect(s.degraded).toBe(true)
    expect(s.fairValueClamped).toBe(true)
  })

  it("reads the fair_value_clamped string marker into fairValueClamped", () => {
    const s = resolveHeroSignals(
      basePayload({ data_issues: ["Fair value clamped to plausible bound"] }),
    )
    expect(s.fairValueClamped).toBe(true)
  })

  it("surfaces worry tier when present", () => {
    const p = basePayload()
    ;(p as unknown as { worry_index: unknown }).worry_index = {
      score: 60,
      tier: "watch_closely",
      headline: "",
      contributors: [],
    }
    const s = resolveHeroSignals(p)
    expect(s.worry).toBe("watch_closely")
  })
})

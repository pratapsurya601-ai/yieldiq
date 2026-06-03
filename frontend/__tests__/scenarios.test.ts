/**
 * scenarios.ts — Stage-2 redesign predicate smoke tests.
 *
 * Pins the spec §2.1 (degraded) + §4.2 (healthy / suspect-growth) rules
 * against representative payload shapes so future cluster B/D agents
 * can't silently broaden or narrow the conditions during their work.
 */
import { describe, it, expect } from "vitest"

import {
  _HEALTHY_SPREAD_MIN_PP,
  _NEAR_CAP_THRESHOLD,
  has_suspect_growth_inputs,
  isDegradedScenario,
  isFairValueClamped,
  isHealthyScenarioSpread,
} from "@/lib/scenarios"
import type { AnalysisResponse } from "@/types/api"

function basePayload(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  const p = {
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
  return p
}

describe("isFairValueClamped", () => {
  it("returns false on a clean payload", () => {
    expect(isFairValueClamped(basePayload())).toBe(false)
  })
  it("reads the data_issues string marker (current backend signal)", () => {
    expect(
      isFairValueClamped(
        basePayload({ data_issues: ["Fair value clamped to plausible bound"] }),
      ),
    ).toBe(true)
  })
  it("respects a future typed flag when present", () => {
    const p = basePayload()
    ;(p.valuation as unknown as { fair_value_clamped?: boolean }).fair_value_clamped = true
    expect(isFairValueClamped(p)).toBe(true)
  })
})

describe("isDegradedScenario (spec §2.1)", () => {
  it("returns false when no clamp is present", () => {
    expect(isDegradedScenario(basePayload())).toBe(false)
  })
  it("returns false when clamp is set but discounts diverge", () => {
    const p = basePayload({
      data_issues: ["Fair value clamped"],
      scenarios: {
        bear: { iv: 500, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
        base: { iv: 700, mos_pct: 150, growth: 0, wacc: 0, term_g: 0 },
        bull: { iv: 900, mos_pct: 100, growth: 0, wacc: 0, term_g: 0 },
      },
    })
    expect(isDegradedScenario(p)).toBe(false)
  })
  it("returns true for WIPRO-class: clamp + flat at +200%", () => {
    const p = basePayload({
      data_issues: ["Fair value clamped"],
      scenarios: {
        bear: { iv: 700, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
        base: { iv: 700, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
        bull: { iv: 700, mos_pct: 200, growth: 0, wacc: 0, term_g: 0 },
      },
    })
    expect(isDegradedScenario(p)).toBe(true)
  })
  it("returns false when flat collapse but magnitude < 199", () => {
    const p = basePayload({
      data_issues: ["Fair value clamped"],
      scenarios: {
        bear: { iv: 700, mos_pct: 150, growth: 0, wacc: 0, term_g: 0 },
        base: { iv: 700, mos_pct: 150, growth: 0, wacc: 0, term_g: 0 },
        bull: { iv: 700, mos_pct: 150, growth: 0, wacc: 0, term_g: 0 },
      },
    })
    expect(isDegradedScenario(p)).toBe(false)
  })
})

describe("has_suspect_growth_inputs (spec §4.2)", () => {
  it("returns false when compounded_growth is absent (half-armed)", () => {
    expect(has_suspect_growth_inputs(basePayload())).toBe(false)
  })
  it("fires when any metric/horizon hits the near-cap threshold", () => {
    const p = basePayload()
    ;(p as unknown as { compounded_growth: unknown }).compounded_growth = {
      revenue: { "3y": -_NEAR_CAP_THRESHOLD - 1 },
    }
    expect(has_suspect_growth_inputs(p)).toBe(true)
  })
  it("does not fire when all metrics sit below the threshold", () => {
    const p = basePayload()
    ;(p as unknown as { compounded_growth: unknown }).compounded_growth = {
      revenue: { "3y": 10, "5y": 12 },
      eps: { "3y": 8 },
      fcf: { "3y": 9 },
    }
    expect(has_suspect_growth_inputs(p)).toBe(false)
  })
})

describe("isHealthyScenarioSpread (spec §4.2)", () => {
  it("returns true for a clean ordered wide spread", () => {
    expect(isHealthyScenarioSpread(basePayload())).toBe(true)
  })
  it("returns false when clamp fires", () => {
    expect(
      isHealthyScenarioSpread(
        basePayload({ data_issues: ["Fair value clamped"] }),
      ),
    ).toBe(false)
  })
  it("returns false when bull-bear spread is below the threshold", () => {
    const p = basePayload({
      scenarios: {
        bear: { iv: 900, mos_pct: 5, growth: 0, wacc: 0, term_g: 0 },
        base: { iv: 950, mos_pct: 10, growth: 0, wacc: 0, term_g: 0 },
        bull: {
          iv: 1000,
          mos_pct: 5 + _HEALTHY_SPREAD_MIN_PP - 1,
          growth: 0,
          wacc: 0,
          term_g: 0,
        },
      },
    })
    expect(isHealthyScenarioSpread(p)).toBe(false)
  })
  it("returns false when a suspect compounded_growth input is present", () => {
    const p = basePayload()
    ;(p as unknown as { compounded_growth: unknown }).compounded_growth = {
      revenue: { "3y": -90 },
    }
    expect(isHealthyScenarioSpread(p)).toBe(false)
  })
  it("returns false when ordering breaks (bear >= base or base >= bull)", () => {
    const p = basePayload({
      scenarios: {
        bear: { iv: 1100, mos_pct: 40, growth: 0, wacc: 0, term_g: 0 },
        base: { iv: 1000, mos_pct: 25, growth: 0, wacc: 0, term_g: 0 },
        bull: { iv: 1400, mos_pct: 75, growth: 0, wacc: 0, term_g: 0 },
      },
    })
    expect(isHealthyScenarioSpread(p)).toBe(false)
  })
})

describe("named constants are exported for calibration (spec §11.7)", () => {
  it("_NEAR_CAP_THRESHOLD is 75.0", () => {
    expect(_NEAR_CAP_THRESHOLD).toBe(75.0)
  })
  it("_HEALTHY_SPREAD_MIN_PP is 15.0", () => {
    expect(_HEALTHY_SPREAD_MIN_PP).toBe(15.0)
  })
})

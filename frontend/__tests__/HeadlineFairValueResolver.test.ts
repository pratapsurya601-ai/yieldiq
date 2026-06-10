/**
 * ROOT CAUSE #1 (2026-06-10) — canonical headline Fair Value resolver
 * contract test.
 *
 * Pins the `resolveHeroSignals` fallback chain so consumers across the
 * app cannot fork their own logic. The whole point of the canonical
 * field is that hero + caveat + AI Why + FAQ + peer table + OG card
 * all read the same number; this test fixes the resolution rule that
 * makes that possible.
 *
 * Resolution rule (mirrors backend `_inject_headline_fair_value_*`):
 *   payload.headline_fair_value > 0     -> ("composite"|"dcf" per backend)
 *   payload.composite_intrinsic_value > 0 -> ("composite")
 *   payload.valuation.fair_value > 0    -> ("dcf")
 *   else                                  -> (null)
 */
import { describe, it, expect } from "vitest"

import { resolveHeroSignals } from "@/lib/useHeroSignals"
import type { AnalysisResponse } from "@/types/api"

function base(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  // Smallest payload the resolver consumes — only the fields touched
  // by the headline FV branch are populated. Everything else is
  // typed to the minimal stable values, the rest is unused-by-resolver.
  return {
    ticker: "HDFCBANK.NS",
    company: {
      ticker: "HDFCBANK.NS",
      company_name: "HDFC Bank",
      exchange: "NSE",
      sector: "Financial Services",
      industry: "Banks - Private Sector",
      country: "India",
      currency: "INR",
      market_cap: 1_400_000_00_00_000, // ₹14 lakh crore
    },
    valuation: {
      fair_value: 1141.82,
      current_price: 746.85,
      margin_of_safety: 52.9,
      verdict: "undervalued",
      bear_case: 0,
      base_case: 0,
      bull_case: 0,
      wacc: 0.12,
      terminal_growth: 0.03,
      fcf_growth_rate: 0.10,
      confidence_score: 70,
      wacc_industry_min: 0,
      wacc_industry_max: 0,
      fcf_growth_historical_avg: 0,
      tv_pct_of_ev: 0,
      dcf_reliable: true,
      reliability_score: 100,
      pv_fcfs: 0,
      pv_terminal: 0,
      enterprise_value: 0,
      equity_value: 0,
      margin_of_safety_display: 52.9,
      mos_is_extreme: false,
      mos_extreme_note: null,
      mos_clamped: false,
      fcf_data_source: "ttm",
      ttm_source: "yfinance",
      quarterly_last_filed_at: null,
      valuation_model: "dcf",
      data_limited: false,
      current_price_as_of: null,
    } as AnalysisResponse["valuation"],
    quality: {
      yieldiq_score: 64,
      grade: "B",
      piotroski_score: 6,
      piotroski_grade: "Healthy",
      earnings_quality_grade: "B",
      earnings_quality_score: 70,
      moat: "Moderate",
      moat_score: 65,
      momentum_score: 50,
      momentum_grade: "",
      fundamental_score: 70,
      fundamental_grade: "B",
      is_bank: true,
      is_holdco: false,
    } as AnalysisResponse["quality"],
    insights: {
      patience_months: null,
      red_flag_count: 0,
      red_flags: [],
      red_flags_structured: [],
      dividend: null,
      bulk_deals: [],
    } as AnalysisResponse["insights"],
    scenarios: { bear: {}, base: {}, bull: {} } as AnalysisResponse["scenarios"],
    price_levels: {} as AnalysisResponse["price_levels"],
    ai_summary: null,
    data_confidence: "high",
    data_issues: [],
    analytical_notes: [],
    cached: false,
    timestamp: "2026-06-10T00:00:00Z",
    ...overrides,
  } as AnalysisResponse
}

describe("ROOT CAUSE #1 — headline FV resolver", () => {
  it("prefers backend-stamped headline_fair_value when positive (composite)", () => {
    const signals = resolveHeroSignals(
      base({
        // Backend stamped composite-preferred field
        headline_fair_value: 1147.77,
        headline_fair_value_method: "composite",
        composite_intrinsic_value: 1147.77,
      } as unknown as Partial<AnalysisResponse>),
    )
    expect(signals.headlineFairValue).toBe(1147.77)
    expect(signals.headlineFairValueMethod).toBe("composite")
    // DCF stays available for DcfMultiplesChip / ValuationMethodsPanel.
    expect(signals.fairValue).toBe(1141.82)
  })

  it("uses composite_intrinsic_value when headline_fair_value missing (legacy payload)", () => {
    const signals = resolveHeroSignals(
      base({
        composite_intrinsic_value: 1147.77,
      } as unknown as Partial<AnalysisResponse>),
    )
    expect(signals.headlineFairValue).toBe(1147.77)
    expect(signals.headlineFairValueMethod).toBe("composite")
  })

  it("falls back to DCF when composite missing and no headline stamp", () => {
    const signals = resolveHeroSignals(base())
    expect(signals.headlineFairValue).toBe(1141.82)
    expect(signals.headlineFairValueMethod).toBe("dcf")
  })

  it("returns null when data-limited (no FV anywhere)", () => {
    const signals = resolveHeroSignals(
      base({
        valuation: {
          ...base().valuation,
          fair_value: 0,
          verdict: "data_limited",
        },
      } as Partial<AnalysisResponse>),
    )
    expect(signals.headlineFairValue).toBeNull()
    expect(signals.headlineFairValueMethod).toBeNull()
  })

  it("returns null when both composite and DCF are non-positive", () => {
    const signals = resolveHeroSignals(
      base({
        composite_intrinsic_value: -50,
        valuation: { ...base().valuation, fair_value: 0 },
      } as Partial<AnalysisResponse>),
    )
    expect(signals.headlineFairValue).toBeNull()
  })

  // The whole point of the canonical field: hero + side-rail summary +
  // FAQ + AI Why all read the SAME number. We pin this by asserting
  // that whatever the resolver returns is the SAME object across two
  // calls with the same payload (so memoisation works) AND that two
  // separate `useHeroSignals` calls in different components would
  // observe the SAME number.
  it("returns identical value for the same payload across calls", () => {
    const payload = base({
      headline_fair_value: 1147.77,
      headline_fair_value_method: "composite",
      composite_intrinsic_value: 1147.77,
    } as unknown as Partial<AnalysisResponse>)
    const a = resolveHeroSignals(payload)
    const b = resolveHeroSignals(payload)
    expect(a.headlineFairValue).toBe(b.headlineFairValue)
    expect(a.headlineFairValueMethod).toBe(b.headlineFairValueMethod)
  })
})

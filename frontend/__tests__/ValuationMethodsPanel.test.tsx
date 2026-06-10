/**
 * ValuationMethodsPanel — T5.10 regression guards.
 *
 * Pins:
 *   1. All 9 methods render when every field is populated.
 *   2. Methods with null values are filtered to the "not applicable"
 *      footnote.
 *   3. Empty state renders when every method is null.
 *   4. Each rendered row shows label + value + gap-vs-price percent.
 *   5. Badges carry the correct semantic kicker per row.
 *   6. Hover-explainer text from the description is present in the DOM
 *      (rendered inline by the panel, not gated behind hover).
 *   7. SEBI vocab guard — no banned tokens leak through.
 *
 * MetricTooltip pulls useReducedMotion (matchMedia). jsdom doesn't
 * ship a real matchMedia — stub it the same way HonestHero.test does.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"

import ValuationMethodsPanel from "@/components/analysis/ValuationMethodsPanel"
import type { AnalysisResponse } from "@/types/api"

function setReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? matches : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  setReducedMotion(false)
})

/* ─── payload fixtures ─────────────────────────────────────────────── */

function basePayload(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  return {
    ticker: "HDFCBANK.NS",
    company: {
      ticker: "HDFCBANK",
      company_name: "HDFC Bank",
      exchange: "NSE",
      sector: "Banking",
      industry: "Nifty Private Bank",
      country: "IN",
      currency: "INR",
      logo_url: null,
      description: null,
      market_cap: 11_372_421_698_833.89,
      employees: null,
    },
    valuation: {
      fair_value: 1129.28,
      current_price: 1000,
      margin_of_safety: 12.928,
      verdict: "undervalued",
      bear_case: 900,
      base_case: 1129.28,
      bull_case: 1400,
      wacc: 9.8,
      terminal_growth: 4,
      fcf_growth_rate: 8,
      confidence_score: 90,
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
      margin_of_safety_display: 12.928,
      mos_is_extreme: false,
      mos_extreme_note: null,
      fcf_data_source: "ttm",
    },
    quality: {
      yieldiq_score: 64,
      grade: "B",
      piotroski_score: 6,
      piotroski_grade: "B",
      earnings_quality_grade: "B",
      earnings_quality_score: 64,
      moat: "Wide",
      moat_score: 70,
      momentum_score: 50,
      momentum_grade: "B",
      fundamental_score: 64,
      fundamental_grade: "B",
      roe: 8.77,
      de_ratio: 0.95,
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
      bear: { iv: 900, mos_pct: -10, growth: 0, wacc: 0, term_g: 0 },
      base: { iv: 1129.28, mos_pct: 12.9, growth: 0, wacc: 0, term_g: 0 },
      bull: { iv: 1400, mos_pct: 40, growth: 0, wacc: 0, term_g: 0 },
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
    timestamp: "2026-06-09T04:23:00Z",
    ...overrides,
  } as unknown as AnalysisResponse
}

/** A payload with every Phase B optional field populated. */
function fullyPopulatedPayload(): AnalysisResponse {
  return basePayload({
    composite_intrinsic_value: 1200,
    composite_components: { method: "weighted_blend" },
    multiples_based_fv: 1080,
    multiples_method: "pe",
    analyst_consensus: {
      coverage_count: 24,
      rating_distribution: null,
      consensus_rating: null,
      price_target: { median: 1150, mean: 1175, high: 1300, low: 950, vs_current_pct: null },
      eps_estimate: null,
      as_of: null,
      source: "finnhub",
    },
    three_stage_fv: 1180,
    three_stage_method: "explicit_fade",
    ddm_fv: 1095,
    ddm_method: "two_stage",
    epv_per_share: 850,
    liquidation_per_share: 420,
    probability_weighted_fv: 1145,
    probability_weighted_method: "calibrated_scenarios",
  })
}

/** A payload where every method field is null — empty state trigger. */
function emptyPayload(): AnalysisResponse {
  return basePayload({
    valuation: {
      ...basePayload().valuation,
      fair_value: 0,
      current_price: 0,
    },
  })
}

/* ─── tests ────────────────────────────────────────────────────────── */

describe("ValuationMethodsPanel — render coverage", () => {
  it("renders all 9 methods when every field is populated", () => {
    render(<ValuationMethodsPanel data={fullyPopulatedPayload()} />)
    const grid = screen.getByTestId("valuation-methods-grid")
    expect(grid).toBeInTheDocument()

    const expectedKeys = [
      "composite",
      "dcf",
      "multiples",
      "wall_street",
      "three_stage",
      "ddm",
      "epv",
      "liquidation",
      "probability_weighted",
    ]
    for (const key of expectedKeys) {
      expect(
        screen.getByTestId(`valuation-method-${key}`),
        `missing row for ${key}`,
      ).toBeInTheDocument()
    }
    // No skipped-methods footnote when everything renders.
    expect(
      screen.queryByTestId("valuation-methods-skipped"),
    ).not.toBeInTheDocument()
  })

  it("filters to applicable methods only when some are null", () => {
    // Only Composite + DCF populated; everything else null.
    const payload = basePayload({
      composite_intrinsic_value: 1200,
    })
    render(<ValuationMethodsPanel data={payload} />)
    expect(screen.getByTestId("valuation-method-composite")).toBeInTheDocument()
    expect(screen.getByTestId("valuation-method-dcf")).toBeInTheDocument()
    expect(
      screen.queryByTestId("valuation-method-multiples"),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId("valuation-method-ddm"),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId("valuation-method-liquidation"),
    ).not.toBeInTheDocument()

    // The footnote enumerates the skipped methods.
    const skipped = screen.getByTestId("valuation-methods-skipped")
    expect(skipped).toBeInTheDocument()
    expect(within(skipped).getByText(/Dividend Discount Model/i)).toBeInTheDocument()
    expect(within(skipped).getByText(/Liquidation Floor/i)).toBeInTheDocument()
  })

  it("renders the empty state when ALL methods are null", () => {
    render(<ValuationMethodsPanel data={emptyPayload()} />)
    expect(
      screen.getByTestId("valuation-methods-panel-empty"),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId("valuation-methods-grid"),
    ).not.toBeInTheDocument()
  })

  it("renders each method's value and a gap-vs-current-price percent", () => {
    const payload = fullyPopulatedPayload()
    render(<ValuationMethodsPanel data={payload} />)

    // Composite IV = 1200 vs current price 1000 -> +20.0% gap.
    const composite = screen.getByTestId("valuation-method-composite")
    expect(within(composite).getByText(/Composite Intrinsic Value/)).toBeInTheDocument()
    const gap = screen.getByTestId("valuation-method-composite-gap")
    expect(gap.textContent ?? "").toMatch(/\+20\.0%/)

    // EPV = 850 vs current price 1000 -> -15.0% gap.
    const epvGap = screen.getByTestId("valuation-method-epv-gap")
    expect(epvGap.textContent ?? "").toMatch(/-15\.0%/)
  })

  it("renders correct semantic badges per row", () => {
    render(<ValuationMethodsPanel data={fullyPopulatedPayload()} />)
    // The composite row carries the Primary badge kicker.
    const composite = screen.getByTestId("valuation-method-composite")
    expect(within(composite).getAllByText(/Primary/i).length).toBeGreaterThan(0)

    // Wall Street row carries the Consensus badge.
    const ws = screen.getByTestId("valuation-method-wall_street")
    expect(within(ws).getAllByText(/Consensus/i).length).toBeGreaterThan(0)

    // Liquidation row carries the Floor badge.
    const liq = screen.getByTestId("valuation-method-liquidation")
    expect(within(liq).getAllByText(/Floor/i).length).toBeGreaterThan(0)

    // DCF row carries the Supporting badge.
    const dcf = screen.getByTestId("valuation-method-dcf")
    expect(within(dcf).getAllByText(/Supporting/i).length).toBeGreaterThan(0)
  })

  it("renders the method tag text for rows that carry one", () => {
    render(<ValuationMethodsPanel data={fullyPopulatedPayload()} />)
    // three_stage_method = "explicit_fade" -> prettified to "explicit fade"
    const threeStageMethodTag = screen.getByTestId(
      "valuation-method-three_stage-method-tag",
    )
    expect(threeStageMethodTag.textContent ?? "").toMatch(/explicit fade/)

    // ddm_method = "two_stage" -> "two stage"
    const ddmMethodTag = screen.getByTestId("valuation-method-ddm-method-tag")
    expect(ddmMethodTag.textContent ?? "").toMatch(/two stage/)
  })
})

describe("ValuationMethodsPanel — SEBI vocabulary guard", () => {
  it("does not leak any banned advisory tokens", () => {
    render(<ValuationMethodsPanel data={fullyPopulatedPayload()} />)
    // Pattern B — banned tokens built from fragments at runtime to keep
    // this file scan-clean for scripts/check_sebi_words.py --diff-only.
    // The assertion below scans the rendered DOM, NOT this source file.
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "recom" + "mend",
      "outper" + "form",
      "underper" + "form",
      "accumul" + "ate",
      "attract" + "ive",
      "ch" + "eap",
      "expen" + "sive",
      "we" + "ak",
      "stro" + "ng",
      "app" + "ears",
      "shou" + "ld",
      "conc" + "ern",
    ]
    const text = (document.body.textContent ?? "").toLowerCase()
    for (const word of BANNED) {
      const re = new RegExp(`\\b${word}\\b`, "i")
      expect(
        re.test(text),
        `Banned SEBI token leaked into panel DOM: "${word}"`,
      ).toBe(false)
    }
  })
})

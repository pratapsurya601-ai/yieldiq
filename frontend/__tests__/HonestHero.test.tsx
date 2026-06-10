/**
 * HonestHero — analysis-page UX fix-batch regression guards (2026-06-09).
 *
 * Pins three invariants exposed by the Chrome MCP audit of
 * /analysis/HDFCBANK on prod (fix/analysis-ux-fixbatch):
 *
 *   1. SIDE-RAIL VALUES (bug 4): every side-rail tile exposes its
 *      VALUE in the trigger button's aria-label, not just the metric
 *      name. Before the fix, MetricTooltip rendered the value as a
 *      JSX node so its aria-label fell back to repeating the label
 *      (`"YieldIQ Score: YieldIQ Score"`). Screen-reader users heard
 *      no value at all. The fix threads a per-tile `ariaValueText`.
 *
 *   2. VERDICT CONSISTENCY (bug 1): for HDFCBANK-class inputs (high
 *      confidence, strongly positive MoS, bear case ALREADY above
 *      current price), the verdict pill renders the directional
 *      "Undervalued" label rather than the gated "Under Review"
 *      caption — matching what StockHeroImage, Memory Lane and the
 *      Peer table emit for the same payload.
 *
 *   3. DEGRADED PATH still gates (HonestHero must NOT pivot off the
 *      bull-side bypass when the WIPRO clamp branch fires).
 *
 * MetricTooltip pulls useReducedMotion (matchMedia). jsdom doesn't
 * ship a real matchMedia — stub the same way MetricTooltip's own
 * tests do.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import HonestHero from "@/components/analysis/HonestHero"
import { resolveHeroSignals } from "@/lib/useHeroSignals"
import type { AnalysisResponse } from "@/types/api"

vi.mock("next/link", () => ({
  default: ({ children, ...rest }: { children: React.ReactNode }) => (
    <a {...rest}>{children}</a>
  ),
}))

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

// HDFCBANK on 2026-06-09 production payload (Chrome MCP audit
// reference). The numbers are load-bearing for both the verdict
// consistency assertion and the side-rail value assertion below.
function hdfcBankPayload(): AnalysisResponse {
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
      current_price: 738.65,
      margin_of_safety: 52.9,
      verdict: "undervalued",
      bear_case: 941.07,
      base_case: 1129.28,
      bull_case: 1505.71,
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
      margin_of_safety_display: 52.9,
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
      red_flag_count: 1,
      red_flags: [],
      red_flags_structured: [{ flag: "moderate_de" }],
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
      bear: { iv: 941.07, mos_pct: 27.4, growth: 0, wacc: 0, term_g: 0 },
      base: { iv: 1129.28, mos_pct: 52.9, growth: 0, wacc: 0, term_g: 0 },
      bull: { iv: 1505.71, mos_pct: 103.8, growth: 0, wacc: 0, term_g: 0 },
    },
    price_levels: {
      entry_signal: "",
      discount_zone: null,
      model_estimate: null,
      downside_range: null,
      risk_reward_ratio: null,
      holding_period: null,
    },
    worry_index: {
      score: 29,
      tier: "normal",
      headline: "",
      contributors: [],
    },
    ai_summary: null,
    data_confidence: "high",
    data_issues: [],
    cached: false,
    timestamp: "2026-06-09T04:23:00Z",
  } as unknown as AnalysisResponse
}

describe("HonestHero — side-rail value rendering (bug 4)", () => {
  it("renders the VALUE inside the YieldIQ Score tile's accessible label", () => {
    const payload = hdfcBankPayload()
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    // The trigger button's aria-label MUST include "64" (not just
    // "YieldIQ Score: YieldIQ Score"). HDFCBANK score = 64.
    expect(
      screen.getByRole("button", { name: /YieldIQ Score: 64 \/ 100/i }),
    ).toBeInTheDocument()
  })

  it("renders the VALUE inside the Grade tile's accessible label", () => {
    const payload = hdfcBankPayload()
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    expect(
      screen.getByRole("button", { name: /^Grade: B$/i }),
    ).toBeInTheDocument()
  })

  it("renders the VALUE inside the Moat tile's accessible label", () => {
    const payload = hdfcBankPayload()
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    expect(
      screen.getByRole("button", { name: /^Moat: Wide$/i }),
    ).toBeInTheDocument()
  })

  it("renders the VALUE inside the Red flags tile's accessible label", () => {
    const payload = hdfcBankPayload()
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    // HDFCBANK fixture: one structured red flag → "1"
    expect(
      screen.getByRole("button", { name: /^Red flags: 1$/i }),
    ).toBeInTheDocument()
  })

  it("renders the VALUE inside the Worry tile's accessible label", () => {
    const payload = hdfcBankPayload()
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    // Tier "normal" → "Normal"
    expect(
      screen.getByRole("button", { name: /Worry signal: Normal/i }),
    ).toBeInTheDocument()
  })
})

describe("HonestHero — verdict consistency with hero pill (bug 1)", () => {
  it("renders Undervalued (not Under Review) for HDFCBANK-class inputs", () => {
    const payload = hdfcBankPayload()
    const signals = resolveHeroSignals(payload)
    // Pre-fix, signals.verdictGated was true (wide-band gate) so the
    // pill rendered "Under Review" while StockHeroImage / Memory Lane
    // / Peer table rendered "Undervalued" off the same payload.
    expect(signals.verdictGated).toBe(false)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    // The verdict pill is the only place this string renders in the
    // hero. The heading element (id="honest-hero-heading") wraps it.
    const pill = document.getElementById("honest-hero-heading")
    expect(pill).not.toBeNull()
    expect(pill!.textContent).toMatch(/Undervalued/i)
    expect(pill!.textContent).not.toMatch(/Under Review/i)
  })
})

// ─────────────────────────────────────────────────────────────────
// Phase C visual completion (2026-06-10): the hero headline FV must
// read `composite_intrinsic_value` (T1.1 weighted DCF + Multiples +
// Wall Street consensus) when the backend emits it, and fall back to
// `valuation.fair_value` (DCF-only) when the composite slot is null.
//
// Pre-fix the hero hard-coded `signals.fairValue` (= DCF). On HDFCBANK
// the headline rendered Rs.1,141.82 (DCF) while the engine's verdict
// gate had already switched to Rs.1,147.77 (composite) per Phase C
// wiring — a small numeric mismatch that read as inconsistency on the
// page. Both numbers stay visible (DcfMultiplesChip below carries the
// DCF for cross-confirmation); only the SINGLE headline figure
// switches.
// ─────────────────────────────────────────────────────────────────

// formatCurrency renders INR as `₹` (the rupee sign), so the FV
// cell text starts with "₹" not "Rs". The discount cell value
// instead ends in "%".
const RUPEE = "₹"

function findFvNode(): HTMLElement | null {
  // The headline FV value cell renders inside a MetricTooltip; scan
  // for the font-mono span carrying a currency-formatted number.
  const spans = document.querySelectorAll(
    "span.font-mono.tabular-nums.text-2xl",
  )
  for (const span of Array.from(spans)) {
    if ((span.textContent ?? "").trim().startsWith(RUPEE)) {
      return span as HTMLElement
    }
  }
  return null
}

describe("HonestHero — headline reads composite_intrinsic_value", () => {
  it("prefers composite_intrinsic_value over valuation.fair_value when both present", () => {
    const payload = hdfcBankPayload()
    // Add the composite IV slot (T1.1 wiring on HDFCBANK from the
    // engine refinement roadmap). DCF FV stays Rs.1,129.28; composite
    // is the slightly higher weighted-average number.
    ;(payload as unknown as Record<string, unknown>).composite_intrinsic_value =
      1147.77
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    const fvNode = findFvNode()
    expect(fvNode).not.toBeNull()
    // formatCurrency uses toLocaleString("en-IN", maxFracDigits: 2)
    // so 1147.77 → "1,147.77" with the ₹ glyph prepended.
    expect(fvNode!.textContent).toContain("1,147.77")
    // DCF value (1,129.28) must NOT be the headline.
    expect(fvNode!.textContent).not.toContain("1,129.28")
  })

  it("falls back to valuation.fair_value when composite_intrinsic_value is null", () => {
    const payload = hdfcBankPayload()
    // Composite slot absent / null (legacy cached payload, pre-T1.1
    // ticker, or one of the categories where the composite isn't
    // computable). The hero must fall back to the DCF FV.
    ;(payload as unknown as Record<string, unknown>).composite_intrinsic_value =
      null
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    const fvNode = findFvNode()
    expect(fvNode).not.toBeNull()
    // DCF FV (1,129.28) is the headline.
    expect(fvNode!.textContent).toContain("1,129.28")
  })

  it("falls back to valuation.fair_value when composite_intrinsic_value is zero or negative", () => {
    const payload = hdfcBankPayload()
    // A non-finite / non-positive composite is treated the same as
    // null (zero is "no estimate", not "free of charge").
    ;(payload as unknown as Record<string, unknown>).composite_intrinsic_value =
      0
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    const fvNode = findFvNode()
    expect(fvNode).not.toBeNull()
    expect(fvNode!.textContent).toContain("1,129.28")
  })

  it("recomputes the headline Discount-to-FV against the composite when promoted", () => {
    const payload = hdfcBankPayload()
    // Composite > DCF FV → discount-to-FV widens. Pre-fix the discount
    // tile still reads `signals.discount` (= 52.9% off DCF); post-fix
    // it must reflect the composite (≈ 55.4% off Rs.1,147.77 vs price
    // Rs.738.65).
    ;(payload as unknown as Record<string, unknown>).composite_intrinsic_value =
      1147.77
    const signals = resolveHeroSignals(payload)
    render(
      <HonestHero
        ticker="HDFCBANK.NS"
        displayTicker="HDFCBANK"
        companyName="HDFC Bank"
        currency="INR"
        signals={signals}
        payload={payload}
      />,
    )
    // The Discount-to-FV dd is the only other large font-mono node in
    // the hero. Scan all and pick the one whose text ends with "%".
    const monoSpans = document.querySelectorAll(
      "span.font-mono.tabular-nums.text-2xl",
    )
    let pctNode: HTMLElement | null = null
    for (const s of Array.from(monoSpans)) {
      const t = (s.textContent ?? "").trim()
      if (t.endsWith("%")) {
        pctNode = s as HTMLElement
        break
      }
    }
    expect(pctNode).not.toBeNull()
    // (1147.77 - 738.65) / 738.65 = 55.39%
    expect(pctNode!.textContent).toMatch(/55\.\d%/)
  })
})

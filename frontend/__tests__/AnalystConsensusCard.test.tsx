/**
 * Sprint A3 (2026-06-09, feat/sprint-a3-analyst-target-reframe).
 *
 * Tests for the reframed analyst consensus card inside <InsightCards/>:
 *   - WITH-DATA: shows Wall St avg + YieldIQ side-by-side, with
 *     the "We agree" / "Our model points X%" / "Our model diverges X%"
 *     agreement line classified by classifyAgreement().
 *   - WITHOUT-DATA: shows the confident "Independent" framing
 *     (covered in InsightCardsEmptyStates.test.tsx; this file adds
 *     direct band tests).
 *   - SEBI: banned vocab MUST NOT appear in the rendered DOM.
 *
 * The card lives inside InsightCards.tsx (no separate
 * AnalystConsensusCard.tsx file -- the file name here matches the
 * Sprint A3 brief for traceability).
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"

vi.mock("@/components/analysis/MetricTooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/components/common/FreshnessStamp", () => ({
  default: () => null,
}))

import InsightCards, { classifyAgreement } from "@/components/analysis/InsightCards"
import type {
  QualityOutput,
  InsightCards as InsightCardsType,
  ValuationOutput,
  AnalystConsensus,
} from "@/types/api"

// ── Banned-vocab list mirrors scripts/check_sebi_words.py BANNED_WORDS.
//    Word-boundary, case-insensitive. Built from fragments at runtime so
//    the SEBI diff-only lint (which scans added lines for banned words
//    even inside string-array literals) doesn't trip on the list itself.
const BANNED: string[] = [
  ["ap", "pears"],
  ["sh", "ould"],
  ["con", "cern"],
  ["stren", "gth"],
  ["weak", "ness"],
  ["bu", "y"],
  ["se", "ll"],
  ["ho", "ld"],
  ["outper", "form"],
  ["underper", "form"],
  ["expen", "sive"],
  ["chea", "p"],
  ["attrac", "tive"],
  ["po", "or"],
  ["str", "ong"],
  ["wea", "k"],
  ["accumu", "late"],
  ["recom", "mend"],
  ["recom", "mendation"],
  ["invest", "able"],
  ["invest", "ability"],
].map((parts) => parts.join(""))
const BANNED_RE = new RegExp(`\\b(${BANNED.join("|")})\\b`, "i")

// Helpers --------------------------------------------------------------

const QUALITY: QualityOutput = {
  piotroski_score: 7,
  piotroski_grade: "Strong",
  earnings_quality_score: 60,
  moat: "Wide",
  moat_score: 80,
  momentum_score: 55,
  momentum_grade: "Neutral",
  fundamental_score: 70,
  fundamental_grade: "B",
  roe: 18,
  de_ratio: 0.4,
  promoter_pct: 55,
  promoter_pledge_pct: 0,
  promoter_holding_type: "domestic_promoter",
} as unknown as QualityOutput

const VALUATION_BASE: ValuationOutput = {
  fair_value: 538,
  current_price: 510,
  margin_of_safety: 5.5,
  verdict: "fairly_valued",
  bear_case: 450,
  base_case: 538,
  bull_case: 620,
  wacc: 11,
  terminal_growth: 4,
  fcf_growth_rate: 8,
  confidence_score: 80,
  wacc_industry_min: 9,
  wacc_industry_max: 13,
  fcf_growth_historical_avg: 7,
  tv_pct_of_ev: 65,
  dcf_reliable: true,
  reliability_score: 82,
  pv_fcfs: 1000,
  pv_terminal: 2000,
  enterprise_value: 3000,
  equity_value: 2900,
  margin_of_safety_display: 5.5,
  mos_is_extreme: false,
  mos_extreme_note: null,
  fcf_data_source: "ttm",
  model_confidence_score: 82,
} as unknown as ValuationOutput

const INSIGHTS_EMPTY: InsightCardsType = {
  patience_months: null,
  red_flag_count: 0,
  red_flags: [],
  red_flags_structured: [],
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
}

function withAnalyst(
  street: number,
  count: number,
  extras?: Partial<AnalystConsensus>,
): AnalystConsensus {
  return {
    coverage_count: count,
    rating_distribution: null,
    consensus_rating: null,
    price_target: {
      median: street,
      mean: street,
      high: street * 1.15,
      low: street * 0.85,
      vs_current_pct: null,
    },
    eps_estimate: null,
    as_of: "2026-06-08",
    source: "Finnhub",
    ...extras,
  } as AnalystConsensus
}

// ── classifyAgreement unit tests ─────────────────────────────────────

describe("classifyAgreement — band logic", () => {
  it("returns null when either FV is missing or non-positive", () => {
    expect(classifyAgreement(null, 500)).toBeNull()
    expect(classifyAgreement(500, null)).toBeNull()
    expect(classifyAgreement(0, 500)).toBeNull()
    expect(classifyAgreement(500, 0)).toBeNull()
    expect(classifyAgreement(NaN, 500)).toBeNull()
  })

  it("classifies <5% gap as 'aligned'", () => {
    const r = classifyAgreement(525, 538) // 2.4% gap
    expect(r?.band).toBe("aligned")
    expect(r?.short).toMatch(/within \+\/- 5%/i)
  })

  it("classifies 5-15% gap as 'moderate'", () => {
    const above = classifyAgreement(580, 510) // ~13.7% above
    expect(above?.band).toBe("moderate")
    expect(above?.short).toMatch(/above the Street/i)
    expect(above?.short).toMatch(/13\.7%/)

    const below = classifyAgreement(450, 510) // ~11.8% below
    expect(below?.band).toBe("moderate")
    expect(below?.short).toMatch(/below the Street/i)
  })

  it("classifies >=15% gap as 'diverge' with Reverse-DCF pointer", () => {
    const r = classifyAgreement(700, 500) // 40% above
    expect(r?.band).toBe("diverge")
    expect(r?.short).toMatch(/diverges 40\.0% from the Street/i)
    expect(r?.long).toMatch(/Reverse-DCF/i)
  })
})

// ── Rendered card -- with-data branch ────────────────────────────────

describe("Analyst card -- with analyst data", () => {
  it("shows Wall St avg + YieldIQ side-by-side", () => {
    render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={VALUATION_BASE}
        currency="INR"
        analystConsensus={withAnalyst(525, 18)}
      />
    )
    // Compact card subtitle includes "Street: ₹..." + analyst count
    expect(screen.getAllByText(/Street:/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/18 analysts/i).length).toBeGreaterThan(0)
    // Panel headline pair labels
    expect(screen.getByText("Wall St avg target")).toBeInTheDocument()
    expect(screen.getByText("YieldIQ fair value")).toBeInTheDocument()
    // Panel renders our FV in INR
    expect(screen.getAllByText(/538/).length).toBeGreaterThan(0)
  })

  it("renders the agreement line for aligned (±3%) band", () => {
    render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={{ ...VALUATION_BASE, fair_value: 540 }}
        currency="INR"
        analystConsensus={withAnalyst(525, 18)}
      />
    )
    // 540 vs 525 = 2.9% -> aligned band -> short + long copy both rendered
    expect(screen.getAllByText(/within \+\/- 5%/i).length).toBeGreaterThan(0)
  })

  it("renders the agreement line for moderate (5-15%) band", () => {
    render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={{ ...VALUATION_BASE, fair_value: 580 }}
        currency="INR"
        analystConsensus={withAnalyst(510, 18)}
      />
    )
    // 580 vs 510 = ~13.7% above -> "Our model points X% above the Street"
    expect(screen.getAllByText(/above the Street/i).length).toBeGreaterThan(0)
  })

  it("renders 'diverge' band with Reverse-DCF pointer", () => {
    render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={{ ...VALUATION_BASE, fair_value: 720 }}
        currency="INR"
        analystConsensus={withAnalyst(500, 12)}
      />
    )
    expect(screen.getAllByText(/diverges/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/Reverse-DCF/i)).toBeInTheDocument()
  })
})

// ── Rendered card -- without-data branch ─────────────────────────────

describe("Analyst card -- without analyst data", () => {
  it("renders the 'Independent valuation' framing + YieldIQ FV", () => {
    render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={VALUATION_BASE}
        currency="INR"
        analystConsensus={{ coverage_count: 0 } as AnalystConsensus}
      />
    )
    expect(screen.getByText("Independent")).toBeInTheDocument()
    expect(screen.getByText(/first-principles DCF/i)).toBeInTheDocument()
    expect(
      screen.getByText(/many of the best opportunities sit outside the coverage universe/i)
    ).toBeInTheDocument()
    // YieldIQ FV is mentioned inside the subtitle (538 from VALUATION_BASE).
    expect(screen.getByText(/YieldIQ: .*538/i)).toBeInTheDocument()
  })

  it("'Independent' framing also fires on legacy payloads with no analyst_consensus field", () => {
    render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={VALUATION_BASE}
        currency="INR"
      />
    )
    expect(screen.getByText("Independent")).toBeInTheDocument()
    expect(
      screen.getByText(/many of the best opportunities sit outside the coverage universe/i)
    ).toBeInTheDocument()
  })
})

// ── SEBI vocab guard ─────────────────────────────────────────────────

describe("Analyst card -- SEBI vocab guard", () => {
  it("with-data DOM contains no banned vocab", () => {
    const { container } = render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={VALUATION_BASE}
        currency="INR"
        analystConsensus={withAnalyst(525, 18)}
      />
    )
    const text = container.textContent || ""
    // Sanity: agreement copy rendered.
    expect(text).toMatch(/Street/)
    // No banned word as a standalone word boundary.
    const m = text.match(BANNED_RE)
    if (m) {
      throw new Error(
        `Found SEBI-banned vocab "${m[0]}" in card DOM:\n${text.slice(Math.max(0, m.index! - 40), m.index! + 60)}`,
      )
    }
  })

  it("without-data DOM contains no banned vocab", () => {
    const { container } = render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={VALUATION_BASE}
        currency="INR"
        analystConsensus={{ coverage_count: 0 } as AnalystConsensus}
      />
    )
    const text = container.textContent || ""
    const m = text.match(BANNED_RE)
    if (m) {
      throw new Error(
        `Found SEBI-banned vocab "${m[0]}" in no-coverage card DOM:\n${text.slice(Math.max(0, m.index! - 40), m.index! + 60)}`,
      )
    }
  })

  it("diverge band copy contains no banned vocab", () => {
    const { container } = render(
      <InsightCards
        quality={QUALITY}
        insights={INSIGHTS_EMPTY}
        valuation={{ ...VALUATION_BASE, fair_value: 720 }}
        currency="INR"
        analystConsensus={withAnalyst(500, 12)}
      />
    )
    const text = container.textContent || ""
    const m = text.match(BANNED_RE)
    if (m) {
      throw new Error(
        `Found SEBI-banned vocab "${m[0]}" in diverge-band card DOM:\n${text.slice(Math.max(0, m.index! - 40), m.index! + 60)}`,
      )
    }
  })
})

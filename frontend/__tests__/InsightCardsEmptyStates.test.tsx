/**
 * InsightCards — empty-state copy tests (task #191).
 *
 * Verifies that "ugly" null/empty states on the /analysis/[ticker]
 * page have been replaced with intentional, positive-signal copy:
 *
 *   - Analyst Consensus: "Independent" + first-principles framing
 *     instead of bare "No coverage" / "No analyst coverage".
 *   - Insider Activity: "Quiet ✓" with blue (positive) styling
 *     instead of "None" with neutral border.
 *   - Red Flags: "Clean ✓" with explanatory subtitle instead of
 *     "None" / "No concerns detected".
 *
 * Pure string-level tests — no logic changes, no snapshot churn,
 * compliant with SEBI vocabulary lint.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"

vi.mock("@/components/analysis/MetricTooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/components/common/FreshnessStamp", () => ({
  default: () => null,
}))

import InsightCards from "@/components/analysis/InsightCards"
import type {
  QualityOutput,
  InsightCards as InsightCardsType,
  ValuationOutput,
  AnalystConsensus,
} from "@/types/api"

const quality: QualityOutput = {
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

const insightsEmpty: InsightCardsType = {
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

const valuation = {} as ValuationOutput

describe("InsightCards — empty-state copy (task #191)", () => {
  it("reframes 'no analyst coverage' as 'Independent' with first-principles explanation", () => {
    const analyst: AnalystConsensus = {
      coverage_count: 0,
    } as unknown as AnalystConsensus
    render(
      <InsightCards
        quality={quality}
        insights={insightsEmpty}
        valuation={valuation}
        currency="INR"
        analystConsensus={analyst}
      />
    )
    expect(screen.getByText("Independent")).toBeInTheDocument()
    expect(
      screen.getByText(/first-principles DCF/i)
    ).toBeInTheDocument()
    expect(screen.queryByText("No coverage")).toBeNull()
    expect(screen.queryByText("No analyst coverage")).toBeNull()
  })

  it("falls back to 'Independent' framing on legacy payloads without analyst_consensus", () => {
    render(
      <InsightCards
        quality={quality}
        insights={insightsEmpty}
        valuation={valuation}
        currency="INR"
      />
    )
    expect(screen.getByText("Independent")).toBeInTheDocument()
    expect(screen.queryByText("No coverage")).toBeNull()
    expect(screen.queryByText("No analyst coverage")).toBeNull()
  })

  it("renders 'Quiet ✓' for Insider Activity when no bulk/block deals in 90 days", () => {
    render(
      <InsightCards
        quality={quality}
        insights={insightsEmpty}
        valuation={valuation}
        currency="INR"
      />
    )
    expect(screen.getByText("Quiet ✓")).toBeInTheDocument()
    expect(
      screen.getByText("No bulk or block deals filed in last 90 days")
    ).toBeInTheDocument()
  })

  it("renders 'Clean ✓' for Red Flags when none are flagged", () => {
    render(
      <InsightCards
        quality={quality}
        insights={insightsEmpty}
        valuation={valuation}
        currency="INR"
      />
    )
    expect(screen.getByText("Clean ✓")).toBeInTheDocument()
    expect(
      screen.getByText(
        /No governance, accounting, or solvency concerns flagged/i
      )
    ).toBeInTheDocument()
    expect(screen.queryByText("No concerns detected")).toBeNull()
  })

  it("renders the no-coverage card with the rewritten Sprint A3 Independent framing", () => {
    // Sprint A3 (2026-06-09): the broker-research line was replaced
    // with a confident "Independent valuation" framing that positions
    // no-coverage as a feature (many of the best opportunities sit
    // outside the coverage universe) rather than a missing third-party
    // validation. The legacy "Not tracked by broker research desks"
    // copy is gone -- it read as apologetic per the analysis-page
    // competitor audit.
    render(
      <InsightCards
        quality={quality}
        insights={insightsEmpty}
        valuation={valuation}
        currency="INR"
      />
    )
    expect(
      screen.getByText(/many of the best opportunities sit outside the coverage universe/i)
    ).toBeInTheDocument()
    // Old apologetic copy must be gone.
    expect(
      screen.queryByText(/Not tracked by broker research desks/i)
    ).toBeNull()
  })
})

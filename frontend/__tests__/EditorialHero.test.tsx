/**
 * EditorialHero — "Under Review" guard tests.
 *
 * Regression coverage for MUTHOOTFIN P0 (2026-05-17): when the
 * underlying FV / DCF / data-quality signals say the model output is
 * unreliable, the prominent verdict header must NOT render a positive
 * "Notably Undervalued" / "Below Fair Value" label. It must read
 * "Under Review" so the header agrees with the yellow caution banner
 * and the "Fair value clamped" caution below it.
 *
 * The six unreliability triggers (any one fires):
 *   1. valuationVerdict ∈ {data_limited, under_review, unavailable, avoid}
 *   2. dcfReliable === false
 *   3. dataConfidence ∈ {low, unusable}
 *   4. fvClamped === true
 *   5. dataLimited === true
 *   6. score100 < 50
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import type { PrismData } from "@/components/prism/types"
import type { Verdict } from "@/types/api"

// Mock heavyweight visual children so the test focuses on the headline.
// next/dynamic with ssr:false would otherwise try to spin up the
// narrator; Prism/ScoreCard pull SVG-heavy children we don't care about
// here.
vi.mock("next/dynamic", () => ({
  default: () => () => null,
}))
vi.mock("@/components/prism/Prism", () => ({
  default: () => null,
}))
vi.mock("@/components/prism/PillarExplainer", () => ({
  default: () => null,
}))
vi.mock("@/components/analysis/ScoreCard", () => ({
  default: () => null,
}))
vi.mock("@/components/analysis/MetricTooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/components/analysis/FvConfidenceBand", () => ({
  default: () => null,
}))

import EditorialHero from "@/components/analysis/EditorialHero"

const prism: PrismData = {
  ticker: "MUTHOOTFIN.NS",
  company_name: "Muthoot Finance",
  verdict_band: "undervalued",
  verdict_label: "Below Fair Value",
  pillars: [],
  overall: 5,
  refraction_index: 1,
  pulse_velocity_hz: 1,
  disclaimer: "Not investment advice.",
}

function renderHero(overrides: Partial<React.ComponentProps<typeof EditorialHero>> = {}) {
  return render(
    <EditorialHero
      data={prism}
      fairValue={3000}
      currentPrice={1500}
      marginOfSafety={100} // strongly undervalued by MoS — would say "Notably Undervalued"
      moat="Narrow"
      currency="INR"
      score100={70}
      grade="B"
      valuationVerdict={"undervalued" as Verdict}
      {...overrides}
    />,
  )
}

describe("EditorialHero — Under Review guard", () => {
  it("renders the normal verdict label when data is reliable", () => {
    renderHero()
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Notably Undervalued",
    )
  })

  it("collapses the headline to 'Under Review' when fvClamped=true (MUTHOOTFIN P0)", () => {
    renderHero({ fvClamped: true })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Under Review",
    )
    expect(screen.getByTestId("editorial-hero-region").textContent).toBe(
      "Under Review",
    )
  })

  it("collapses the headline to 'Under Review' when dcfReliable=false", () => {
    renderHero({ dcfReliable: false })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Under Review",
    )
  })

  it("collapses the headline to 'Under Review' when dataConfidence='low'", () => {
    renderHero({ dataConfidence: "low" })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Under Review",
    )
  })

  it("collapses the headline to 'Under Review' when dataConfidence='unusable'", () => {
    renderHero({ dataConfidence: "unusable" })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Under Review",
    )
  })

  it("collapses the headline to 'Under Review' when score100 < 50 (e.g. 40/C)", () => {
    renderHero({ score100: 40, grade: "C" })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Under Review",
    )
  })

  it("collapses the headline to 'Under Review' for backend verdict ∈ unreliable set", () => {
    for (const v of ["data_limited", "under_review", "unavailable", "avoid"] as const) {
      const { unmount } = renderHero({ valuationVerdict: v as unknown as Verdict })
      expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
        "Under Review",
      )
      unmount()
    }
  })

  it("still uses normal label for score == 50 (boundary)", () => {
    renderHero({ score100: 50 })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Notably Undervalued",
    )
  })

  it("collapses headline when dataLimited=true even if MoS is positive", () => {
    renderHero({ dataLimited: true })
    expect(screen.getByTestId("editorial-hero-headline").textContent).toBe(
      "Under Review",
    )
  })
})

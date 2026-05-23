/**
 * Phase C.3 (2026-05-25) — ScoreBreakdownPanel smoke tests.
 *
 * Pins the rendered shape of the "Why this score?" transparency panel:
 *   - returns null when score_breakdown is absent (legacy payload)
 *   - renders the component table when breakdown is present
 *   - renders the MoS-dominance cap modifier when one is provided
 *   - exposes the panel as a native <details>/<summary> for keyboard a11y
 *
 * Reference: docs/diagnostics/phase-c-score-formula-2026-05-25.md.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import ScoreBreakdownPanel from "@/components/analysis/ScoreBreakdownPanel"
import type { ScoreBreakdown } from "@/types/api"

const FULL_BREAKDOWN: ScoreBreakdown = {
  components: [
    {
      name: "Business Quality (50pts)",
      weight_max: 50,
      points: 44,
      source: "piotroski+moat",
    },
    {
      name: "Growth (20pts)",
      weight_max: 20,
      points: 15,
      source: "revenue_growth",
    },
    {
      name: "Valuation (20pts)",
      weight_max: 20,
      points: 20,
      source: "mos_pct",
    },
    {
      name: "Sentiment (10pts)",
      weight_max: 10,
      points: 7,
      source: "analyst_upside",
    },
  ],
  modifiers: [
    {
      name: "MoS-dominance cap",
      delta: -36,
      reason: "|MoS|=43% — composite capped at 50.",
    },
  ],
  base_score: 86,
  final_score: 50,
  note: "Score is floored, not rounded.",
}

describe("ScoreBreakdownPanel", () => {
  it("renders nothing when breakdown is absent", () => {
    const { container } = render(<ScoreBreakdownPanel breakdown={null} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when breakdown has no components", () => {
    const { container } = render(
      <ScoreBreakdownPanel
        breakdown={{
          components: [],
          modifiers: [],
          base_score: 0,
          final_score: 0,
        }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders all 4 components when breakdown is present", () => {
    render(<ScoreBreakdownPanel breakdown={FULL_BREAKDOWN} />)
    expect(screen.getByText(/Business Quality/)).toBeInTheDocument()
    expect(screen.getByText(/Growth/)).toBeInTheDocument()
    expect(screen.getByText(/Valuation/)).toBeInTheDocument()
    expect(screen.getByText(/Sentiment/)).toBeInTheDocument()
  })

  it("renders the MoS-dominance cap modifier when present", () => {
    render(<ScoreBreakdownPanel breakdown={FULL_BREAKDOWN} />)
    expect(screen.getByText("MoS-dominance cap")).toBeInTheDocument()
    expect(
      screen.getByText(/composite capped at 50/),
    ).toBeInTheDocument()
    expect(screen.getByText("-36")).toBeInTheDocument()
  })

  it("does not render the modifiers section when none are present", () => {
    const noMods: ScoreBreakdown = {
      ...FULL_BREAKDOWN,
      modifiers: [],
      base_score: 78,
      final_score: 78,
    }
    render(<ScoreBreakdownPanel breakdown={noMods} />)
    expect(screen.queryByText(/Modifiers/i)).toBeNull()
  })

  it("renders the floor-vs-rounding note when provided", () => {
    render(<ScoreBreakdownPanel breakdown={FULL_BREAKDOWN} />)
    expect(
      screen.getByText(/Score is floored, not rounded\./),
    ).toBeInTheDocument()
  })

  it("uses a native <details>/<summary> for collapsible a11y", () => {
    const { container } = render(
      <ScoreBreakdownPanel breakdown={FULL_BREAKDOWN} />,
    )
    const details = container.querySelector("details")
    expect(details).not.toBeNull()
    const summary = details!.querySelector("summary")
    expect(summary).not.toBeNull()
    expect(summary!.textContent).toMatch(/Why this score\?/i)
  })
})

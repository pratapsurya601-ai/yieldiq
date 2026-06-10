/**
 * InflationRegimePanel tests (2026-06-10).
 *
 * Covers the four-regime classification (low / normal / high /
 * extreme), the self-hide invariant when the adjustment is absent,
 * and the SEBI-safe vocabulary on the model_note strip.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import InflationRegimePanel from "@/components/analysis/InflationRegimePanel"

type AdjustmentBlock = NonNullable<
  Parameters<typeof InflationRegimePanel>[0]["adjustment"]
>

function makeAdjustment(over: Partial<AdjustmentBlock> = {}): AdjustmentBlock {
  return {
    current_cpi_pct: 5.0,
    regime: "normal",
    real_wacc_pct: 7.0,
    real_growth_pct: 3.0,
    nominal_fv: 1000,
    real_terms_fv: 980,
    fv_distortion_pct: -2.0,
    model_note: "use_nominal",
    ...over,
  } as AdjustmentBlock
}

describe("InflationRegimePanel", () => {
  it("self-hides when adjustment is null", () => {
    const { container } = render(<InflationRegimePanel adjustment={null} />)
    expect(container.firstChild).toBeNull()
  })

  it("self-hides when adjustment is undefined", () => {
    const { container } = render(<InflationRegimePanel />)
    expect(container.firstChild).toBeNull()
  })

  it("renders the normal-regime band with both FVs", () => {
    render(<InflationRegimePanel adjustment={makeAdjustment()} />)
    expect(screen.getByTestId("inflation-regime-panel")).toBeInTheDocument()
    expect(screen.getByText(/Normal inflation/i)).toBeInTheDocument()
    expect(screen.getByText(/Nominal-terms FV/i)).toBeInTheDocument()
    // "Real-terms FV" is the ValuationCard label AND inside the
    // DistortionStrip body copy ("Real-terms FV is +N% relative to ..."),
    // so the panel can legitimately render the phrase more than once.
    // Assert at least one occurrence rather than uniqueness.
    expect(screen.getAllByText(/Real-terms FV/i).length).toBeGreaterThan(0)
  })

  it("renders an extreme-regime warning and a wide distortion gap", () => {
    render(
      <InflationRegimePanel
        adjustment={makeAdjustment({
          current_cpi_pct: 9.5,
          regime: "extreme",
          real_wacc_pct: 3.0,
          real_growth_pct: -2.0,
          nominal_fv: 1000,
          real_terms_fv: 1280,
          fv_distortion_pct: 28.0,
          model_note: "use_real",
        })}
      />,
    )
    expect(screen.getByText(/Extreme inflation/i)).toBeInTheDocument()
    // The signed distortion percent renders twice in the DistortionStrip
    // (once as the prominent right-aligned figure, once inline in the
    // explanatory sentence). Both occurrences are intentional — assert
    // presence rather than uniqueness.
    expect(screen.getAllByText(/\+28\.00%/).length).toBeGreaterThan(0)
    // ModelNote strip frames the real-terms recompute as a model
    // note, not as advice. SEBI vocabulary check: the string contains
    // "anchor", not advice verbs. In the extreme regime the phrase
    // renders both in the regime blurb and the model-note label, so
    // assert presence rather than uniqueness.
    expect(
      screen.getAllByText(/conservative anchor/i).length,
    ).toBeGreaterThan(0)
  })

  it("renders the not-computable fallback when real_terms_fv is null", () => {
    render(
      <InflationRegimePanel
        adjustment={makeAdjustment({
          regime: "high",
          current_cpi_pct: 7.5,
          real_terms_fv: null,
          fv_distortion_pct: 0,
          model_note: "use_nominal",
        })}
      />,
    )
    expect(
      screen.getByText(/Real-terms recompute not available/i),
    ).toBeInTheDocument()
  })

  it("does not leak advice vocabulary in any regime", () => {
    // Build banned tokens from fragments (CLAUDE.md SEBI guard rule 5).
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "stro" + "ng b" + "uy",
      "stro" + "ng s" + "ell",
    ]
    const regimes: AdjustmentBlock["regime"][] = [
      "low",
      "normal",
      "high",
      "extreme",
    ]
    for (const r of regimes) {
      const { container, unmount } = render(
        <InflationRegimePanel
          adjustment={makeAdjustment({ regime: r })}
        />,
      )
      const text = container.textContent?.toLowerCase() ?? ""
      for (const word of BANNED) {
        expect(text.includes(word)).toBe(false)
      }
      unmount()
    }
  })
})

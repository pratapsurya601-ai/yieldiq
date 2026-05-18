/**
 * ConfidenceIndicators tests.
 *
 * Covers:
 *   - The "render nothing" path on legacy cached payloads (all four
 *     signals null/undefined) — must NOT produce a section heading
 *     or empty band.
 *   - Tone bucketing: ≥80 green, 50-79 amber, <50 red.
 *   - Per-chip null-skip behaviour (one score present, others null).
 *   - Analyst-opinion-required banner visibility + citation of the
 *     defense-PSU caveat from `data_issues`.
 *   - Generic fallback copy when no matching data_issues string is
 *     provided.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import ConfidenceIndicators, {
  toneForScore,
} from "@/components/analysis/ConfidenceIndicators"

describe("toneForScore", () => {
  it("returns green for ≥ 80", () => {
    expect(toneForScore(80)).toBe("green")
    expect(toneForScore(99)).toBe("green")
    expect(toneForScore(100)).toBe("green")
  })

  it("returns amber for 50–79", () => {
    expect(toneForScore(50)).toBe("amber")
    expect(toneForScore(65)).toBe("amber")
    expect(toneForScore(79)).toBe("amber")
  })

  it("returns red for < 50", () => {
    expect(toneForScore(0)).toBe("red")
    expect(toneForScore(49)).toBe("red")
  })
})

describe("ConfidenceIndicators", () => {
  it("renders nothing when all signals are absent (legacy payload)", () => {
    const { container } = render(<ConfidenceIndicators />)
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when scores are null and flag is false", () => {
    const { container } = render(
      <ConfidenceIndicators
        dataQualityScore={null}
        modelConfidenceScore={null}
        valuationStabilityScore={null}
        analystOpinionRequired={false}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders all three chips with correct tones when scores are present", () => {
    render(
      <ConfidenceIndicators
        dataQualityScore={92}
        modelConfidenceScore={64}
        valuationStabilityScore={30}
      />,
    )
    expect(screen.getByTestId("confidence-indicators")).toBeInTheDocument()
    expect(screen.getByTestId("confidence-chip-data_quality")).toHaveAttribute(
      "data-tone",
      "green",
    )
    expect(
      screen.getByTestId("confidence-chip-model_confidence"),
    ).toHaveAttribute("data-tone", "amber")
    expect(
      screen.getByTestId("confidence-chip-valuation_stability"),
    ).toHaveAttribute("data-tone", "red")
  })

  it("skips chips that are null while rendering siblings", () => {
    render(
      <ConfidenceIndicators
        dataQualityScore={85}
        modelConfidenceScore={null}
        valuationStabilityScore={null}
      />,
    )
    expect(screen.getByTestId("confidence-chip-data_quality")).toBeInTheDocument()
    expect(
      screen.queryByTestId("confidence-chip-model_confidence"),
    ).toBeNull()
    expect(
      screen.queryByTestId("confidence-chip-valuation_stability"),
    ).toBeNull()
  })

  it("shows the analyst-opinion banner when flag is true", () => {
    render(
      <ConfidenceIndicators
        analystOpinionRequired={true}
        dataIssues={[
          "Defense PSU — trailing financials understate forward order book",
        ]}
      />,
    )
    const banner = screen.getByTestId("analyst-opinion-banner")
    expect(banner).toBeInTheDocument()
    expect(banner.textContent).toMatch(/Defense PSU/)
  })

  it("falls back to generic copy when no matching data_issue is present", () => {
    render(
      <ConfidenceIndicators
        analystOpinionRequired={true}
        dataIssues={["Some unrelated note about cashflow"]}
      />,
    )
    const banner = screen.getByTestId("analyst-opinion-banner")
    expect(banner).toBeInTheDocument()
    expect(banner.textContent).toMatch(/regime change|forward analyst/i)
  })

  it("renders banner alone when flag is true but scores are null", () => {
    render(<ConfidenceIndicators analystOpinionRequired={true} />)
    expect(screen.getByTestId("analyst-opinion-banner")).toBeInTheDocument()
    expect(screen.queryByTestId("confidence-score-chips")).toBeNull()
  })

  it("renders chips alone when scores are present but flag is false", () => {
    render(
      <ConfidenceIndicators
        dataQualityScore={75}
        analystOpinionRequired={false}
      />,
    )
    expect(screen.queryByTestId("analyst-opinion-banner")).toBeNull()
    expect(screen.getByTestId("confidence-score-chips")).toBeInTheDocument()
  })

  it("includes tooltip text on each chip", () => {
    render(<ConfidenceIndicators dataQualityScore={90} />)
    const chip = screen.getByTestId("confidence-chip-data_quality")
    const title = chip.getAttribute("title") ?? ""
    expect(title).toMatch(/Data Quality/)
    expect(title).toMatch(/90\/100/)
  })
})

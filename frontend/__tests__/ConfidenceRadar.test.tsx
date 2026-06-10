/**
 * ConfidenceRadar tests.
 *
 * Coverage:
 *   - All five axes render (label + polygon path)
 *   - Overall score is the mean of *non-null* pillars (null pillars
 *     are excluded so banks / holdcos don't have their averages
 *     pulled down by an n/a sensitivity slot)
 *   - Pillar breakdown details expand on user interaction
 *   - Null-only payload renders the honest empty state (no all-zero
 *     polygon mis-read as "every pillar failed")
 *   - SEBI vocab guard — radar copy never leaks any banned-vocab
 *     token (see scripts/check_sebi_words.py BANNED_WORDS)
 *   - Tone bands match ConfidenceIndicators (≥80 green, 50–79 amber,
 *     <50 red) for the per-pillar chips in the breakdown
 *   - Clamps out-of-range values without crashing (e.g. 105 → 100)
 *   - Empty state copy mentions ticker so users know what's missing
 *   - Caveat copy mentions "statistically computed" — the audit-#5
 *     differentiator vs. qualitative competitor frameworks
 */

import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"

import {
  ConfidenceRadar,
  type ConfidenceRadarPillars,
} from "@/components/analysis/ConfidenceRadar"

// ── SEBI vocab guard — fragments at runtime so the diff-only lint
//    doesn't trip on the literal array (see frontend/CLAUDE.md
//    standing rule #5).
const BANNED: string[] = [
  ["ap", "pears"],
  ["sh", "ould"],
  ["con", "cern"],
  ["stren", "gth"],
  ["weakn", "ess"],
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

// ── Mock ResizeObserver — recharts <ResponsiveContainer> hits it on
//    mount. jsdom doesn't ship one.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof MockResizeObserver }).ResizeObserver =
  MockResizeObserver

const FULL_PILLARS: ConfidenceRadarPillars = {
  data_quality: 90,
  model_confidence: 70,
  valuation_stability: 60,
  sensitivity: 80,
  composite_agreement: 50,
}

describe("ConfidenceRadar", () => {
  it("renders the radar shell with a non-empty marker when at least one pillar is present", () => {
    render(<ConfidenceRadar ticker="HDFCBANK" pillars={FULL_PILLARS} />)
    const radar = screen.getByTestId("confidence-radar")
    expect(radar).toBeInTheDocument()
    expect(radar.getAttribute("data-empty")).not.toBe("true")
  })

  it("renders all five axis labels inside the pillar breakdown", () => {
    render(<ConfidenceRadar ticker="HDFCBANK" pillars={FULL_PILLARS} />)
    expect(
      screen.getByTestId("radar-explainer-data_quality"),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId("radar-explainer-model_confidence"),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId("radar-explainer-valuation_stability"),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId("radar-explainer-sensitivity"),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId("radar-explainer-composite_agreement"),
    ).toBeInTheDocument()
  })

  it("computes the overall score as the mean of non-null pillars", () => {
    // (90+70+60+80+50) / 5 = 70
    render(<ConfidenceRadar ticker="HDFCBANK" pillars={FULL_PILLARS} />)
    const overall = screen.getByTestId("radar-overall-score")
    expect(overall.textContent).toMatch(/\b70\b/)
    expect(overall.textContent).toMatch(/\/100/)
  })

  it("excludes null pillars from the overall score (bank with null sensitivity)", () => {
    // (80 + 60 + 70 + null + 60) / 4 = 67.5 → 68
    render(
      <ConfidenceRadar
        ticker="ICICIBANK"
        pillars={{
          data_quality: 80,
          model_confidence: 60,
          valuation_stability: 70,
          sensitivity: null,
          composite_agreement: 60,
        }}
      />,
    )
    const overall = screen.getByTestId("radar-overall-score")
    expect(overall.textContent).toMatch(/\b68\b/)
  })

  it("renders n/a chip for absent pillars in the breakdown", () => {
    render(
      <ConfidenceRadar
        ticker="ICICIBANK"
        pillars={{
          data_quality: 80,
          model_confidence: 60,
          valuation_stability: 70,
          sensitivity: null,
          composite_agreement: 60,
        }}
      />,
    )
    expect(
      screen.getByTestId("radar-pillar-na-sensitivity"),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId("radar-pillar-chip-sensitivity"),
    ).toBeNull()
  })

  it("applies tone bands per pillar matching ConfidenceIndicators thresholds", () => {
    render(
      <ConfidenceRadar
        ticker="TCS"
        pillars={{
          data_quality: 92, // green ≥ 80
          model_confidence: 65, // amber 50–79
          valuation_stability: 30, // red < 50
          sensitivity: 80, // green at boundary
          composite_agreement: 49, // red just below boundary
        }}
      />,
    )
    expect(
      screen
        .getByTestId("radar-pillar-chip-data_quality")
        .getAttribute("data-tone"),
    ).toBe("green")
    expect(
      screen
        .getByTestId("radar-pillar-chip-model_confidence")
        .getAttribute("data-tone"),
    ).toBe("amber")
    expect(
      screen
        .getByTestId("radar-pillar-chip-valuation_stability")
        .getAttribute("data-tone"),
    ).toBe("red")
    expect(
      screen
        .getByTestId("radar-pillar-chip-sensitivity")
        .getAttribute("data-tone"),
    ).toBe("green")
    expect(
      screen
        .getByTestId("radar-pillar-chip-composite_agreement")
        .getAttribute("data-tone"),
    ).toBe("red")
  })

  it("expands the pillar breakdown details element on click", () => {
    render(<ConfidenceRadar ticker="HDFCBANK" pillars={FULL_PILLARS} />)
    const details = screen.getByTestId(
      "radar-pillar-explainers",
    ) as HTMLDetailsElement
    expect(details.open).toBe(false)
    const summary = details.querySelector("summary")!
    fireEvent.click(summary)
    expect(details.open).toBe(true)
  })

  it("renders the empty state when every pillar is null (legacy payload)", () => {
    render(
      <ConfidenceRadar
        ticker="NEWCO"
        pillars={{
          data_quality: null,
          model_confidence: null,
          valuation_stability: null,
          sensitivity: null,
          composite_agreement: null,
        }}
      />,
    )
    const radar = screen.getByTestId("confidence-radar")
    expect(radar.getAttribute("data-empty")).toBe("true")
    expect(radar.textContent).toMatch(/NEWCO/)
    expect(screen.queryByTestId("radar-chart-wrap")).toBeNull()
    expect(screen.queryByTestId("radar-overall-score")).toBeNull()
  })

  it("clamps out-of-range pillar values without crashing the chart", () => {
    expect(() =>
      render(
        <ConfidenceRadar
          ticker="EDGE"
          pillars={{
            data_quality: 150, // clamped to 100
            model_confidence: -20, // clamped to 0
            valuation_stability: 50,
            sensitivity: 75,
            composite_agreement: 60,
          }}
        />,
      ),
    ).not.toThrow()
    // Overall uses clamped values: (100 + 0 + 50 + 75 + 60) / 5 = 57
    const overall = screen.getByTestId("radar-overall-score")
    expect(overall.textContent).toMatch(/\b57\b/)
  })

  it("mentions the statistical differentiator in the caveat copy (audit #5)", () => {
    render(<ConfidenceRadar ticker="HDFCBANK" pillars={FULL_PILLARS} />)
    const caveat = screen.getByTestId("radar-caveat")
    expect(caveat.textContent).toMatch(/statistically computed/i)
  })

  it("does not leak SEBI-banned vocabulary in any rendered copy", () => {
    const { container } = render(
      <ConfidenceRadar ticker="HDFCBANK" pillars={FULL_PILLARS} />,
    )
    const text = container.textContent ?? ""
    const m = text.match(BANNED_RE)
    expect(
      m,
      `SEBI vocab leak in ConfidenceRadar: ${m?.[0]}`,
    ).toBeNull()
  })

  it("does not leak SEBI-banned vocabulary in the empty state either", () => {
    const { container } = render(
      <ConfidenceRadar
        ticker="HDFCBANK"
        pillars={{
          data_quality: null,
          model_confidence: null,
          valuation_stability: null,
          sensitivity: null,
          composite_agreement: null,
        }}
      />,
    )
    const text = container.textContent ?? ""
    const m = text.match(BANNED_RE)
    expect(
      m,
      `SEBI vocab leak in empty state: ${m?.[0]}`,
    ).toBeNull()
  })
})

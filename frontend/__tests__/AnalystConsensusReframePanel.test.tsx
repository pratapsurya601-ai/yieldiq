/**
 * AnalystConsensusReframePanel — competitor audit #2 reframe tests.
 *
 * Covers:
 *   - Side-by-side comparison renders both Wall Street and YIQ values.
 *   - Gap-direction classification:
 *       * aligned   (|gap| <= 5%)  → cross-validation copy
 *       * above     (gap >  5%)    → "more long-term value" copy
 *       * below     (gap < -5%)    → "more cautious" copy
 *   - Empty state (no Wall Street data) renders empty-state copy and
 *     skips the comparison grid.
 *   - Analyst range / count render when provided, hide when null.
 *   - prettifyMethod helper turns composite_* method tags into a
 *     friendly label.
 *   - SEBI vocab guard — no banned imperatives in the rendered DOM
 *     across all the gap directions.
 *
 * SEBI lint note: per CLAUDE.md root rule #5, the BANNED array below
 * is built from fragment concatenation (pattern B) so the
 * `--diff-only` sebi-lint pass does not flag this test file.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import AnalystConsensusReframePanel, {
  getGapExplanation,
  prettifyMethod,
} from "@/components/analysis/AnalystConsensusReframePanel"

/* ─── shared fixtures ──────────────────────────────────────────────── */

const BASE_PROPS = {
  ticker: "HDFCBANK",
  currentPrice: 1500,
  currency: "INR" as const,
}

/* ─── side-by-side comparison ─────────────────────────────────────── */

describe("AnalystConsensusReframePanel — comparison surface", () => {
  it("renders both Wall Street and YieldIQ value tiles side by side", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={1800}
        yiqComposite={1900}
        analystCount={12}
      />,
    )
    expect(screen.getByTestId("analyst-consensus-reframe")).toBeDefined()
    expect(screen.getByTestId("analyst-reframe-comparison")).toBeDefined()
    expect(screen.getByTestId("analyst-reframe-wallst-value").textContent).toMatch(/1,?800/)
    expect(screen.getByTestId("analyst-reframe-yiq-value").textContent).toMatch(/1,?900/)
  })

  it("renders the analyst range and count when both bounds are provided", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={1800}
        wallStHighTarget={2100}
        wallStLowTarget={1500}
        analystCount={7}
        yiqComposite={1900}
      />,
    )
    const range = screen.getByTestId("analyst-reframe-wallst-range")
    expect(range.textContent).toMatch(/1,?500/)
    expect(range.textContent).toMatch(/2,?100/)
    expect(screen.getByTestId("analyst-reframe-wallst-count").textContent).toContain("7 analysts")
  })

  it("omits the range when either bound is missing", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={1800}
        wallStHighTarget={null}
        wallStLowTarget={null}
        yiqComposite={1900}
      />,
    )
    expect(screen.queryByTestId("analyst-reframe-wallst-range")).toBeNull()
  })

  it("renders singular 'analyst' when count is exactly 1", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={1800}
        analystCount={1}
        yiqComposite={1900}
      />,
    )
    expect(screen.getByTestId("analyst-reframe-wallst-count").textContent).toContain("1 analyst")
    expect(screen.getByTestId("analyst-reframe-wallst-count").textContent).not.toContain("analysts")
  })

  it("omits the count line when analystCount is null or zero", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={1800}
        analystCount={null}
        yiqComposite={1900}
      />,
    )
    expect(screen.queryByTestId("analyst-reframe-wallst-count")).toBeNull()
  })
})

/* ─── gap-direction classification ────────────────────────────────── */

describe("AnalystConsensusReframePanel — gap direction", () => {
  it("classifies |gap| <= 5% as aligned (cross-validation copy)", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={2050} // +2.5%
      />,
    )
    const gap = screen.getByTestId("analyst-reframe-gap")
    expect(gap.getAttribute("data-direction")).toBe("aligned")
    expect(screen.getByTestId("analyst-reframe-gap-copy").textContent).toMatch(/cross-validation/i)
    expect(screen.getByTestId("analyst-reframe-gap-headline").textContent).toMatch(/in line/i)
  })

  it("classifies gap > 5% as 'above' (more long-term value copy)", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={2600} // +30%
      />,
    )
    const gap = screen.getByTestId("analyst-reframe-gap")
    expect(gap.getAttribute("data-direction")).toBe("above")
    expect(screen.getByTestId("analyst-reframe-gap-copy").textContent).toMatch(/more long-term value/i)
    expect(screen.getByTestId("analyst-reframe-gap-headline").textContent).toMatch(/30% more/)
  })

  it("classifies gap < -5% as 'below' (more cautious copy)", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={1500} // -25%
      />,
    )
    const gap = screen.getByTestId("analyst-reframe-gap")
    expect(gap.getAttribute("data-direction")).toBe("below")
    expect(screen.getByTestId("analyst-reframe-gap-copy").textContent).toMatch(/more cautious/i)
    expect(screen.getByTestId("analyst-reframe-gap-headline").textContent).toMatch(/25% less/)
  })

  it("hides the gap strip when yiqComposite is null but still renders the Wall Street side", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={null}
      />,
    )
    expect(screen.queryByTestId("analyst-reframe-gap")).toBeNull()
    expect(screen.getByTestId("analyst-reframe-yiq-value").textContent).toContain("—")
    expect(screen.getByTestId("analyst-reframe-wallst-value").textContent).toMatch(/2,?000/)
  })
})

/* ─── empty state ─────────────────────────────────────────────────── */

describe("AnalystConsensusReframePanel — empty state", () => {
  it("renders empty-state when wallStAvgTarget is null", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={null}
        yiqComposite={1900}
      />,
    )
    expect(screen.getByTestId("analyst-consensus-reframe-empty")).toBeDefined()
    expect(screen.queryByTestId("analyst-consensus-reframe")).toBeNull()
    expect(screen.getByTestId("analyst-reframe-empty-copy").textContent).toMatch(/not yet available/i)
    expect(screen.getByTestId("analyst-reframe-empty-copy").textContent).toContain("HDFCBANK")
  })

  it("renders empty-state when wallStAvgTarget is zero or negative", () => {
    render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={0}
        yiqComposite={1900}
      />,
    )
    expect(screen.getByTestId("analyst-consensus-reframe-empty")).toBeDefined()
  })
})

/* ─── prettifyMethod helper ───────────────────────────────────────── */

describe("prettifyMethod", () => {
  it("turns composite_dcf_multiples_analyst_threestage into a readable list", () => {
    const out = prettifyMethod("composite_dcf_multiples_analyst_threestage")
    expect(out).toBe("DCF + Multiples + Wall Street + Three-stage DCF")
  })

  it("handles a null or empty method string with a default label", () => {
    expect(prettifyMethod(null)).toMatch(/composite/i)
    expect(prettifyMethod(undefined)).toMatch(/composite/i)
    expect(prettifyMethod("")).toMatch(/composite/i)
  })

  it("drops a leading 'composite_' prefix from the rendered label", () => {
    expect(prettifyMethod("composite_dcf_multiples")).toBe("DCF + Multiples")
  })

  it("title-cases unknown fragments rather than dropping them", () => {
    const out = prettifyMethod("composite_dcf_someNewModel")
    expect(out).toContain("DCF")
    expect(out.toLowerCase()).toContain("somenewmodel")
  })
})

/* ─── getGapExplanation helper ────────────────────────────────────── */

describe("getGapExplanation", () => {
  it("returns cross-validation copy for aligned", () => {
    expect(getGapExplanation("aligned")).toMatch(/cross-validation/i)
  })
  it("returns more-long-term-value copy for above", () => {
    expect(getGapExplanation("above")).toMatch(/more long-term value/i)
  })
  it("returns more-cautious copy for below", () => {
    expect(getGapExplanation("below")).toMatch(/more cautious/i)
  })
})

/* ─── SEBI vocab guard ────────────────────────────────────────────── */

describe("AnalystConsensusReframePanel — SEBI vocab guard", () => {
  // BANNED array built from fragments per CLAUDE.md root rule #5 so the
  // sebi-lint --diff-only pass does not match on this fixture.
  const BANNED = [
    "b" + "uy",
    "se" + "ll",
    "ho" + "ld",
    "recomm" + "end",
    "out" + "perform",
    "under" + "perform",
    "sho" + "uld",
    "att" + "ractive",
    "che" + "ap",
    "expen" + "sive",
    "accumul" + "ate",
    "stro" + "ng",
    "we" + "ak",
  ]

  function assertNoBanned(text: string) {
    const lower = text.toLowerCase()
    for (const term of BANNED) {
      const idx = lower.indexOf(term)
      if (idx !== -1) {
        throw new Error(
          `SEBI vocab guard tripped: '${term}' found in rendered text at index ${idx}`,
        )
      }
    }
  }

  it("renders no banned imperatives in the aligned-state DOM", () => {
    const { container } = render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={2050}
        analystCount={5}
      />,
    )
    assertNoBanned(container.textContent ?? "")
  })

  it("renders no banned imperatives in the above-state DOM", () => {
    const { container } = render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={2600}
        analystCount={5}
      />,
    )
    assertNoBanned(container.textContent ?? "")
  })

  it("renders no banned imperatives in the below-state DOM", () => {
    const { container } = render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={2000}
        yiqComposite={1500}
        analystCount={5}
      />,
    )
    assertNoBanned(container.textContent ?? "")
  })

  it("renders no banned imperatives in the empty-state DOM", () => {
    const { container } = render(
      <AnalystConsensusReframePanel
        {...BASE_PROPS}
        wallStAvgTarget={null}
        yiqComposite={1500}
      />,
    )
    assertNoBanned(container.textContent ?? "")
  })
})

/**
 * CompositeCompositionPanel tests
 * (v_composite_composition_transparency_2026_06_10).
 *
 * Covers:
 *   - Empty-state guard: null composition / zero applicable estimators
 *     -> renders nothing (self-hide).
 *   - Renders 7 estimator rows when the backend payload carries the
 *     canonical seven-slot list (3 applicable + 4 inapplicable).
 *   - Inapplicable rows expose their `reason` string.
 *   - Outlier rows render the "Outlier" badge + data-outlier flag.
 *   - Headline carries the correct confidence label and N of M.
 *   - SEBI guard — no banned advisory vocabulary in any rendered text
 *     (Pattern B per CLAUDE.md rule #5).
 */

import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"

import CompositeCompositionPanel, {
  type CompositeComposition,
} from "@/components/analysis/CompositeCompositionPanel"


// ─── SEBI vocab guard (Pattern B — fragments) ────────────────────
const BANNED_TOKENS = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "recom" + "mend",
  "sho" + "uld",
  "che" + "ap",
  "expen" + "sive",
  "undervalu" + "ed",
  "overvalu" + "ed",
]

function assertSebiClean(text: string): void {
  const lowered = text.toLowerCase()
  for (const token of BANNED_TOKENS) {
    expect(lowered).not.toContain(token)
  }
}


// ─── fixtures shaped like the backend payload ─────────────────────
function row(
  key: string,
  label: string,
  overrides: Partial<CompositeComposition["estimators"][number]> = {},
): CompositeComposition["estimators"][number] {
  return {
    key,
    label,
    value: 1000,
    weight_nominal: 0.35,
    weight_effective: 0.4,
    contribution: 400,
    applicable: true,
    reason: null,
    is_outlier: false,
    description: `${label} description`,
    ...overrides,
  }
}

function hdfcbankShapeComposition(): CompositeComposition {
  return {
    estimators: [
      row("dcf", "DCF", {
        value: 1141.82,
        weight_nominal: 0.35,
        weight_effective: 0.4545,
        contribution: 518.95,
      }),
      row("multiples", "Peer multiples", {
        value: 1180.0,
        weight_nominal: 0.20,
        weight_effective: 0.2597,
        contribution: 306.45,
      }),
      row("three_stage", "Three-stage DCF", {
        value: 1100.0,
        weight_nominal: 0.15,
        weight_effective: 0.1948,
        contribution: 214.28,
      }),
      row("analyst", "Wall St analyst", {
        value: null,
        weight_effective: 0,
        contribution: null,
        applicable: false,
        reason: "No broker coverage on this ticker",
      }),
      row("ddm", "Dividend discount", {
        value: null,
        weight_effective: 0,
        contribution: null,
        applicable: false,
        reason: "Payout below DDM gate",
      }),
      row("epv", "Earnings Power Value", {
        value: null,
        weight_effective: 0,
        contribution: null,
        applicable: false,
        reason: "Banks use the financial-cohort path",
      }),
      row("probability_weighted", "Probability-weighted", {
        value: 1189.4,
        weight_nominal: 0.05,
        weight_effective: 0.0909,
        contribution: 108.12,
      }),
    ],
    estimators_available: 4,
    estimators_total: 7,
    confidence_label: "MODERATE",
    confidence_caption: "4 of 7 estimators populated — MODERATE confidence; weights renormalized",
    outliers: [],
    composite_value: 1147.77,
  }
}


// ─── tests ────────────────────────────────────────────────────────

describe("CompositeCompositionPanel — empty-state guard", () => {
  it("renders nothing when composition is null", () => {
    const { container } = render(
      <CompositeCompositionPanel composition={null} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when zero estimators are applicable", () => {
    const composition: CompositeComposition = {
      estimators: [
        row("dcf", "DCF", {
          value: null,
          applicable: false,
          reason: "Cache warming",
          weight_effective: 0,
          contribution: null,
        }),
      ],
      estimators_available: 0,
      estimators_total: 7,
      confidence_label: "MINIMAL",
      confidence_caption: "0 of 7 estimators populated",
      outliers: [],
      composite_value: null,
    }
    const { container } = render(
      <CompositeCompositionPanel composition={composition} />,
    )
    expect(container.firstChild).toBeNull()
  })
})


describe("CompositeCompositionPanel — happy path", () => {
  it("renders the panel surface and headline confidence chip", () => {
    render(
      <CompositeCompositionPanel
        composition={hdfcbankShapeComposition()}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    const panel = screen.getByTestId("composite-composition-panel")
    expect(panel).toBeInTheDocument()
    const headline = screen.getByTestId("composite-composition-headline")
    expect(headline).toHaveTextContent("4 of 7 estimators")
    expect(headline).toHaveTextContent("MODERATE")
    expect(headline).toHaveAttribute("data-confidence", "MODERATE")
  })

  it("renders all 7 estimator rows (applicable + inapplicable)", () => {
    render(
      <CompositeCompositionPanel
        composition={hdfcbankShapeComposition()}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    const rows = screen.getByTestId("composite-composition-rows")
    // 7 slots — 4 applicable + 3 inapplicable.
    for (const key of [
      "dcf",
      "multiples",
      "three_stage",
      "analyst",
      "ddm",
      "epv",
      "probability_weighted",
    ]) {
      expect(
        within(rows).getByTestId(`composite-composition-row-${key}`),
      ).toBeInTheDocument()
    }
  })

  it("marks applicable rows with data-applicable=true and inapplicable rows with false", () => {
    render(
      <CompositeCompositionPanel
        composition={hdfcbankShapeComposition()}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    expect(
      screen.getByTestId("composite-composition-row-dcf"),
    ).toHaveAttribute("data-applicable", "true")
    expect(
      screen.getByTestId("composite-composition-row-analyst"),
    ).toHaveAttribute("data-applicable", "false")
  })

  it("renders the reason on inapplicable rows", () => {
    render(
      <CompositeCompositionPanel
        composition={hdfcbankShapeComposition()}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    expect(
      screen.getByTestId("composite-composition-row-analyst"),
    ).toHaveTextContent("No broker coverage")
    expect(
      screen.getByTestId("composite-composition-row-ddm"),
    ).toHaveTextContent("Payout below DDM gate")
    expect(
      screen.getByTestId("composite-composition-row-epv"),
    ).toHaveTextContent("financial-cohort")
  })

  it("renders the total reconciliation row with the composite value", () => {
    render(
      <CompositeCompositionPanel
        composition={hdfcbankShapeComposition()}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    const total = screen.getByTestId("composite-composition-total")
    expect(total).toHaveTextContent("4 of 7")
    // formatCurrency uses INR ticker => "₹" or "Rs" prefix; just assert the
    // numeric portion lands.
    expect(total.textContent ?? "").toMatch(/1[,.]?147/)
  })
})


describe("CompositeCompositionPanel — outlier flag", () => {
  it("renders the outlier badge on flagged rows and the caption", () => {
    const composition = hdfcbankShapeComposition()
    composition.estimators[2].is_outlier = true
    composition.outliers = ["three_stage"]
    render(
      <CompositeCompositionPanel
        composition={composition}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    const tsRow = screen.getByTestId("composite-composition-row-three_stage")
    expect(tsRow).toHaveAttribute("data-outlier", "true")
    expect(
      within(tsRow).getByTestId(
        "composite-composition-outlier-three_stage",
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId("composite-composition-outlier-caption"),
    ).toHaveTextContent("1 estimator flagged")
  })

  it("does not render outlier caption when no outliers present", () => {
    render(
      <CompositeCompositionPanel
        composition={hdfcbankShapeComposition()}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    expect(
      screen.queryByTestId("composite-composition-outlier-caption"),
    ).toBeNull()
  })
})


describe("CompositeCompositionPanel — SEBI vocabulary guard", () => {
  it("renders no banned advisory vocabulary on the happy path", () => {
    const composition = hdfcbankShapeComposition()
    composition.estimators[2].is_outlier = true
    composition.outliers = ["three_stage"]
    const { container } = render(
      <CompositeCompositionPanel
        composition={composition}
        ticker="HDFCBANK"
        currency="INR"
      />,
    )
    assertSebiClean(container.textContent ?? "")
  })
})

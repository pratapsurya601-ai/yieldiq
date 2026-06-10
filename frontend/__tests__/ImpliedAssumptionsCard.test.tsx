/**
 * ImpliedAssumptionsCard — primitive tests (2026-06-10).
 *
 * Pins:
 *   1. Renders nothing when `implied` is null / undefined / missing the
 *      required headline value (legacy-payload back-compat).
 *   2. Renders the headline, label chip, plausibility meter, and
 *      consensus / trailing comparison rows when fully populated.
 *   3. Per-row self-hide: missing consensus shows "No analyst coverage";
 *      missing trailing CAGR shows "Insufficient history".
 *   4. Plausibility tone bands: score >= 70 -> emerald fill,
 *      30-69 -> amber, < 30 -> rose.
 *   5. Meter reflects the score via inline width %.
 *   6. SEBI vocabulary regression — the rendered DOM contains ZERO
 *      banned-vocabulary tokens regardless of label / score.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import ImpliedAssumptionsCard, {
  type ImpliedAssumptionsPayload,
} from "@/components/analysis/ImpliedAssumptionsCard"

// Per CLAUDE.md Standing Rule 5 Pattern B: build banned tokens at
// runtime from string concatenation so this file passes the
// --diff-only SEBI lint without per-line annotations.
const BANNED_RUNTIME_TOKENS = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "ac" + "cumulate",
  "ex" + "pensive",
  "ch" + "eap",
  "at" + "tractive",
  "reco" + "mmend",
  "out" + "perform",
  "under" + "perform",
]

beforeEach(() => {
  cleanup()
  // jsdom — light matchMedia stub for completeness; component does
  // not currently read it but defensive in case future polish lands.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
})

function makePayload(
  overrides: Partial<ImpliedAssumptionsPayload> = {},
): ImpliedAssumptionsPayload {
  return {
    implied_revenue_cagr_pct: 14.5,
    implied_terminal_growth_pct: 4.0,
    implied_margin_expansion_bps: 250,
    implied_wacc_pct: 11.5,
    consensus_revenue_cagr_pct: 9.0,
    growth_gap_pp: 5.5,
    market_expectation_label: "aggressive",
    plausibility_score: 50,
    headline:
      "Current price implies 14.5% CAGR vs consensus 9.0% -- aggressive",
    ...overrides,
  }
}

describe("ImpliedAssumptionsCard — render guards", () => {
  it("renders nothing when `implied` is null", () => {
    const { container } = render(<ImpliedAssumptionsCard implied={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when `implied` is undefined", () => {
    const { container } = render(
      <ImpliedAssumptionsCard implied={undefined} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when implied_revenue_cagr_pct is NaN", () => {
    const { container } = render(
      <ImpliedAssumptionsCard
        implied={makePayload({ implied_revenue_cagr_pct: Number.NaN })}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when implied_revenue_cagr_pct is missing", () => {
    // Cast through unknown to simulate a malformed payload from a stale
    // cached row — the component must still self-hide rather than
    // throw and crash the whole analysis page.
    const { container } = render(
      <ImpliedAssumptionsCard
        implied={
          {
            ...makePayload(),
            implied_revenue_cagr_pct: undefined,
          } as unknown as ImpliedAssumptionsPayload
        }
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe("ImpliedAssumptionsCard — populated payload", () => {
  it("renders headline value, chip, meter, and both comparison rows", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload()}
        trailingRevenueCagr={0.09}
      />,
    )
    expect(screen.getByTestId("implied-assumptions-card")).toBeInTheDocument()
    expect(
      screen.getByTestId("implied-assumptions-headline-value").textContent,
    ).toContain("14.5%")
    expect(screen.getByTestId("implied-assumptions-chip").textContent).toContain(
      "aggressive",
    )
    expect(
      screen.getByTestId("implied-assumptions-headline").textContent,
    ).toContain("consensus")
    // Both comparison rows render their values
    expect(
      screen.getByTestId("implied-assumptions-consensus").textContent,
    ).toContain("9.0%")
    expect(
      screen.getByTestId("implied-assumptions-trailing").textContent,
    ).toContain("9.0%")
    // Plausibility meter
    expect(screen.getByTestId("implied-assumptions-score").textContent).toContain(
      "50",
    )
    expect(screen.getByTestId("implied-assumptions-caption")).toBeInTheDocument()
  })

  it("renders solver echoes (WACC, terminal g, margin gap) when present", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload()}
        trailingRevenueCagr={0.09}
      />,
    )
    expect(screen.getByTestId("implied-assumptions-wacc").textContent).toContain(
      "11.5%",
    )
    expect(
      screen.getByTestId("implied-assumptions-terminal").textContent,
    ).toContain("4.0%")
    expect(
      screen.getByTestId("implied-assumptions-margin-bps").textContent,
    ).toContain("250")
  })

  it("self-hides margin gap echo when null", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload({ implied_margin_expansion_bps: null })}
      />,
    )
    expect(
      screen.queryByTestId("implied-assumptions-margin-bps"),
    ).not.toBeInTheDocument()
  })

  it("self-hides WACC echo when null", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload({ implied_wacc_pct: null })}
      />,
    )
    expect(
      screen.queryByTestId("implied-assumptions-wacc"),
    ).not.toBeInTheDocument()
  })
})

describe("ImpliedAssumptionsCard — per-row fallback copy", () => {
  it("renders 'No analyst coverage' when consensus is null", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload({
          consensus_revenue_cagr_pct: null,
          growth_gap_pp: null,
        })}
        trailingRevenueCagr={0.09}
      />,
    )
    expect(
      screen.getByTestId("implied-assumptions-consensus").textContent,
    ).toContain("No analyst coverage")
  })

  it("renders 'Insufficient history' when trailing CAGR is null", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload()}
        trailingRevenueCagr={null}
      />,
    )
    expect(
      screen.getByTestId("implied-assumptions-trailing").textContent,
    ).toContain("Insufficient history")
  })
})

describe("ImpliedAssumptionsCard — plausibility tone bands", () => {
  it("emerald band fills the meter for score >= 70", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload({ plausibility_score: 90 })}
      />,
    )
    const fill = screen.getByTestId("implied-assumptions-meter-fill")
    expect(fill.className).toMatch(/bg-emerald-/)
    expect((fill as HTMLElement).style.width).toBe("90%")
  })

  it("amber band fills the meter for 30 <= score < 70", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload({ plausibility_score: 50 })}
      />,
    )
    const fill = screen.getByTestId("implied-assumptions-meter-fill")
    expect(fill.className).toMatch(/bg-amber-/)
    expect((fill as HTMLElement).style.width).toBe("50%")
  })

  it("rose band fills the meter for score < 30", () => {
    render(
      <ImpliedAssumptionsCard
        implied={makePayload({ plausibility_score: 15 })}
      />,
    )
    const fill = screen.getByTestId("implied-assumptions-meter-fill")
    expect(fill.className).toMatch(/bg-rose-/)
    expect((fill as HTMLElement).style.width).toBe("15%")
  })

  it("clamps out-of-range scores to [0, 100]", () => {
    const { rerender } = render(
      <ImpliedAssumptionsCard
        implied={makePayload({ plausibility_score: -10 })}
      />,
    )
    let fill = screen.getByTestId("implied-assumptions-meter-fill")
    expect((fill as HTMLElement).style.width).toBe("0%")

    rerender(
      <ImpliedAssumptionsCard
        implied={makePayload({ plausibility_score: 500 })}
      />,
    )
    fill = screen.getByTestId("implied-assumptions-meter-fill")
    expect((fill as HTMLElement).style.width).toBe("100%")
  })
})

describe("ImpliedAssumptionsCard — SEBI regression", () => {
  it("renders zero banned vocabulary tokens for every label band", () => {
    const labels = ["modest", "moderate", "aggressive", "extreme"]
    for (const lbl of labels) {
      cleanup()
      render(
        <ImpliedAssumptionsCard
          implied={makePayload({
            market_expectation_label: lbl,
            // Update the headline so the label substring matches and we
            // exercise the headline render path with each label.
            headline: `Current price implies 14.5% CAGR -- ${lbl}`,
          })}
          trailingRevenueCagr={0.09}
        />,
      )
      const dom = screen
        .getByTestId("implied-assumptions-card")
        .textContent?.toLowerCase() ?? ""
      for (const banned of BANNED_RUNTIME_TOKENS) {
        expect(dom.includes(banned)).toBe(false)
      }
    }
  })
})

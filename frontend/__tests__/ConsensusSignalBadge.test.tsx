/**
 * ConsensusSignalBadge tests (2026-06-10).
 *
 * Covers:
 *   - Empty state (signal null / total_estimators 0) renders nothing.
 *   - Happy path: headline + level pill + summary chips render.
 *   - Breakdown is collapsed by default; toggle reveals the per-
 *     estimator list with the correct direction chips.
 *   - Tone classes follow (level, direction) — positive for
 *     very_high above_price, negative for very_high below_price,
 *     muted for dispersed.
 *   - Sanity warnings render when present.
 *   - SEBI guard — no banned advisory vocab in any rendered text,
 *     using fragment-built tokens (Pattern B per
 *     CLAUDE.md rule #5).
 */

import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"

import ConsensusSignalBadge, {
  type ConsensusSignal,
} from "@/components/analysis/ConsensusSignalBadge"


// ─────────────────────────────────────────────────────────────────
// SEBI vocab guard (Pattern B — fragments)
// ─────────────────────────────────────────────────────────────────
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


// ─────────────────────────────────────────────────────────────────
// Fixtures — mirror the backend shape exactly
// ─────────────────────────────────────────────────────────────────
function makeSignal(overrides: Partial<ConsensusSignal> = {}): ConsensusSignal {
  return {
    direction_agreement_count: 6,
    total_estimators: 7,
    direction_agreement_pct: 85.7,
    magnitude_clustering_cv: 0.12,
    consensus_level: "very_high",
    consensus_direction: "above_price",
    headline: "6 of 7 estimators agree: above current price",
    sanity_warnings: [],
    estimator_breakdown: [
      { name: "DCF", slot: "dcf", value: 1129, direction: "above_price" },
      { name: "Multiples", slot: "multiples", value: 1200, direction: "above_price" },
      { name: "Wall Street", slot: "analyst", value: 1150, direction: "above_price" },
      { name: "Three-stage", slot: "three_stage", value: 1080, direction: "above_price" },
      { name: "DDM", slot: "ddm", value: 1095, direction: "above_price" },
      { name: "EPV", slot: "epv", value: 1075, direction: "above_price" },
      { name: "Probability-weighted", slot: "probability_weighted", value: 850, direction: "below_price" },
    ],
    ...overrides,
  }
}


// ─────────────────────────────────────────────────────────────────
// Empty / null behaviour
// ─────────────────────────────────────────────────────────────────
describe("ConsensusSignalBadge — empty / null", () => {
  it("renders nothing when signal is null", () => {
    const { container } = render(<ConsensusSignalBadge signal={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when signal is undefined", () => {
    const { container } = render(<ConsensusSignalBadge signal={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when total_estimators is zero", () => {
    const { container } = render(
      <ConsensusSignalBadge
        signal={makeSignal({
          total_estimators: 0,
          direction_agreement_count: 0,
          estimator_breakdown: [],
          headline: "No estimators available for cross-engine consensus",
        })}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when total_estimators is missing", () => {
    const bad = {
      direction_agreement_count: 0,
    } as unknown as ConsensusSignal
    const { container } = render(<ConsensusSignalBadge signal={bad} />)
    expect(container).toBeEmptyDOMElement()
  })
})


// ─────────────────────────────────────────────────────────────────
// Happy path
// ─────────────────────────────────────────────────────────────────
describe("ConsensusSignalBadge — happy path", () => {
  it("renders the headline verbatim from the backend", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    const headline = screen.getByTestId("consensus-headline")
    expect(headline).toHaveTextContent(
      "6 of 7 estimators agree: above current price",
    )
  })

  it("renders the level pill", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    const pill = screen.getByTestId("consensus-level-pill")
    expect(pill).toHaveTextContent(/very high consensus/i)
  })

  it("renders the agreement summary chips", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    expect(screen.getByText("6/7")).toBeInTheDocument()
    expect(screen.getByText("86%")).toBeInTheDocument()
  })

  it("renders the magnitude CV chip when present", () => {
    render(<ConsensusSignalBadge signal={makeSignal({
      magnitude_clustering_cv: 0.23,
    })} />)
    expect(screen.getByText("0.23")).toBeInTheDocument()
  })

  it("omits the CV chip when CV is null", () => {
    render(<ConsensusSignalBadge signal={makeSignal({
      magnitude_clustering_cv: null,
    })} />)
    expect(screen.queryByText(/magnitude cv/i)).not.toBeInTheDocument()
  })
})


// ─────────────────────────────────────────────────────────────────
// Breakdown toggle
// ─────────────────────────────────────────────────────────────────
describe("ConsensusSignalBadge — breakdown toggle", () => {
  it("hides the breakdown list by default", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    expect(screen.queryByTestId("consensus-breakdown")).not.toBeInTheDocument()
  })

  it("shows the breakdown list after clicking the toggle", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    fireEvent.click(screen.getByRole("button", { name: /show details/i }))
    const list = screen.getByTestId("consensus-breakdown")
    expect(list).toBeInTheDocument()
    expect(list.children.length).toBe(7)
    // Spot-check a couple labels and direction chips render.
    expect(screen.getByText("DCF")).toBeInTheDocument()
    expect(screen.getByText("Probability-weighted")).toBeInTheDocument()
    // 6 chips read "above price", 1 reads "below price".
    expect(screen.getAllByText(/above price/i).length).toBe(6)
    expect(screen.getAllByText(/below price/i).length).toBe(1)
  })

  it("collapses the breakdown again after a second click", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    const toggle = screen.getByRole("button", { name: /show details/i })
    fireEvent.click(toggle)
    expect(screen.getByTestId("consensus-breakdown")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /hide details/i }))
    expect(screen.queryByTestId("consensus-breakdown")).not.toBeInTheDocument()
  })

  it("does not render the toggle when breakdown is empty", () => {
    render(
      <ConsensusSignalBadge
        signal={makeSignal({ estimator_breakdown: [] })}
      />,
    )
    expect(
      screen.queryByRole("button", { name: /details/i }),
    ).not.toBeInTheDocument()
  })
})


// ─────────────────────────────────────────────────────────────────
// Tone (color-coding)
// ─────────────────────────────────────────────────────────────────
describe("ConsensusSignalBadge — tone", () => {
  it("uses success tone for very_high + above_price", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    const root = screen.getByTestId("consensus-signal-badge")
    expect(root.className).toMatch(/success/)
  })

  it("uses danger tone for very_high + below_price", () => {
    render(<ConsensusSignalBadge signal={makeSignal({
      consensus_direction: "below_price",
      headline: "6 of 7 estimators agree: below current price",
    })} />)
    const root = screen.getByTestId("consensus-signal-badge")
    expect(root.className).toMatch(/danger/)
  })

  it("uses warning tone for high + near_price", () => {
    render(<ConsensusSignalBadge signal={makeSignal({
      consensus_level: "high",
      consensus_direction: "near_price",
      headline: "5 of 7 estimators agree: near current price",
    })} />)
    const root = screen.getByTestId("consensus-signal-badge")
    expect(root.className).toMatch(/warning/)
  })

  it("uses muted tone for dispersed signal", () => {
    render(<ConsensusSignalBadge signal={makeSignal({
      consensus_level: "dispersed",
      consensus_direction: "split",
      headline: "Estimators split across directions (3 of 7 lead)",
      direction_agreement_count: 3,
    })} />)
    const root = screen.getByTestId("consensus-signal-badge")
    // muted = generic ink token, no success/danger/warning
    expect(root.className).not.toMatch(/success/)
    expect(root.className).not.toMatch(/danger/)
    expect(root.className).not.toMatch(/warning/)
  })
})


// ─────────────────────────────────────────────────────────────────
// Sanity warnings
// ─────────────────────────────────────────────────────────────────
describe("ConsensusSignalBadge — sanity warnings", () => {
  it("renders each sanity warning when present", () => {
    render(
      <ConsensusSignalBadge
        signal={makeSignal({
          sanity_warnings: [
            "Only 2 estimators available; headline carries low confidence",
            "Estimator magnitudes vary widely (CV = 0.62)",
          ],
        })}
      />,
    )
    const list = screen.getByTestId("consensus-warnings")
    expect(list.children.length).toBe(2)
    expect(list).toHaveTextContent(/only 2 estimators/i)
    expect(list).toHaveTextContent(/low confidence/i)
    expect(list).toHaveTextContent(/vary widely/i)
  })

  it("omits the warnings list when empty", () => {
    render(<ConsensusSignalBadge signal={makeSignal()} />)
    expect(screen.queryByTestId("consensus-warnings")).not.toBeInTheDocument()
  })
})


// ─────────────────────────────────────────────────────────────────
// SEBI vocab guard on rendered text
// ─────────────────────────────────────────────────────────────────
describe("ConsensusSignalBadge — SEBI vocab", () => {
  it("contains no banned advisory vocab in the collapsed state", () => {
    const { container } = render(
      <ConsensusSignalBadge signal={makeSignal()} />,
    )
    assertSebiClean(container.textContent ?? "")
  })

  it("contains no banned advisory vocab when expanded", () => {
    const { container } = render(
      <ConsensusSignalBadge signal={makeSignal()} />,
    )
    fireEvent.click(screen.getByRole("button", { name: /show details/i }))
    assertSebiClean(container.textContent ?? "")
  })

  it("contains no banned advisory vocab on the negative tone path", () => {
    const { container } = render(
      <ConsensusSignalBadge signal={makeSignal({
        consensus_direction: "below_price",
        headline: "6 of 7 estimators agree: below current price",
      })} />,
    )
    assertSebiClean(container.textContent ?? "")
  })

  it("contains no banned vocab on the dispersed path", () => {
    const { container } = render(
      <ConsensusSignalBadge signal={makeSignal({
        consensus_level: "dispersed",
        consensus_direction: "split",
        headline: "Estimators split across directions (3 of 7 lead)",
        sanity_warnings: [
          "Top two direction buckets tied — no leading direction",
        ],
      })} />,
    )
    assertSebiClean(container.textContent ?? "")
  })
})

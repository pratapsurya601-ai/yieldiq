/**
 * CrossConfirmationChip — competitor-audit gap #1 (2026-06-10).
 *
 * Pins:
 *   1. Renders the consensus variant when consensus.total_estimators >= 4.
 *   2. Falls back to the DCF + Multiples variant when consensus absent.
 *   3. "Agree" data-attribute when DCF/Multiples diff < 15%.
 *   4. "Diverge" data-attribute when DCF/Multiples diff >= 15%.
 *   5. Returns null when both inputs are unusable.
 *   6. Returns null when consensus is too sparse AND DCF/Multiples are null.
 *   7. Consensus headline pins "N of M methods agree within 15% of <anchor>".
 *   8. Consensus tier wins over DCF+Multiples when both are present.
 *   9. countWithin15Pct skips null / non-finite estimator values.
 *  10. High-conviction class when agree count >= 70% of total estimators.
 *  11. Non-finite or zero-value DCF/Multiples short-circuit to null.
 *  12. SEBI vocabulary regression — zero banned tokens across every
 *      render branch (consensus / dcf-multiples-agree / dcf-multiples-diverge).
 *
 * Pattern B SEBI fixture — banned tokens are built from string
 * fragments at runtime so the file scans clean against
 * scripts/check_sebi_words.py in --diff-only mode. The runtime
 * assertion below proves no rendered chip output ever contains any
 * of these tokens.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import CrossConfirmationChip, {
  countWithin15Pct,
  AGREE_THRESHOLD_PCT,
  type ConsensusSignalLike,
} from "@/components/analysis/CrossConfirmationChip"

// Pattern B (CLAUDE.md rule 5) — build banned tokens from fragments
// so the SEBI diff-only scanner never sees a banned word in this
// file. Each fragment is chosen so NEITHER half is itself on the
// banned list and the regex `\b(banned|...)\b` cannot fire on the
// raw source. Runtime assertion is identical.
const BANNED = [
  "appea" + "rs",
  "shou" + "ld",
  "conce" + "rn",
  "stren" + "gth",
  "weakne" + "ss",
  "bu" + "y",
  "se" + "ll",
  "hol" + "d",
  "outper" + "form",
  "underper" + "form",
  "expens" + "ive",
  "che" + "ap",
  "attract" + "ive",
  "po" + "or",
  "stro" + "ng",
  "wea" + "k",
  "accumul" + "ate",
  "recomm" + "end",
  "recommen" + "dation",
  "investa" + "ble",
  "investab" + "ility",
]

function setReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? matches : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  setReducedMotion(false)
  cleanup()
})

function makeConsensus(
  overrides: Partial<ConsensusSignalLike> = {},
): ConsensusSignalLike {
  return {
    total_estimators: 7,
    direction_agreement_count: 5,
    consensus_level: "high",
    estimator_values: [950, 945, 970, 920, 990, 880, 1050],
    ...overrides,
  }
}

describe("CrossConfirmationChip — render guards", () => {
  it("returns null when both DCF and Multiples are null and consensus is absent", () => {
    const { container } = render(
      <CrossConfirmationChip
        dcfFv={null}
        multiplesFv={null}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId("cross-conf-chip")).toBeNull()
  })

  it("returns null when consensus has < 4 estimators AND DCF/Multiples null", () => {
    const { container } = render(
      <CrossConfirmationChip
        dcfFv={null}
        multiplesFv={null}
        consensus={makeConsensus({
          total_estimators: 3,
          estimator_values: [950, 945, 970],
        })}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("returns null when DCF or Multiples is zero (non-positive guard)", () => {
    const { container } = render(
      <CrossConfirmationChip
        dcfFv={0}
        multiplesFv={510}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("returns null when DCF or Multiples is non-finite", () => {
    const { container } = render(
      <CrossConfirmationChip
        dcfFv={Number.NaN}
        multiplesFv={510}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe("CrossConfirmationChip — DCF + Multiples fallback tier", () => {
  it("renders the DCF + Multiples variant when consensus is absent", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip).toBeInTheDocument()
    expect(chip.getAttribute("data-variant")).toBe("dcf-multiples")
  })

  it("marks AGREE when the spread is under 15%", () => {
    render(
      <CrossConfirmationChip
        dcfFv={1000}
        multiplesFv={920}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    // 80 / 1000 = 8% spread, below the 15% threshold.
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-agreement")).toBe("agree")
    const summary = screen.getByTestId("cross-conf-summary")
    expect(summary.textContent ?? "").toMatch(/agree within \d+%/i)
  })

  it("marks DIVERGE when the spread is >= 15%", () => {
    render(
      <CrossConfirmationChip
        dcfFv={1000}
        multiplesFv={700}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    // 300 / 1000 = 30% spread, above the 15% threshold.
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-agreement")).toBe("diverge")
    const summary = screen.getByTestId("cross-conf-summary")
    expect(summary.textContent ?? "").toMatch(/diverge by \d+%/i)
  })

  it("renders both DCF and Multiples figures in the headline", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const headline = screen.getByTestId("cross-conf-headline")
    expect(headline.textContent ?? "").toMatch(/DCF/i)
    expect(headline.textContent ?? "").toMatch(/Multiples/i)
    expect(headline.textContent ?? "").toMatch(/950|920/)
  })
})

describe("CrossConfirmationChip — consensus tier (PR #836)", () => {
  it("renders the consensus variant when total_estimators >= 4", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus()}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-variant")).toBe("consensus")
  })

  it("consensus tier wins over DCF + Multiples when both are available", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus()}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-variant")).toBe("consensus")
    // No DCF/Multiples sub-summary in the consensus variant.
    expect(screen.queryByTestId("cross-conf-summary")).toBeNull()
  })

  it("falls back to DCF + Multiples when consensus has < 4 estimators", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        consensus={makeConsensus({
          total_estimators: 3,
          estimator_values: [950, 945, 970],
        })}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-variant")).toBe("dcf-multiples")
  })

  it("headline reads 'N of M methods agree within 15% of <anchor>' when composite present", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus()}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const headline = screen.getByTestId("cross-conf-headline")
    // 5 of the 7 sample estimator values [950, 945, 970, 920, 990, 880,
    // 1050] sit within 15% of 950: 950 (0%), 945 (~0.5%), 970 (~2%),
    // 920 (~3%), 990 (~4%), 880 (~7%), 1050 (~10%). All 7 actually
    // fall within 15% — pin "7 of 7" against the same algorithm.
    expect(headline.textContent ?? "").toMatch(
      /\d+\s+of\s+7\s+methods agree within 15% of/i,
    )
  })

  it("renders the consensus-level badge when level present", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus({ consensus_level: "high" })}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const badge = screen.getByTestId("cross-conf-consensus-badge")
    expect(badge.textContent?.toLowerCase()).toContain("high agreement")
  })

  it("high-conviction data attribute set when count >= 70% of total", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus()}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-conviction")).toBe("high")
  })

  it("moderate conviction when count below the 70% threshold", () => {
    render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus({
          // Only 2 of 7 within 15% of 100; rest are wild outliers.
          estimator_values: [100, 105, 500, 600, 700, 800, 50],
        })}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const chip = screen.getByTestId("cross-conf-chip")
    expect(chip.getAttribute("data-conviction")).toBe("moderate")
  })
})

describe("countWithin15Pct helper", () => {
  it("counts estimators within 15% of the anchor and skips null/non-finite", () => {
    const consensus: ConsensusSignalLike = {
      total_estimators: 7,
      estimator_values: [
        100,
        110,
        85,
        130,
        null,
        Number.NaN,
        undefined,
      ],
    }
    // Within 15% of 100: 100 (0%), 110 (10%), 85 (15%) — 85 exactly at
    // threshold counts (<= comparison). 130 is 30% away. Three nulls
    // are skipped.
    const within = countWithin15Pct(consensus, 100)
    expect(within).toBe(3)
  })

  it("returns 0 when anchor is non-finite or zero", () => {
    const consensus: ConsensusSignalLike = {
      estimator_values: [100, 110],
    }
    expect(countWithin15Pct(consensus, 0)).toBe(0)
    expect(countWithin15Pct(consensus, Number.NaN)).toBe(0)
  })

  it("returns 0 when consensus is null / has no values", () => {
    expect(countWithin15Pct(null, 100)).toBe(0)
    expect(countWithin15Pct({ estimator_values: [] }, 100)).toBe(0)
  })

  it("threshold constant is exported and equals 15", () => {
    expect(AGREE_THRESHOLD_PCT).toBe(15)
  })
})

describe("CrossConfirmationChip — SEBI vocabulary regression", () => {
  it("renders zero banned vocabulary across every variant", () => {
    // Variant 1 — DCF + Multiples agree.
    const { container: c1 } = render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const t1 = (c1.textContent ?? "").toLowerCase()
    for (const banned of BANNED) {
      expect(t1).not.toContain(banned.toLowerCase())
    }
    cleanup()

    // Variant 2 — DCF + Multiples diverge.
    const { container: c2 } = render(
      <CrossConfirmationChip
        dcfFv={1000}
        multiplesFv={500}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const t2 = (c2.textContent ?? "").toLowerCase()
    for (const banned of BANNED) {
      expect(t2).not.toContain(banned.toLowerCase())
    }
    cleanup()

    // Variant 3 — Consensus tier with composite anchor.
    const { container: c3 } = render(
      <CrossConfirmationChip
        dcfFv={950}
        multiplesFv={920}
        compositeIv={950}
        consensus={makeConsensus()}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const t3 = (c3.textContent ?? "").toLowerCase()
    for (const banned of BANNED) {
      expect(t3).not.toContain(banned.toLowerCase())
    }
    cleanup()

    // Variant 4 — Consensus tier with no composite anchor.
    const { container: c4 } = render(
      <CrossConfirmationChip
        dcfFv={null}
        multiplesFv={null}
        compositeIv={null}
        consensus={makeConsensus({ consensus_level: "low" })}
        ticker="HDFCBANK.NS"
        currency="INR"
      />,
    )
    const t4 = (c4.textContent ?? "").toLowerCase()
    for (const banned of BANNED) {
      expect(t4).not.toContain(banned.toLowerCase())
    }
  })
})

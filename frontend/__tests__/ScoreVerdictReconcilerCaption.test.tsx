/**
 * ScoreVerdictReconcilerCaption tests
 * (v_score_verdict_divergence_caption_2026_06_10).
 *
 * Covers:
 *   - Self-hides when divergence prop is null / undefined (legacy payloads).
 *   - Self-hides when diverges is false (aligned signals).
 *   - Self-hides when explanation is missing / empty / whitespace.
 *   - Renders for HDFCBANK-shape (score 40 + verdict undervalued) and
 *     for premium-compounder shape (score 80 + verdict overvalued).
 *   - SEBI guard — no banned advisory vocabulary in any rendered text
 *     (Pattern B per CLAUDE.md rule #5).
 */

import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"

import ScoreVerdictReconcilerCaption, {
  type ScoreVerdictDivergence,
} from "@/components/analysis/ScoreVerdictReconcilerCaption"


// ── SEBI vocab guard (Pattern B per CLAUDE.md rule #5) ──────────────
const BANNED_FRAGMENTS = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "re" + "commend",
  "sho" + "uld",
  "che" + "ap",
  "expen" + "sive",
  "att" + "ractive",
  "investa" + "ble",
  "out" + "perform",
  "under" + "perform",
  "accumu" + "late",
  "con" + "cern",
  "appe" + "ars",
  "po" + "or",
]


function assertSebiClean(text: string): void {
  const lowered = text.toLowerCase()
  for (const fragment of BANNED_FRAGMENTS) {
    expect(lowered).not.toContain(fragment)
  }
}


// ── fixtures shaped like the backend payload ─────────────────────────


function hdfcbankShape(): ScoreVerdictDivergence {
  return {
    score_percentile: 40,
    verdict_signal: "undervalued",
    diverges: true,
    explanation:
      "Quality blend reads 40 of 100. Valuation verdict reads " +
      "Undervalued. The two answer different questions: business " +
      "quality (ROE, moat, margins, growth) versus price vs intrinsic " +
      "value today. Both readings are informational.",
  }
}


function premiumCompounderShape(): ScoreVerdictDivergence {
  return {
    score_percentile: 80,
    verdict_signal: "overvalued",
    diverges: true,
    explanation:
      "Quality blend reads 80 of 100. Valuation verdict reads " +
      "Overvalued. The two answer different questions: business " +
      "quality (ROE, moat, margins, growth) versus price vs intrinsic " +
      "value today. Both readings are informational.",
  }
}


function alignedBullShape(): ScoreVerdictDivergence {
  return {
    score_percentile: 75,
    verdict_signal: "undervalued",
    diverges: false,
    explanation:
      "Quality blend reads 75 of 100. Valuation verdict reads " +
      "Undervalued. Both signals point the same way.",
  }
}


// ── self-hide branches ──────────────────────────────────────────────


describe("ScoreVerdictReconcilerCaption — self-hide branches", () => {
  it("renders nothing when divergence is null", () => {
    const { container } = render(
      <ScoreVerdictReconcilerCaption divergence={null} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when divergence is undefined (legacy payload)", () => {
    const { container } = render(
      <ScoreVerdictReconcilerCaption divergence={undefined} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when diverges is false (signals aligned)", () => {
    const { container } = render(
      <ScoreVerdictReconcilerCaption divergence={alignedBullShape()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when diverges is missing", () => {
    const { container } = render(
      <ScoreVerdictReconcilerCaption
        divergence={{
          score_percentile: 40,
          verdict_signal: "undervalued",
          explanation: "...",
        }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when explanation is empty / whitespace", () => {
    const { container: a } = render(
      <ScoreVerdictReconcilerCaption
        divergence={{ ...hdfcbankShape(), explanation: "" }}
      />,
    )
    expect(a.firstChild).toBeNull()

    const { container: b } = render(
      <ScoreVerdictReconcilerCaption
        divergence={{ ...hdfcbankShape(), explanation: "   " }}
      />,
    )
    expect(b.firstChild).toBeNull()

    const { container: c } = render(
      <ScoreVerdictReconcilerCaption
        divergence={{ ...hdfcbankShape(), explanation: null }}
      />,
    )
    expect(c.firstChild).toBeNull()
  })
})


// ── render branches ─────────────────────────────────────────────────


describe("ScoreVerdictReconcilerCaption — render branches", () => {
  it("renders for HDFCBANK shape (score 40 + undervalued verdict)", () => {
    render(<ScoreVerdictReconcilerCaption divergence={hdfcbankShape()} />)
    const node = screen.getByTestId("score-verdict-reconciler-caption")
    expect(node).toBeInTheDocument()
    expect(node).toHaveAttribute("data-diverges", "true")

    const scoreChip = screen.getByTestId("score-verdict-reconciler-caption-score")
    expect(scoreChip).toHaveTextContent("Score 40 / 100")

    const explanation = screen.getByTestId(
      "score-verdict-reconciler-caption-explanation",
    )
    expect(explanation).toHaveTextContent(/40 of 100/i)
    expect(explanation).toHaveTextContent(/Undervalued/i)
    expect(explanation).toHaveTextContent(/different questions/i)
  })

  it("renders for premium-compounder shape (score 80 + overvalued)", () => {
    render(
      <ScoreVerdictReconcilerCaption divergence={premiumCompounderShape()} />,
    )
    const node = screen.getByTestId("score-verdict-reconciler-caption")
    expect(node).toBeInTheDocument()
    const explanation = screen.getByTestId(
      "score-verdict-reconciler-caption-explanation",
    )
    expect(explanation).toHaveTextContent(/80 of 100/i)
    expect(explanation).toHaveTextContent(/Overvalued/i)
  })

  it("omits the score chip when score_percentile is null", () => {
    render(
      <ScoreVerdictReconcilerCaption
        divergence={{ ...hdfcbankShape(), score_percentile: null }}
      />,
    )
    expect(
      screen.queryByTestId("score-verdict-reconciler-caption-score"),
    ).not.toBeInTheDocument()
    // But the explanation still renders.
    expect(
      screen.getByTestId("score-verdict-reconciler-caption-explanation"),
    ).toBeInTheDocument()
  })

  it("carries an aria-label and note role for assistive tech", () => {
    render(<ScoreVerdictReconcilerCaption divergence={hdfcbankShape()} />)
    const node = screen.getByTestId("score-verdict-reconciler-caption")
    expect(node).toHaveAttribute("role", "note")
    expect(node).toHaveAttribute(
      "aria-label",
      expect.stringMatching(/score.*verdict/i),
    )
  })

  it("passes through extra className", () => {
    render(
      <ScoreVerdictReconcilerCaption
        divergence={hdfcbankShape()}
        className="lg:mt-8"
      />,
    )
    const node = screen.getByTestId("score-verdict-reconciler-caption")
    expect(node.className).toContain("lg:mt-8")
  })
})


// ── SEBI guard on rendered DOM ──────────────────────────────────────


describe("ScoreVerdictReconcilerCaption — SEBI vocab guard", () => {
  it("rendered DOM is free of banned advisory tokens (HDFCBANK shape)", () => {
    const { container } = render(
      <ScoreVerdictReconcilerCaption divergence={hdfcbankShape()} />,
    )
    assertSebiClean(container.textContent ?? "")
  })

  it("rendered DOM is free of banned advisory tokens (premium shape)", () => {
    const { container } = render(
      <ScoreVerdictReconcilerCaption divergence={premiumCompounderShape()} />,
    )
    assertSebiClean(container.textContent ?? "")
  })
})

// __tests__/prismNarrative.test.ts
// Covers every branch of generatePrismNarrative() including the
// default fall-through. Order matters — earlier rules win when
// multiple thresholds overlap.

import { describe, it, expect } from "vitest"

import {
  axesFromPillars,
  generatePrismNarrative,
  type PrismAxes,
} from "@/lib/prismNarrative"

function axes(over: Partial<PrismAxes>): PrismAxes {
  return {
    pulse: 5,
    quality: 5,
    moat: 5,
    safety: 5,
    growth: 5,
    value: 5,
    ...over,
  }
}

describe("generatePrismNarrative", () => {
  it("rule 1 — quality>=7 AND value>=7 → both-above-7 frame", () => {
    expect(generatePrismNarrative(axes({ quality: 8, value: 7.5 }))).toBe(
      "Quality and value pillars both score above 7.",
    )
  })

  it("rule 2 — quality>=7 AND growth>=7 → compounder frame", () => {
    expect(generatePrismNarrative(axes({ quality: 9, growth: 8 }))).toBe(
      "Quality and growth pillars both score above 7.",
    )
  })

  it("rule 3 — growth>=7 AND value<=4 → growth-vs-value-split frame", () => {
    expect(generatePrismNarrative(axes({ growth: 8, value: 3 }))).toBe(
      "Growth scores above 7 while value sits at or below 4.",
    )
  })

  it("rule 4 — moat>=7 AND safety>=7 → defensive moat frame", () => {
    expect(generatePrismNarrative(axes({ moat: 8, safety: 8 }))).toBe(
      "Moat and safety pillars both score above 7.",
    )
  })

  it("rule 5 — quality>=7 AND value<=4 → quality-vs-value-split frame", () => {
    expect(generatePrismNarrative(axes({ quality: 8, value: 3 }))).toBe(
      "Quality scores above 7 while value sits at or below 4.",
    )
  })

  it("rule 6 — value>=7 AND quality<=4 → value-vs-quality-split frame", () => {
    expect(generatePrismNarrative(axes({ value: 8, quality: 3 }))).toBe(
      "Value scores above 7 while quality sits at or below 4.",
    )
  })

  it("rule 7 — safety<=4 AND growth>=6 → growth-vs-safety-split frame", () => {
    expect(generatePrismNarrative(axes({ safety: 3, growth: 7 }))).toBe(
      "Growth is above 6 while safety sits at or below 4.",
    )
  })

  it("rule 8 — safety<=3 alone → stress-signal frame", () => {
    expect(generatePrismNarrative(axes({ safety: 2, growth: 4 }))).toBe(
      "Safety pillar is at or below 3 — review the risks below.",
    )
  })

  it("rule 9 — growth<=3 AND value>=6 → value-vs-growth-split frame", () => {
    expect(generatePrismNarrative(axes({ growth: 2, value: 7 }))).toBe(
      "Value is above 6 while growth sits at or below 3.",
    )
  })

  // Bug 8 (P2, 2026-06-09): the rule-10 fall-through used to be a
  // single sentence ("A balanced profile across the six pillars.")
  // that fired regardless of actual pillar variance — confirmed
  // misfiring on HDFCBANK whose pillars spanned 2..8. Replaced with
  // three variance-keyed sub-cases.
  describe("rule 10 fall-through — variance-discriminated", () => {
    it("tight cluster (range < 1.5) → tightly-balanced copy", () => {
      // All six axes at 5.0 — range = 0.
      expect(generatePrismNarrative(axes({}))).toBe(
        "Tightly balanced — every pillar within 1.5 of the others.",
      )
    })

    it("moderate spread (1.5 <= range < 3.0) → mostly-balanced with leader/trailer", () => {
      // value=6.5 leader, growth=4.5 trailer, range = 2.0. None of
      // the explicit threshold rules trip (no axis >= 7 and no axis
      // <= 4) so we land in the fall-through.
      const out = generatePrismNarrative(
        axes({ value: 6.5, growth: 4.5, quality: 5, moat: 5, safety: 5 }),
      )
      expect(out).toBe("Mostly balanced — Value leads at 6.5, Growth trails at 4.5.")
    })

    it("wide spread (range >= 3.0) → uneven-across-pillars with leader/lagger", () => {
      // moat=6.5 leader, value=3.5 lagger, range = 3.0. None of the
      // explicit threshold rules trip (need >= 7 / <= 3 etc.) so the
      // fall-through runs.
      const out = generatePrismNarrative(
        axes({ moat: 6.5, value: 3.5, quality: 5, growth: 5, safety: 5 }),
      )
      expect(out).toBe("Moat leads (6.5) while Value lags (3.5) — uneven across pillars.")
    })

    it("never returns the old generic balanced copy", () => {
      // Regression: any fall-through must NOT emit the bare
      // "A balanced profile across the six pillars." string —
      // that was the audit-flagged copy on HDFCBANK.
      const banned = "A balanced profile across the six pillars."
      const samples: PrismAxes[] = [
        { pulse: 5, quality: 5, moat: 5, safety: 5, growth: 5, value: 5 },
        { pulse: 4, quality: 5, moat: 5, safety: 5, growth: 5, value: 6 },
        { pulse: 6, quality: 6.5, moat: 5, safety: 5, growth: 4.5, value: 5 },
        { pulse: 3, quality: 5.5, moat: 6.5, safety: 5, growth: 4, value: 5 },
      ]
      for (const a of samples) {
        expect(generatePrismNarrative(a)).not.toBe(banned)
      }
    })
  })

  it("priority — earlier rules win when multiple match", () => {
    // quality>=7 & value>=7 also satisfies rule 2 (growth=8 here) and
    // rule 4 (moat=8). Rule 1 must win.
    expect(
      generatePrismNarrative(
        axes({ quality: 8, value: 8, growth: 8, moat: 8 }),
      ),
    ).toBe("Quality and value pillars both score above 7.")
  })
})

describe("axesFromPillars", () => {
  it("maps pillar array → axes object", () => {
    const a = axesFromPillars([
      { key: "pulse", score: 6 },
      { key: "quality", score: 8 },
      { key: "moat", score: 7 },
      { key: "safety", score: 5 },
      { key: "growth", score: 4 },
      { key: "value", score: 3 },
    ])
    expect(a).toEqual({
      pulse: 6,
      quality: 8,
      moat: 7,
      safety: 5,
      growth: 4,
      value: 3,
    })
  })

  it("coerces null/missing scores to 5 (neutral)", () => {
    const a = axesFromPillars([
      { key: "quality", score: null },
      { key: "value", score: 9 },
      // safety / moat / growth / pulse missing entirely
    ])
    expect(a.quality).toBe(5)
    expect(a.value).toBe(9)
    expect(a.safety).toBe(5)
    expect(a.moat).toBe(5)
    expect(a.growth).toBe(5)
    expect(a.pulse).toBe(5)
  })
})

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

  it("rule 10 — default balanced fall-through", () => {
    expect(generatePrismNarrative(axes({}))).toBe(
      "A balanced profile across the six pillars.",
    )
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

/**
 * True (Buffett) Margin of Safety helper contract test (2026-06-14).
 *
 * Pins the two canonical helpers that the MoS-headline rollout depends
 * on, so the ~25 display surfaces cannot fork their own arithmetic:
 *
 *   computeTrueMos(fv, price)  = (1 − price/fv) × 100   [FV + price in scope]
 *   trueMosFromUpside(upside)  = upside / (1 + upside/100) [upside-% only]
 *
 * The two MUST agree for the same stock — that algebraic identity is the
 * whole reason peer/screener surfaces (which carry only the upside-%
 * field) can show the same true MoS as the hero (which has FV + price).
 */
import { describe, it, expect } from "vitest"

import { computeTrueMos, trueMosFromUpside } from "@/lib/utils"

describe("computeTrueMos", () => {
  it("computes (1 − price/fv) × 100", () => {
    // FV 1.8× price → +65% upside, but only ~44.4% true MoS.
    expect(computeTrueMos(180, 100)).toBeCloseTo(44.444, 2)
    // FV 3× price → +200% upside, ~66.7% true MoS (still < 100).
    expect(computeTrueMos(300, 100)).toBeCloseTo(66.667, 2)
    // At fair value → 0% MoS.
    expect(computeTrueMos(100, 100)).toBeCloseTo(0, 6)
  })

  it("goes negative (unbounded) when overvalued", () => {
    // Price 2× FV → −100% MoS.
    expect(computeTrueMos(100, 200)).toBeCloseTo(-100, 6)
    expect(computeTrueMos(100, 300)).toBeCloseTo(-200, 6)
  })

  it("never exceeds +100% for any positive price", () => {
    expect(computeTrueMos(1_000_000, 1)).toBeLessThan(100)
    expect(computeTrueMos(1_000_000, 1)).toBeGreaterThan(99.9)
  })

  it("returns null for missing / non-positive inputs", () => {
    expect(computeTrueMos(null, 100)).toBeNull()
    expect(computeTrueMos(100, null)).toBeNull()
    expect(computeTrueMos(undefined, 100)).toBeNull()
    expect(computeTrueMos(0, 100)).toBeNull()
    expect(computeTrueMos(100, 0)).toBeNull()
    expect(computeTrueMos(-100, 100)).toBeNull()
    expect(computeTrueMos(NaN, 100)).toBeNull()
    expect(computeTrueMos(Infinity, 100)).toBeNull()
  })
})

describe("trueMosFromUpside", () => {
  it("matches the algebraic identity trueMos = upside / (1 + upside/100)", () => {
    expect(trueMosFromUpside(65)).toBeCloseTo(39.394, 2)
    expect(trueMosFromUpside(200)).toBeCloseTo(66.667, 2)
    expect(trueMosFromUpside(0)).toBeCloseTo(0, 6)
    // Negative (overvalued) upside maps to a more-negative true MoS.
    expect(trueMosFromUpside(-50)).toBeCloseTo(-100, 6)
  })

  it("agrees with computeTrueMos for the same stock", () => {
    // FV 180, price 100 → upside +80%.
    const fv = 180
    const price = 100
    const upside = ((fv - price) / price) * 100
    expect(trueMosFromUpside(upside)).toBeCloseTo(
      computeTrueMos(fv, price) as number,
      6,
    )
  })

  it("returns null for null / non-finite input or degenerate upside ≤ −100", () => {
    expect(trueMosFromUpside(null)).toBeNull()
    expect(trueMosFromUpside(undefined)).toBeNull()
    expect(trueMosFromUpside(NaN)).toBeNull()
    // upside −100 ⇒ FV 0 ⇒ identity degenerates (denominator 0).
    expect(trueMosFromUpside(-100)).toBeNull()
    expect(trueMosFromUpside(-150)).toBeNull()
  })
})

/**
 * FeeImpactCalculator — pure fee-math + SEBI-vocab guard tests.
 *
 * The math helpers are the high-risk surface: a fee calculator that
 * renders ₹NaN or diverges from a standard SIP calculator destroys
 * trust instantly. These assertions pin:
 *   - the lump-sum sanity anchors (must reproduce the live page exactly),
 *   - a hand-checked annuity-due SIP corpus,
 *   - the i≈0 (no-growth) and years=0 guards,
 *   - blank/NaN mid-edit inputs never producing NaN.
 *
 * The SEBI-vocab assertion mirrors __tests__/TaxEfficiencyCalculator:
 * the rendered DOM must contain none of the regulator-banned imperative
 * tokens. The BANNED array is built from fragments at runtime so the
 * diff-only sebi-lint scan stays clean (CLAUDE.md Pattern B).
 */
import { describe, expect, it } from "vitest"
import { render } from "@testing-library/react"

import FeeImpactCalculator, {
  lumpSumFutureValue,
  sipFutureValue,
  sipTotalInvested,
  safeNum,
} from "@/app/(app)/funds/[scheme_code]/FeeImpactCalculator"

describe("lumpSumFutureValue — sanity anchors", () => {
  // Anchor from the live page: ₹36,000 · 20y · 12% gross ·
  // Direct 0.62 / Regular 1.21 → 3,47,267 / 3,10,775 / 2,79,456.
  it("reproduces the No-fees / Direct / Regular anchors", () => {
    expect(Math.round(lumpSumFutureValue(36000, 12, 20))).toBe(347267)
    expect(Math.round(lumpSumFutureValue(36000, 12 - 0.62, 20))).toBe(310775)
    expect(Math.round(lumpSumFutureValue(36000, 12 - 1.21, 20))).toBe(279456)
  })

  it("returns the principal unchanged at years=0", () => {
    expect(lumpSumFutureValue(100000, 12, 0)).toBe(100000)
  })

  it("stays finite for a negative net return", () => {
    const v = lumpSumFutureValue(100000, -5, 10)
    expect(Number.isFinite(v)).toBe(true)
    expect(v).toBeLessThan(100000)
  })

  it("treats a NaN return as zero (never NaN corpus)", () => {
    expect(lumpSumFutureValue(100000, Number.NaN, 10)).toBe(100000)
  })
})

describe("sipFutureValue — annuity-due (start-of-month)", () => {
  // Hand-checked: ₹5,000/mo · 10y · 12% net, contribution at the START
  // of each month. Standard begin-of-period SIP corpus ≈ ₹11,20,179.
  it("matches the hand-checked 10y / 12% corpus", () => {
    expect(Math.round(sipFutureValue(5000, 12, 10))).toBe(1120179)
  })

  it("uses the no-growth limit P×n when the rate is ≈0", () => {
    // net 0% → monthly rate ≈ 0 → FV must equal total contributions.
    expect(sipFutureValue(5000, 0, 10)).toBe(600000)
  })

  it("returns 0 at years=0 (no months, no NaN)", () => {
    expect(sipFutureValue(5000, 12, 0)).toBe(0)
  })

  it("stays finite for a negative net return", () => {
    const v = sipFutureValue(5000, -5, 10)
    expect(Number.isFinite(v)).toBe(true)
    expect(v).toBeGreaterThan(0)
  })

  it("treats a NaN monthly contribution as zero", () => {
    expect(sipFutureValue(Number.NaN, 12, 10)).toBe(0)
  })

  it("rounds fractional years to whole months", () => {
    // 0.5y → round(6) months; still finite and positive.
    const v = sipFutureValue(5000, 12, 0.5)
    expect(Number.isFinite(v)).toBe(true)
    expect(v).toBeGreaterThan(0)
  })
})

describe("sipTotalInvested", () => {
  it("is P × months", () => {
    expect(sipTotalInvested(5000, 10)).toBe(600000)
    expect(sipTotalInvested(5000, 0)).toBe(0)
  })
})

describe("safeNum", () => {
  it("coerces non-finite to 0 and passes finite through", () => {
    expect(safeNum(Number.NaN)).toBe(0)
    expect(safeNum(Number.POSITIVE_INFINITY)).toBe(0)
    expect(safeNum(42)).toBe(42)
  })
})

describe("derived fee figures", () => {
  it("fee drag and Direct-vs-Regular gap are non-negative in both modes", () => {
    const gross = 12
    const lumpZero = lumpSumFutureValue(100000, gross, 10)
    const lumpDirect = lumpSumFutureValue(100000, gross - 0.5, 10)
    const lumpRegular = lumpSumFutureValue(100000, gross - 1.5, 10)
    expect(lumpZero - lumpDirect).toBeGreaterThan(0)
    expect(lumpDirect - lumpRegular).toBeGreaterThan(0)

    const sipZero = sipFutureValue(5000, gross, 10)
    const sipDirect = sipFutureValue(5000, gross - 0.5, 10)
    const sipRegular = sipFutureValue(5000, gross - 1.5, 10)
    expect(sipZero - sipDirect).toBeGreaterThan(0)
    expect(sipDirect - sipRegular).toBeGreaterThan(0)
  })
})

describe("SEBI vocabulary guard", () => {
  it("renders no regulator-banned imperative vocabulary", () => {
    const { container } = render(
      <FeeImpactCalculator terDirect={0.62} terRegular={1.21} />,
    )
    const text = (container.textContent || "").toLowerCase()
    // Mirrors scripts/check_sebi_words.py BANNED_WORDS (the imperative /
    // verdict tokens this component must never render). Built from
    // fragments so the diff-only sebi-lint scan stays clean (CLAUDE.md
    // Pattern B). Word-boundary tested to match the linter's \b semantics.
    // "advice" is intentionally absent — the honest "Not advice."
    // disclaimer is SEBI-clean and ships in the live component.
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "rec" + "ommend",
      "sh" + "ould",
      "accumu" + "late",
      "outper" + "form",
      "attrac" + "tive",
      "expen" + "sive",
      "che" + "ap",
    ]
    for (const term of BANNED) {
      expect(new RegExp(`\\b${term}\\b`).test(text)).toBe(false)
    }
  })

  it("renders no ₹NaN with default prefilled inputs", () => {
    const { container } = render(
      <FeeImpactCalculator terDirect={0.62} terRegular={1.21} />,
    )
    expect(container.textContent || "").not.toContain("NaN")
  })
})

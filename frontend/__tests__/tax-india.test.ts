/**
 * tax-india.ts unit tests.
 *
 * Pins:
 *   1. classifyHolding boundary at 12 months.
 *   2. STCG rate × cess on a clean gain.
 *   3. LTCG ₹1L exemption: zero tax up to ₹1L, then 10%+cess on the surplus.
 *   4. Pre-exhausted exemption: LTCG taxes the full gain.
 *   5. Capital loss → zero tax under both regimes.
 *   6. preTaxReturn / postTaxReturn agree on gain ratio.
 *   7. annualiseReturn matches CAGR formula for whole-year holds.
 *   8. formatRate handles sign + decimals + non-finite.
 */

import { describe, it, expect } from "vitest"

import {
  classifyHolding,
  computeCapitalGainsTax,
  preTaxReturn,
  postTaxReturn,
  annualiseReturn,
  formatRate,
  LTCG_THRESHOLD_MONTHS,
  LTCG_ANNUAL_EXEMPTION_INR,
  STCG_RATE,
  LTCG_RATE,
  CESS_RATE,
} from "@/lib/tax-india"

describe("classifyHolding", () => {
  it("returns stcg below the 12-month threshold", () => {
    expect(classifyHolding(0)).toBe("stcg")
    expect(classifyHolding(11.9)).toBe("stcg")
  })

  it("returns ltcg at and beyond the threshold", () => {
    expect(classifyHolding(LTCG_THRESHOLD_MONTHS)).toBe("ltcg")
    expect(classifyHolding(36)).toBe("ltcg")
  })

  it("treats invalid input as stcg (most conservative)", () => {
    expect(classifyHolding(Number.NaN)).toBe("stcg")
    expect(classifyHolding(-5)).toBe("stcg")
  })
})

describe("computeCapitalGainsTax — STCG path", () => {
  it("charges 15% + 4% cess on the gain", () => {
    // Entry 1000 → Exit 2000, held 6 months. Gain = 1000.
    const t = computeCapitalGainsTax(1000, 2000, 6)
    expect(t.regime).toBe("stcg")
    expect(t.gain).toBe(1000)
    expect(t.taxableGain).toBe(1000)
    expect(t.baseTax).toBeCloseTo(1000 * STCG_RATE, 6) // 150
    expect(t.cess).toBeCloseTo(150 * CESS_RATE, 6) // 6
    expect(t.totalTax).toBeCloseTo(156, 6)
    expect(t.netGain).toBeCloseTo(1000 - 156, 6)
    expect(t.effectiveRate).toBeCloseTo(156 / 1000, 6) // 0.156
  })
})

describe("computeCapitalGainsTax — LTCG path", () => {
  it("zero tax when the LTCG gain is fully within the ₹1L exemption", () => {
    // 50k gain, held 18 months — under the ₹1L exemption.
    const t = computeCapitalGainsTax(100_000, 150_000, 18)
    expect(t.regime).toBe("ltcg")
    expect(t.gain).toBe(50_000)
    expect(t.taxableGain).toBe(0)
    expect(t.totalTax).toBe(0)
    expect(t.netGain).toBe(50_000)
  })

  it("taxes only the surplus above the exemption", () => {
    // Gain = ₹1.5L → taxable surplus = ₹50k → tax = 50k×10%×1.04 = 5200.
    const t = computeCapitalGainsTax(500_000, 650_000, 18)
    expect(t.regime).toBe("ltcg")
    expect(t.taxableGain).toBe(50_000)
    expect(t.baseTax).toBeCloseTo(50_000 * LTCG_RATE, 6) // 5000
    expect(t.cess).toBeCloseTo(5000 * CESS_RATE, 6) // 200
    expect(t.totalTax).toBeCloseTo(5200, 6)
    expect(t.netGain).toBeCloseTo(150_000 - 5200, 6)
  })

  it("treats already-used exemption from other positions correctly", () => {
    // Same ₹1.5L gain but ₹1L exemption already consumed elsewhere this FY.
    const t = computeCapitalGainsTax(500_000, 650_000, 18, {
      exemptionUsed: LTCG_ANNUAL_EXEMPTION_INR,
    })
    expect(t.taxableGain).toBe(150_000)
    expect(t.baseTax).toBeCloseTo(15_000, 6)
    expect(t.cess).toBeCloseTo(600, 6)
    expect(t.totalTax).toBeCloseTo(15_600, 6)
  })

  it("partial exemption used: deducts only the remaining ₹40k", () => {
    // ₹60k already used → ₹40k exemption remaining.
    // Gain ₹1L → taxable ₹60k → tax = 60k×10%×1.04 = 6240.
    const t = computeCapitalGainsTax(200_000, 300_000, 18, {
      exemptionUsed: 60_000,
    })
    expect(t.taxableGain).toBe(60_000)
    expect(t.totalTax).toBeCloseTo(6_240, 6)
  })
})

describe("computeCapitalGainsTax — capital loss", () => {
  it("zero tax on a STCG-window loss", () => {
    const t = computeCapitalGainsTax(2000, 1500, 6)
    expect(t.gain).toBe(-500)
    expect(t.totalTax).toBe(0)
    expect(t.netGain).toBe(-500)
    expect(t.effectiveRate).toBe(0)
  })

  it("zero tax on an LTCG-window loss", () => {
    const t = computeCapitalGainsTax(2000, 1500, 24)
    expect(t.regime).toBe("ltcg")
    expect(t.totalTax).toBe(0)
  })
})

describe("preTaxReturn / postTaxReturn", () => {
  it("preTaxReturn returns 0 on degenerate entry", () => {
    expect(preTaxReturn(0, 100)).toBe(0)
    expect(preTaxReturn(-50, 100)).toBe(0)
  })

  it("postTaxReturn is strictly less than preTaxReturn when there is a taxed gain", () => {
    const pre = preTaxReturn(1000, 2000)
    const post = postTaxReturn(1000, 2000, 6) // STCG
    expect(pre).toBeGreaterThan(post)
    // Post-tax delta must be exactly the cess-adjusted STCG drag.
    expect(pre - post).toBeCloseTo(STCG_RATE * (1 + CESS_RATE), 6)
  })

  it("LTCG within exemption yields post-tax == pre-tax", () => {
    const pre = preTaxReturn(100_000, 150_000)
    const post = postTaxReturn(100_000, 150_000, 18)
    expect(pre).toBeCloseTo(post, 9)
  })
})

describe("annualiseReturn", () => {
  it("matches the standard CAGR formula for whole-year holds", () => {
    // 21% over 2 years annualises to sqrt(1.21) − 1 ≈ 0.10.
    const a = annualiseReturn(0.21, 24)
    expect(a).toBeCloseTo(Math.sqrt(1.21) - 1, 6)
  })

  it("returns the raw return when holdingMonths is zero", () => {
    expect(annualiseReturn(0.15, 0)).toBe(0.15)
  })
})

describe("formatRate", () => {
  it("renders positive rates with a leading + and one decimal by default", () => {
    expect(formatRate(0.1234)).toBe("+12.3%")
  })

  it("renders negative rates with their native sign", () => {
    expect(formatRate(-0.045)).toBe("-4.5%")
  })

  it("renders zero without a sign", () => {
    expect(formatRate(0)).toBe("0.0%")
  })

  it("returns the em-dash sentinel for non-finite input", () => {
    expect(formatRate(Number.NaN)).toBe("—")
    expect(formatRate(Number.POSITIVE_INFINITY)).toBe("—")
  })
})

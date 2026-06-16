import { describe, it, expect } from "vitest"
import {
  annualizeReturn,
  formatAnnualizedPct,
  formatTrailingReturn,
  RETURN_WINDOW_YEARS,
} from "@/lib/fund-annualize"

describe("fund-annualize", () => {
  describe("annualizeReturn", () => {
    it("passes the 1Y window through unchanged (×100, no de-compounding)", () => {
      // 0.088 cumulative over 1y is already a one-year return → 8.8%.
      expect(annualizeReturn(0.088, 1)).toBeCloseTo(8.8, 6)
      expect(annualizeReturn(0.088, RETURN_WINDOW_YEARS.ret_1y)).toBeCloseTo(8.8, 6)
    })

    it("annualizes a 3Y cumulative 0.77 to ~21.0% p.a.", () => {
      // (1.77)^(1/3) − 1 = 0.20996… → ≈21.0% per annum.
      const v = annualizeReturn(0.77, 3)
      expect(v).not.toBeNull()
      expect(v as number).toBeCloseTo(21.0, 1)
    })

    it("annualizes a 5Y cumulative below its cumulative percent", () => {
      // A 100% total over 5 years is far less than 100%/yr — ~14.87% p.a.
      const v = annualizeReturn(1.0, 5)
      expect(v as number).toBeCloseTo(14.87, 1)
    })

    it("returns null for null / undefined input", () => {
      expect(annualizeReturn(null, 3)).toBeNull()
      expect(annualizeReturn(undefined, 5)).toBeNull()
    })

    it("returns null for non-finite input", () => {
      expect(annualizeReturn(NaN, 3)).toBeNull()
      expect(annualizeReturn(Infinity, 3)).toBeNull()
    })

    it("guards (1 + cumulative) <= 0 (total loss) by returning null", () => {
      // 1 + (−1) = 0 → n-th root undefined for display.
      expect(annualizeReturn(-1, 5)).toBeNull()
      // 1 + (−1.2) = −0.2 → negative base, would be NaN/imaginary.
      expect(annualizeReturn(-1.2, 3)).toBeNull()
    })

    it("handles a negative-but-survivable multi-year return", () => {
      // −0.27 cumulative over 3y → 1.73^(? no): (0.73)^(1/3) − 1 ≈ −9.9%/yr.
      const v = annualizeReturn(-0.27, 3)
      expect(v as number).toBeCloseTo(-9.97, 1)
    })
  })

  describe("formatAnnualizedPct", () => {
    it("renders a null as an em dash", () => {
      expect(formatAnnualizedPct(null)).toBe("—")
    })

    it("signs positives with + and negatives with a real minus", () => {
      expect(formatAnnualizedPct(21.0)).toBe("+21.0%")
      expect(formatAnnualizedPct(-9.97)).toBe("−10.0%")
    })

    it("renders exactly zero without a sign", () => {
      expect(formatAnnualizedPct(0)).toBe("0.0%")
    })
  })

  describe("formatTrailingReturn", () => {
    it("annualizes then formats in one call (3Y 0.77 → +21.0%)", () => {
      expect(formatTrailingReturn(0.77, 3)).toBe("+21.0%")
    })

    it("renders a null cumulative as an em dash", () => {
      expect(formatTrailingReturn(null, 5)).toBe("—")
    })

    it("renders a total-loss guard as an em dash", () => {
      expect(formatTrailingReturn(-1, 5)).toBe("—")
    })
  })
})

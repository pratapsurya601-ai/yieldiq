import { describe, it, expect } from "vitest"
import {
  computeFairValue,
  dcfFactor,
  calibrateFromTwoAnchors,
  calibrateFromSingleAnchor,
} from "@/lib/dcfClient"

const DEFAULT_INPUTS = {
  wacc: 0.11,
  terminal_growth: 0.04,
  revenue_cagr_yr1_5: 0.10,
  operating_margin: 0.20,
  tax_rate: 0.25,
}

describe("dcfClient", () => {
  describe("dcfFactor", () => {
    it("is monotonically decreasing in WACC", () => {
      const a = dcfFactor(0.08, 0.04, 0.10)
      const b = dcfFactor(0.12, 0.04, 0.10)
      const c = dcfFactor(0.15, 0.04, 0.10)
      expect(a).toBeGreaterThan(b)
      expect(b).toBeGreaterThan(c)
    })

    it("is monotonically increasing in revenue CAGR", () => {
      const a = dcfFactor(0.11, 0.04, 0.05)
      const b = dcfFactor(0.11, 0.04, 0.10)
      const c = dcfFactor(0.11, 0.04, 0.20)
      expect(a).toBeLessThan(b)
      expect(b).toBeLessThan(c)
    })

    it("is monotonically increasing in terminal growth", () => {
      const a = dcfFactor(0.11, 0.02, 0.10)
      const b = dcfFactor(0.11, 0.05, 0.10)
      expect(a).toBeLessThan(b)
    })

    it("clamps when WACC drops to terminal-growth band (no blow-up)", () => {
      // wacc - tg < 0.02 triggers the snap; result must stay finite
      const f = dcfFactor(0.07, 0.07, 0.10)
      expect(Number.isFinite(f)).toBe(true)
      expect(f).toBeGreaterThan(0)
    })
  })

  describe("computeFairValue", () => {
    const calib = {
      fcfPerShareBase: 80,
      netDebtPerShare: 20,
      baseMargin: 0.20,
      baseTax: 0.25,
    }

    it("returns 0 on degenerate (FV < 0) corner", () => {
      const fv = computeFairValue(
        {
          ...DEFAULT_INPUTS,
          wacc: 0.15,
          revenue_cagr_yr1_5: -0.05,
          operating_margin: 0.0,
        },
        calib,
      )
      expect(fv).toBe(0)
    })

    it("scales linearly with FCF base (sanity)", () => {
      const fvA = computeFairValue(DEFAULT_INPUTS, {
        ...calib,
        netDebtPerShare: 0,
      })
      const fvB = computeFairValue(DEFAULT_INPUTS, {
        ...calib,
        fcfPerShareBase: 160,
        netDebtPerShare: 0,
      })
      expect(fvB).toBeCloseTo(fvA * 2, 5)
    })

    it("higher margin → higher FV", () => {
      const fvLow = computeFairValue(
        { ...DEFAULT_INPUTS, operating_margin: 0.10 },
        calib,
      )
      const fvHigh = computeFairValue(
        { ...DEFAULT_INPUTS, operating_margin: 0.30 },
        calib,
      )
      expect(fvHigh).toBeGreaterThan(fvLow)
    })

    it("higher tax rate → lower FV", () => {
      const fvLow = computeFairValue(
        { ...DEFAULT_INPUTS, tax_rate: 0.10 },
        calib,
      )
      const fvHigh = computeFairValue(
        { ...DEFAULT_INPUTS, tax_rate: 0.40 },
        calib,
      )
      expect(fvLow).toBeGreaterThan(fvHigh)
    })
  })

  describe("calibrateFromTwoAnchors", () => {
    it("round-trips a known calibration", () => {
      const truth = {
        fcfPerShareBase: 100,
        netDebtPerShare: 25,
        baseMargin: 0.20,
        baseTax: 0.25,
      }
      const inputsA = DEFAULT_INPUTS
      const inputsB = { ...DEFAULT_INPUTS, wacc: 0.13 }
      const fvA = computeFairValue(inputsA, truth)
      const fvB = computeFairValue(inputsB, truth)
      const recovered = calibrateFromTwoAnchors(
        { inputs: inputsA, fairValue: fvA },
        { inputs: inputsB, fairValue: fvB },
      )
      expect(recovered).not.toBeNull()
      expect(recovered!.fcfPerShareBase).toBeCloseTo(100, 2)
      expect(recovered!.netDebtPerShare).toBeCloseTo(25, 2)
    })

    it("returns null when the two factors are degenerate", () => {
      const out = calibrateFromTwoAnchors(
        { inputs: DEFAULT_INPUTS, fairValue: 1000 },
        { inputs: DEFAULT_INPUTS, fairValue: 1000 },
      )
      expect(out).toBeNull()
    })
  })

  describe("calibrateFromSingleAnchor", () => {
    it("recovers FCF base assuming zero net debt", () => {
      const inputs = DEFAULT_INPUTS
      const fv = 1000
      const calib = calibrateFromSingleAnchor({ inputs, fairValue: fv })
      expect(calib.netDebtPerShare).toBe(0)
      // Recompute at the same inputs matches the anchor exactly.
      const fvBack = computeFairValue(inputs, calib)
      expect(fvBack).toBeCloseTo(fv, 4)
    })
  })
})

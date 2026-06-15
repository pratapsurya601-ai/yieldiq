/**
 * FundCard formatting + name-normalization unit tests (WS2).
 *
 * Pure-logic tests over the exported helpers — no React render, so they
 * run in the default node environment (the jsdom render path is unrelated
 * here).
 *
 * The headline regression these lock down: TER is stored in PERCENT
 * (e.g. 1.06 = 1.06%) since the AMFI TER ingestion pipeline landed, but
 * the card formatter used to ×100 it (a leftover from when TER was a
 * decimal fraction), so a 1.06% fund rendered as "106.0%". fmtTerPct must
 * render TER verbatim with a single "%" and guard against any future
 * ×100 unit regression.
 */
// @vitest-environment node
import { describe, expect, it } from "vitest"

import {
  fmtTerPct,
  fmtReturnPct,
  normalizeFundName,
} from "@/app/(app)/funds/FundCard"

describe("fmtTerPct — expense ratio is already PERCENT (never ×100)", () => {
  it("renders a 1.06 TER as 1.06% (never 106.0%)", () => {
    const out = fmtTerPct(1.06)
    expect(out).toBe("1.06%")
    expect(out).not.toBe("106.0%")
    expect(out).not.toBe("106.00%")
  })

  it("renders sub-1% TERs verbatim", () => {
    expect(fmtTerPct(0.62)).toBe("0.62%") // Parag Parikh Flexi Cap (Direct)
    expect(fmtTerPct(0.09)).toBe("0.09%") // a low-TER index fund
    expect(fmtTerPct(1.21)).toBe("1.21%") // Parag Parikh Flexi Cap (Regular)
  })

  it("never renders a TER above ~3% as a real expense ratio", () => {
    // AMFI TERs live in roughly [0, 3]%. A ×100 regression would push
    // every value far past this; the guard suppresses it (null) rather
    // than printing an absurd number.
    for (const realTer of [0.09, 0.5, 0.62, 1.06, 1.21, 2.25]) {
      const out = fmtTerPct(realTer)
      expect(out).not.toBeNull()
      const pct = parseFloat(out as string)
      expect(pct).toBeLessThanOrEqual(3)
    }
  })

  it("suppresses (null) out-of-range / missing values rather than ×100-ing them", () => {
    expect(fmtTerPct(106)).toBeNull() // a stale ×100 value
    expect(fmtTerPct(0)).toBeNull()
    expect(fmtTerPct(-1)).toBeNull()
    expect(fmtTerPct(Number.NaN)).toBeNull()
    expect(fmtTerPct(Number.POSITIVE_INFINITY)).toBeNull()
  })
})

describe("fmtReturnPct — trailing return is a DECIMAL fraction (×100)", () => {
  it("scales a decimal fraction to a signed percent", () => {
    expect(fmtReturnPct(0.088, true)).toBe("+8.8%")
    expect(fmtReturnPct(-0.019382, true)).toBe("-1.9%")
    expect(fmtReturnPct(0, true)).toBe("0.0%")
  })

  it("omits the sign when withSign is false", () => {
    expect(fmtReturnPct(0.088, false)).toBe("8.8%")
  })
})

describe("normalizeFundName — strips stacked plan/option noise + Title-Cases", () => {
  it("clears the real stacked AMFI tail (Direct Plan Growth Plan - Growth Option)", () => {
    expect(
      normalizeFundName(
        "Nippon India Large Cap Fund - Direct Plan Growth Plan - Growth Option",
      ),
    ).toBe("Nippon India Large Cap Fund")
    expect(
      normalizeFundName(
        "Nippon India Large Cap Fund - Direct Plan Growth Plan - Bonus Option",
      ),
    ).toBe("Nippon India Large Cap Fund")
    expect(
      normalizeFundName("Nippon India Small Cap Fund - Direct Plan Growth Plan"),
    ).toBe("Nippon India Small Cap Fund")
  })

  it("clears the clean tail and Title-Cases ALL-CAPS names", () => {
    expect(normalizeFundName("AXIS BLUECHIP FUND - DIRECT PLAN - GROWTH")).toBe(
      "Axis Bluechip Fund",
    )
    expect(normalizeFundName("HDFC TOP 100 FUND - DIRECT PLAN - GROWTH")).toBe(
      "HDFC Top 100 Fund",
    )
  })

  it("leaves no residual ALL-CAPS word in the output", () => {
    const names = [
      "SBI BLUECHIP FUND - DIRECT PLAN - GROWTH",
      "ICICI PRUDENTIAL VALUE DISCOVERY FUND - DIRECT PLAN - IDCW",
      "QUANT ELSS TAX SAVER FUND - DIRECT PLAN - GROWTH",
    ]
    for (const n of names) {
      const out = normalizeFundName(n)
      for (const word of out.split(/\s+/)) {
        // A word is allowed to be all-uppercase ONLY if it's a known
        // acronym (HDFC, SBI, ICICI, ELSS, IDCW, …) or has digits.
        const isAllCaps = word.length > 1 && word === word.toUpperCase() && /[A-Z]/.test(word)
        const isAcronymOrNumeric =
          /\d/.test(word) ||
          ["HDFC", "SBI", "ICICI", "ELSS", "IDCW", "PSU", "ETF", "UTI"].includes(word)
        if (isAllCaps) {
          expect(isAcronymOrNumeric).toBe(true)
        }
      }
    }
  })

  it("preserves a legitimate sub-plan token (Nifty 50 Plan)", () => {
    expect(
      normalizeFundName(
        "Nippon India Index Fund - Nifty 50 Plan - Direct Plan Growth Plan - Growth Option",
      ),
    ).toBe("Nippon India Index Fund - NIFTY 50 Plan")
  })

  it("never blanks out a name", () => {
    expect(normalizeFundName("Direct Plan Growth")).not.toBe("")
    expect(normalizeFundName("")).toBe("")
  })
})

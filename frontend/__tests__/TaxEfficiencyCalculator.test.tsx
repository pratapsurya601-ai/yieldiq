/**
 * TaxEfficiencyCalculator — regression guards.
 *
 * Pins:
 *   1. Renders sliders, inputs, headline metrics, and both regime cards.
 *   2. Below the 12-month slider: STCG card flagged active.
 *   3. At/above 12 months: LTCG card flagged active and shows the
 *      ₹1L-exemption benefit (lower tax owed than STCG on the same gain).
 *   4. Loss scenario: zero tax across both regimes, capital-loss note
 *      renders.
 *   5. Effective rate at 6 months matches 15% × (1 + 4% cess) = 15.6%.
 *   6. Effective rate after the ₹1L exemption is exhausted matches
 *      10% × 1.04 = 10.4% on the surplus.
 *   7. SEBI vocab: zero banned tokens leak into the rendered DOM. The
 *      banned-token fixture is built from string fragments at runtime
 *      so the diff-only SEBI lint pass stays clean (CLAUDE.md §5
 *      Pattern B).
 */

import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"

import TaxEfficiencyCalculator from "@/components/analysis/TaxEfficiencyCalculator"

const BASE_PROPS = {
  ticker: "HDFCBANK.NS",
  currency: "INR",
  entryDefault: 1000,
  currentPrice: 2000,
}

function renderCalc(overrides: Partial<typeof BASE_PROPS> = {}) {
  return render(<TaxEfficiencyCalculator {...BASE_PROPS} {...overrides} />)
}

function setSlider(testId: string, value: number) {
  const input = screen.getByTestId(testId) as HTMLInputElement
  fireEvent.change(input, { target: { value: String(value) } })
}

function setInput(testId: string, value: string) {
  const input = screen.getByTestId(testId) as HTMLInputElement
  fireEvent.change(input, { target: { value } })
}

describe("TaxEfficiencyCalculator — rendering", () => {
  it("renders all primary controls and side-by-side cards", () => {
    renderCalc()
    expect(screen.getByTestId("tax-efficiency-calculator")).toBeTruthy()
    expect(screen.getByTestId("tax-entry-input")).toBeTruthy()
    expect(screen.getByTestId("tax-exit-input")).toBeTruthy()
    expect(screen.getByTestId("tax-qty-input")).toBeTruthy()
    expect(screen.getByTestId("tax-months-slider")).toBeTruthy()
    expect(screen.getByTestId("tax-regime-banner")).toBeTruthy()
    expect(screen.getByTestId("tax-regime-card-stcg")).toBeTruthy()
    expect(screen.getByTestId("tax-regime-card-ltcg")).toBeTruthy()
    expect(screen.getByTestId("tax-efficiency-footnote")).toBeTruthy()
  })

  it("seeds entry/exit inputs from props", () => {
    renderCalc()
    expect(
      (screen.getByTestId("tax-entry-input") as HTMLInputElement).value,
    ).toBe("1000.00")
    expect(
      (screen.getByTestId("tax-exit-input") as HTMLInputElement).value,
    ).toBe("2000.00")
  })
})

describe("TaxEfficiencyCalculator — regime activation", () => {
  it("under 12 months: STCG card is active, LTCG is not", () => {
    renderCalc()
    setSlider("tax-months-slider", 6)
    expect(
      screen.getByTestId("tax-regime-card-stcg").getAttribute("data-active"),
    ).toBe("true")
    expect(
      screen.getByTestId("tax-regime-card-ltcg").getAttribute("data-active"),
    ).toBe("false")
  })

  it("at 12 months: LTCG card is active", () => {
    renderCalc()
    setSlider("tax-months-slider", 12)
    expect(
      screen.getByTestId("tax-regime-card-ltcg").getAttribute("data-active"),
    ).toBe("true")
    expect(
      screen.getByTestId("tax-regime-card-stcg").getAttribute("data-active"),
    ).toBe("false")
  })
})

describe("TaxEfficiencyCalculator — math correctness", () => {
  it("STCG 6 months @ 100 shares × (1000 → 2000) yields 15.6% effective rate", () => {
    renderCalc()
    setSlider("tax-months-slider", 6)
    // 100 shares × ₹1000 gain = ₹100,000 gain. STCG tax = 100k × 15% × 1.04 = ₹15,600.
    // Effective = 15.6%.
    const eff = screen.getByTestId("tax-stcg-eff").textContent ?? ""
    expect(eff).toMatch(/15\.6%/)
  })

  it("LTCG: ₹1L exemption shows zero tax when gain ≤ ₹1L", () => {
    renderCalc({ entryDefault: 100, currentPrice: 150 })
    // 100 shares × (150-100) = ₹5000 gain. Under ₹1L exemption.
    setInput("tax-entry-input", "100")
    setInput("tax-exit-input", "150")
    setSlider("tax-months-slider", 18)
    const owed = screen.getByTestId("tax-ltcg-owed").textContent ?? ""
    expect(owed).toMatch(/₹\s*0/) // formatCurrency renders "₹0" for zero
  })

  it("LTCG surplus above exemption taxed at 10.4% effective", () => {
    renderCalc()
    // 100 × (1000→2000) = ₹100k gain — exactly at the exemption.
    // Bump exit to 3000 → ₹200k gain → ₹100k surplus → tax = ₹10,400.
    setInput("tax-exit-input", "3000")
    setSlider("tax-months-slider", 18)
    const owed = screen.getByTestId("tax-ltcg-owed").textContent ?? ""
    // Currency formatter may render as ₹10,400 / ₹10.4K / ₹0.10L depending
    // on the magnitude bucket. Cross-check via the effective-rate field:
    // 10,400 / 200,000 = 5.2% overall, but the displayed effective rate is
    // tax / gain = 10400/200000 = 5.2%. (Effective rate on full gain, not
    // on surplus.) The LTCG-on-surplus rate is 10.4%; the SHOWN effective
    // rate dilutes via the exemption — that's exactly the user-facing pin.
    const eff = screen.getByTestId("tax-ltcg-eff").textContent ?? ""
    expect(eff).toMatch(/5\.2%/)
    expect(owed.replace(/[,\s]/g, "")).toMatch(/10400|10\.4K|0\.10L|10K/i)
  })

  it("Loss scenario: both regimes show zero tax and the loss note appears", () => {
    renderCalc()
    setInput("tax-entry-input", "2000")
    setInput("tax-exit-input", "1500")
    setSlider("tax-months-slider", 6)
    expect(screen.getByTestId("tax-stcg-owed").textContent).toMatch(/₹\s*0/)
    expect(screen.getByTestId("tax-ltcg-owed").textContent).toMatch(/₹\s*0/)
    expect(screen.getByTestId("tax-loss-note")).toBeTruthy()
  })
})

describe("TaxEfficiencyCalculator — slider interactivity", () => {
  it("slider readout updates as user drags", () => {
    renderCalc()
    setSlider("tax-months-slider", 24)
    expect(screen.getByTestId("tax-months-readout").textContent).toMatch(
      /24\s*months/,
    )
  })

  it("annualised post-tax is hidden when months = 0", () => {
    renderCalc()
    setSlider("tax-months-slider", 0)
    expect(screen.getByTestId("tax-annualised-post").textContent).toBe("—")
  })
})

describe("TaxEfficiencyCalculator — SEBI guard", () => {
  it("renders zero banned vocabulary tokens", () => {
    // Pattern B from CLAUDE.md §5 — banned tokens built at runtime
    // from string fragments so diff-only SEBI lint over this test
    // file stays clean.
    const BANNED: string[] = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "appe" + "ars",
      "sho" + "uld",
      "con" + "cern",
      "stren" + "gth",
      "wea" + "kness",
      "outperf" + "orm",
      "underperf" + "orm",
      "expen" + "sive",
      "che" + "ap",
      "attrac" + "tive",
      "po" + "or",
      "stro" + "ng",
      "we" + "ak",
      "accumu" + "late",
      "recomm" + "end",
      "recomm" + "endation",
      "invest" + "able",
      "invest" + "ability",
    ]

    renderCalc()
    setSlider("tax-months-slider", 18)

    // Word-boundary match — same rule as scripts/check_sebi_words.py, so
    // legitimate substrings like "holding period" (contains "hold") and
    // "Bharti Airtel" (contains "rti") don't false-positive.
    const text = document.body.textContent?.toLowerCase() ?? ""
    for (const word of BANNED) {
      const lc = word.toLowerCase()
      const re = new RegExp(`\\b${lc.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`)
      expect(
        re.test(text),
        `banned token "${word}" leaked into rendered DOM`,
      ).toBe(false)
    }
  })
})

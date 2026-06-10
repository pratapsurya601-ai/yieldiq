/**
 * Tests for the public /discount-rate-calculator page (T6.1).
 *
 * Surfaces under test:
 *
 *   1. Page renders without crashing — hero copy, formula card, footer
 *      disclaimer all present.
 *   2. Sector selector lists ALL 14 calibrated defaults.
 *   3. Default WACC headline matches the live computation for the
 *      initially selected sector (IT Services). The brief tolerates a
 *      ±0.5pp band — we assert the rendered text falls inside it.
 *   4. Changing sector to "Banks" updates the displayed WACC headline.
 *   5. "Notable cases" section renders all three example tickers.
 *   6. SEBI vocab guard — the rendered DOM must not contain any of the
 *      banned tokens. Per root CLAUDE.md rule #5 the BANNED array is
 *      built from string fragments at runtime (Pattern B) so this
 *      test file itself is scan-clean under sebi-lint --diff-only.
 *   7. Footer disclaimer copy is present.
 */

import { describe, it, expect, beforeEach } from "vitest"
import { render, fireEvent, screen, within } from "@testing-library/react"

// The page module is an RSC with `generateMetadata` + force-static. We
// render the default-exported component as a plain function call — RTL
// handles the server-component-shape just fine because nothing in this
// page invokes server-only APIs (no fetch, no headers, no cookies). The
// interactive Calculator below it is a client component and gets
// hydrated as normal.
import DiscountRateCalculatorPage from "@/app/(marketing)/discount-rate-calculator/page"
import { SECTOR_DEFAULTS } from "@/app/(marketing)/discount-rate-calculator/Calculator"

// ──────────────────────────────────────────────────────────────────────
// SEBI banned-token list — Pattern B (root CLAUDE.md rule #5).
// Built from string fragments at runtime so the diff-only lint scan
// over this file does NOT see the banned tokens as literals. The
// runtime assertion is identical to a literal array.
// ──────────────────────────────────────────────────────────────────────
const SEBI_BANNED: readonly string[] = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "rec" + "ommend",
  "sho" + "uld",
  "outper" + "form",
  "underper" + "form",
  "accumu" + "late",
  "attra" + "ctive",
  "che" + "ap",
  "expen" + "sive",
  "we" + "ak",
  "stro" + "ng",
  "appe" + "ars",
  "conc" + "ern",
  "underva" + "lued",
  "overva" + "lued",
]

function assertNoBannedTokens(container: HTMLElement) {
  const haystack = (container.textContent ?? "").toLowerCase()
  for (const token of SEBI_BANNED) {
    const re = new RegExp(`\\b${token}\\b`, "i")
    expect(
      re.test(haystack),
      `Rendered DOM contains SEBI-banned token "${token}"`,
    ).toBe(false)
  }
}

// ──────────────────────────────────────────────────────────────────────
// Math oracle — mirror the in-component WACC formula so the test
// expectation is computed from the same defaults the component ships
// rather than a hard-coded magic number. If the defaults move, this
// test still passes; if the FORMULA breaks, this test catches it.
// ──────────────────────────────────────────────────────────────────────
const DEFAULT_RISK_FREE = 0.071
const DEFAULT_ERP = 0.075

function expectedWaccPct(sector: keyof typeof SECTOR_DEFAULTS): number {
  const d = SECTOR_DEFAULTS[sector]
  const ke = DEFAULT_RISK_FREE + d.beta * DEFAULT_ERP
  const atKd = d.costOfDebt * (1 - d.taxRate)
  const wacc = d.debtRatio * atKd + (1 - d.debtRatio) * ke
  return wacc * 100
}

describe("DiscountRateCalculatorPage", () => {
  let container: HTMLElement

  beforeEach(() => {
    container = render(<DiscountRateCalculatorPage />).container
  })

  it("renders the hero with H1 + the WACC formula", () => {
    const h1 = container.querySelector("h1")
    expect(h1).not.toBeNull()
    expect(h1?.textContent).toContain("WACC Calculator")
    const text = container.textContent ?? ""
    // Formula is rendered as monospaced copy in the hero card.
    expect(text).toContain("WACC =")
    expect(text).toContain("Ke = Rf")
  })

  it("renders all 14 calibrated sectors in the selector", () => {
    const select = container.querySelector(
      "#sector-select",
    ) as HTMLSelectElement
    expect(select).not.toBeNull()
    const optionTexts = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent ?? "",
    )
    const expected = Object.keys(SECTOR_DEFAULTS)
    expect(optionTexts.length).toBe(expected.length)
    for (const sector of expected) {
      expect(optionTexts).toContain(sector)
    }
  })

  it("renders a default WACC for IT Services within ±0.5pp of the formula", () => {
    const output = screen.getByTestId("wacc-output")
    const raw = output.textContent ?? ""
    const match = raw.match(/([0-9]+(?:\.[0-9]+)?)%/)
    expect(match, `expected percent in headline, got: ${raw}`).not.toBeNull()
    const renderedPct = Number(match![1])
    const expected = expectedWaccPct("IT Services")
    expect(
      Math.abs(renderedPct - expected),
      `IT Services WACC ${renderedPct}% ≠ formula ${expected.toFixed(2)}%`,
    ).toBeLessThanOrEqual(0.5)
  })

  it("updates the displayed WACC when the sector changes to Banks", () => {
    const select = container.querySelector(
      "#sector-select",
    ) as HTMLSelectElement
    const output = screen.getByTestId("wacc-output")
    const before = output.textContent ?? ""

    fireEvent.change(select, { target: { value: "Banks" } })

    const after = output.textContent ?? ""
    expect(after).not.toBe(before)
    const match = after.match(/([0-9]+(?:\.[0-9]+)?)%/)
    expect(match, `expected percent after sector change: ${after}`).not.toBeNull()
    const renderedPct = Number(match![1])
    const expected = expectedWaccPct("Banks")
    expect(Math.abs(renderedPct - expected)).toBeLessThanOrEqual(0.5)
  })

  it("renders the 'Notable cases' section with HDFCBANK, TCS, TATASTEEL", () => {
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (h) => h.textContent ?? "",
    )
    expect(headings).toContain("Notable cases")

    // Each ticker is included in the rendered prose.
    const text = container.textContent ?? ""
    expect(text).toContain("HDFCBANK")
    expect(text).toContain("TCS")
    expect(text).toContain("TATASTEEL")
  })

  it("renders the footer disclaimer copy", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("Damodaran India 2026")
    expect(text).toContain("calibrated defaults")
    expect(text).toContain("educational use only")
  })

  it("rendered DOM is SEBI-clean (no banned vocabulary tokens)", () => {
    assertNoBannedTokens(container)
  })

  it("changing sector then checking each option does not introduce banned vocab", () => {
    const select = container.querySelector(
      "#sector-select",
    ) as HTMLSelectElement
    for (const sector of Object.keys(SECTOR_DEFAULTS)) {
      fireEvent.change(select, { target: { value: sector } })
      assertNoBannedTokens(container)
    }
  })

  it("hero links out to methodology and accuracy backtest pages", () => {
    const links = Array.from(container.querySelectorAll("a")).map(
      (a) => a.getAttribute("href") ?? "",
    )
    expect(links).toContain("/methodology")
    expect(links).toContain("/methodology/accuracy")
    expect(links).toContain("/how-it-works")
  })

  it("breakdown card lists each WACC component", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("Cost of equity")
    expect(text).toContain("After-tax cost of debt")
    expect(text).toContain("Equity weight")
    expect(text).toContain("Debt weight")
    expect(text).toContain("Final WACC")
  })

  it("each sector option renders a numerically valid WACC headline", () => {
    const select = container.querySelector(
      "#sector-select",
    ) as HTMLSelectElement
    const output = screen.getByTestId("wacc-output")
    for (const sector of Object.keys(SECTOR_DEFAULTS) as Array<
      keyof typeof SECTOR_DEFAULTS
    >) {
      fireEvent.change(select, { target: { value: sector } })
      const txt = output.textContent ?? ""
      const m = txt.match(/([0-9]+(?:\.[0-9]+)?)%/)
      expect(m, `bad WACC headline for ${sector}: ${txt}`).not.toBeNull()
      const pct = Number(m![1])
      // Sanity bounds: a WACC under 0 or over 30% suggests a formula bug.
      expect(pct).toBeGreaterThan(0)
      expect(pct).toBeLessThan(30)
      const expected = expectedWaccPct(sector)
      expect(
        Math.abs(pct - expected),
        `${sector}: rendered ${pct}% vs formula ${expected.toFixed(2)}%`,
      ).toBeLessThanOrEqual(0.5)
    }
    void within // satisfy import — kept for symmetry with RTL conventions
  })
})

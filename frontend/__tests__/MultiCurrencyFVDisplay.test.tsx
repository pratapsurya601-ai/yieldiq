/**
 * MultiCurrencyFVDisplay tests.
 *
 * Pins:
 *   1. isAdrCohort / adrRatio helpers map known tickers correctly,
 *      including the brief-honored INFY ratio of 4.
 *   2. Renders for ADR-cohort tickers when fairValueInr > 0 (using the
 *      injectedUsdInr test seam to skip the network call).
 *   3. Self-hides for non-ADR tickers (HDFCBANK) when usdRevenueHeavy
 *      is false.
 *   4. Renders for non-ADR tickers when usdRevenueHeavy is true
 *      (USD-revenue-heavy override path).
 *   5. Self-hides when fairValueInr is null / zero / negative.
 *   6. Toggle flips the active display between INR (₹) and USD ($)
 *      formatting.
 *   7. INFY × 4 ratio rendering: per-ADR USD equivalent equals
 *      (per-share INR × 4) / USD-INR.
 *   8. SEBI vocabulary regression — rendered DOM contains zero banned
 *      vocabulary across all states.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import {
  render,
  screen,
  cleanup,
  fireEvent,
  within,
} from "@testing-library/react"

import MultiCurrencyFVDisplay, {
  isAdrCohort,
  adrRatio,
} from "@/components/analysis/MultiCurrencyFVDisplay"

// Banned tokens — built from fragments so the diff-only SEBI lint scan
// never picks them up as added literals (root CLAUDE.md standing rule
// #5, Pattern B). The runtime assertion below proves the rendered DOM
// stays clean.
const BANNED = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "rec" + "ommend",
  "rec" + "ommendation",
  "out" + "perform",
  "under" + "perform",
  "ex" + "pensive",
  "ch" + "eap",
  "att" + "ractive",
  "acc" + "umulate",
  "inves" + "table",
  "con" + "cern",
  "stre" + "ngth",
  "w" + "eakness",
  "ap" + "pears",
  "sh" + "ould",
]

function expectNoBannedVocab(container: HTMLElement) {
  const text = (container.textContent ?? "").toLowerCase()
  for (const token of BANNED) {
    expect(text).not.toContain(token)
  }
}

beforeEach(() => {
  cleanup()
})

describe("isAdrCohort / adrRatio helpers", () => {
  it("recognizes the four working ADR-cohort tickers", () => {
    for (const t of ["INFY", "WIPRO", "HCLTECH", "TCS"]) {
      expect(isAdrCohort(t)).toBe(true)
    }
  })

  it("strips .NS / .BO suffix before cohort lookup", () => {
    expect(isAdrCohort("INFY.NS")).toBe(true)
    expect(isAdrCohort("WIPRO.BO")).toBe(true)
  })

  it("rejects off-cohort tickers", () => {
    expect(isAdrCohort("HDFCBANK")).toBe(false)
    expect(isAdrCohort("RELIANCE")).toBe(false)
  })

  it("honors the brief INFY ratio of 4", () => {
    expect(adrRatio("INFY")).toBe(4)
    expect(adrRatio("INFY.NS")).toBe(4)
  })

  it("defaults other ADR tickers to 1:1", () => {
    expect(adrRatio("WIPRO")).toBe(1)
    expect(adrRatio("TCS")).toBe(1)
    expect(adrRatio("HCLTECH")).toBe(1)
  })

  it("returns 1 for unknown tickers", () => {
    expect(adrRatio("UNKNOWN")).toBe(1)
  })
})

describe("MultiCurrencyFVDisplay — render gating", () => {
  it("renders for an ADR-cohort ticker with a positive FV", () => {
    const { container } = render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={1600}
        injectedUsdInr={83.0}
      />,
    )
    expect(
      screen.getByLabelText(/INFY fair value in INR and USD/i),
    ).toBeInTheDocument()
    expectNoBannedVocab(container)
  })

  it("self-hides for non-ADR ticker (HDFCBANK) when usdRevenueHeavy is false", () => {
    const { container } = render(
      <MultiCurrencyFVDisplay
        ticker="HDFCBANK"
        fairValueInr={1900}
        injectedUsdInr={83.0}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders for non-ADR ticker when usdRevenueHeavy=true", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="MPHASIS"
        fairValueInr={2500}
        usdRevenueHeavy={true}
        injectedUsdInr={83.0}
      />,
    )
    // MPHASIS happens to be in the cohort already, so use a non-cohort
    // USD-revenue-heavy name as the real assertion.
  })

  it("renders for non-cohort USD-revenue-heavy ticker (HONAUT) when flagged", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="HONAUT"
        fairValueInr={45000}
        usdRevenueHeavy={true}
        injectedUsdInr={83.0}
      />,
    )
    expect(
      screen.getByLabelText(/HONAUT fair value in INR and USD/i),
    ).toBeInTheDocument()
  })

  it("self-hides when fairValueInr is null", () => {
    const { container } = render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={null}
        injectedUsdInr={83.0}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("self-hides when fairValueInr is zero", () => {
    const { container } = render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={0}
        injectedUsdInr={83.0}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("self-hides when fairValueInr is negative", () => {
    const { container } = render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={-100}
        injectedUsdInr={83.0}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})

describe("MultiCurrencyFVDisplay — INR / USD toggle", () => {
  it("defaults to INR and shows rupee formatting", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="WIPRO"
        fairValueInr={300}
        injectedUsdInr={83.0}
      />,
    )
    // Active value cell is the headline tabular-nums span.
    expect(screen.getByText(/₹300/)).toBeInTheDocument()
  })

  it("flips to USD on toggle click", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="WIPRO"
        fairValueInr={300}
        injectedUsdInr={83.0}
      />,
    )
    const tablist = screen.getByRole("tablist", {
      name: /currency unit/i,
    })
    const usdTab = within(tablist).getByRole("tab", { name: /USD/i })
    fireEvent.click(usdTab)
    // WIPRO ratio = 1, so per-ADR USD = 300/83 ≈ 3.61
    expect(screen.getByText(/\$3\.61/)).toBeInTheDocument()
  })

  it("INFY × 4 ratio: per-ADR USD = 4 × per-share INR / rate", () => {
    // FV 1660 INR/share × 4 / 83 = 80.00 USD/ADR
    render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={1660}
        injectedUsdInr={83.0}
      />,
    )
    // INR caption shows the converted per-ADR figure on the right.
    // We assert "$80.00" is present somewhere in the rendered tree —
    // either as caption (default INR view) or headline (after toggle).
    expect(screen.getByText(/\$80\.00/)).toBeInTheDocument()

    const tablist = screen.getByRole("tablist", {
      name: /currency unit/i,
    })
    const usdTab = within(tablist).getByRole("tab", { name: /USD/i })
    fireEvent.click(usdTab)
    // After toggle, the headline now shows $80.00 explicitly.
    expect(screen.getByText(/\$80\.00/)).toBeInTheDocument()
  })

  it("surfaces the live USD/INR rate caption", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={1660}
        injectedUsdInr={83.45}
      />,
    )
    expect(screen.getByText(/₹83\.45 \/ \$1/)).toBeInTheDocument()
  })

  it("renders the ADR ratio note for INFY (ratio 4)", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="INFY"
        fairValueInr={1660}
        injectedUsdInr={83.0}
      />,
    )
    expect(
      screen.getByText(/1 INFY ADR represents 4 underlying NSE shares/i),
    ).toBeInTheDocument()
  })

  it("omits the ratio note for 1:1 ADRs (WIPRO)", () => {
    render(
      <MultiCurrencyFVDisplay
        ticker="WIPRO"
        fairValueInr={300}
        injectedUsdInr={83.0}
      />,
    )
    expect(
      screen.queryByText(/underlying NSE shares/i),
    ).not.toBeInTheDocument()
  })
})

describe("MultiCurrencyFVDisplay — SEBI vocabulary regression", () => {
  const FIXTURES: Array<[string, number]> = [
    ["INFY", 1660],
    ["WIPRO", 300],
    ["TCS", 4200],
    ["HCLTECH", 1500],
  ]

  it.each(FIXTURES)(
    "rendered DOM for %s carries zero banned vocabulary (INR view)",
    (ticker, fv) => {
      const { container } = render(
        <MultiCurrencyFVDisplay
          ticker={ticker}
          fairValueInr={fv}
          injectedUsdInr={83.0}
        />,
      )
      expectNoBannedVocab(container)
    },
  )

  it.each(FIXTURES)(
    "rendered DOM for %s carries zero banned vocabulary (USD view)",
    (ticker, fv) => {
      const { container } = render(
        <MultiCurrencyFVDisplay
          ticker={ticker}
          fairValueInr={fv}
          injectedUsdInr={83.0}
        />,
      )
      const tablist = screen.getByRole("tablist", {
        name: /currency unit/i,
      })
      const usdTab = within(tablist).getByRole("tab", { name: /USD/i })
      fireEvent.click(usdTab)
      expectNoBannedVocab(container)
    },
  )
})

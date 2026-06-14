/**
 * IntrinsicValueSection — narrative templates + methods rows +
 * reconciliation note + thesis-redesign composition
 * (feat/intrinsic-value-thesis-redesign).
 *
 * Pins:
 *   1. The SEBI-cleared narrative templates render with the correct
 *      numbers ("trades X% below/above", near-parity, data-limited) —
 *      now emitted by <IntrinsicHero>, same testids and copy.
 *   2. "Based on N methods" rows self-show/hide for DCF / Peer
 *      Multiples / sector-specific estimator.
 *   3. The italic reconciliation note picks the right descriptive
 *      sentence for each DCF-vs-multiples split.
 *   4. data_limited renders template [D] and hides methods, strip,
 *      scenario cards, gauge, and drivers.
 *   5. The redesign composition: IntrinsicHero headline numeral,
 *      ValuationRangeStrip, ScenarioCards, ConfidenceGauge, and
 *      ValuationDrivers all mount from this section (the retired
 *      IntrinsicValueCard's iv-card surface no longer exists).
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import IntrinsicValueSection from "@/components/analysis/IntrinsicValueSection"
import type { QualityOutput, ScenariosOutput } from "@/types/api"

function stubMatchMedia() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  stubMatchMedia()
})

const BASE = {
  ticker: "TEST.NS",
  displayTicker: "TEST",
  companyName: "Test Industries",
  currency: "INR",
}

const SCENARIOS: ScenariosOutput = {
  bear: { iv: 900, mos_pct: -10, growth: 4, wacc: 11, term_g: 3 },
  base: { iv: 1200, mos_pct: 20, growth: 8, wacc: 10, term_g: 4 },
  bull: { iv: 1500, mos_pct: 50, growth: 12, wacc: 9, term_g: 5 },
}

const QUALITY = {
  roe: 17.2,
  de_ratio: 0.4,
  revenue_cagr_3y: 0.124,
} as QualityOutput

describe("IntrinsicValueSection — narrative templates", () => {
  it("renders the trades-below template with the exact numbers", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
      />,
    )
    const p = screen.getByTestId("iv-narrative")
    expect(p.getAttribute("data-template")).toBe("trades-below")
    const text = p.textContent ?? ""
    expect(text).toContain("The intrinsic value of Test Industries (TEST)")
    expect(text).toContain("under the base case")
    // trueMos = (1 − 1000/1200) × 100 = 16.666…% → 16.7%
    // (old upside 20.0% drops to the secondary iv-hero-upside line)
    expect(text).toMatch(/trades 16\.7%\s+below/)
    expect(text).toContain("intrinsic value")
  })

  it("renders the trades-above template when price > IV", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={800}
        currentPrice={1000}
        dcfValue={780}
      />,
    )
    const p = screen.getByTestId("iv-narrative")
    expect(p.getAttribute("data-template")).toBe("trades-above")
    // trueMos = (1 − 1000/800) × 100 = −25.0%; |trueMos| = 25.0%
    // (old |upside| 20.0% drops to the secondary iv-hero-upside line)
    expect(p.textContent ?? "").toMatch(/trades 25\.0%\s+above/)
  })

  it("renders the near-parity template inside the 5% band", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1020}
        currentPrice={1000}
        dcfValue={1010}
      />,
    )
    const p = screen.getByTestId("iv-narrative")
    expect(p.getAttribute("data-template")).toBe("parity")
    const text = p.textContent ?? ""
    expect(text).toMatch(/sits\s+within 2\.0% of that figure/)
    expect(text).toMatch(/close to parity under this model/)
  })

  it("bolds the key numbers in ink while prose stays muted", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
      />,
    )
    const p = screen.getByTestId("iv-narrative")
    const bold = Array.from(p.querySelectorAll("span.font-semibold"))
    const boldText = bold.map((b) => b.textContent ?? "").join(" | ")
    expect(boldText).toContain("1,200")
    expect(boldText).toContain("1,000")
    // trueMos = (1 − 1000/1200) × 100 = 16.7% is now the bolded headline pct
    expect(boldText).toContain("16.7%")
  })

  it("renders the data-limited template and hides every numeric surface", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={null}
        currentPrice={1000}
        scenarios={SCENARIOS}
        confidence={82}
        quality={QUALITY}
        fcfYield={4.8}
        dataLimited
      />,
    )
    const p = screen.getByTestId("iv-narrative")
    expect(p.getAttribute("data-template")).toBe("data-limited")
    const text = p.textContent ?? ""
    expect(text).toContain(
      "An intrinsic value for Test Industries (TEST) is not published yet",
    )
    expect(text).toContain("Check back after the next data refresh.")
    expect(screen.queryByTestId("iv-methods")).toBeNull()
    expect(screen.queryByTestId("iv-reconciliation")).toBeNull()
    // Thesis-redesign surfaces are suppressed too — no fabricated zeros.
    expect(screen.queryByTestId("iv-range-strip")).toBeNull()
    expect(screen.queryByTestId("iv-scenarios")).toBeNull()
    expect(screen.queryByTestId("iv-confidence-gauge")).toBeNull()
    expect(screen.queryByTestId("iv-drivers")).toBeNull()
  })
})

describe("IntrinsicValueSection — methods rows", () => {
  it("renders DCF + Multiples + sector rows when all are present", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        multiplesValue={1250}
        multiplesMethod="pe"
        sectorSpecificValue={1180}
        sectorSpecificLabel="Bank Residual Income"
      />,
    )
    expect(screen.getByTestId("iv-methods").textContent).toMatch(
      /Based on 3 methods:/i,
    )
    expect(screen.getByTestId("iv-method-dcf").textContent).toMatch(/DCF/)
    expect(screen.getByTestId("iv-method-multiples").textContent).toMatch(
      /Peer Multiples \(P\/E\)/,
    )
    expect(screen.getByTestId("iv-method-sector").textContent).toMatch(
      /Bank Residual Income/,
    )
  })

  it("self-hides the multiples and sector rows when null", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        multiplesValue={null}
        sectorSpecificValue={null}
      />,
    )
    expect(screen.getByTestId("iv-methods").textContent).toMatch(
      /Based on 1 method:/i,
    )
    expect(screen.getByTestId("iv-method-dcf")).toBeInTheDocument()
    expect(screen.queryByTestId("iv-method-multiples")).toBeNull()
    expect(screen.queryByTestId("iv-method-sector")).toBeNull()
  })
})

describe("IntrinsicValueSection — reconciliation note", () => {
  it("agree-above: both estimates read above the current price", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        multiplesValue={1250}
        multiplesMethod="pe"
      />,
    )
    expect(screen.getByTestId("iv-reconciliation").textContent).toBe(
      "Both the DCF and the peer-multiples estimate read above the current price.",
    )
  })

  it("agree-below: both estimates read below the current price", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={800}
        currentPrice={1000}
        dcfValue={900}
        multiplesValue={950}
        multiplesMethod="pb"
      />,
    )
    expect(screen.getByTestId("iv-reconciliation").textContent).toBe(
      "Both the DCF and the peer-multiples estimate read below the current price.",
    )
  })

  it("split: DCF below, peer multiples above", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1050}
        currentPrice={1000}
        dcfValue={900}
        multiplesValue={1250}
        multiplesMethod="pe"
      />,
    )
    expect(screen.getByTestId("iv-reconciliation").textContent).toBe(
      "The DCF reads below the current price, while peer multiples read above it.",
    )
  })

  it("inverse split: DCF above, peer multiples below", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1050}
        currentPrice={1000}
        dcfValue={1200}
        multiplesValue={900}
        multiplesMethod="pe"
      />,
    )
    expect(screen.getByTestId("iv-reconciliation").textContent).toBe(
      "The DCF reads above the current price, while peer multiples read below it.",
    )
  })

  it("one-method-only when the multiples estimate is unavailable", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        multiplesValue={null}
      />,
    )
    expect(screen.getByTestId("iv-reconciliation").textContent).toBe(
      "Only the DCF estimate is available for this ticker; the peer-multiples comparison is not applicable.",
    )
  })
})

describe("IntrinsicValueSection — heading + hero composition", () => {
  it("renders the numbered heading and the headline gap numeral", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
      />,
    )
    const section = screen.getByTestId("intrinsic-value-section")
    expect(section.textContent).toMatch(/1\.\s*INTRINSIC VALUE/)
    const hero = screen.getByTestId("iv-hero")
    expect(hero.getAttribute("data-direction")).toBe("below")
    const pct = screen.getByTestId("iv-hero-pct")
    expect(pct.getAttribute("data-direction")).toBe("discount")
    // trueMos = (1 − 1000/1200) × 100 = 16.7% is now the headline numeral
    expect(pct.textContent).toContain("16.7%")
    // The retired IntrinsicValueCard surface must not exist anymore.
    expect(screen.queryByTestId("iv-card")).toBeNull()
  })

  it("replaces the body with degradedContent when degraded", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        scenarios={SCENARIOS}
        degraded
        degradedContent={<div data-testid="degraded-slot">clamped</div>}
      />,
    )
    expect(screen.getByTestId("degraded-slot")).toBeInTheDocument()
    expect(screen.queryByTestId("iv-hero")).toBeNull()
    expect(screen.queryByTestId("iv-narrative")).toBeNull()
    expect(screen.queryByTestId("iv-range-strip")).toBeNull()
    expect(screen.queryByTestId("iv-scenarios")).toBeNull()
  })
})

describe("IntrinsicValueSection — thesis-redesign surfaces", () => {
  it("renders the range strip and the three scenario cards from scenarios", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        scenarios={SCENARIOS}
      />,
    )
    expect(screen.getByTestId("iv-range-strip")).toBeInTheDocument()
    expect(screen.getByTestId("iv-range-marker-iv").textContent).toContain(
      "1,200",
    )
    expect(screen.getByTestId("iv-scenarios")).toBeInTheDocument()
    expect(screen.getByTestId("iv-scenario-bear").textContent).toContain("900")
    expect(screen.getByTestId("iv-scenario-base").textContent).toContain(
      "1,200",
    )
    expect(screen.getByTestId("iv-scenario-bull").textContent).toContain(
      "1,500",
    )
    // Assumption detail row carries the per-case inputs.
    expect(
      screen.getByTestId("iv-scenario-detail-base").textContent,
    ).toContain("FCF growth 8.0% · WACC 10.0% · terminal 4.0%")
  })

  it("hides the strip and cards when scenarios are absent", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
      />,
    )
    expect(screen.queryByTestId("iv-range-strip")).toBeNull()
    expect(screen.queryByTestId("iv-scenarios")).toBeNull()
  })

  it("renders the confidence gauge with overall + pillar rows", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        confidence={82}
        confidencePillars={{
          model_confidence: 80,
          data_quality: 90,
          valuation_stability: 75,
        }}
      />,
    )
    expect(screen.getByTestId("iv-confidence-gauge")).toBeInTheDocument()
    expect(screen.getByTestId("iv-confidence-overall").textContent).toContain(
      "82",
    )
    expect(
      screen.getByTestId("iv-confidence-pillar-valuation_stability")
        .textContent,
    ).toContain("Valuation stability")
  })

  it("hides the gauge when confidence and every pillar are null", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        confidence={null}
        confidencePillars={{
          model_confidence: null,
          data_quality: null,
          valuation_stability: null,
        }}
      />,
    )
    expect(screen.queryByTestId("iv-confidence-gauge")).toBeNull()
  })

  it("renders the drivers strip when at least two drivers resolve", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        quality={QUALITY}
        fcfYield={4.8}
      />,
    )
    expect(screen.getByTestId("iv-drivers")).toBeInTheDocument()
    expect(screen.getByTestId("iv-driver-growth").textContent).toContain(
      "12.4%",
    )
    expect(screen.getByTestId("iv-driver-returns").textContent).toContain(
      "17.2%",
    )
  })
})

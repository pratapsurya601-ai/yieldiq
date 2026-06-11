/**
 * IntrinsicValueSection — narrative templates + methods rows +
 * reconciliation note (feat/alphaspread-style-opening).
 *
 * Pins:
 *   1. The SEBI-cleared narrative templates render with the correct
 *      numbers ("trades X% below/above", near-parity, data-limited).
 *   2. "Based on N methods" rows self-show/hide for DCF / Peer
 *      Multiples / sector-specific estimator.
 *   3. The italic reconciliation note picks the right descriptive
 *      sentence for each DCF-vs-multiples split.
 *   4. data_limited renders template [D] and hides methods + bars.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import IntrinsicValueSection from "@/components/analysis/IntrinsicValueSection"

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
    // pct = |1200 − 1000| / 1000 = 20.0
    expect(text).toMatch(/trades 20\.0%\s+below/)
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
    // pct = |800 − 1000| / 1000 = 20.0
    expect(p.textContent ?? "").toMatch(/trades 20\.0%\s+above/)
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
    expect(boldText).toContain("20.0%")
  })

  it("renders the data-limited template and hides methods + bars", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={null}
        currentPrice={1000}
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
    expect(screen.queryByTestId("iv-card-bars")).toBeNull()
    expect(screen.queryByTestId("iv-reconciliation")).toBeNull()
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

describe("IntrinsicValueSection — heading + card composition", () => {
  it("renders the numbered heading and the IV card", () => {
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
    expect(screen.getByTestId("iv-card").textContent).toMatch(
      /TEST Intrinsic Value/,
    )
  })

  it("replaces the two-column body with degradedContent when degraded", () => {
    render(
      <IntrinsicValueSection
        {...BASE}
        intrinsicValue={1200}
        currentPrice={1000}
        dcfValue={1150}
        degraded
        degradedContent={<div data-testid="degraded-slot">clamped</div>}
      />,
    )
    expect(screen.getByTestId("degraded-slot")).toBeInTheDocument()
    expect(screen.queryByTestId("iv-card")).toBeNull()
    expect(screen.queryByTestId("iv-narrative")).toBeNull()
  })
})

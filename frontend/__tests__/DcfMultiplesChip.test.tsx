/**
 * DcfMultiplesChip — primitive tests (Sprint A2, 2026-06-09).
 *
 * Pins:
 *   1. Renders both pills (DCF + multiples) when both values present.
 *   2. Renders nothing when multiplesValue is null (banks / out-of-cohort).
 *   3. Renders nothing when multiplesMethod is null.
 *   4. Summary line: "above" when both > price, "below" when both < price,
 *      "disagree" when one above and the other below.
 *   5. Multiples pill is wrapped in <MetricTooltip /> so the hover
 *      tooltip opens via the existing primitive (mouseEnter -> aria-expanded).
 *   6. SEBI vocabulary regression — the entire rendered DOM contains
 *      ZERO banned vocabulary across all three agreement states.
 *      This is the runtime backstop to scripts/check_sebi_words.py.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act, fireEvent, cleanup } from "@testing-library/react"
import DcfMultiplesChip from "@/components/analysis/DcfMultiplesChip"

// Banned tokens mirror scripts/check_sebi_words.py BANNED_WORDS. These
// constants only ever render INSIDE this test file (never to the DOM),
// so we per-line sebi-allow each entry. The runtime assertion below
// proves no rendered chip output ever contains any of these tokens.
const BANNED_WORDS = [
  "appears",        // sebi-allow: appears
  "should",         // sebi-allow: should
  "concern",        // sebi-allow: concern
  "strength",       // sebi-allow: strength
  "weakness",       // sebi-allow: weakness
  "buy",            // sebi-allow: buy
  "sell",           // sebi-allow: sell
  "outperform",     // sebi-allow: outperform
  "underperform",   // sebi-allow: underperform
  "expensive",      // sebi-allow: expensive
  "cheap",          // sebi-allow: cheap
  "attractive",     // sebi-allow: attractive
  "accumulate",     // sebi-allow: accumulate
  "recommend",      // sebi-allow: recommend
  "recommendation", // sebi-allow: recommendation
  "investable",     // sebi-allow: investable
  "investability",  // sebi-allow: investability
]

// MetricTooltip pulls useReducedMotion which reads matchMedia. jsdom
// doesn't ship a real matchMedia — stub the same way MetricTooltip's
// own tests do.
function setReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? matches : false,
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
  setReducedMotion(false)
  cleanup()
})

describe("DcfMultiplesChip — render guards", () => {
  it("renders both pills when both values present", () => {
    render(
      <DcfMultiplesChip
        ticker="DABUR.NS"
        dcfValue={537.93}
        multiplesValue={510.42}
        multiplesMethod="pe"
        currentPrice={420}
        currency="INR"
        sectorMedianMultiple={48.2}
      />,
    )
    expect(screen.getByTestId("dcf-multiples-chip")).toBeInTheDocument()
    expect(screen.getByTestId("dcf-multiples-chip-dcf")).toBeInTheDocument()
    expect(screen.getByTestId("dcf-multiples-chip-multiples")).toBeInTheDocument()
    // The two pill values are rendered in their own spans — pin both.
    expect(screen.getByTestId("dcf-multiples-chip-dcf").textContent).toMatch(/537/)
    expect(screen.getByTestId("dcf-multiples-chip-multiples").textContent).toMatch(/510/)
  })

  it("renders nothing when multiplesValue is null (no peer cohort)", () => {
    const { container } = render(
      <DcfMultiplesChip
        ticker="DABUR.NS"
        dcfValue={537.93}
        multiplesValue={null}
        multiplesMethod={null}
        currentPrice={420}
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId("dcf-multiples-chip")).toBeNull()
  })

  it("renders nothing when multiplesMethod is null even if value is set", () => {
    const { container } = render(
      <DcfMultiplesChip
        ticker="DABUR.NS"
        dcfValue={537.93}
        multiplesValue={510.42}
        multiplesMethod={null}
        currentPrice={420}
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when currentPrice is non-positive", () => {
    const { container } = render(
      <DcfMultiplesChip
        ticker="DABUR.NS"
        dcfValue={537.93}
        multiplesValue={510.42}
        multiplesMethod="pe"
        currentPrice={0}
        currency="INR"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe("DcfMultiplesChip — agreement summary line", () => {
  it("says BOTH ABOVE when both FVs exceed price", () => {
    render(
      <DcfMultiplesChip
        ticker="DABUR.NS"
        dcfValue={537.93}
        multiplesValue={510.42}
        multiplesMethod="pe"
        currentPrice={420}
        currency="INR"
      />,
    )
    const summary = screen.getByTestId("dcf-multiples-chip-summary")
    expect(summary.textContent).toMatch(/Both methods estimate fair value above the current/i)
  })

  it("says BOTH BELOW when both FVs are under price", () => {
    render(
      <DcfMultiplesChip
        ticker="HUL.NS"
        dcfValue={2200}
        multiplesValue={2150}
        multiplesMethod="pe"
        currentPrice={2500}
        currency="INR"
      />,
    )
    const summary = screen.getByTestId("dcf-multiples-chip-summary")
    expect(summary.textContent).toMatch(/Both methods estimate fair value below the current/i)
  })

  it("says METHODS DISAGREE when DCF above price but multiples below", () => {
    render(
      <DcfMultiplesChip
        ticker="ITC.NS"
        dcfValue={520}
        multiplesValue={380}
        multiplesMethod="pe"
        currentPrice={450}
        currency="INR"
      />,
    )
    const summary = screen.getByTestId("dcf-multiples-chip-summary")
    expect(summary.textContent).toMatch(/Methods disagree/i)
  })

  it("says METHODS DISAGREE when DCF below price but multiples above", () => {
    render(
      <DcfMultiplesChip
        ticker="ITC.NS"
        dcfValue={380}
        multiplesValue={520}
        multiplesMethod="pb"
        currentPrice={450}
        currency="INR"
      />,
    )
    const summary = screen.getByTestId("dcf-multiples-chip-summary")
    expect(summary.textContent).toMatch(/Methods disagree/i)
  })
})

describe("DcfMultiplesChip — multiples-pill MetricTooltip", () => {
  it("wraps the multiples pill in MetricTooltip and opens on hover", async () => {
    render(
      <DcfMultiplesChip
        ticker="DABUR.NS"
        dcfValue={537.93}
        multiplesValue={510.42}
        multiplesMethod="pe"
        currentPrice={420}
        currency="INR"
        sectorMedianMultiple={48.2}
      />,
    )
    const wrapper = screen.getByTestId("metric-tooltip-multiples-based-fair-value")
    expect(wrapper).toBeTruthy()
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    expect(trigger).not.toBeNull()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    const popover = screen.getByTestId("metric-tooltip-content")
    expect(popover).toBeInTheDocument()
    // The tooltip body describes the COMPUTATION, including the
    // sector-median multiple value when supplied.
    expect(popover.textContent).toMatch(/Sector-median P\/E 48\.2/i)
  })
})

describe("DcfMultiplesChip — SEBI vocabulary regression", () => {
  // Render each agreement state and assert that the joined visible
  // text contains zero banned tokens. This is the chip's runtime
  // backstop to scripts/check_sebi_words.py — even if the lint script
  // misses a string interpolated at render time, this test fires.
  const FIXTURES: Array<{
    name: string
    dcf: number
    mult: number
    method: "pe" | "pb"
    price: number
    median: number | null
  }> = [
    { name: "both above", dcf: 537.93, mult: 510.42, method: "pe", price: 420, median: 48.2 },
    { name: "both below", dcf: 2200, mult: 2150, method: "pe", price: 2500, median: 60.1 },
    { name: "disagree (dcf-above)", dcf: 520, mult: 380, method: "pb", price: 450, median: 12.4 },
    { name: "disagree (mult-above)", dcf: 380, mult: 520, method: "pb", price: 450, median: 12.4 },
  ]
  for (const f of FIXTURES) {
    it(`contains no banned vocab — ${f.name}`, () => {
      render(
        <DcfMultiplesChip
          ticker="TEST.NS"
          dcfValue={f.dcf}
          multiplesValue={f.mult}
          multiplesMethod={f.method}
          currentPrice={f.price}
          currency="INR"
          sectorMedianMultiple={f.median}
        />,
      )
      // textContent of the full chip — covers the agreement line, both
      // pills, and the visible labels. Tooltip body opens only on
      // hover, so a separate fixture covers that surface below.
      const dom = (screen.getByTestId("dcf-multiples-chip").textContent || "").toLowerCase()
      for (const w of BANNED_WORDS) {
        expect(dom).not.toMatch(new RegExp(`\\b${w}\\b`, "i"))
      }
    })
  }

  it("tooltip body also contains no banned vocab", async () => {
    render(
      <DcfMultiplesChip
        ticker="TEST.NS"
        dcfValue={537.93}
        multiplesValue={510.42}
        multiplesMethod="pe"
        currentPrice={420}
        currency="INR"
        sectorMedianMultiple={48.2}
      />,
    )
    const wrapper = screen.getByTestId("metric-tooltip-multiples-based-fair-value")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    const popoverText = (
      screen.getByTestId("metric-tooltip-content").textContent || ""
    ).toLowerCase()
    for (const w of BANNED_WORDS) {
      expect(popoverText).not.toMatch(new RegExp(`\\b${w}\\b`, "i"))
    }
  })
})

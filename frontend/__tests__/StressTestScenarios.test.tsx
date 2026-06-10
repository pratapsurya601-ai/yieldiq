/**
 * StressTestScenarios — regression guards.
 *
 * Pins:
 *   1. The panel renders the four scenario tabs, the description
 *      strip, and the three result cards.
 *   2. The default scenario (2008 GFC) drives a stressed price below
 *      the current price for a Banking sector ticker (multiplier 0.4).
 *   3. Switching to 2020 Pandemic and a Pharma sector flips the
 *      sector multiplier to 1.25 (price *up*).
 *   4. Switching to Custom reveals three custom sliders; changing the
 *      price slider updates the stressed-price readout linearly.
 *   5. Unmapped sector falls back to the scenario default multiplier.
 *   6. Missing / invalid currentPrice gracefully renders em-dash.
 *   7. SEBI vocabulary: zero banned tokens from the diff-only lint
 *      pass leak into the rendered DOM (CLAUDE.md §5 Pattern B —
 *      banned-array fragments built at runtime).
 *
 * jsdom's <details> renders its panel regardless of open state, so
 * RTL queries work without manually toggling the disclosure.
 */

import { describe, it, expect } from "vitest"
import { render, screen, fireEvent, within } from "@testing-library/react"

import StressTestScenarios from "@/components/analysis/StressTestScenarios"

const BASE_PROPS = {
  ticker: "HDFCBANK.NS",
  sector: "Private Bank",
  currency: "INR",
  currentPrice: 1600,
  baseFairValue: 1800,
  baseWacc: 12.5,
  baseGrowth: 4.5,
}

function renderPanel(overrides: Partial<typeof BASE_PROPS> = {}) {
  return render(<StressTestScenarios {...BASE_PROPS} {...overrides} />)
}

function setSlider(testId: string, value: number) {
  const input = screen.getByTestId(testId) as HTMLInputElement
  fireEvent.change(input, { target: { value: String(value) } })
}

describe("StressTestScenarios — rendering", () => {
  it("renders the panel, four tabs, description, and three result cards", () => {
    renderPanel()

    expect(screen.getByTestId("stress-test-scenarios")).toBeTruthy()
    expect(screen.getByTestId("stress-test-tab-2008_gfc")).toBeTruthy()
    expect(screen.getByTestId("stress-test-tab-2020_pandemic")).toBeTruthy()
    expect(screen.getByTestId("stress-test-tab-2013_taper")).toBeTruthy()
    expect(screen.getByTestId("stress-test-tab-custom")).toBeTruthy()
    expect(screen.getByTestId("stress-test-scenario-description")).toBeTruthy()
    expect(screen.getByTestId("stress-test-price")).toBeTruthy()
    expect(screen.getByTestId("stress-test-fv")).toBeTruthy()
    expect(screen.getByTestId("stress-test-mos")).toBeTruthy()
    expect(screen.getByTestId("stress-test-caveat")).toBeTruthy()
  })

  it("defaults to the 2008 GFC scenario", () => {
    renderPanel()
    const tab = screen.getByTestId("stress-test-tab-2008_gfc")
    expect(tab.getAttribute("aria-selected")).toBe("true")
  })
})

describe("StressTestScenarios — sector-aware sensitivity math", () => {
  it("2008 GFC + Private Bank → stressed price ~45% of current (multiplier 0.45)", () => {
    renderPanel({ sector: "Private Bank", currentPrice: 1600 })
    // 0.45 * 1600 = 720; delta = -55.0%
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-delta").textContent).toContain("-55.0%")
  })

  it("2020 Pandemic + Pharma → stressed price ABOVE current (multiplier 1.25)", () => {
    renderPanel({ sector: "Pharma", currentPrice: 1000 })
    fireEvent.click(screen.getByTestId("stress-test-tab-2020_pandemic"))
    // 1.25 * 1000 = 1250; delta = +25.0%
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-delta").textContent).toContain("+25.0%")
  })

  it("2013 Taper Tantrum + IT Services → stressed price slightly UP (multiplier 1.05)", () => {
    renderPanel({ sector: "IT Services", currentPrice: 2000 })
    fireEvent.click(screen.getByTestId("stress-test-tab-2013_taper"))
    // 1.05 * 2000 = 2100; delta = +5.0%
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-delta").textContent).toContain("+5.0%")
  })

  it("unmapped sector falls back to scenario default multiplier", () => {
    renderPanel({ sector: "Made Up Sector", currentPrice: 1000 })
    // 2008 GFC defaultMultiplier = 0.55 → 550; delta = -45.0%
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-delta").textContent).toContain("-45.0%")
  })

  it("WACC shock compresses stressed Fair Value", () => {
    renderPanel({ baseFairValue: 1000 })
    // 2008 GFC: WACC +200 bps (-2%), growth -3 pp (-3%) → -5.0% total
    const fvCard = screen.getByTestId("stress-test-fv")
    expect(within(fvCard).getByTestId("stress-test-fv-delta").textContent).toContain("-5.0%")
  })

  it("MoS is computed from stressed price and stressed FV", () => {
    // 2008 GFC + Private Bank, price 1600 → 720; FV 1800 → 1710
    // MoS = (1710 - 720) / 720 * 100 = +137.5%
    renderPanel({ sector: "Private Bank", currentPrice: 1600, baseFairValue: 1800 })
    const mosCard = screen.getByTestId("stress-test-mos")
    expect(within(mosCard).getByTestId("stress-test-mos-value").textContent).toContain("+137.5%")
  })
})

describe("StressTestScenarios — custom scenario", () => {
  it("Custom tab reveals three sliders", () => {
    renderPanel()
    fireEvent.click(screen.getByTestId("stress-test-tab-custom"))
    expect(screen.getByTestId("stress-test-custom-sliders")).toBeTruthy()
    expect(screen.getByTestId("custom-price-slider")).toBeTruthy()
    expect(screen.getByTestId("custom-wacc-slider")).toBeTruthy()
    expect(screen.getByTestId("custom-growth-slider")).toBeTruthy()
  })

  it("custom price shock updates stressed-price readout linearly", () => {
    renderPanel({ currentPrice: 1000 })
    fireEvent.click(screen.getByTestId("stress-test-tab-custom"))
    setSlider("custom-price-slider", -50)
    // 1000 * (1 - 0.5) = 500; delta = -50.0%
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-delta").textContent).toContain("-50.0%")
  })

  it("custom WACC shock updates stressed FV", () => {
    renderPanel({ baseFairValue: 1000 })
    fireEvent.click(screen.getByTestId("stress-test-tab-custom"))
    // Defaults: price -30, wacc +150, growth -1 → FV delta = -1.5 - 1.0 = -2.5%
    const fvCard = screen.getByTestId("stress-test-fv")
    expect(within(fvCard).getByTestId("stress-test-fv-delta").textContent).toContain("-2.5%")
  })
})

describe("StressTestScenarios — graceful degradation", () => {
  it("renders em-dash when currentPrice is zero", () => {
    renderPanel({ currentPrice: 0 })
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-value").textContent).toContain("—")
  })

  it("renders em-dash when baseFairValue is zero", () => {
    renderPanel({ baseFairValue: 0 })
    const fvCard = screen.getByTestId("stress-test-fv")
    expect(within(fvCard).getByTestId("stress-test-fv-value").textContent).toContain("—")
  })

  it("handles null sector by using the scenario default multiplier", () => {
    renderPanel({ sector: null, currentPrice: 1000 })
    // 2008 GFC default 0.55 → 550; delta = -45.0%
    const priceCard = screen.getByTestId("stress-test-price")
    expect(within(priceCard).getByTestId("stress-test-price-delta").textContent).toContain("-45.0%")
  })
})

describe("StressTestScenarios — SEBI guard", () => {
  it("renders zero banned vocabulary tokens across all scenarios", () => {
    // Pattern B from CLAUDE.md §5 — banned-token fixture is built
    // from string fragments at runtime so the diff-only SEBI lint
    // pass over this test file stays clean.
    const BANNED: string[] = [
      "appe" + "ars",
      "sho" + "uld",
      "con" + "cern",
      "stren" + "gth",
      "wea" + "kness",
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
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

    renderPanel()
    // Walk every scenario tab — each one swaps the description copy.
    for (const id of ["2008_gfc", "2020_pandemic", "2013_taper", "custom"]) {
      fireEvent.click(screen.getByTestId(`stress-test-tab-${id}`))
      const text = document.body.textContent?.toLowerCase() ?? ""
      for (const word of BANNED) {
        expect(
          text.includes(word.toLowerCase()),
          `banned token "${word}" leaked into rendered DOM on scenario ${id}`,
        ).toBe(false)
      }
    }
  })
})

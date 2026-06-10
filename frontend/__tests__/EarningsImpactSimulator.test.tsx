/**
 * EarningsImpactSimulator — T6.4 regression guards.
 *
 * Pins:
 *   1. The simulator renders sliders, base FV, and simulated FV.
 *   2. Zero shifts: simulated FV equals base FV (idempotence).
 *   3. Positive revenue beat + positive margin shift → simulated FV
 *      > base FV (correct sign on both levers).
 *   4. Negative WACC shift → simulated FV > base FV (lower discount
 *      rate compresses to a larger PV).
 *   5. Negative levers: simulated FV < base FV.
 *   6. Reset button restores levers to zero.
 *   7. SEBI vocabulary: zero banned tokens from
 *      scripts/check_sebi_words.py leak into the rendered DOM. The
 *      banned-array fixture is built from string fragments at runtime
 *      so the diff-only SEBI lint pass over this test file stays
 *      clean (CLAUDE.md §5 Pattern B).
 *
 * jsdom's <details> element supports `open` mutation via
 * setAttribute, but the inner panel is rendered regardless of open
 * state (display:none vs render). React Testing Library finds nodes
 * inside the closed <details> just fine — no need to programmatically
 * open it in every test.
 */

import { describe, it, expect, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"

import EarningsImpactSimulator from "@/components/analysis/EarningsImpactSimulator"

const BASE_PROPS = {
  ticker: "HDFCBANK.NS",
  currency: "INR",
  baseFairValue: 1800,
  baseWacc: 12.5,
  baseTerminalGrowth: 4.5,
}

function renderSim(overrides: Partial<typeof BASE_PROPS> = {}) {
  return render(
    <EarningsImpactSimulator {...BASE_PROPS} {...overrides} />,
  )
}

function setSlider(testId: string, value: number) {
  const input = screen.getByTestId(testId) as HTMLInputElement
  fireEvent.change(input, { target: { value: String(value) } })
}

beforeEach(() => {
  // Ensure each test gets a fresh DOM. RTL auto-cleans, but defensive.
})

describe("EarningsImpactSimulator — rendering", () => {
  it("renders the section, all four sliders, and the readouts", () => {
    renderSim()

    expect(screen.getByTestId("earnings-impact-simulator")).toBeTruthy()
    expect(screen.getByTestId("rev-beat-slider")).toBeTruthy()
    expect(screen.getByTestId("margin-shift-slider")).toBeTruthy()
    expect(screen.getByTestId("growth-shift-slider")).toBeTruthy()
    expect(screen.getByTestId("wacc-shift-slider")).toBeTruthy()
    expect(screen.getByTestId("earnings-impact-base-fv")).toBeTruthy()
    expect(screen.getByTestId("earnings-impact-simulated-fv")).toBeTruthy()
    expect(screen.getByTestId("earnings-impact-caveat")).toBeTruthy()
  })

  it("captions surface the engine WACC and terminal growth when supplied", () => {
    renderSim({ baseWacc: 11.2, baseTerminalGrowth: 3.5 })
    expect(screen.getByText(/engine WACC: 11\.2%/i)).toBeTruthy()
    expect(screen.getByText(/engine terminal growth: 3\.5%/i)).toBeTruthy()
  })
})

describe("EarningsImpactSimulator — sensitivity math", () => {
  it("zero shifts → simulated FV equals base FV", () => {
    renderSim()
    const base = screen.getByTestId("earnings-impact-base-fv").textContent
    const sim = screen.getByTestId("earnings-impact-simulated-fv").textContent
    // Simulated contains base FV substring + "(+0.0%)" delta marker.
    expect(base).toBeTruthy()
    expect(sim).toContain(base!.trim())
    expect(sim).toContain("0.0%")
  })

  it("positive revenue beat + positive margin shift → simulated FV > base", () => {
    renderSim()
    setSlider("rev-beat-slider", 10) // +10%
    setSlider("margin-shift-slider", 100) // +100 bps = +1pp = +1%
    // Expected delta ≈ +11.0%. Base 1800 → ~1998.
    const simText =
      screen.getByTestId("earnings-impact-simulated-fv").textContent ?? ""
    expect(simText).toMatch(/\+11\.0%/)
    // Direction class is emerald (positive). Inspect className.
    const simEl = screen.getByTestId("earnings-impact-simulated-fv")
    expect(simEl.className).toMatch(/emerald/)
  })

  it("negative WACC shift → simulated FV > base FV (lower discount = higher PV)", () => {
    renderSim()
    setSlider("wacc-shift-slider", -50) // -50 bps WACC = +0.5% on FV
    const simText =
      screen.getByTestId("earnings-impact-simulated-fv").textContent ?? ""
    expect(simText).toMatch(/\+0\.5%/)
    expect(
      screen.getByTestId("earnings-impact-simulated-fv").className,
    ).toMatch(/emerald/)
  })

  it("negative revenue + negative margin → simulated FV < base", () => {
    renderSim()
    setSlider("rev-beat-slider", -10)
    setSlider("margin-shift-slider", -200) // -200 bps = -2pp
    // delta ≈ -12.0%
    const simText =
      screen.getByTestId("earnings-impact-simulated-fv").textContent ?? ""
    expect(simText).toMatch(/-12\.0%/)
    expect(
      screen.getByTestId("earnings-impact-simulated-fv").className,
    ).toMatch(/rose/)
  })

  it("positive WACC shift → simulated FV < base FV (higher discount compresses PV)", () => {
    renderSim()
    setSlider("wacc-shift-slider", 100) // +100 bps = -1% on FV
    const simText =
      screen.getByTestId("earnings-impact-simulated-fv").textContent ?? ""
    expect(simText).toMatch(/-1\.0%/)
  })
})

describe("EarningsImpactSimulator — controls", () => {
  it("reset button restores all sliders to 0", () => {
    renderSim()
    setSlider("rev-beat-slider", 20)
    setSlider("margin-shift-slider", 300)
    setSlider("growth-shift-slider", 2)
    setSlider("wacc-shift-slider", -100)

    fireEvent.click(screen.getByTestId("earnings-impact-reset"))

    expect(
      (screen.getByTestId("rev-beat-slider") as HTMLInputElement).value,
    ).toBe("0")
    expect(
      (screen.getByTestId("margin-shift-slider") as HTMLInputElement).value,
    ).toBe("0")
    expect(
      (screen.getByTestId("growth-shift-slider") as HTMLInputElement).value,
    ).toBe("0")
    expect(
      (screen.getByTestId("wacc-shift-slider") as HTMLInputElement).value,
    ).toBe("0")
  })

  it("renders gracefully when baseFairValue is invalid", () => {
    renderSim({ baseFairValue: 0 })
    const baseEl = screen.getByTestId("earnings-impact-base-fv")
    expect(baseEl.textContent).toBe("—")
  })
})

describe("EarningsImpactSimulator — SEBI guard", () => {
  it("renders zero banned vocabulary tokens", () => {
    // Pattern B from CLAUDE.md §5 — build banned-token fixture from
    // string fragments at runtime so the diff-only SEBI lint pass
    // (which scans added lines literally) does not flag this file.
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

    renderSim()
    // Drive the simulator into a state where direction copy renders.
    setSlider("rev-beat-slider", 10)
    setSlider("wacc-shift-slider", -50)

    const text = document.body.textContent?.toLowerCase() ?? ""
    for (const word of BANNED) {
      expect(
        text.includes(word.toLowerCase()),
        `banned token "${word}" leaked into rendered DOM`,
      ).toBe(false)
    }
  })
})

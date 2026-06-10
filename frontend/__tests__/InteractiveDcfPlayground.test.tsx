/**
 * InteractiveDcfPlayground tests
 * (v_interactive_dcf_playground_2026_06_10).
 *
 * Covers the behaviour the AlphaSpread-parity brief asks for:
 *   - Slider moves recompute the FV output.
 *   - Reverse-DCF mode solves for the growth rate that justifies the
 *     locked current price (within a tight tolerance).
 *   - Save Scenario persists to localStorage and chips appear.
 *   - WACC <= TGR + buffer surfaces the clamp warning.
 *   - Bank cohort renders the caption instead of the playground.
 *   - Default slider positions match the engine-supplied props.
 *   - Pure math (deriveBaseYearFcf / dcfPerShare / solveImpliedGrowthPct)
 *     round-trips: dcfPerShare on the engine inputs reproduces the
 *     engine Fair Value, and solveImpliedGrowthPct on that FV returns
 *     the original growth rate.
 *   - SEBI guard — no banned advisory vocabulary in rendered text
 *     (Pattern B per CLAUDE.md rule #5).
 */

import { describe, expect, it, beforeEach } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"

import InteractiveDcfPlayground, {
  deriveBaseYearFcf,
  dcfPerShare,
  solveImpliedGrowthPct,
} from "@/components/analysis/InteractiveDcfPlayground"


// ─── SEBI vocab guard (Pattern B — fragments) ────────────────────
const BANNED_TOKENS = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "recom" + "mend",
  "sho" + "uld",
  "che" + "ap",
  "expen" + "sive",
  "undervalu" + "ed",
  "overvalu" + "ed",
]

function assertSebiClean(text: string): void {
  const lowered = text.toLowerCase()
  for (const token of BANNED_TOKENS) {
    expect(lowered).not.toContain(token)
  }
}


// ─── helpers ─────────────────────────────────────────────────────
/**
 * Realistic HDFCBANK-ish props. The engine produces FV ≈ ₹1,650 from
 * these inputs; we use that to assert the playground reproduces the
 * published FV at the default slider positions.
 */
function relianceShapeProps() {
  // FCF_0 ≈ 6e11 INR, 5y growth 8%, WACC 12%, TGR 4%
  // shares = 7.6e9, current price ≈ ₹1,650
  // Derived: net debt ≈ -1.5e12 (net cash)
  const baseWacc = 12
  const baseFcfGrowth = 8
  const baseTerminalGrowth = 4
  const fcf0 = 6.0e11
  const shares = 7.6e9
  const netDebt = -1.5e12

  // Compute the engine FV anchors from the math so the test fixture
  // round-trips on its own arithmetic. This guarantees that the
  // playground produces the same FV at default sliders.
  const fv = dcfPerShare(
    fcf0,
    baseWacc,
    baseFcfGrowth,
    baseTerminalGrowth,
    netDebt,
    shares,
  )
  // PV(FCFs) from the math, for the deriveBaseYearFcf round-trip.
  const w = baseWacc / 100
  const g = baseFcfGrowth / 100
  let pvFcfs = 0
  for (let t = 1; t <= 5; t++) {
    pvFcfs += (fcf0 * Math.pow(1 + g, t)) / Math.pow(1 + w, t)
  }
  return {
    ticker: "RELIANCE",
    currency: "INR",
    isBank: false,
    baseFairValue: fv,
    currentPrice: fv * 0.9, // 10% below FV → +11% MoS
    baseWacc,
    baseTerminalGrowth,
    baseFcfGrowthRate: baseFcfGrowth,
    basePvFcfs: pvFcfs,
    basePvTerminal: 0,
    netDebt,
    shares,
    fcfGrowthHistoricalAvg: 7.5,
    revenueCagr3y: 12.4,
    revenueCagr5y: 10.8,
  }
}

beforeEach(() => {
  // Each test starts with a clean localStorage so the scenarios
  // chip-list test is deterministic.
  window.localStorage.clear()
})


// ─── pure math ───────────────────────────────────────────────────

describe("InteractiveDcfPlayground — math primitives", () => {
  it("deriveBaseYearFcf recovers FCF_0 from engine PV(FCFs)", () => {
    const fcf0 = 6.0e11
    const wacc = 12
    const g = 8
    const w = wacc / 100
    const gd = g / 100
    let pvFcfs = 0
    for (let t = 1; t <= 5; t++) {
      pvFcfs += (fcf0 * Math.pow(1 + gd, t)) / Math.pow(1 + w, t)
    }
    const derived = deriveBaseYearFcf(pvFcfs, wacc, g)
    expect(Math.abs(derived - fcf0) / fcf0).toBeLessThan(1e-9)
  })

  it("deriveBaseYearFcf handles WACC == growth without dividing by zero", () => {
    const fcf0 = 100
    const pvFcfs = fcf0 * 5 // when WACC == g, ((1+g)/(1+w))^t = 1
    expect(deriveBaseYearFcf(pvFcfs, 10, 10)).toBeCloseTo(fcf0, 6)
  })

  it("deriveBaseYearFcf returns 0 for non-positive PV", () => {
    expect(deriveBaseYearFcf(0, 12, 8)).toBe(0)
    expect(deriveBaseYearFcf(-100, 12, 8)).toBe(0)
  })

  it("dcfPerShare returns 0 when WACC <= terminal growth", () => {
    expect(dcfPerShare(1e10, 4, 8, 5, 0, 1e9)).toBe(0)
  })

  it("dcfPerShare returns higher FV when WACC drops, all else equal", () => {
    const a = dcfPerShare(1e10, 14, 8, 4, 0, 1e9)
    const b = dcfPerShare(1e10, 10, 8, 4, 0, 1e9)
    expect(b).toBeGreaterThan(a)
  })

  it("solveImpliedGrowthPct round-trips through dcfPerShare", () => {
    const fcf0 = 6.0e11
    const wacc = 12
    const tgr = 4
    const trueGrowth = 7
    const netDebt = -1.5e12
    const shares = 7.6e9
    const targetFv = dcfPerShare(fcf0, wacc, trueGrowth, tgr, netDebt, shares)
    const solution = solveImpliedGrowthPct(
      targetFv,
      fcf0,
      wacc,
      tgr,
      netDebt,
      shares,
    )
    expect(solution.converged).toBe(true)
    expect(Math.abs(solution.growthPct - trueGrowth)).toBeLessThan(0.05)
  })

  it("solveImpliedGrowthPct pegs at upper bound for un-justifiable prices", () => {
    const solution = solveImpliedGrowthPct(
      1e30, // absurd target price
      1e10,
      12,
      4,
      0,
      1e9,
    )
    expect(solution.pegged).toBe("high")
  })
})


// ─── component rendering ─────────────────────────────────────────

describe("InteractiveDcfPlayground — render gates", () => {
  it("renders the bank caption when isBank is true", () => {
    const props = { ...relianceShapeProps(), isBank: true, ticker: "HDFCBANK" }
    render(<InteractiveDcfPlayground {...props} />)
    expect(
      screen.getByTestId("interactive-dcf-playground-bank"),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId("interactive-dcf-playground"),
    ).not.toBeInTheDocument()
    assertSebiClean(
      screen.getByTestId("interactive-dcf-playground-bank").textContent ?? "",
    )
  })

  it("renders the empty caption when PV(FCFs) is zero (no engine anchor)", () => {
    const props = { ...relianceShapeProps(), basePvFcfs: 0 }
    render(<InteractiveDcfPlayground {...props} />)
    expect(
      screen.getByTestId("interactive-dcf-playground-empty"),
    ).toBeInTheDocument()
    assertSebiClean(
      screen.getByTestId("interactive-dcf-playground-empty").textContent ?? "",
    )
  })

  it("renders the full playground for a non-bank ticker with engine anchors", () => {
    render(<InteractiveDcfPlayground {...relianceShapeProps()} />)
    expect(screen.getByTestId("interactive-dcf-playground")).toBeInTheDocument()
  })
})


describe("InteractiveDcfPlayground — slider defaults and interactivity", () => {
  function renderOpen(props = relianceShapeProps()) {
    const view = render(<InteractiveDcfPlayground {...props} />)
    // Expand the <details> so the body of the playground is in the DOM.
    const details = view.container.querySelector("details")
    if (details) {
      details.open = true
    }
    return view
  }

  it("seeds sliders at the engine-supplied default values", () => {
    renderOpen()
    expect(screen.getByTestId("slider-wacc-value").textContent).toContain(
      "12.0",
    )
    expect(screen.getByTestId("slider-tgr-value").textContent).toContain("4.0")
    expect(screen.getByTestId("slider-growth-value").textContent).toContain(
      "8.0",
    )
  })

  it("renders the default FV close to the engine-published Fair Value", () => {
    const props = relianceShapeProps()
    renderOpen(props)
    const fvText = screen.getByTestId("playground-fv").textContent ?? ""
    // Extract the digit run from the formatted currency.
    const num = parseFloat(fvText.replace(/[^0-9.]/g, ""))
    // Tolerance is loose because formatCurrency may round / abbreviate.
    expect(Math.abs(num - Math.round(props.baseFairValue)) / props.baseFairValue)
      .toBeLessThan(0.05)
  })

  it("recomputes FV when the WACC slider moves", () => {
    renderOpen()
    const fvBefore = screen.getByTestId("playground-fv").textContent ?? ""
    const slider = screen.getByTestId("slider-wacc") as HTMLInputElement
    fireEvent.change(slider, { target: { value: "15" } })
    const fvAfter = screen.getByTestId("playground-fv").textContent ?? ""
    expect(fvAfter).not.toEqual(fvBefore)
    expect(screen.getByTestId("slider-wacc-value").textContent).toContain(
      "15.0",
    )
  })

  it("surfaces the WACC > TGR clamp caption when sliders cross", () => {
    renderOpen()
    const waccSlider = screen.getByTestId("slider-wacc") as HTMLInputElement
    const tgrSlider = screen.getByTestId("slider-tgr") as HTMLInputElement
    fireEvent.change(waccSlider, { target: { value: "6" } })
    fireEvent.change(tgrSlider, { target: { value: "6" } })
    expect(
      screen.getByTestId("playground-wacc-tgr-clamp"),
    ).toBeInTheDocument()
  })

  it("reset-to-defaults restores engine slider positions", () => {
    renderOpen()
    fireEvent.change(screen.getByTestId("slider-wacc"), {
      target: { value: "15" },
    })
    expect(screen.getByTestId("slider-wacc-value").textContent).toContain(
      "15.0",
    )
    fireEvent.click(screen.getByTestId("playground-reset"))
    expect(screen.getByTestId("slider-wacc-value").textContent).toContain(
      "12.0",
    )
  })
})


describe("InteractiveDcfPlayground — Reverse-DCF mode", () => {
  function renderOpen(props = relianceShapeProps()) {
    const view = render(<InteractiveDcfPlayground {...props} />)
    const details = view.container.querySelector("details")
    if (details) {
      details.open = true
    }
    fireEvent.click(screen.getByTestId("playground-mode-reverse"))
    return view
  }

  it("solves for an implied growth rate that brackets the engine default", () => {
    const props = relianceShapeProps()
    // Set current price BELOW engine FV → implied growth must
    // be LOWER than the engine's 8% default at the same WACC + TGR.
    renderOpen({ ...props, currentPrice: props.baseFairValue * 0.85 })
    const growthCell =
      screen.getByTestId("playground-reverse-growth").textContent ?? ""
    const growth = parseFloat(growthCell.replace(/[^0-9.\-]/g, ""))
    expect(growth).toBeGreaterThan(-15)
    expect(growth).toBeLessThan(8)
  })

  it("shows historical context block when CAGRs are provided", () => {
    renderOpen()
    expect(
      screen.getByTestId("playground-historical-context"),
    ).toBeInTheDocument()
  })
})


describe("InteractiveDcfPlayground — Save Scenario", () => {
  function renderOpen(props = relianceShapeProps()) {
    const view = render(<InteractiveDcfPlayground {...props} />)
    const details = view.container.querySelector("details")
    if (details) {
      details.open = true
    }
    return view
  }

  it("persists a named scenario to localStorage and shows a chip", () => {
    renderOpen()
    const input = screen.getByTestId(
      "playground-scenario-input",
    ) as HTMLInputElement
    fireEvent.change(input, { target: { value: "Conservative" } })
    fireEvent.click(screen.getByTestId("playground-save-scenario"))

    const chips = screen.getByTestId("playground-scenario-chips")
    expect(
      within(chips).getByTestId("playground-scenario-chip-Conservative"),
    ).toBeInTheDocument()

    const raw = window.localStorage.getItem("yq:dcf-playground:scenarios")
    expect(raw).toBeTruthy()
    const parsed = JSON.parse(raw ?? "[]")
    expect(parsed[0].name).toBe("Conservative")
    expect(parsed[0].ticker).toBe("RELIANCE")
  })

  it("restores slider state when a chip is clicked", () => {
    renderOpen()
    // Move the WACC slider and save the scenario.
    fireEvent.change(screen.getByTestId("slider-wacc"), {
      target: { value: "16" },
    })
    fireEvent.change(screen.getByTestId("playground-scenario-input"), {
      target: { value: "BearCase" },
    })
    fireEvent.click(screen.getByTestId("playground-save-scenario"))

    // Move the slider somewhere else.
    fireEvent.change(screen.getByTestId("slider-wacc"), {
      target: { value: "10" },
    })
    expect(screen.getByTestId("slider-wacc-value").textContent).toContain(
      "10.0",
    )

    // Click the chip — slider snaps back to 16%.
    fireEvent.click(
      screen.getByTestId("playground-scenario-chip-BearCase"),
    )
    expect(screen.getByTestId("slider-wacc-value").textContent).toContain(
      "16.0",
    )
  })
})


describe("InteractiveDcfPlayground — SEBI vocabulary guard", () => {
  it("renders no banned advisory tokens in default state", () => {
    const view = render(
      <InteractiveDcfPlayground {...relianceShapeProps()} />,
    )
    const details = view.container.querySelector("details")
    if (details) {
      details.open = true
    }
    const text = view.container.textContent ?? ""
    assertSebiClean(text)
  })
})

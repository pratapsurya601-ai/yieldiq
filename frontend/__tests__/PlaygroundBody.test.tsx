import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, act, fireEvent } from "@testing-library/react"

// Mock auth store BEFORE importing the body
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { tier: string }) => unknown) =>
    selector({ tier: "pro" }),
}))

// Mock API client
const mockRecompute = vi.fn()
const mockReverse = vi.fn()
vi.mock("@/lib/api", () => ({
  recomputeDcfPlayground: (...args: unknown[]) => mockRecompute(...args),
  reverseEngineerDcf: (...args: unknown[]) => mockReverse(...args),
}))

// CountUp uses IntersectionObserver — stub it
class MockIO {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

import PlaygroundBody from "@/app/(app)/analysis/[ticker]/playground/PlaygroundBody"

const FAKE_RECOMPUTE = {
  ticker: "HDFCBANK.NS",
  fair_value: 1131,
  bear_fv: 950,
  bull_fv: 1300,
  base_fv: 1131,
  current_price: 786,
  margin_of_safety: 43.9,
  verdict: "undervalued",
  inputs_echo: {
    wacc: 0.11,
    terminal_growth: 0.04,
    revenue_cagr_yr1_5: 0.1,
    operating_margin: 0.2,
    tax_rate: 0.25,
  },
  as_of: "2026-05-25T00:00:00Z",
}

const FAKE_REVERSE = {
  ticker: "HDFCBANK.NS",
  market_price: 786,
  implied_wacc: 0.135,
  implied_terminal_growth: 0.025,
  implied_revenue_cagr: 0.05,
  iterations: {
    wacc_converged: true,
    terminal_growth_converged: true,
    revenue_cagr_converged: true,
    max_iters: 50,
  },
  base_inputs: {
    wacc: 0.11,
    terminal_growth: 0.04,
    revenue_cagr_yr1_5: 0.1,
    operating_margin: 0.2,
    tax_rate: 0.25,
  },
  as_of: "2026-05-25T00:00:00Z",
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe("PlaygroundBody", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", MockIO)
    mockRecompute.mockReset()
    mockReverse.mockReset()
    mockRecompute.mockResolvedValue(FAKE_RECOMPUTE)
    mockReverse.mockResolvedValue(FAKE_REVERSE)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders all five sliders for a paid user", () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    const sliders = screen.getAllByRole("slider") as HTMLInputElement[]
    expect(sliders.length).toBe(5)
    // none disabled
    sliders.forEach((s) => expect(s.disabled).toBe(false))
  })

  it("debounces slider changes with a 300ms timer (only one fetch fires)", async () => {
    vi.useFakeTimers()
    try {
      render(<PlaygroundBody ticker="HDFCBANK.NS" />)
      // initial mount schedules a debounce
      await act(async () => {
        vi.advanceTimersByTime(310)
      })
      await act(async () => {
        await Promise.resolve()
      })
      expect(mockRecompute).toHaveBeenCalledTimes(1)

      const sliders = screen.getAllByRole("slider") as HTMLInputElement[]
      fireEvent.change(sliders[0], { target: { value: "0.12" } })
      fireEvent.change(sliders[0], { target: { value: "0.13" } })
      fireEvent.change(sliders[0], { target: { value: "0.14" } })
      // before debounce settles, no additional call
      expect(mockRecompute).toHaveBeenCalledTimes(1)
      await act(async () => {
        vi.advanceTimersByTime(310)
      })
      await act(async () => {
        await Promise.resolve()
      })
      expect(mockRecompute).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it("renders reverse-engineered panel after recompute resolves", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    // Wait for natural setTimeout (300ms) — use real timers, just sleep
    await new Promise((r) => setTimeout(r, 400))
    await flushPromises()
    expect(mockRecompute).toHaveBeenCalled()
    expect(mockReverse).toHaveBeenCalled()
    expect(screen.getByText(/What the market is pricing in/i)).toBeTruthy()
    expect(screen.getByText("Adopt these assumptions")).toBeTruthy()
  })

  it("Adopt-assumptions click pushes implied WACC into the slider", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await new Promise((r) => setTimeout(r, 400))
    await flushPromises()
    fireEvent.click(screen.getByText("Adopt these assumptions"))
    // 0.135 → 13.5%. Asserts on the WACC slider's aria-valuetext so we
    // don't collide with any other "13.5%" string that may render in
    // the reverse-engineered card.
    const waccSlider = document.getElementById("slider-wacc") as HTMLInputElement
    expect(waccSlider).toBeTruthy()
    expect(Number(waccSlider.value)).toBeCloseTo(0.135, 3)
  })
})

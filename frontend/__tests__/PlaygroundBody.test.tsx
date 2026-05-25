import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, act, waitFor, fireEvent } from "@testing-library/react"

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

describe("PlaygroundBody", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal("IntersectionObserver", MockIO)
    mockRecompute.mockReset()
    mockReverse.mockReset()
    mockRecompute.mockResolvedValue({
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
      as_of: new Date().toISOString(),
    })
    mockReverse.mockResolvedValue({
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
      as_of: new Date().toISOString(),
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("debounces slider changes to one POST after 300ms", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    // initial mount fires one
    await act(async () => {
      vi.advanceTimersByTime(310)
    })
    await waitFor(() => expect(mockRecompute).toHaveBeenCalledTimes(1))

    // simulate three rapid slider changes — only one network call
    // is expected after the 300ms debounce settles
    const sliders = screen.getAllByRole("slider") as HTMLInputElement[]
    expect(sliders.length).toBeGreaterThan(0)
    fireEvent.change(sliders[0], { target: { value: "0.12" } })
    fireEvent.change(sliders[0], { target: { value: "0.13" } })
    fireEvent.change(sliders[0], { target: { value: "0.14" } })
    await act(async () => {
      vi.advanceTimersByTime(310)
    })
    await waitFor(() => expect(mockRecompute).toHaveBeenCalledTimes(2))
  })

  it("renders the reverse-engineered panel after price is known", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await act(async () => {
      vi.advanceTimersByTime(310)
    })
    await waitFor(() => expect(mockRecompute).toHaveBeenCalled())
    await waitFor(() => expect(mockReverse).toHaveBeenCalled())
    expect(
      screen.getByText(/What the market is pricing in/i),
    ).toBeTruthy()
    expect(screen.getByText("Adopt these assumptions")).toBeTruthy()
  })

  it("Adopt-assumptions wiring sets the sliders to the implied values", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await act(async () => {
      vi.advanceTimersByTime(310)
    })
    await waitFor(() => expect(mockReverse).toHaveBeenCalled())
    fireEvent.click(screen.getByText("Adopt these assumptions"))
    // The WACC slider will now reflect the implied value (0.135 → 13.5%)
    await waitFor(() => {
      expect(screen.getByText("13.5%")).toBeTruthy()
    })
  })
})

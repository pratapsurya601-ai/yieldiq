import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, act, fireEvent } from "@testing-library/react"

// Mock auth store BEFORE importing the body
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { tier: string }) => unknown) =>
    selector({ tier: "pro" }),
}))

// Mock next/navigation — the body uses useSearchParams / useRouter /
// usePathname to round-trip the slider state through the URL. The
// tests don't exercise navigation but we need the hooks to return
// something non-null.
const mockReplace = vi.fn()
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
  usePathname: () => "/analysis/HDFCBANK.NS/playground",
}))

// Mock API client. The body calls `recomputeDcfPlayground` TWICE on
// mount (canonical + perturbed-WACC anchors) to calibrate the
// client-side DCF, then NEVER again — every slider drag is computed
// locally. The reverse-engineer fetch fires once after calibration
// resolves.
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

const ANCHOR_A = {
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

// Anchor B is the +2pp WACC perturbation — the body uses these two
// points to solve for K (= fcf/share base) and offset (= net debt /
// share). Distinct FV from anchor A is required so the linear system
// is non-degenerate.
const ANCHOR_B = { ...ANCHOR_A, fair_value: 900, base_fv: 1131 }

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
    await Promise.resolve()
  })
}

describe("PlaygroundBody", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", MockIO)
    mockRecompute.mockReset()
    mockReverse.mockReset()
    mockReplace.mockReset()
    // First call returns anchor A, second returns anchor B.
    mockRecompute
      .mockResolvedValueOnce(ANCHOR_A)
      .mockResolvedValueOnce(ANCHOR_B)
    mockReverse.mockResolvedValue(FAKE_REVERSE)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders all five sliders for a paid user", () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    const sliders = screen.getAllByRole("slider") as HTMLInputElement[]
    expect(sliders.length).toBe(5)
    sliders.forEach((s) => expect(s.disabled).toBe(false))
  })

  it("calibrates with exactly two backend calls on mount", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await flushPromises()
    // Two anchor recomputes — and that's it. Subsequent slider drags
    // must not hit the network.
    expect(mockRecompute).toHaveBeenCalledTimes(2)
  })

  it("slider drags do NOT trigger additional backend recomputes", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await flushPromises()
    expect(mockRecompute).toHaveBeenCalledTimes(2)
    const sliders = screen.getAllByRole("slider") as HTMLInputElement[]
    fireEvent.change(sliders[0], { target: { value: "0.12" } })
    fireEvent.change(sliders[0], { target: { value: "0.13" } })
    fireEvent.change(sliders[0], { target: { value: "0.14" } })
    await flushPromises()
    // No new network call — math runs in-browser.
    expect(mockRecompute).toHaveBeenCalledTimes(2)
  })

  it("renders preset scenario buttons", () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    expect(screen.getByText(/Growth halved/i)).toBeTruthy()
    expect(screen.getByText(/Margins compress/i)).toBeTruthy()
    expect(screen.getByText(/Higher rates/i)).toBeTruthy()
  })

  it("preset button mutates slider state (Growth halved cuts CAGR)", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await flushPromises()
    const cagrSlider = document.getElementById(
      "slider-revenue_cagr_yr1_5",
    ) as HTMLInputElement
    expect(cagrSlider).toBeTruthy()
    const before = Number(cagrSlider.value)
    fireEvent.click(screen.getByText(/Growth halved/i))
    const after = Number(cagrSlider.value)
    expect(after).toBeLessThan(before)
  })

  it("renders the side-by-side YieldIQ-base vs your-FV labels", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await flushPromises()
    expect(screen.getByText(/YieldIQ base/i)).toBeTruthy()
    expect(screen.getByText(/Your assumptions/i)).toBeTruthy()
  })

  it("renders Reset to YieldIQ defaults button", () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    expect(screen.getByText(/Reset to YieldIQ defaults/i)).toBeTruthy()
  })

  it("renders reverse-engineered panel after calibration resolves", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await flushPromises()
    expect(mockReverse).toHaveBeenCalled()
    expect(screen.getByText(/What the market is pricing in/i)).toBeTruthy()
    expect(screen.getByText("Adopt these assumptions")).toBeTruthy()
  })

  it("Adopt-assumptions click pushes implied WACC into the slider", async () => {
    render(<PlaygroundBody ticker="HDFCBANK.NS" />)
    await flushPromises()
    fireEvent.click(screen.getByText("Adopt these assumptions"))
    const waccSlider = document.getElementById("slider-wacc") as HTMLInputElement
    expect(waccSlider).toBeTruthy()
    expect(Number(waccSlider.value)).toBeCloseTo(0.135, 3)
  })
})

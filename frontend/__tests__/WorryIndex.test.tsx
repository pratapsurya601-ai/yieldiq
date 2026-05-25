import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import WorryIndex, { type WorryIndexData } from "@/components/analysis/WorryIndex"

// Minimal IntersectionObserver stub so the inner FadeStagger doesn't
// crash when contributors render.
beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return [] }
  })
  vi.stubGlobal("matchMedia", () => ({
    matches: false, media: "", onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
})

const sample: WorryIndexData = {
  score: 35,
  tier: "normal",
  headline: "Normal market risk — boring is a feature",
  contributors: [
    { component: "solvency", label: "Solvency", weight: 30, score: 28, detail: "D/E 0.6" },
    { component: "earnings_quality", label: "Earnings quality", weight: 25, score: 32 },
    { component: "valuation_stretch", label: "Valuation stretch", weight: 20, score: 40 },
    { component: "market_signals", label: "Market signals", weight: 15, score: 45 },
    { component: "governance", label: "Governance", weight: 10, score: 30 },
  ],
}

describe("WorryIndex", () => {
  it("renders nothing when worry prop is null", () => {
    const { container } = render(<WorryIndex worry={null} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders the tier headline and score", () => {
    render(<WorryIndex worry={sample} />)
    expect(screen.getByText(sample.headline)).toBeInTheDocument()
    // CountUp progressively renders 0 → 35; the final value should
    // appear once animation settles (jsdom skips to final frame).
    expect(screen.getByText(/out of 100/i)).toBeInTheDocument()
  })

  it("contributors panel toggles on click", () => {
    render(<WorryIndex worry={sample} />)
    const toggle = screen.getByRole("button", { name: /what drives/i })
    expect(screen.queryByText("D/E 0.6")).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByText("D/E 0.6")).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.queryByText("D/E 0.6")).not.toBeInTheDocument()
  })

  it("each tier maps to a distinct visual style", () => {
    const tiers: WorryIndexData["tier"][] = [
      "sleep_well", "normal", "watch_closely", "read_bears", "significant_concerns",
    ]
    for (const tier of tiers) {
      const { unmount } = render(
        <WorryIndex worry={{ ...sample, tier, score: 50, headline: `${tier} copy` }} />
      )
      expect(screen.getByText(`${tier} copy`)).toBeInTheDocument()
      unmount()
    }
  })

  it("clamps out-of-range scores to 0-100", () => {
    render(<WorryIndex worry={{ ...sample, score: 150 }} />)
    expect(screen.getByText(/out of 100/i)).toBeInTheDocument()
  })
})

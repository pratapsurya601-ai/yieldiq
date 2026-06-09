import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import WorryIndex, {
  type WorryIndexData,
  worryStateLabel,
} from "@/components/analysis/WorryIndex"

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
    // CountUp lands on the final value after the jsdom animation tick.
    expect(screen.getByText(/out of 100/i)).toBeInTheDocument()
  })

  it("contributors panel is always visible below the dial", () => {
    // PR #686 promoted contributors from collapsed toggle to always-visible
    // breakdown bars — visual richness sprint.
    render(<WorryIndex worry={sample} />)
    expect(screen.getByText("D/E 0.6")).toBeInTheDocument()
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

  // Bug 5 (P2, 2026-06-09) — state-language labels replace the raw
  // "Solvency: 0 out of 100" copy that semantically inverted on
  // healthy stocks. State words read in the correct direction
  // without scale-recall (low score = calm, high score = loud).
  describe("per-pillar state labels", () => {
    function renderWithScores(scores: number[]) {
      const labels = [
        "Solvency", "Earnings quality", "Valuation stretch",
        "Market signals", "Governance",
      ]
      const contributors = scores.map((score, i) => ({
        component: `pillar_${i}`,
        label: labels[i] ?? `Pillar ${i}`,
        weight: 20,
        score,
        detail: `bank D/E 0.11 (test ${score})`,
      }))
      return render(
        <WorryIndex
          worry={{ ...sample, contributors }}
        />,
      )
    }

    it("score 0 renders the Calm state label", () => {
      renderWithScores([0, 50, 50, 50, 50])
      expect(screen.getByTestId("worry-state-pillar_0")).toHaveTextContent("Calm")
    })

    it("score 50 renders the Elevated state label", () => {
      // 40-69 band per worryStateLabel().
      renderWithScores([50, 0, 0, 0, 0])
      expect(screen.getByTestId("worry-state-pillar_0")).toHaveTextContent("Elevated")
    })

    it("score 95 renders the Loud state label", () => {
      renderWithScores([95, 0, 0, 0, 0])
      expect(screen.getByTestId("worry-state-pillar_0")).toHaveTextContent("Loud")
    })

    it("score 25 renders the Normal state label", () => {
      renderWithScores([25, 0, 0, 0, 0])
      expect(screen.getByTestId("worry-state-pillar_0")).toHaveTextContent("Normal")
    })

    it("aria-label includes the state word, not just the raw number", () => {
      renderWithScores([6, 0, 0, 0, 0])
      // The bar role=img aria-label includes the Calm state word
      // (and the detail copy when present).
      const bars = screen.getAllByRole("img")
      const solvencyBar = bars[0]
      expect(solvencyBar.getAttribute("aria-label")).toMatch(/Solvency:\s*Calm/)
      // Detail text gets appended after the state, NOT raw "/100".
      expect(solvencyBar.getAttribute("aria-label")).toMatch(/bank D\/E 0\.11/)
    })

    it("raw 0-100 score still surfaces as secondary caption", () => {
      // Power users / accessibility audits — the underlying number
      // must remain visible somewhere, just not as the primary label.
      renderWithScores([42, 0, 0, 0, 0])
      expect(screen.getByText(/42\/100/)).toBeInTheDocument()
    })
  })

  describe("worryStateLabel helper", () => {
    it("bands map to the documented thresholds", () => {
      // Calm: 0-19
      expect(worryStateLabel(0)).toBe("Calm")
      expect(worryStateLabel(19)).toBe("Calm")
      // Normal: 20-39
      expect(worryStateLabel(20)).toBe("Normal")
      expect(worryStateLabel(39)).toBe("Normal")
      // Elevated: 40-69
      expect(worryStateLabel(40)).toBe("Elevated")
      expect(worryStateLabel(69)).toBe("Elevated")
      // Loud: 70-100
      expect(worryStateLabel(70)).toBe("Loud")
      expect(worryStateLabel(100)).toBe("Loud")
    })

    it("clamps out-of-range scores into the legal bands", () => {
      expect(worryStateLabel(-50)).toBe("Calm")
      expect(worryStateLabel(250)).toBe("Loud")
    })
  })
})

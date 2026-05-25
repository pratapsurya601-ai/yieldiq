/**
 * Tests for TrustStrip — the Alpha-Spread-style stat row used above
 * numbered sections on the Summary tab (#ASD-restyle, 2026-05-25).
 *
 * Policy: real data only. Callers are expected to omit cards rather
 * than pad with mocks. These tests verify the component honours that:
 *
 *  * empty stats array → render nothing (null)
 *  * partial data (2 cards) → render exactly 2 cards (no padding)
 *  * full data (4 cards) → render 4 cards with correct accents
 *  * accent → color class on the value (green / red / neutral)
 *  * "—" passed as the value → still rendered (caller's responsibility)
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import TrustStrip, {
  type TrustStat,
} from "@/components/analysis/TrustStrip"

describe("TrustStrip", () => {
  it("renders nothing when stats is empty", () => {
    const { container } = render(<TrustStrip stats={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders exactly 2 cards when given partial data — no padding", () => {
    const stats: TrustStat[] = [
      { label: "Yield", value: "2.40%", accent: "neutral" },
      { label: "Payout", value: "30%", accent: "neutral" },
    ]
    render(<TrustStrip stats={stats} />)
    const cards = screen.getAllByTestId("trust-strip-card")
    expect(cards).toHaveLength(2)
    expect(screen.getByText("Yield")).toBeInTheDocument()
    expect(screen.getByText("Payout")).toBeInTheDocument()
  })

  it("renders 4 cards with correct accent attributes when given full data", () => {
    const stats: TrustStat[] = [
      { label: "Bear MoS", value: "-30.0%", accent: "red" },
      { label: "Base MoS", value: "+12.5%", accent: "green" },
      { label: "Bull MoS", value: "+55.0%", accent: "green" },
      { label: "Model Confidence", value: "90/100", accent: "neutral" },
    ]
    render(<TrustStrip stats={stats} />)
    const cards = screen.getAllByTestId("trust-strip-card")
    expect(cards).toHaveLength(4)

    const values = screen.getAllByText(/MoS|100/)
    // Spot-check accents via the data-accent attribute on the value <p>.
    const accents = Array.from(
      document.querySelectorAll("[data-accent]"),
    ).map((el) => el.getAttribute("data-accent"))
    expect(accents).toEqual(["red", "green", "green", "neutral"])
    expect(values.length).toBeGreaterThan(0)
  })

  it("renders an em-dash value when the caller passes '—'", () => {
    const stats: TrustStat[] = [
      { label: "Revenue 3y CAGR", value: "—", accent: "neutral" },
      { label: "Profit 3y CAGR", value: "12.0%", accent: "neutral" },
    ]
    render(<TrustStrip stats={stats} />)
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("caps at 4 cards even if more are passed (defensive)", () => {
    const stats: TrustStat[] = Array.from({ length: 6 }, (_, i) => ({
      label: `Stat ${i}`,
      value: `${i}`,
      accent: "neutral" as const,
    }))
    render(<TrustStrip stats={stats} />)
    expect(screen.getAllByTestId("trust-strip-card")).toHaveLength(4)
  })

  it("treats missing accent as neutral", () => {
    const stats: TrustStat[] = [
      { label: "X", value: "1" },
      { label: "Y", value: "2" },
    ]
    render(<TrustStrip stats={stats} />)
    const accents = Array.from(
      document.querySelectorAll("[data-accent]"),
    ).map((el) => el.getAttribute("data-accent"))
    expect(accents).toEqual(["neutral", "neutral"])
  })
})

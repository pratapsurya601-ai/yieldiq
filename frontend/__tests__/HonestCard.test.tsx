/**
 * HonestCard smoke + snapshot tests (Phase 3 manifesto, 2026-05-25).
 *
 * Pins:
 *   1. All 4 sections render when honest_card payload is populated.
 *   2. Section headings match Design Manifesto Rule 10 wording.
 *   3. Component self-hides when card is null / empty.
 *   4. Snapshot of the populated state.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import HonestCard from "@/components/analysis/HonestCard"
import type { HonestCardOutput } from "@/types/api"

const MOCK_CARD: HonestCardOutput = {
  confident_facts: [
    "Market cap: ₹24.00L Cr — derived from latest shares × live price",
    "Dividend declared in last 12 months: ₹19.50/share",
    "Dividend paid for 7 consecutive years",
    "Latest filed financials: period ending 2025-03-31",
  ],
  best_estimate:
    "Fair value ₹1,131. Bear ₹942, bull ₹1,507. Model confidence 90/100.",
  uncertainty_factors: [
    "Leverage at 0.95 is above sector median 0.60 — debt sensitivity matters here",
    "Model fit on this archetype is limited (confidence 67/100) — wide variance across scenarios",
  ],
  invalidating_conditions: [
    "Fair value drops more than 15% from one quarter's results — re-rating triggered",
    "Loan / advances growth below 8% for 2 consecutive quarters — bear case becomes base",
    "Gross NPA above 2% — solvency concerns enter the model",
  ],
}

describe("HonestCard", () => {
  it("renders all 4 section headings", () => {
    render(<HonestCard card={MOCK_CARD} />)
    expect(screen.getByText(/here's what we're confident about/i)).toBeTruthy()
    expect(screen.getByText(/here's our best estimate/i)).toBeTruthy()
    expect(screen.getByText(/here's where we could be wrong/i)).toBeTruthy()
    expect(screen.getByText(/things that would change our verdict/i)).toBeTruthy()
  })

  it("renders the headline title", () => {
    render(<HonestCard card={MOCK_CARD} />)
    expect(screen.getByText(/^The Honest Card$/)).toBeTruthy()
  })

  it("renders every confident_fact bullet", () => {
    render(<HonestCard card={MOCK_CARD} />)
    for (const fact of MOCK_CARD.confident_facts) {
      expect(screen.getByText(fact)).toBeTruthy()
    }
  })

  it("renders the best_estimate sentence verbatim", () => {
    render(<HonestCard card={MOCK_CARD} />)
    expect(screen.getByText(MOCK_CARD.best_estimate)).toBeTruthy()
  })

  it("renders all 3 invalidating conditions numbered", () => {
    render(<HonestCard card={MOCK_CARD} />)
    for (const cond of MOCK_CARD.invalidating_conditions) {
      expect(screen.getByText(cond)).toBeTruthy()
    }
  })

  it("renders the footer disclaimer", () => {
    render(<HonestCard card={MOCK_CARD} />)
    expect(
      screen.getByText(/Auto-generated.*Not investment advice/i),
    ).toBeTruthy()
  })

  it("renders nothing when card is null", () => {
    const { container } = render(<HonestCard card={null} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when every section is empty", () => {
    const { container } = render(
      <HonestCard
        card={{
          confident_facts: [],
          best_estimate: "",
          uncertainty_factors: [],
          invalidating_conditions: [],
        }}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("snapshot — populated card", () => {
    const { container } = render(<HonestCard card={MOCK_CARD} />)
    expect(container.firstChild).toMatchSnapshot()
  })
})

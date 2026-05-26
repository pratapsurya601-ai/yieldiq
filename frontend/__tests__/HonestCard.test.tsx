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

  // ── Regression: P0 hotfix 2026-05-26 ────────────────────────────
  // PR #651 shipped FadeStagger wrappers with `className="contents"`.
  // `display: contents` collapses the element's CSS box, so the
  // IntersectionObserver attached by useInViewOnce never fires
  // (zero-area elements don't intersect), `inView` stays false, and
  // the staggered items render at opacity:0 forever. Net effect:
  // confident_facts / uncertainty_factors / invalidating_conditions
  // rendered as empty section headers in production.
  //
  // Pin: the FadeStagger wrappers used by BulletList / NumberedList
  // must never use `display: contents` (or any class that strips the
  // CSS box from the observed element).
  it("renders all 4 sections with populated data — bullets visible (P0 #651-fix)", () => {
    const { container } = render(<HonestCard card={MOCK_CARD} />)
    const staggers = container.querySelectorAll('[data-anim="fade-stagger"]')
    // Two FadeStagger wrappers: BulletList (confident, uncertainty)
    // and NumberedList (invalidating) — 3 in total for MOCK_CARD.
    expect(staggers.length).toBe(3)
    staggers.forEach((node) => {
      // The container must have a real layout box so the IO observer
      // can fire. `contents` (or `display: contents` inline) reproduces
      // the regression.
      expect(node.className).not.toMatch(/\bcontents\b/)
      expect((node as HTMLElement).style.display).not.toBe("contents")
    })
    // Each stagger contains the right number of rendered children
    // (data-stagger-index="0..N-1"). If the wrapper collapsed, the
    // children would not be enumerable in DOM order either.
    const totalStaggerItems = container.querySelectorAll(
      "[data-stagger-index]",
    ).length
    expect(totalStaggerItems).toBe(
      MOCK_CARD.confident_facts.length +
        MOCK_CARD.uncertainty_factors.length +
        MOCK_CARD.invalidating_conditions.length,
    )
  })

  it("gracefully hides sections with empty arrays", () => {
    const partial: HonestCardOutput = {
      confident_facts: ["Only fact we have"],
      best_estimate: "Fair value ₹100. Bear ₹80, bull ₹120. Model confidence 60/100.",
      uncertainty_factors: [],
      invalidating_conditions: [],
    }
    render(<HonestCard card={partial} />)
    expect(screen.getByText(/here's what we're confident about/i)).toBeTruthy()
    expect(screen.getByText(/here's our best estimate/i)).toBeTruthy()
    expect(screen.queryByText(/here's where we could be wrong/i)).toBeNull()
    expect(
      screen.queryByText(/things that would change our verdict/i),
    ).toBeNull()
  })
})

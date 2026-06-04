/**
 * AdrCohortBanner tests.
 *
 * Covers the post-PR-1a copy refresh:
 *   - Renders for the four working ADR-cohort tickers
 *     (INFY / WIPRO / HCLTECH / TECHM).
 *   - Renders TickerAvatar in the header (asserted by the avatar's
 *     own data-testid; no need to mock — the component is pure).
 *   - Does NOT render for an off-cohort ticker (HDFCBANK).
 *   - Copy frames the ADR sourcing as a qualification on real data,
 *     not as an apology for a broken product.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import AdrCohortBanner, {
  isAdrAffected,
} from "@/components/analysis/AdrCohortBanner"

const COHORT_TICKERS = ["INFY", "WIPRO", "HCLTECH", "TECHM"] as const

describe("AdrCohortBanner", () => {
  it.each(COHORT_TICKERS)(
    "renders the new copy for %s",
    (ticker) => {
      render(<AdrCohortBanner ticker={ticker} />)
      // Status landmark for screen readers.
      const status = screen.getByRole("status")
      expect(status).toBeInTheDocument()
      // Ticker symbol surfaces in the header (next to the avatar).
      expect(status.textContent).toContain(ticker)
      // Copy frames the page values as the latest cached compute, not
      // as something the user is told to discount.
      expect(status.textContent).toMatch(/latest cached compute/i)
      // Forward-looking framing on the direct NSE data path.
      expect(status.textContent).toMatch(/direct NSE data path/i)
    },
  )

  it("renders the TickerAvatar chip in the header", () => {
    render(<AdrCohortBanner ticker="INFY" />)
    // TickerAvatar exposes either ticker-avatar-image (logo branch)
    // or ticker-avatar-monogram (fallback). Either is acceptable —
    // we only care that the chip rendered.
    const avatar =
      screen.queryByTestId("ticker-avatar-image") ??
      screen.queryByTestId("ticker-avatar-monogram")
    expect(avatar).not.toBeNull()
  })

  it("returns null for a non-cohort ticker", () => {
    const { container } = render(<AdrCohortBanner ticker="HDFCBANK" />)
    expect(container).toBeEmptyDOMElement()
  })

  it("tolerates .NS / .BO suffixes", () => {
    expect(isAdrAffected("INFY.NS")).toBe(true)
    expect(isAdrAffected("INFY.BO")).toBe(true)
    expect(isAdrAffected("HDFCBANK.NS")).toBe(false)
  })
})

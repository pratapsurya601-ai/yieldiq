/**
 * PortfolioHero — audit 2026-06-10 (P2).
 *
 * The /watchlist redirect lands on `/portfolio?tab=watchlist`. Before
 * this component shipped the watchlist tab opened with an empty
 * `.skeleton rounded-2xl` gradient block above the tabs because
 * `PortfolioSumOfPartsCard` was the only above-the-tabs surface and it
 * returns null for users with zero holdings. The hero closes that gap
 * with a SEBI-clean value prop in the empty state and a KPI gradient
 * in the populated state.
 *
 * These tests pin the two render branches so future refactors can't
 * accidentally reintroduce the empty-gradient regression.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import PortfolioHero from "@/components/portfolio/PortfolioHero"
import type { LiveHolding, HoldingsLiveResponse } from "@/lib/api"

type Summary = HoldingsLiveResponse["summary"]

function h(
  ticker: string,
  pnlPct: number,
  pnlAbs = pnlPct * 10,
): LiveHolding {
  return {
    ticker,
    display_ticker: ticker.replace(".NS", ""),
    company_name: ticker,
    sector: "Financial Services",
    entry_price: 100,
    quantity: 10,
    account_label: "default",
    current_price: 100 + pnlAbs / 10,
    invested_value: 1000,
    current_value: 1000 + pnlAbs,
    pnl_abs: pnlAbs,
    pnl_pct: pnlPct,
    day_change_abs: null,
    day_change_pct: null,
    fair_value: 120,
    mos_pct: 20,
    verdict: "fairly_valued",
    score: 60,
    saved_at: "",
    notes: "",
  }
}

function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    total_invested: 30_000,
    total_current_value: 36_000,
    total_pnl_abs: 6_000,
    total_pnl_pct: 20,
    winners: 2,
    losers: 1,
    count: 3,
    ...overrides,
  }
}

describe("PortfolioHero", () => {
  describe("empty state (no holdings)", () => {
    it("renders the value prop and CTAs when summary is undefined", () => {
      render(<PortfolioHero summary={undefined} holdings={[]} isLoading={false} />)
      expect(screen.getByTestId("portfolio-hero-empty")).toBeInTheDocument()
      expect(
        screen.getByText(/track your stocks/i),
      ).toBeInTheDocument()
      expect(
        screen.getByText(/fair-value gaps/i),
      ).toBeInTheDocument()
      expect(screen.getByTestId("portfolio-hero-import")).toHaveAttribute(
        "href",
        "/portfolio/import",
      )
      expect(screen.getByTestId("portfolio-hero-search")).toHaveAttribute(
        "href",
        "/search",
      )
      // Crucially: no KPI rendering when there are no holdings.
      expect(screen.queryByTestId("portfolio-hero-summary")).toBeNull()
      expect(screen.queryByTestId("portfolio-hero-total-value")).toBeNull()
    })

    it("renders the empty state when summary.count === 0", () => {
      render(
        <PortfolioHero
          summary={summary({
            count: 0,
            total_invested: 0,
            total_current_value: 0,
            total_pnl_abs: 0,
            total_pnl_pct: 0,
            winners: 0,
            losers: 0,
          })}
          holdings={[]}
          isLoading={false}
        />,
      )
      expect(screen.getByTestId("portfolio-hero-empty")).toBeInTheDocument()
      expect(screen.queryByTestId("portfolio-hero-summary")).toBeNull()
    })
  })

  describe("populated state (holdings present)", () => {
    it("renders total value, P&L, and the top mover when holdings are non-empty", () => {
      const holdings = [
        h("ASIANPAINT.NS", 5),    // +5%
        h("TCS.NS", -18),         // -18% (largest absolute mover)
        h("HDFCBANK.NS", 12),     // +12%
      ]
      render(
        <PortfolioHero
          summary={summary({ count: 3 })}
          holdings={holdings}
          isLoading={false}
        />,
      )
      expect(screen.getByTestId("portfolio-hero-summary")).toBeInTheDocument()
      // Compact formatter renders 36_000 as "₹36.0K".
      expect(screen.getByTestId("portfolio-hero-total-value")).toHaveTextContent(
        /36\.0K/,
      )
      expect(screen.getByTestId("portfolio-hero-pnl-abs")).toHaveTextContent(/\+/)
      expect(screen.getByTestId("portfolio-hero-count")).toHaveTextContent("3")
      // Top mover by abs(pnl_pct) → TCS at -18%.
      const topMover = screen.getByTestId("portfolio-hero-top-mover")
      expect(topMover).toHaveTextContent(/TCS/)
      expect(topMover).toHaveTextContent(/-18\.0%/)
      // Empty-state copy must NOT appear when holdings exist.
      expect(screen.queryByTestId("portfolio-hero-empty")).toBeNull()
    })

    it("renders winners and losers split using the >= 0 convention", () => {
      const holdings = [
        h("A.NS", 0),    // tie → winners
        h("B.NS", 8),    // winner
        h("C.NS", -3),   // loser
      ]
      render(
        <PortfolioHero
          summary={summary({ count: 3 })}
          holdings={holdings}
          isLoading={false}
        />,
      )
      // Buckets sum to count (3) — same convention as the prior inline
      // gradient card on the holdings tab.
      expect(screen.getByText(/2 \/ 1/)).toBeInTheDocument()
    })
  })

  describe("loading state", () => {
    it("renders a labelled skeleton (not the empty gradient) while in flight", () => {
      const { container } = render(
        <PortfolioHero summary={undefined} holdings={[]} isLoading={true} />,
      )
      const skeleton = screen.getByTestId("portfolio-hero-loading")
      expect(skeleton).toBeInTheDocument()
      expect(skeleton).toHaveAttribute("aria-busy", "true")
      expect(skeleton).toHaveAttribute("aria-label", "Loading portfolio summary")
      // Neither real branch mounts during loading — that was the
      // exact bug the audit caught.
      expect(container.querySelector('[data-testid="portfolio-hero-empty"]')).toBeNull()
      expect(container.querySelector('[data-testid="portfolio-hero-summary"]')).toBeNull()
    })
  })
})

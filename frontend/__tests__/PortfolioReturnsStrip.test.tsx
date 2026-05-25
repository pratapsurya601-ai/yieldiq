/**
 * PortfolioReturnsStrip (P0 #5 Feature C, 2026-05-25).
 *
 * Today only the Unrealized card is wired to real data; the other
 * four render LIMITED DATA chips and become populated as backend
 * services land. These tests pin that contract so a future change
 * doesn't silently turn a LIMITED chip into a stale zero.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type React from "react"

const getHoldingsLiveMock = vi.fn()
vi.mock("@/lib/api", () => ({
  getHoldingsLive: () => getHoldingsLiveMock(),
}))

import PortfolioReturnsStrip from "@/components/portfolio/PortfolioReturnsStrip"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  getHoldingsLiveMock.mockReset()
})

describe("PortfolioReturnsStrip", () => {
  it("renders five cards with LIMITED DATA chips for the four unbuilt drivers", async () => {
    getHoldingsLiveMock.mockResolvedValue({
      holdings: [],
      summary: {
        total_invested: 1000,
        total_current_value: 1200,
        total_pnl_abs: 200,
        total_pnl_pct: 20,
        winners: 1,
        losers: 0,
        count: 1,
      },
    })
    renderWithClient(<PortfolioReturnsStrip />)
    await waitFor(() => expect(screen.getByTestId("returns-strip")).toBeInTheDocument())

    // All 5 cards present.
    expect(screen.getByTestId("returns-unrealized")).toBeInTheDocument()
    expect(screen.getByTestId("returns-realized")).toBeInTheDocument()
    expect(screen.getByTestId("returns-dividends")).toBeInTheDocument()
    expect(screen.getByTestId("returns-fx")).toBeInTheDocument()
    expect(screen.getByTestId("returns-forward-div")).toBeInTheDocument()

    // Exactly 4 LIMITED DATA chips (the unbuilt cards).
    expect(screen.getAllByText(/LIMITED DATA/)).toHaveLength(4)
  })

  it("formats the Unrealized card with sign + compact rupees", async () => {
    getHoldingsLiveMock.mockResolvedValue({
      holdings: [],
      summary: {
        total_invested: 100000,
        total_current_value: 150000,
        total_pnl_abs: 50000,
        total_pnl_pct: 50,
        winners: 1,
        losers: 0,
        count: 1,
      },
    })
    renderWithClient(<PortfolioReturnsStrip />)
    await waitFor(() => expect(screen.getByTestId("returns-strip")).toBeInTheDocument())
    const card = screen.getByTestId("returns-unrealized")
    expect(card.textContent).toMatch(/\+₹50\.0K/)
    expect(card.textContent).toMatch(/\+50\.00%/)
  })

  it("renders nothing when the user has zero holdings", async () => {
    getHoldingsLiveMock.mockResolvedValue({
      holdings: [],
      summary: {
        total_invested: 0,
        total_current_value: 0,
        total_pnl_abs: 0,
        total_pnl_pct: 0,
        winners: 0,
        losers: 0,
        count: 0,
      },
    })
    const { container } = renderWithClient(<PortfolioReturnsStrip />)
    await waitFor(() => {
      expect(container.querySelector('[data-testid="returns-strip"]')).toBeNull()
    })
  })
})

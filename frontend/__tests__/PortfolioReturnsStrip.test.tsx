/**
 * PortfolioReturnsStrip (P0 #5 Feature C, 2026-05-25; updated P0 hotfix 2026-05-26).
 *
 * Hotfix #2 (2026-05-26): only the Unrealized card renders today.
 * Realized / Dividends / Currency / Forward-Dividends are gated behind
 * backend services that don't exist; rather than rendering four
 * "LIMITED DATA" placeholders (which read as broken in prod), those
 * tiles are intentionally not rendered. The LIMITED DATA chip is
 * reserved for partially-populated values, never for nulls.
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
  it("renders only the Unrealized card while other drivers are unbuilt", async () => {
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

    // Only Unrealized is wired today.
    expect(screen.getByTestId("returns-unrealized")).toBeInTheDocument()
    expect(screen.queryByTestId("returns-realized")).not.toBeInTheDocument()
    expect(screen.queryByTestId("returns-dividends")).not.toBeInTheDocument()
    expect(screen.queryByTestId("returns-fx")).not.toBeInTheDocument()
    expect(screen.queryByTestId("returns-forward-div")).not.toBeInTheDocument()

    // LIMITED DATA chip is reserved for partial values — never null.
    expect(screen.queryAllByText(/LIMITED DATA/)).toHaveLength(0)
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

/**
 * Portfolio Sum-of-Parts FV card (P0 #2, 2026-05-25).
 *
 * Verdict thresholds and LIMITED DATA chip behaviour are pinned here
 * so the headline copy can't drift from the backend's verdict_label
 * field (see backend/tests/test_portfolio_sop_and_sparklines.py).
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type React from "react"

const getSopMock = vi.fn()
vi.mock("@/lib/api", () => ({
  getPortfolioSumOfParts: () => getSopMock(),
}))

import PortfolioSumOfPartsCard from "@/components/portfolio/PortfolioSumOfPartsCard"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  getSopMock.mockReset()
})

describe("PortfolioSumOfPartsCard", () => {
  it("renders Undervalued headline + bar segments when IV > MV", async () => {
    getSopMock.mockResolvedValue({
      market_value: 1000,
      intrinsic_value: 1400,
      gap_pct: 40,
      verdict_label: "Undervalued",
      holdings_with_fv_count: 3,
      holdings_without_fv_count: 0,
      total_holdings: 3,
      as_of: "2026-05-25T14:00:00Z",
    })
    renderWithClient(<PortfolioSumOfPartsCard />)
    await waitFor(() => expect(screen.getByTestId("sop-card")).toBeInTheDocument())
    expect(screen.getByTestId("sop-headline-verdict")).toHaveTextContent("Undervalued")
    expect(screen.getByTestId("sop-headline-gap")).toHaveTextContent("40.0%")
    expect(screen.getByTestId("sop-bar-market")).toBeInTheDocument()
    expect(screen.getByTestId("sop-bar-intrinsic")).toBeInTheDocument()
    expect(screen.getByText(/3 of 3 holdings/i)).toBeInTheDocument()
    // No LIMITED DATA chip when coverage is full.
    expect(screen.queryByText(/LIMITED DATA/)).not.toBeInTheDocument()
  })

  it("renders LIMITED DATA chip when some holdings lack a cached FV", async () => {
    getSopMock.mockResolvedValue({
      market_value: 1000,
      intrinsic_value: 1100,
      gap_pct: 10,
      verdict_label: "Fairly Valued",
      holdings_with_fv_count: 2,
      holdings_without_fv_count: 1,
      total_holdings: 3,
      as_of: "2026-05-25T14:00:00Z",
    })
    renderWithClient(<PortfolioSumOfPartsCard />)
    await waitFor(() => expect(screen.getByTestId("sop-card")).toBeInTheDocument())
    expect(screen.getByText(/LIMITED DATA/)).toBeInTheDocument()
    expect(screen.getByTestId("sop-headline-verdict")).toHaveTextContent("Fairly Valued")
  })

  it("shows the empty state when no holdings have a cached FV", async () => {
    getSopMock.mockResolvedValue({
      market_value: 500,
      intrinsic_value: null,
      gap_pct: null,
      verdict_label: null,
      holdings_with_fv_count: 0,
      holdings_without_fv_count: 2,
      total_holdings: 2,
      as_of: "2026-05-25T14:00:00Z",
    })
    renderWithClient(<PortfolioSumOfPartsCard />)
    await waitFor(() => expect(screen.getByTestId("sop-empty")).toBeInTheDocument())
    expect(screen.getByText(/No DCF coverage/i)).toBeInTheDocument()
    expect(screen.getByText(/Analyse a stock/i)).toBeInTheDocument()
  })

  it("renders nothing when the user has zero holdings", async () => {
    getSopMock.mockResolvedValue({
      market_value: 0,
      intrinsic_value: null,
      gap_pct: null,
      verdict_label: null,
      holdings_with_fv_count: 0,
      holdings_without_fv_count: 0,
      total_holdings: 0,
      as_of: "2026-05-25T14:00:00Z",
    })
    const { container } = renderWithClient(<PortfolioSumOfPartsCard />)
    await waitFor(() => {
      // Either nothing renders or only an aria-busy skeleton briefly.
      expect(container.querySelector('[data-testid="sop-card"]')).toBeNull()
      expect(container.querySelector('[data-testid="sop-empty"]')).toBeNull()
    })
  })
})

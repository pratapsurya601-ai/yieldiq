/**
 * Portfolio Updates Feed (P0 #1) -- UpdatesFeed component smoke tests.
 *
 * Pins:
 *   1. Empty state per category renders the right copy.
 *   2. Populated path: rows render headline + detail + ticker + date.
 *   3. Category filter buttons drive a re-fetch with the right param.
 *   4. Load-more is hidden when total <= page size.
 *
 * The API client is mocked at the module boundary so no network is
 * hit; the QueryClient is constructed with retry: false so failures
 * surface immediately.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getPortfolioUpdates: vi.fn(),
}))

import { getPortfolioUpdates } from "@/lib/api"
import UpdatesFeed from "@/components/portfolio/UpdatesFeed"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const ONE_ITEM = {
  id: 1,
  ticker: "HDFCBANK",
  event_at: "2026-05-22T00:00:00+00:00",
  category: "dividends" as const,
  headline: "FY25 Final dividend declared: ₹19.50/share, ex-date 14 Jun 2026",
  detail: "The company has declared a dividend of ₹19.50 per share.",
  source_ref: null,
  created_at: "2026-05-23T03:00:00+00:00",
}

beforeEach(() => {
  vi.mocked(getPortfolioUpdates).mockReset()
})

describe("UpdatesFeed", () => {
  it("renders the empty-state copy for the 'all' filter when no items", async () => {
    vi.mocked(getPortfolioUpdates).mockResolvedValue({
      items: [],
      total: 0,
      portfolio_id: "me",
    })
    renderWithClient(<UpdatesFeed />)
    await waitFor(() =>
      expect(screen.getByText(/No updates yet for any of your holdings/i)).toBeInTheDocument(),
    )
  })

  it("renders the headline, detail, and ticker for a populated feed", async () => {
    vi.mocked(getPortfolioUpdates).mockResolvedValue({
      items: [ONE_ITEM],
      total: 1,
      portfolio_id: "me",
    })
    renderWithClient(<UpdatesFeed />)
    await waitFor(() => expect(screen.getByText(ONE_ITEM.headline)).toBeInTheDocument())
    expect(screen.getByText(ONE_ITEM.detail)).toBeInTheDocument()
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument()
    // No load-more when total fits in one page.
    expect(screen.queryByText(/Load more/i)).toBeNull()
  })

  it("re-queries with the chosen category when a filter button is clicked", async () => {
    vi.mocked(getPortfolioUpdates).mockResolvedValue({
      items: [],
      total: 0,
      portfolio_id: "me",
    })
    renderWithClient(<UpdatesFeed />)
    await waitFor(() => expect(getPortfolioUpdates).toHaveBeenCalled())
    const earningsBtn = screen.getByRole("button", { name: /Earnings/i })
    fireEvent.click(earningsBtn)
    await waitFor(() =>
      expect(getPortfolioUpdates).toHaveBeenCalledWith(
        expect.objectContaining({ category: "earnings", offset: 0 }),
      ),
    )
    // Empty-state copy switches to the earnings-specific message.
    await waitFor(() =>
      expect(screen.getByText(/No earnings updates yet/i)).toBeInTheDocument(),
    )
  })

  it("shows 'Load more' when total exceeds the page size", async () => {
    vi.mocked(getPortfolioUpdates).mockResolvedValue({
      items: Array.from({ length: 25 }, (_, i) => ({ ...ONE_ITEM, id: i + 1 })),
      total: 60,
      portfolio_id: "me",
    })
    renderWithClient(<UpdatesFeed />)
    await waitFor(() => expect(screen.getByText(/Load more/i)).toBeInTheDocument())
  })
})

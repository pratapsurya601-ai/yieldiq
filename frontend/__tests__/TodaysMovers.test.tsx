/**
 * TodaysMovers — daily-engagement widget on /home.
 *
 * Pins three render states the feat/home-commodities-movers PR ships:
 *
 *   1. Loading  — the skeleton renders before the API resolves.
 *   2. Populated — gainers + losers each show 5 rows, every row carries
 *                  a TickerAvatar, and the row links to /analysis/{T}.
 *   3. Empty    — stale=true (or zero gainers) renders the data-lag
 *                 message, not an error/crash.
 *
 * The point of these tests is structural drift detection: if someone
 * accidentally swaps the avatar or removes the per-row link, the
 * snapshot diff catches it. We mock `@/lib/api` to keep the test
 * hermetic — no real network in unit tests.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getTodayMovers: vi.fn(),
}))

import { getTodayMovers } from "@/lib/api"
import TodaysMovers from "@/components/home/v2/TodaysMovers"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const POPULATED_RESPONSE = {
  as_of: "2026-06-08T15:30:00+05:30",
  cohort: "nifty500",
  stale: false,
  gainers: [
    { ticker: "HDFCBANK", company_name: "HDFC Bank", change_pct: 4.2, close: 1650.5, prev_close: 1584.0 },
    { ticker: "RELIANCE", company_name: "Reliance",  change_pct: 3.8, close: 2300.0, prev_close: 2215.7 },
    { ticker: "TATAMOTORS", company_name: "Tata Motors", change_pct: 3.5, close: 850.0, prev_close: 821.3 },
    { ticker: "MARUTI",  company_name: "Maruti",     change_pct: 2.9, close: 9800.0, prev_close: 9523.8 },
    { ticker: "LT",      company_name: "L&T",        change_pct: 2.7, close: 3600.0, prev_close: 3505.4 },
  ],
  losers: [
    { ticker: "BHARTIARTL", company_name: "Bharti Airtel", change_pct: -3.1, close: 1200.0, prev_close: 1238.4 },
    { ticker: "TCS",        company_name: "TCS",            change_pct: -2.7, close: 3500.0, prev_close: 3597.1 },
    { ticker: "INFY",       company_name: "Infosys",        change_pct: -2.4, close: 1450.0, prev_close: 1485.7 },
    { ticker: "WIPRO",      company_name: "Wipro",          change_pct: -2.1, close:  450.0, prev_close:  459.6 },
    { ticker: "HCLTECH",    company_name: "HCL Tech",       change_pct: -1.9, close: 1300.0, prev_close: 1325.2 },
  ],
}

describe("TodaysMovers", () => {
  it("renders the skeleton before the API resolves (loading state)", () => {
    // Returning a never-resolving promise keeps the component on its
    // loading branch so we can pin the skeleton structure.
    vi.mocked(getTodayMovers).mockReturnValue(new Promise(() => {}))
    const { container } = renderWithClient(<TodaysMovers />)
    expect(container.querySelector("[data-testid='movers-skeleton']")).not.toBeNull()
    expect(container).toMatchSnapshot()
  })

  it("renders 5 gainers + 5 losers with avatars + analysis links (populated)", async () => {
    vi.mocked(getTodayMovers).mockResolvedValue(POPULATED_RESPONSE)
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(screen.getAllByTestId("movers-row").length).toBe(10)
    })
    // Each row must carry a TickerAvatar (image OR letter-mark
    // fallback — both have stable data-testids).
    const avatars = container.querySelectorAll(
      "[data-testid='ticker-avatar-image'], [data-testid='ticker-avatar-monogram']",
    )
    expect(avatars.length).toBe(10)
    // Each row's link must point at /analysis/{ticker}.
    const links = screen.getAllByTestId("movers-row")
    expect(links[0].getAttribute("href")).toBe("/analysis/HDFCBANK")
    expect(links[5].getAttribute("href")).toBe("/analysis/BHARTIARTL")
    // SEBI watch — verify no advisory copy snuck into the rendered DOM.
    const text = container.textContent || ""
    expect(text.toLowerCase()).not.toContain("buy")
    expect(text.toLowerCase()).not.toContain("recommend") // sebi-allow: recommend
    expect(text).toContain("Today’s Movers")
    expect(container).toMatchSnapshot()
  })

  it("renders the data-lag empty state when the response is stale", async () => {
    vi.mocked(getTodayMovers).mockResolvedValue({
      as_of: "2026-05-20T15:30:00+05:30",
      cohort: "nifty500",
      stale: true,
      gainers: [],
      losers: [],
    })
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(container.querySelector("[data-testid='movers-empty']")).not.toBeNull()
    })
    expect(screen.queryAllByTestId("movers-row").length).toBe(0)
    expect(container.textContent).toContain("Markets data lagging")
    expect(container).toMatchSnapshot()
  })
})

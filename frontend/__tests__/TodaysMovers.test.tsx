/**
 * TodaysMovers — daily-engagement widget on /home.
 *
 * Pins the render states the feat/quant-picks-previews-movers-fallback
 * PR ships:
 *
 *   1. Loading  — the skeleton renders before the API resolves.
 *   2. Live     — gainers + losers each show 5 rows, every row carries
 *                 a TickerAvatar, and the row links to /analysis/{T}.
 *   3. Cached   — live response is stale → render the localStorage
 *                 snapshot with a "Showing last refresh • DD MMM" tag.
 *   4. Preview  — live + cache both unavailable → render the top-3 of
 *                 each quant-pick preset under a "Worth a look" heading.
 *   5. Retry    — neither live nor cache nor preset previews resolved →
 *                 single-line "lagging" message + actionable Retry button.
 *   6. Manual refresh button always present, triggers refetch.
 *
 * The point of these tests is structural drift detection: the new
 * fallback chain is the whole point of the redesign and the snapshots
 * are how we notice when someone accidentally re-introduces the
 * full-panel empty state.
 *
 * Mocks: `@/lib/api` for hermetic network isolation; `window.localStorage`
 * is the real browser implementation that jsdom ships, cleared per test.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getTodayMovers: vi.fn(),
  runPreset: vi.fn(),
  runScreener: vi.fn(),
}))

import { getTodayMovers, runPreset, runScreener } from "@/lib/api"
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

const STALE_RESPONSE = {
  as_of: "2026-05-20T15:30:00+05:30",
  cohort: "nifty500",
  stale: true,
  gainers: [],
  losers: [],
}

// Stub a quant-picks preset response so the Worth-a-look fallback has
// something to render. Backend ScreenerStock has more fields than this
// — these are the minimum that the row renderer reads.
const PRESET_RESPONSE = {
  results: [
    { ticker: "BHARTIARTL.NS", company_name: "Bharti", score: 70, fair_value: 1700, current_price: 1180, margin_of_safety: 44, verdict: "Undervalued", moat: "Wide", confidence: "High", sector: "Telecom" },
    { ticker: "LT.NS",         company_name: "L&T",    score: 68, fair_value: 4700, current_price: 3600, margin_of_safety: 31, verdict: "Undervalued", moat: "Wide", confidence: "Medium", sector: "Industrials" },
    { ticker: "WIPRO.NS",      company_name: "Wipro",  score: 62, fair_value:  570, current_price:  450, margin_of_safety: 28, verdict: "Undervalued", moat: "Wide", confidence: "Medium", sector: "IT" },
  ],
  total: 14,
  page: 1,
  page_size: 25,
  filter_applied: { preset: "buffett" },
}

beforeEach(() => {
  // Clear localStorage between tests so each test sees a fresh
  // (no-cache) baseline unless it explicitly writes a snapshot.
  window.localStorage.clear()
  vi.mocked(getTodayMovers).mockReset()
  vi.mocked(runPreset).mockReset()
  vi.mocked(runScreener).mockReset()
  // Default preset stubs — individual tests override when they need a
  // different shape. Returning the same payload for every preset is
  // fine because the test only asserts at the row-count / data-testid
  // level, not at the "this row belongs to which preset" level.
  vi.mocked(runPreset).mockResolvedValue(PRESET_RESPONSE)
  vi.mocked(runScreener).mockResolvedValue(PRESET_RESPONSE)
})

describe("TodaysMovers", () => {
  it("renders the skeleton before the API resolves (loading state)", () => {
    // Returning a never-resolving promise keeps the component on its
    // loading branch so we can pin the skeleton structure.
    vi.mocked(getTodayMovers).mockReturnValue(new Promise(() => {}))
    const { container } = renderWithClient(<TodaysMovers />)
    expect(container.querySelector("[data-testid='movers-skeleton']")).not.toBeNull()
  })

  it("renders 5 gainers + 5 losers with avatars + analysis links (live)", async () => {
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
    expect(avatars.length).toBeGreaterThanOrEqual(10)
    // Each row's link must point at /analysis/{ticker}.
    const links = screen.getAllByTestId("movers-row")
    expect(links[0].getAttribute("href")).toBe("/analysis/HDFCBANK")
    expect(links[5].getAttribute("href")).toBe("/analysis/BHARTIARTL")
    // SEBI watch — verify no advisory copy snuck into the rendered DOM.
    const text = container.textContent || ""
    expect(text.toLowerCase()).not.toContain("buy")
    expect(text.toLowerCase()).not.toContain("recommend") // sebi-allow: recommend
    expect(text).toContain("Today’s Movers")
  })

  it("Tier-1: renders the localStorage cache with a freshness tag when live is stale", async () => {
    // Seed localStorage with a previous successful payload — this is
    // what happens after at least one fresh fetch has completed
    // before the next fetch returns stale.
    window.localStorage.setItem(
      "yieldiq:lastSeenMovers",
      JSON.stringify({
        cached_at: "2026-06-08T09:15:00+05:30",
        payload: POPULATED_RESPONSE,
      }),
    )
    // Live response comes back stale — must fall to the cached payload.
    vi.mocked(getTodayMovers).mockResolvedValue(STALE_RESPONSE)
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(container.querySelector("[data-testid='movers-cached']")).not.toBeNull()
    })
    // The cached snapshot must render the same 10 rows from POPULATED_RESPONSE.
    expect(screen.getAllByTestId("movers-row").length).toBe(10)
    // The freshness tag tells the user this isn't live data.
    expect(container.querySelector("[data-testid='movers-cached-tag']")).not.toBeNull()
    expect(container.textContent).toContain("Showing last refresh")
    // The big-empty whitespace block from the old design must NOT appear.
    expect(container.querySelector("[data-testid='movers-empty']")).toBeNull()
  })

  it("Tier-2: with no cache and stale live, renders the 'Worth a look' preview from quant presets", async () => {
    vi.mocked(getTodayMovers).mockResolvedValue(STALE_RESPONSE)
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(container.querySelector("[data-testid='movers-worth-a-look']")).not.toBeNull()
    })
    // Heading switches to "Worth a look" so we never mislabel preset
    // picks as actual market movers.
    expect(container.textContent).toContain("Worth a look")
    expect(container.textContent).not.toContain("Today’s Movers")
    // 3 preview columns (3 presets), 3 rows each = 9 ticker rows.
    expect(screen.getAllByTestId("movers-worth-a-look-row").length).toBe(9)
    // No big empty-state block.
    expect(container.querySelector("[data-testid='movers-empty']")).toBeNull()
  })

  it("Tier-3: with no cache and ALL queries returning empty, renders the single-line retry fallback", async () => {
    vi.mocked(getTodayMovers).mockResolvedValue(STALE_RESPONSE)
    // Empty results from every preset = Tier-2 cannot render, so we
    // fall through to the compact Tier-3 line + Retry button.
    const EMPTY_PRESET = { results: [], total: 0, page: 1, page_size: 25, filter_applied: {} }
    vi.mocked(runPreset).mockResolvedValue(EMPTY_PRESET)
    vi.mocked(runScreener).mockResolvedValue(EMPTY_PRESET)
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(container.querySelector("[data-testid='movers-empty']")).not.toBeNull()
    })
    // The Tier-3 panel is compact (single line + retry button), not
    // the wasteful full-panel block. Assert by structure: an inline
    // Retry button must be rendered alongside the message.
    expect(container.querySelector("[data-testid='movers-retry']")).not.toBeNull()
    expect(container.textContent).toContain("Markets data lagging")
    expect(container.textContent).toContain("refreshing in a moment")
  })

  it("manual Refresh button triggers a refetch", async () => {
    vi.mocked(getTodayMovers).mockResolvedValue(POPULATED_RESPONSE)
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(screen.getAllByTestId("movers-row").length).toBe(10)
    })
    // Sanity: first call was the auto-fire on mount.
    const initialCalls = vi.mocked(getTodayMovers).mock.calls.length
    expect(initialCalls).toBeGreaterThanOrEqual(1)

    const refresh = container.querySelector("[data-testid='movers-refresh']")
    expect(refresh).not.toBeNull()
    await act(async () => {
      fireEvent.click(refresh!)
    })
    // After the click, the API must have been re-invoked at least
    // one more time. (React-Query may dedup if the previous fetch is
    // still in flight; we tolerate that by checking for >= initialCalls + 1
    // OR isFetching === true, whichever fires first.)
    await waitFor(() => {
      expect(vi.mocked(getTodayMovers).mock.calls.length).toBeGreaterThan(initialCalls)
    })
  })

  it("Tier-3 Retry button triggers refetch", async () => {
    vi.mocked(getTodayMovers).mockResolvedValue(STALE_RESPONSE)
    const EMPTY_PRESET = { results: [], total: 0, page: 1, page_size: 25, filter_applied: {} }
    vi.mocked(runPreset).mockResolvedValue(EMPTY_PRESET)
    vi.mocked(runScreener).mockResolvedValue(EMPTY_PRESET)
    const { container } = renderWithClient(<TodaysMovers />)
    await waitFor(() => {
      expect(container.querySelector("[data-testid='movers-retry']")).not.toBeNull()
    })
    const initialCalls = vi.mocked(getTodayMovers).mock.calls.length
    await act(async () => {
      fireEvent.click(container.querySelector("[data-testid='movers-retry']")!)
    })
    await waitFor(() => {
      expect(vi.mocked(getTodayMovers).mock.calls.length).toBeGreaterThan(initialCalls)
    })
  })
})

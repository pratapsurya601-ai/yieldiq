/**
 * NewsFvCorrelationPanel — smoke tests.
 *
 * Pins:
 *   1. Empty payload (no material moves) -> renders the steady-state
 *      empty copy, not the timeline header.
 *   2. Populated payload -> renders one timeline entry per correlation,
 *      with FV-before / FV-after / pct-change and the linked driver
 *      headlines.
 *   3. "No clear headline driver" inline copy when likely_drivers is
 *      empty for a given FV change.
 *   4. SEBI vocabulary regression: rendered DOM contains zero banned
 *      tokens regardless of headline text. (Banned-tokens list is
 *      built from string fragments at runtime so this file passes
 *      --diff-only SEBI lint per CLAUDE.md Standing Rule 5 Pattern B.)
 *   5. Error path (fetch returns !ok) -> renders nothing — additive
 *      panel discipline.
 */
import React from "react"
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, waitFor, cleanup } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import NewsFvCorrelationPanel from "@/components/analysis/NewsFvCorrelationPanel"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const EMPTY_RESPONSE = {
  ticker: "RELIANCE",
  display_ticker: "RELIANCE",
  correlations: [],
  summary: {
    total_material_moves: 0,
    moves_with_drivers: 0,
    window_days: 7,
    min_driver_score: 0.15,
    top_drivers_per_move: 3,
  },
}

const POPULATED_RESPONSE = {
  ticker: "RELIANCE",
  display_ticker: "RELIANCE",
  correlations: [
    {
      fv_change_date: "2026-10-12",
      fv_before: 2400.0,
      fv_after: 2520.0,
      pct_change: 5.0,
      likely_drivers: [
        {
          news_id: "url-1",
          headline: "Q2 earnings beat consensus expectations",
          source: "Mint",
          url: "https://example.com/a",
          published_at: "2026-10-11T10:00:00Z",
          sentiment_score: 0.6,
          sentiment_label: "positive",
          importance: "high",
          source_quality_tier: "A",
          relevance_score: 0.82,
        },
      ],
    },
    {
      fv_change_date: "2026-09-15",
      fv_before: 2300.0,
      fv_after: 2200.0,
      pct_change: -4.35,
      likely_drivers: [],
    },
  ],
  summary: {
    total_material_moves: 2,
    moves_with_drivers: 1,
    window_days: 7,
    min_driver_score: 0.15,
    top_drivers_per_move: 3,
  },
}

function installFetchMock(payload: unknown, status = 200) {
  const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url)
    if (u.includes("/news-fv-correlation/")) {
      return new Response(JSON.stringify(payload), { status })
    }
    return new Response("not found", { status: 404 })
  })
  // @ts-expect-error — installing a jsdom fetch stub
  globalThis.fetch = fetchMock
  return fetchMock
}

// Per CLAUDE.md Standing Rule 5 Pattern B: build banned tokens at
// runtime from string concatenation so this file passes the
// --diff-only SEBI lint without per-line annotations.
const BANNED_RUNTIME_TOKENS = [
  "b" + "uy",
  "se" + "ll",
  "ho" + "ld",
  "ac" + "cumulate",
  "ex" + "pensive",
  "ch" + "eap",
  "at" + "tractive",
  "reco" + "mmend",
  "out" + "perform",
  "under" + "perform",
]

beforeEach(() => {
  cleanup()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("NewsFvCorrelationPanel", () => {
  it("renders the empty-state copy when correlations is empty", async () => {
    installFetchMock(EMPTY_RESPONSE)
    renderWithClient(<NewsFvCorrelationPanel ticker="RELIANCE" />)
    await waitFor(() => {
      expect(
        screen.getByText(/fair value has been steady/i),
      ).toBeInTheDocument()
    })
  })

  it("renders one timeline entry per correlation with FV deltas", async () => {
    installFetchMock(POPULATED_RESPONSE)
    renderWithClient(<NewsFvCorrelationPanel ticker="RELIANCE" />)

    // Both pct-change badges land.
    await waitFor(() => {
      expect(screen.getByText("+5.00%")).toBeInTheDocument()
    })
    expect(screen.getByText("-4.35%")).toBeInTheDocument()

    // Headline of the linked driver renders.
    expect(
      screen.getByText(/q2 earnings beat consensus expectations/i),
    ).toBeInTheDocument()

    // Source label renders.
    expect(screen.getByText("Mint")).toBeInTheDocument()

    // Empty-driver row renders the honest inline disclaimer.
    expect(
      screen.getByText(/no clear headline driver in the news window/i),
    ).toBeInTheDocument()
  })

  it("never leaks SEBI-banned vocabulary into the rendered DOM", async () => {
    installFetchMock(POPULATED_RESPONSE)
    const { container } = renderWithClient(
      <NewsFvCorrelationPanel ticker="RELIANCE" />,
    )
    await waitFor(() => {
      expect(screen.getByText(/News & fair value/i)).toBeInTheDocument()
    })
    const text = (container.textContent || "").toLowerCase()
    for (const token of BANNED_RUNTIME_TOKENS) {
      // Word-boundary check so "earnings beat" doesn't trip on "eat".
      const re = new RegExp(`\\b${token}\\b`, "i")
      expect(re.test(text)).toBe(false)
    }
  })

  it("renders nothing on fetch error", async () => {
    installFetchMock({ error: "boom" }, 500)
    const { container } = renderWithClient(
      <NewsFvCorrelationPanel ticker="RELIANCE" />,
    )
    // Wait long enough for the query to flush past loading state.
    await new Promise((r) => setTimeout(r, 50))
    // The error branch returns null — only the loading skeleton is
    // ever DOM-mounted; after the failed query it unmounts.
    await waitFor(() => {
      expect(
        container.querySelector('section[aria-label="News drove fair value"]'),
      ).toBeNull()
    })
  })
})

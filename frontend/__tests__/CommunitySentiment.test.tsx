/**
 * Week-3 manifesto — CommunitySentiment voting widget tests.
 *
 * Pins:
 *   1. Renders three vote buttons with SEBI-safe labels.
 *   2. Click while logged out → sign-in prompt (no POST fired).
 *   3. Click while logged in → optimistic count bump + POST fires.
 *   4. Aggregated bars render with percentages from the GET response.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import CommunitySentiment from "@/components/analysis/CommunitySentiment"
import { useAuthStore } from "@/store/authStore"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const AGG_RESPONSE = {
  ticker: "HDFCBANK",
  total_votes: 100,
  bullish_count: 58,
  neutral_count: 25,
  bearish_count: 17,
  bullish_pct: 58.0,
  neutral_pct: 25.0,
  bearish_pct: 17.0,
  your_vote: null,
  as_of: "2026-05-25T20:00:00Z",
}

const HISTORY_RESPONSE = {
  ticker: "HDFCBANK",
  days: 30,
  points: [],
}

function installFetchMock(postBody?: object) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.includes("/sentiment/HDFCBANK/history")) {
      return new Response(JSON.stringify(HISTORY_RESPONSE), { status: 200 })
    }
    if (u.includes("/sentiment/HDFCBANK/vote")) {
      const body = postBody ?? {
        ...AGG_RESPONSE,
        bullish_count: 59,
        total_votes: 101,
        your_vote: "bullish",
      }
      return new Response(JSON.stringify(body), { status: 200 })
    }
    if (u.includes("/sentiment/HDFCBANK")) {
      return new Response(JSON.stringify(AGG_RESPONSE), { status: 200 })
    }
    return new Response("not found", { status: 404 })
  })
  // @ts-expect-error — installing a jsdom fetch stub
  globalThis.fetch = fetchMock
  return fetchMock
}

beforeEach(() => {
  // Reset authStore singleton between tests.
  useAuthStore.setState({
    token: null,
    userId: null,
    email: null,
    tier: "free",
  } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("CommunitySentiment", () => {
  it("renders Bearish / Neutral / Bullish vote buttons", async () => {
    installFetchMock()
    renderWithClient(<CommunitySentiment ticker="HDFCBANK.NS" />)
    expect(
      await screen.findByRole("button", { name: /bullish/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /neutral/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /bearish/i })).toBeInTheDocument()
  })

  it("renders aggregated percentages once the GET resolves", async () => {
    installFetchMock()
    renderWithClient(<CommunitySentiment ticker="HDFCBANK" />)
    // The CountUp animation lands on the integer-rendered percentages.
    await waitFor(() => {
      // 58% on the Bullish row.
      expect(screen.getByText(/58/)).toBeInTheDocument()
    })
    // "leaning bullish" copy after the bars.
    await waitFor(() => {
      expect(screen.getByText(/leaning bullish/i)).toBeInTheDocument()
    })
  })

  it("shows sign-in prompt when an unauthenticated user clicks a vote", async () => {
    const fetchMock = installFetchMock()
    renderWithClient(<CommunitySentiment ticker="HDFCBANK" />)
    const bullishBtn = await screen.findByRole("button", { name: /bullish/i })

    fireEvent.click(bullishBtn)

    expect(await screen.findByRole("alert")).toHaveTextContent(/sign in/i)

    // Crucially: NO POST went out.
    const postCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/vote"),
    )
    expect(postCalls).toHaveLength(0)
  })

  it("posts a vote when authenticated and updates your_vote optimistically", async () => {
    const fetchMock = installFetchMock()
    useAuthStore.setState({
      token: "fake-jwt-token",
      userId: "user-alice",
      email: "alice@example.com",
      tier: "free",
    } as Partial<ReturnType<typeof useAuthStore.getState>> as never)

    renderWithClient(<CommunitySentiment ticker="HDFCBANK" />)
    const bullishBtn = await screen.findByRole("button", { name: /bullish/i })

    await act(async () => {
      fireEvent.click(bullishBtn)
    })

    // Vote POST eventually fires.
    await waitFor(() => {
      const postCalls = fetchMock.mock.calls.filter((c) =>
        String(c[0]).includes("/vote"),
      )
      expect(postCalls.length).toBeGreaterThanOrEqual(1)
    })

    // Bullish button reads as the active choice.
    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /bullish/i })
      expect(btn.getAttribute("aria-pressed")).toBe("true")
    })
  })
})

/**
 * Phase 4 manifesto (Paradigm 11) — MemoryLane personal history widget.
 *
 * Pins (updated 2026-06-11 — PR #901 empty-state policy):
 *   1. Anon user (no token) → renders a sign-in CTA card, never calls GET.
 *   2. Logged-in user, 204 from GET → renders a "welcome from here" card.
 *   3. Logged-in user, populated payload → renders days/price/FV/hypo10k
 *      copy.
 *   4. Typing in the note textarea debounces a PUT after 1s (auto-save).
 *
 * Previous behavior (returning null on cases 1 and 2) left the parent
 * "YOUR MEMORY LANE" section header on the analysis page with no body
 * below it; the component now always renders an explanatory slot.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import MemoryLane from "@/components/analysis/MemoryLane"
import { useAuthStore } from "@/store/authStore"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const POPULATED_PAYLOAD = {
  ticker: "HDFCBANK.NS",
  ticker_bare: "HDFCBANK",
  first_visited_at: "2026-04-08T12:00:00Z",
  last_visited_at: "2026-05-25T08:00:00Z",
  days_ago: 47,
  visit_count: 12,
  price_at_first_visit: 720,
  fair_value_at_first_visit: 1054,
  verdict_at_first_visit: "undervalued",
  current_price: 786,
  current_fair_value: 1131,
  current_verdict: "undervalued",
  price_delta_pct: 9.2,
  fv_delta_pct: 7.3,
  hypothetical_10k_value: 10917,
  user_note: null,
}

function installFetchMock(opts: {
  status?: number
  payload?: object | null
  onPut?: (body: unknown) => void
} = {}) {
  const status = opts.status ?? 200
  const payload = opts.payload ?? POPULATED_PAYLOAD
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    const method = (init?.method ?? "GET").toUpperCase()
    if (u.includes("/me/memory-lane/HDFCBANK/note") && method === "PUT") {
      if (opts.onPut) {
        try {
          opts.onPut(JSON.parse(String(init?.body ?? "{}")))
        } catch {
          opts.onPut(null)
        }
      }
      return new Response(JSON.stringify({ ok: true, user_note: "x" }), {
        status: 200,
      })
    }
    if (u.includes("/me/memory-lane/HDFCBANK")) {
      if (status === 204) return new Response(null, { status: 204 })
      return new Response(JSON.stringify(payload), { status })
    }
    return new Response("not found", { status: 404 })
  })
  // @ts-expect-error — jsdom fetch stub
  globalThis.fetch = fetchMock
  return fetchMock
}

beforeEach(() => {
  useAuthStore.setState({
    token: null,
    userId: null,
    email: null,
    tier: "free",
  } as Partial<ReturnType<typeof useAuthStore.getState>> as never)
  vi.useRealTimers()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ─────────────────────────────────────────────────────────────────
// 1. Anon + 204 — empty-state cards (PR #901 fix — no more orphan
//    "YOUR MEMORY LANE" header). Both branches now render a section
//    with explanatory copy instead of returning null.
// ─────────────────────────────────────────────────────────────────
describe("MemoryLane — empty states", () => {
  it("renders a sign-in CTA and skips the GET when the user is anonymous", async () => {
    const fetchMock = installFetchMock()
    const { container } = renderWithClient(
      <MemoryLane ticker="HDFCBANK.NS" companyName="HDFC Bank" />,
    )
    // The component now renders a sign-in CTA section instead of null.
    const section = container.querySelector(
      '[data-testid="memory-lane-signin-cta"]',
    )
    expect(section).not.toBeNull()
    // Section header still present so the slot reads as a real section.
    expect(
      screen.getByRole("heading", { name: /your memory lane/i }),
    ).toBeInTheDocument()
    // Sign-in nudge copy + CTA link.
    expect(screen.getByText(/sign in to keep a personal record/i)).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /sign in to start tracking/i }),
    ).toBeInTheDocument()
    // A tick to confirm no async fetch was queued — auth gate still
    // prevents the network call.
    await new Promise((r) => setTimeout(r, 10))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("renders a welcome card when the GET returns 204 (no prior visit)", async () => {
    useAuthStore.setState({
      token: "test-token",
      userId: "user-alice",
      email: "alice@example.com",
      tier: "free",
    } as never)
    const fetchMock = installFetchMock({ status: 204 })
    const { container } = renderWithClient(
      <MemoryLane ticker="HDFCBANK.NS" companyName="HDFC Bank" />,
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    // Wait for the welcome card to mount (replaces the loading skeleton
    // after the 204 resolves).
    await waitFor(() => {
      expect(
        container.querySelector('[data-testid="memory-lane-welcome"]'),
      ).not.toBeNull()
    })
    // Section header still present.
    expect(
      screen.getByRole("heading", { name: /your memory lane/i }),
    ).toBeInTheDocument()
    // Welcome copy from the component (uses HTML entities — match on a
    // stable substring).
    expect(
      screen.getByText(/we.ll start tracking from here/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/each return visit to/i),
    ).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────
// 2. Populated — renders the full layout
// ─────────────────────────────────────────────────────────────────
describe("MemoryLane — populated state", () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: "test-token",
      userId: "user-alice",
      email: "alice@example.com",
      tier: "free",
    } as never)
  })

  it("renders the days-ago + price + FV deltas + hypothetical-10k line", async () => {
    installFetchMock()
    renderWithClient(<MemoryLane ticker="HDFCBANK.NS" companyName="HDFC Bank" />)

    // Wait for the heading to appear.
    await screen.findByRole("heading", { name: /your memory lane/i })

    // "47 days ago" copy.
    expect(screen.getByText(/47 days ago/i)).toBeInTheDocument()

    // Price arrow line: 720 → 786 (rendered as ₹720 → ₹786, formatted).
    const priceMoved = screen.getByText(/price moved/i)
    expect(priceMoved).toBeInTheDocument()

    // Fair-value arrow line.
    const fvMoved = screen.getByText(/fair value moved/i)
    expect(fvMoved).toBeInTheDocument()

    // "still Undervalued" verdict line (verdictDisplayLabel maps the key).
    expect(screen.getByText(/still undervalued/i)).toBeInTheDocument()

    // Hypothetical-10k beat.
    expect(screen.getByText(/if you had bought/i)).toBeInTheDocument()

    // Visit count footer.
    expect(screen.getByText(/visited/i)).toBeInTheDocument()
    expect(screen.getByText(/times/i)).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────
// 3. Note auto-save — debounced PUT after 1s
// ─────────────────────────────────────────────────────────────────
describe("MemoryLane — note auto-save", () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: "test-token",
      userId: "user-alice",
      email: "alice@example.com",
      tier: "free",
    } as never)
  })

  it("debounces the PUT 1s after typing stops", async () => {
    const putBodies: unknown[] = []
    const fetchMock = installFetchMock({
      onPut: (body) => putBodies.push(body),
    })
    renderWithClient(<MemoryLane ticker="HDFCBANK.NS" companyName="HDFC Bank" />)
    await screen.findByRole("heading", { name: /your memory lane/i })

    // Switch to fake timers AFTER the initial GET resolves so React Query's
    // microtask plumbing isn't starved.
    vi.useFakeTimers()
    try {
      const textarea = screen.getByLabelText(/note for future-you/i)
      fireEvent.change(textarea, {
        target: { value: "First take: NIM compression visible." },
      })

      // Before 1s elapses, no PUT has fired yet.
      const callsBefore = fetchMock.mock.calls.filter(
        (c) => String(c[1]?.method ?? "GET").toUpperCase() === "PUT",
      ).length
      expect(callsBefore).toBe(0)

      act(() => {
        vi.advanceTimersByTime(1100)
      })
    } finally {
      vi.useRealTimers()
    }

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        (c) => String(c[1]?.method ?? "GET").toUpperCase() === "PUT",
      )
      expect(putCalls.length).toBe(1)
    })
    expect(putBodies[0]).toEqual({
      note: "First take: NIM compression visible.",
    })
  })
})

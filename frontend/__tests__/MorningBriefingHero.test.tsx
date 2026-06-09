/**
 * MorningBriefingHero — personalized /home opener.
 *
 * Covers:
 *   1. Loading state — skeleton renders all three placeholder rows
 *      and the actual tile/card content is NOT yet visible.
 *   2. Populated render — portfolio tile + NIFTY tile + briefing
 *      card all appear with the expected text and the briefing
 *      prose is SEBI-clean (no banned advisory verbs).
 *   3. Empty-portfolio render — portfolio tile is suppressed, NIFTY
 *      tile still renders, briefing copy invites onboarding.
 *
 * The auth store is stubbed via a lightweight module mock so we
 * don't need to spin up the full Zustand persistence layer. The
 * api helper is mocked to return one of three fixture shapes per
 * test, exercising the loading / success / empty branches without
 * any network IO.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

// Stub the auth store — only the two fields the hero reads from.
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { email: string | null; displayName: string | null }) => unknown) =>
    selector({ email: "surya@example.com", displayName: "Surya" }),
}))

vi.mock("@/lib/api", () => ({
  getMorningBriefing: vi.fn(),
}))

import { getMorningBriefing, type MorningBriefingResponse } from "@/lib/api"
import MorningBriefingHero from "@/components/home/v2/MorningBriefingHero"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const POPULATED: MorningBriefingResponse = {
  as_of: "2026-06-09T11:14:00+05:30",
  user_name: "Surya",
  portfolio: {
    total_value: 342_180.50,
    day_change: -1420.30,
    day_change_pct: -0.41,
    sparkline_7d: [338_000, 339_200, 340_100, 339_800, 341_500, 343_000, 342_180],
  },
  market: {
    nifty_value: 23_123.45,
    nifty_change_pct: -1.10,
    nifty_sparkline_7d: [23_500, 23_440, 23_390, 23_300, 23_280, 23_200, 23_123],
  },
  briefing_text:
    "NIFTY 50 is down 1.1% today after global cues. HDFCBANK is your biggest drag today (-0.8%). 3 stocks you watch moved more than 2% today.",
}

const EMPTY_PORTFOLIO: MorningBriefingResponse = {
  as_of: "2026-06-09T11:14:00+05:30",
  user_name: "Surya",
  portfolio: null,
  market: {
    nifty_value: 23_500.0,
    nifty_change_pct: 0.42,
    nifty_sparkline_7d: [23_300, 23_320, 23_400, 23_460, 23_500, 23_490, 23_500],
  },
  briefing_text:
    "NIFTY 50 is up 0.4% today. Welcome — add your first stock to start tracking.",
}

const BANNED_WORDS = [
  "buy", "sell", "hold", "recommend", "should",
  "outperform", "attractive", "cheap", "expensive",
]

function assertSebiClean(text: string) {
  const low = text.toLowerCase()
  for (const word of BANNED_WORDS) {
    const re = new RegExp(`\\b${word}\\b`)
    expect(re.test(low), `SEBI lint hit: ${word} in ${text}`).toBe(false)
  }
}

describe("MorningBriefingHero", () => {
  it("renders the loading skeleton before the query resolves", () => {
    // queryFn returns a never-resolving promise so we stay in isLoading.
    vi.mocked(getMorningBriefing).mockReturnValue(new Promise(() => {}))
    renderWithClient(<MorningBriefingHero />)
    // Skeleton structural marker
    expect(screen.getByTestId("morning-briefing-skeleton")).toBeInTheDocument()
    // The real briefing card MUST NOT be in the DOM yet.
    expect(screen.queryByTestId("morning-briefing-card")).not.toBeInTheDocument()
    expect(screen.queryByTestId("morning-briefing-portfolio-tile")).not.toBeInTheDocument()
  })

  it("renders portfolio + NIFTY tiles and SEBI-clean briefing prose on success", async () => {
    vi.mocked(getMorningBriefing).mockResolvedValue(POPULATED)
    renderWithClient(<MorningBriefingHero />)

    // Hero root replaces the skeleton.
    await waitFor(() =>
      expect(screen.getByTestId("morning-briefing-hero")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("morning-briefing-skeleton")).not.toBeInTheDocument()

    // Greeting uses the displayName from the auth store.
    // (greetingWord depends on the local IST hour at test time, so we
    //  assert the name token rather than the time-of-day word.)
    expect(screen.getByText(/Surya/)).toBeInTheDocument()

    // Both tiles are present.
    expect(screen.getByTestId("morning-briefing-portfolio-tile")).toBeInTheDocument()
    expect(screen.getByTestId("morning-briefing-nifty-tile")).toBeInTheDocument()
    // Tile labels
    expect(screen.getByText("Your portfolio")).toBeInTheDocument()
    expect(screen.getByText("NIFTY 50")).toBeInTheDocument()
    // Card label + prose
    expect(screen.getByText("Morning briefing")).toBeInTheDocument()
    const card = screen.getByTestId("morning-briefing-card")
    expect(card.textContent || "").toContain("HDFCBANK")
    expect(card.textContent || "").toContain("drag")
    // SEBI vocab guard on the prose.
    assertSebiClean(card.textContent || "")
    // Sparkline polyline rendered (one per tile).
    const sparks = screen.getAllByTestId("morning-briefing-sparkline")
    expect(sparks.length).toBe(2)
  })

  it("hides the portfolio tile and renders onboarding copy when portfolio is null", async () => {
    vi.mocked(getMorningBriefing).mockResolvedValue(EMPTY_PORTFOLIO)
    renderWithClient(<MorningBriefingHero />)

    await waitFor(() =>
      expect(screen.getByTestId("morning-briefing-hero")).toBeInTheDocument(),
    )

    // Portfolio tile MUST NOT render on the empty path.
    expect(
      screen.queryByTestId("morning-briefing-portfolio-tile"),
    ).not.toBeInTheDocument()
    // NIFTY tile still renders.
    expect(screen.getByTestId("morning-briefing-nifty-tile")).toBeInTheDocument()
    // Briefing prose nudges onboarding instead of citing drag/lift.
    const card = screen.getByTestId("morning-briefing-card")
    expect(card.textContent || "").toMatch(/Welcome/)
    expect(card.textContent || "").toMatch(/add your first stock/)
    expect((card.textContent || "").toLowerCase()).not.toContain("drag")
    expect((card.textContent || "").toLowerCase()).not.toContain("lift")
    assertSebiClean(card.textContent || "")
    // Only ONE sparkline (the NIFTY one) when the portfolio tile is hidden.
    expect(screen.getAllByTestId("morning-briefing-sparkline").length).toBe(1)
  })

  it("falls back to a plain greeting when the briefing query errors", async () => {
    vi.mocked(getMorningBriefing).mockRejectedValue(new Error("upstream 500"))
    renderWithClient(<MorningBriefingHero />)

    // Component sets retry: 1 — give React Query time to fail through
    // the initial fetch + one retry before asserting the fallback.
    await waitFor(
      () =>
        expect(screen.getByTestId("morning-briefing-fallback")).toBeInTheDocument(),
      { timeout: 3500 },
    )
    // Fallback uses the display name + a neutral greeting word; no
    // tiles or briefing card must leak through.
    expect(screen.queryByTestId("morning-briefing-portfolio-tile")).not.toBeInTheDocument()
    expect(screen.queryByTestId("morning-briefing-nifty-tile")).not.toBeInTheDocument()
    expect(screen.queryByTestId("morning-briefing-card")).not.toBeInTheDocument()
    expect(screen.getByText(/Surya/)).toBeInTheDocument()
  })
})

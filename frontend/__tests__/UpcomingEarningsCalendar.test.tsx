/**
 * UpcomingEarningsCalendar — regression guards for the forward
 * earnings-calendar panel that bridges next-earnings + consensus
 * EPS + historical surprise to a per-5%-beat FV sensitivity.
 *
 * Pins:
 *   1. Self-hides cleanly when the API returns impact: null.
 *   2. Renders the "Next earnings in N days" callout, scheduled
 *      date, consensus EPS (per-quarter + annual), historical
 *      surprise, and the +/- per-5%-beat sensitivity when impact
 *      is present.
 *   3. Day-counter renders "Today" at 0, "1 day" at 1, "N days"
 *      otherwise.
 *   4. Unconfirmed yfinance-fallback events surface an "Expected"
 *      hint in the scheduled-date caption (the badge the discover
 *      strip uses for unconfirmed dates).
 *   5. Heuristic badge is always present when the panel renders.
 *   6. SEBI vocabulary: zero banned tokens from
 *      scripts/check_sebi_words.py leak into the rendered DOM.
 *      Banned-array fixture built from string fragments at runtime
 *      so the diff-only SEBI lint pass stays clean (CLAUDE.md §5
 *      Pattern B).
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

import UpcomingEarningsCalendar from "@/components/analysis/UpcomingEarningsCalendar"

// Minimal payload shapes — kept inline so the test isn't coupled to
// a generated client.
function baseImpact(overrides: Record<string, unknown> = {}) {
  return {
    ticker: "INFY",
    estimated_report_date: "2026-06-15",
    days_until: 5,
    consensus_eps_estimate: 15.25,
    consensus_eps_estimate_annual: 61.0,
    consensus_revenue_estimate_cr: null,
    historical_avg_surprise_pct: 0.024,
    historical_surprise_quarters: 4,
    estimated_fv_impact_per_5pct_beat: 0.018,
    sector: "IT Services",
    sector_multiplier: 1.2,
    implied_growth_used: 0.10,
    confirmed: true,
    source: "nse_event_calendar",
    fiscal_period: "Q1FY27",
    notes: ["consensus_revenue_unavailable"],
    method: "forward_v1",
    is_heuristic: true,
    ...overrides,
  }
}

function mockFetch(payload: unknown, ok = true) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok,
    json: async () => payload,
  }) as unknown as typeof fetch
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("UpcomingEarningsCalendar — rendering", () => {
  it("renders the callout, EPS, surprise, and per-5%-beat slot", async () => {
    mockFetch({
      ticker: "INFY",
      impact: baseImpact(),
      is_heuristic: true,
    })
    render(<UpcomingEarningsCalendar ticker="INFY.NS" />)

    await waitFor(() => {
      expect(screen.getByTestId("upcoming-earnings-calendar")).toBeTruthy()
    })

    // Big "in N days" callout — the hero number lives inside the
    // upcoming-earnings-callout testid. Two render sites carry the
    // "5 days" substring (the heading "Next earnings in 5 days" and
    // the hero number), so we anchor the assertion to the callout
    // node rather than a global getByText that would multi-match.
    const callout = screen.getByTestId("upcoming-earnings-callout")
    expect(callout).toBeTruthy()
    expect(callout.textContent).toMatch(/5 days/)
    expect(callout.textContent).toMatch(/until next print/i)

    // Consensus EPS — both annual + per-quarter shown.
    expect(screen.getByText(/Rs\.15\.25/)).toBeTruthy()
    expect(screen.getByText(/Annual: Rs\.61\.00/)).toBeTruthy()

    // Historical surprise + sample size caption.
    expect(screen.getByText(/\+2\.4%/)).toBeTruthy()
    expect(screen.getByText(/Last 4 quarters/i)).toBeTruthy()

    // Per-5%-beat magnitude — rendered as +/- without a sign.
    const perBeat = screen.getByTestId("upcoming-earnings-per-5pct")
    expect(perBeat.textContent).toMatch(/±\s*1\.8%/)

    // Heuristic badge always present when the panel renders.
    expect(screen.getByText(/^Heuristic$/)).toBeTruthy()
  })

  it("renders Today at days_until=0", async () => {
    mockFetch({
      ticker: "INFY",
      impact: baseImpact({ days_until: 0 }),
      is_heuristic: true,
    })
    render(<UpcomingEarningsCalendar ticker="INFY.NS" />)

    await waitFor(() => {
      expect(screen.getByTestId("upcoming-earnings-callout")).toBeTruthy()
    })
    expect(screen.getByText("Today")).toBeTruthy()
  })

  it("renders 1 day at days_until=1", async () => {
    mockFetch({
      ticker: "INFY",
      impact: baseImpact({ days_until: 1 }),
      is_heuristic: true,
    })
    render(<UpcomingEarningsCalendar ticker="INFY.NS" />)

    await waitFor(() => {
      expect(screen.getByTestId("upcoming-earnings-callout")).toBeTruthy()
    })
    expect(screen.getByText("1 day")).toBeTruthy()
  })

  it("surfaces 'Expected (not yet filed)' for unconfirmed yf events", async () => {
    mockFetch({
      ticker: "INFY",
      impact: baseImpact({
        confirmed: false,
        source: "yfinance",
      }),
      is_heuristic: true,
    })
    render(<UpcomingEarningsCalendar ticker="INFY.NS" />)

    await waitFor(() => {
      expect(screen.getByTestId("upcoming-earnings-calendar")).toBeTruthy()
    })
    expect(
      screen.getByText(/Expected \(not yet filed\)/i),
    ).toBeTruthy()
  })

  it("emits no track-record line when historical_surprise_quarters=0", async () => {
    mockFetch({
      ticker: "INFY",
      impact: baseImpact({
        historical_avg_surprise_pct: 0,
        historical_surprise_quarters: 0,
      }),
      is_heuristic: true,
    })
    render(<UpcomingEarningsCalendar ticker="INFY.NS" />)

    await waitFor(() => {
      expect(screen.getByTestId("upcoming-earnings-calendar")).toBeTruthy()
    })
    expect(screen.getByText(/No track record/i)).toBeTruthy()
  })
})

describe("UpcomingEarningsCalendar — self-hide", () => {
  it("renders nothing when impact is null (no upcoming event)", async () => {
    mockFetch({
      ticker: "INFY",
      impact: null,
      reason: "no_upcoming_earnings",
      is_heuristic: true,
    })
    const { container } = render(
      <UpcomingEarningsCalendar ticker="INFY.NS" />,
    )

    // Wait for fetch to resolve, then assert the slot stays empty.
    await waitFor(() => {
      expect(container.querySelector("section")).toBeNull()
    })
  })

  it("renders nothing on a network failure", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(
      new Error("network error"),
    ) as unknown as typeof fetch
    const { container } = render(
      <UpcomingEarningsCalendar ticker="INFY.NS" />,
    )
    await waitFor(() => {
      expect(container.querySelector("section")).toBeNull()
    })
  })

  it("renders nothing when ticker is blank", async () => {
    const { container } = render(<UpcomingEarningsCalendar ticker="" />)
    expect(container.querySelector("section")).toBeNull()
  })
})

describe("UpcomingEarningsCalendar — SEBI vocabulary guard", () => {
  it("no banned advisory token leaks into the rendered DOM", async () => {
    // Pattern B (CLAUDE.md §5): build the banned list from string
    // fragments so the diff-only SEBI lint scan over this file
    // stays clean. The runtime assertion is identical to
    // checking against the literal list.
    const BANNED = [
      "app" + "ears",
      "sho" + "uld",
      "con" + "cern",
      "stren" + "gth",
      "wea" + "kness",
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "outperf" + "orm",
      "underperf" + "orm",
      "expen" + "sive",
      "che" + "ap",
      "attrac" + "tive",
      "po" + "or",
      "stro" + "ng",
      "we" + "ak",
      "accumu" + "late",
      "recomm" + "end",
      "recomm" + "endation",
      "invest" + "able",
      "invest" + "ability",
    ]

    mockFetch({
      ticker: "INFY",
      impact: baseImpact(),
      is_heuristic: true,
    })
    render(<UpcomingEarningsCalendar ticker="INFY.NS" />)

    await waitFor(() => {
      expect(screen.getByTestId("upcoming-earnings-calendar")).toBeTruthy()
    })

    const text = (document.body.textContent || "").toLowerCase()
    for (const word of BANNED) {
      expect(
        text.includes(word.toLowerCase()),
        `banned token "${word}" leaked into rendered DOM`,
      ).toBe(false)
    }
  })
})

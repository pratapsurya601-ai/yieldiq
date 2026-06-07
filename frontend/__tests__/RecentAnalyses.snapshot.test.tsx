/**
 * Snapshot test — locks the upgraded chip render shape for one of the
 * surfaces upgraded in this PR. We render RecentAnalyses with a
 * pre-seeded localStorage so the tile lights up its non-empty path,
 * then snapshot the immediate DOM to catch unintended structural drift
 * (e.g. someone accidentally removing the TickerAvatar).
 *
 * The status-fetch network call is left unmocked; rows resolve as
 * "loading" → "—" placeholders, which is exactly what we want for a
 * stable snapshot (no flaky live-data dependency).
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render } from "@testing-library/react"

import RecentAnalyses from "@/components/home/v2/RecentAnalyses"

// The component fetches summaries on mount. Stub the API so the test
// is hermetic — we want to snapshot the rendered chip layout, not the
// network behavior.
vi.mock("@/lib/api", () => ({
  getStockSummaryStatus: vi.fn().mockResolvedValue({ kind: "unavailable" }),
}))

describe("RecentAnalyses (snapshot)", () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.localStorage.setItem(
      "yq:recent-views",
      JSON.stringify([
        { ticker: "HDFCBANK.NS", viewedAt: 1700000000000 },
        { ticker: "TCS.NS", viewedAt: 1700000001000 },
      ]),
    )
  })

  it("renders TickerAvatar chips for each recent entry", () => {
    const { container } = render(<RecentAnalyses />)
    // Two entries → at least two avatar wrappers must be present.
    const avatars = container.querySelectorAll(
      "[data-testid='ticker-avatar-image'], [data-testid='ticker-avatar-monogram']",
    )
    expect(avatars.length).toBeGreaterThanOrEqual(2)
    // Lock the chip shape: the section heading and links must
    // remain in this exact structural arrangement.
    expect(container.querySelector("section")).toMatchSnapshot()
  })
})

/**
 * T6.5 — Watchlist-Relative Ranking tests.
 *
 * Covers:
 *   - Default sort key is MoS, descending (largest opportunity top).
 *   - Direction toggle flips ordering of present-data rows.
 *   - Alphabetical fallback for the escape hatch.
 *   - Holdings missing FV / MoS always sort to the bottom regardless
 *     of direction (so a half-empty watchlist still ranks usably).
 *   - Top-opportunity highlight renders for present data and is
 *     suppressed for alphabetical / all-missing.
 *   - Empty watchlist renders the empty state.
 *   - SEBI guard: no advisory vocabulary in rendered DOM.
 *
 * The SEBI banned-token array is built from runtime fragments so the
 * sebi-lint diff-only scan in CI does not see the literal strings as
 * "added banned tokens". See CLAUDE.md "SEBI vocab guard tests" rule.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, within, fireEvent } from "@testing-library/react"

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

import {
  WatchlistRanking,
  compareBy,
  fvGapAbs,
  priceChangePct,
  formatMetric,
} from "@/components/watchlist/WatchlistRanking"
import type { WatchlistItemResponse } from "@/types/api"

// ── Fixture builder ──────────────────────────────────────────
function w(
  ticker: string,
  overrides: Partial<WatchlistItemResponse> = {},
): WatchlistItemResponse {
  return {
    ticker,
    company_name: `${ticker} Ltd`,
    added_price: 100,
    target_price: 0,
    alert_mos_threshold: 0,
    notes: "",
    added_at: "2026-01-01T00:00:00Z",
    fair_value: 120,
    mos_pct: 16.6,
    buffett_mos_pct: 16.6,
    verdict: null,
    ...overrides,
  }
}

// ── Sort logic ───────────────────────────────────────────────
describe("compareBy / sort math", () => {
  it("orders larger MoS as the more interesting holding", () => {
    // compareBy now keys on TRUE (Buffett) MoS via buffett_mos_pct.
    // trueMos = upside / (1 + upside/100):
    //   a: 5 / 1.05 ≈ 4.76   b: 25 / 1.25 = 20.0
    // compareNullable(4.76, 20.0) = −15.24 < 0, so b sorts first when desc.
    const a = w("A", { mos_pct: 5, buffett_mos_pct: 5 / 1.05 })
    const b = w("B", { mos_pct: 25, buffett_mos_pct: 25 / 1.25 })
    // compareBy returns a.trueMos - b.trueMos so b (20.0) is "greater" — under
    // descending the caller negates this so b sorts first.
    expect(compareBy(a, b, "mos")).toBeLessThan(0)
  })

  it("falls back to alphabetical when key === alphabetical", () => {
    const a = w("AAA")
    const b = w("BBB")
    expect(compareBy(a, b, "alphabetical")).toBeLessThan(0)
  })

  it("returns +Infinity when the LHS metric is missing (loses regardless of direction)", () => {
    // Must null out buffett_mos_pct AND fair_value so computeTrueMos also returns null.
    const a = w("A", { mos_pct: null, buffett_mos_pct: null, fair_value: null })
    const b = w("B", { mos_pct: 10, buffett_mos_pct: 10 / 1.1 })
    expect(compareBy(a, b, "mos")).toBe(Number.POSITIVE_INFINITY)
  })

  it("fvGapAbs is FV minus added price; null when either missing", () => {
    expect(fvGapAbs(w("A", { fair_value: 150, added_price: 100 }))).toBe(50)
    expect(fvGapAbs(w("A", { fair_value: null }))).toBeNull()
    expect(fvGapAbs(w("A", { added_price: 0 }))).toBeNull()
  })

  it("priceChangePct prefers target, falls back to FV", () => {
    expect(
      priceChangePct(w("A", { added_price: 100, target_price: 110, fair_value: 200 })),
    ).toBe(10)
    expect(
      priceChangePct(w("A", { added_price: 100, target_price: 0, fair_value: 150 })),
    ).toBe(50)
    expect(
      priceChangePct(w("A", { added_price: 100, target_price: 0, fair_value: null })),
    ).toBeNull()
  })

  it("formatMetric pretty-prints MoS with sign and one decimal", () => {
    // formatMetric now reads TRUE (Buffett) MoS from buffett_mos_pct.
    // trueMos = upside / (1 + upside/100):
    //   12.345 / 1.12345 ≈ 10.988 → toFixed(1) = "11.0"
    //   -4.4   / 0.956   ≈ -4.603 → toFixed(1) = "-4.6"
    // null case: buffett_mos_pct null + fair_value null → computeTrueMos returns null → "—"
    expect(formatMetric(w("A", { mos_pct: 12.345, buffett_mos_pct: 12.345 / 1.12345 }), "mos")).toBe("MoS +11.0%")
    expect(formatMetric(w("A", { mos_pct: -4.4, buffett_mos_pct: -4.4 / 0.956 }), "mos")).toBe("MoS -4.6%")
    expect(formatMetric(w("A", { mos_pct: null, buffett_mos_pct: null, fair_value: null }), "mos")).toBe("—")
  })
})

// ── Render: default sort = MoS desc ──────────────────────────
describe("WatchlistRanking — default render", () => {
  // trueMos from upside:  LOW 2/1.02≈1.96  MID 14/1.14≈12.28  HIGH 35/1.35≈25.93
  // Descending true-MoS order: HIGH > MID > LOW (same as upside order).
  // Banner shows HIGH's true-MoS: (1 - 100/135)*100 = 25.926% → "MoS +25.9%"
  const holdings = [
    w("LOW",  { mos_pct: 2,  buffett_mos_pct: 2  / 1.02  }),
    w("HIGH", { mos_pct: 35, buffett_mos_pct: 35 / 1.35  }),
    w("MID",  { mos_pct: 14, buffett_mos_pct: 14 / 1.14  }),
  ]

  it("renders the highest MoS holding first", () => {
    render(<WatchlistRanking holdings={holdings} />)
    const list = screen.getByTestId("watchlist-ranking-list")
    const items = within(list).getAllByRole("listitem")
    expect(items[0].getAttribute("data-testid")).toBe("watchlist-ranking-row-HIGH")
    expect(items[1].getAttribute("data-testid")).toBe("watchlist-ranking-row-MID")
    expect(items[2].getAttribute("data-testid")).toBe("watchlist-ranking-row-LOW")
  })

  it("shows the top-opportunity highlight for the leader", () => {
    render(<WatchlistRanking holdings={holdings} />)
    const banner = screen.getByTestId("watchlist-top-opportunity")
    expect(within(banner).getByText(/HIGH/)).toBeInTheDocument()
    // Headline is true MoS: 35/1.35 ≈ 25.926% → toFixed(1) = "25.9"
    expect(within(banner).getByText(/MoS \+25\.9%/)).toBeInTheDocument()
  })
})

// ── Direction toggle ─────────────────────────────────────────
describe("WatchlistRanking — direction toggle", () => {
  it("toggling direction reverses the present-data order", () => {
    const holdings = [
      w("A", { mos_pct: 10, buffett_mos_pct: 10 / 1.10 }),
      w("B", { mos_pct: 30, buffett_mos_pct: 30 / 1.30 }),
    ]
    render(<WatchlistRanking holdings={holdings} />)
    let items = within(screen.getByTestId("watchlist-ranking-list")).getAllByRole(
      "listitem",
    )
    expect(items[0].getAttribute("data-testid")).toBe("watchlist-ranking-row-B")

    fireEvent.click(screen.getByTestId("watchlist-rank-direction"))

    items = within(screen.getByTestId("watchlist-ranking-list")).getAllByRole(
      "listitem",
    )
    expect(items[0].getAttribute("data-testid")).toBe("watchlist-ranking-row-A")
  })
})

// ── Missing-data behavior ────────────────────────────────────
describe("WatchlistRanking — missing data", () => {
  it("rows without MoS sort to the bottom even on ascending direction", () => {
    const holdings = [
      w("MISSING", { mos_pct: null, buffett_mos_pct: null, fair_value: null }),
      w("LOW",  { mos_pct: 5,  buffett_mos_pct: 5  / 1.05 }),
      w("HIGH", { mos_pct: 25, buffett_mos_pct: 25 / 1.25 }),
    ]
    render(<WatchlistRanking holdings={holdings} />)
    // Flip to ascending — the missing row must still be last.
    fireEvent.click(screen.getByTestId("watchlist-rank-direction"))
    const items = within(screen.getByTestId("watchlist-ranking-list")).getAllByRole(
      "listitem",
    )
    expect(items[items.length - 1].getAttribute("data-testid")).toBe(
      "watchlist-ranking-row-MISSING",
    )
  })
})

// ── Sort key change resets direction ─────────────────────────
describe("WatchlistRanking — sort key switching", () => {
  it("switching to alphabetical orders A to Z and hides the highlight", () => {
    const holdings = [
      w("ZEBRA", { mos_pct: 40 }),
      w("APPLE", { mos_pct: 5 }),
      w("MANGO", { mos_pct: 18 }),
    ]
    render(<WatchlistRanking holdings={holdings} />)
    fireEvent.change(screen.getByTestId("watchlist-rank-key"), {
      target: { value: "alphabetical" },
    })
    const items = within(screen.getByTestId("watchlist-ranking-list")).getAllByRole(
      "listitem",
    )
    expect(items[0].getAttribute("data-testid")).toBe("watchlist-ranking-row-APPLE")
    expect(items[1].getAttribute("data-testid")).toBe("watchlist-ranking-row-MANGO")
    expect(items[2].getAttribute("data-testid")).toBe("watchlist-ranking-row-ZEBRA")
    // Highlight is suppressed for alphabetical sort.
    expect(screen.queryByTestId("watchlist-top-opportunity")).toBeNull()
  })

  it("switching to FV-gap re-orders by absolute rupee gap", () => {
    const holdings = [
      w("SMALLGAP", { fair_value: 110, added_price: 100, mos_pct: 9 }),
      w("BIGGAP", { fair_value: 300, added_price: 100, mos_pct: 66 }),
    ]
    render(<WatchlistRanking holdings={holdings} />)
    fireEvent.change(screen.getByTestId("watchlist-rank-key"), {
      target: { value: "fv_gap" },
    })
    const items = within(screen.getByTestId("watchlist-ranking-list")).getAllByRole(
      "listitem",
    )
    expect(items[0].getAttribute("data-testid")).toBe("watchlist-ranking-row-BIGGAP")
  })
})

// ── Remove button ────────────────────────────────────────────
describe("WatchlistRanking — remove handler", () => {
  it("forwards remove clicks to the parent handler", () => {
    const onRemove = vi.fn()
    render(
      <WatchlistRanking holdings={[w("PICK", { mos_pct: 20 })]} onRemove={onRemove} />,
    )
    fireEvent.click(screen.getByLabelText(/Remove PICK from watchlist/))
    expect(onRemove).toHaveBeenCalledWith("PICK")
  })
})

// ── Empty state ──────────────────────────────────────────────
describe("WatchlistRanking — empty state", () => {
  it("renders the descriptive empty state when no holdings are provided", () => {
    render(<WatchlistRanking holdings={[]} />)
    expect(screen.getByTestId("watchlist-ranking-empty")).toBeInTheDocument()
    expect(screen.queryByTestId("watchlist-ranking-list")).toBeNull()
  })
})

// ── SEBI guard ───────────────────────────────────────────────
//
// Build banned tokens from runtime fragments so the diff-only sebi-lint
// scan doesn't trip on the test file. See CLAUDE.md, agent-dispatch
// rule #5.
describe("WatchlistRanking — SEBI guard", () => {
  it("does not render any banned advisory vocabulary", () => {
    const holdings = [
      w("ONE", { mos_pct: 20 }),
      w("TWO", { mos_pct: -5 }),
    ]
    const { container } = render(<WatchlistRanking holdings={holdings} />)
    const text = (container.textContent || "").toLowerCase()
    const banned = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "reco" + "mmend",
      "outper" + "form",
      "underper" + "form",
      "acc" + "umulate",
      "che" + "ap",
      "expen" + "sive",
      "attra" + "ctive",
    ]
    for (const tok of banned) {
      expect(text.includes(tok)).toBe(false)
    }
  })
})

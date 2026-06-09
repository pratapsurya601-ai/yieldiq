/**
 * QuantPicksGrid — 4-tile screener preview on /home.
 *
 * Pins the redesign shipped in
 * feat/quant-picks-previews-movers-fallback: each tile now renders the
 * top-3 ticker previews (TickerAvatar + ticker + MoS) instead of just
 * a bare count number, and the footer dynamically reads
 * "See N more →" / "View all →" / "Tap to refine filters →" depending
 * on how many results the preset returned.
 *
 * Mocks: `@/lib/api` so the 4 tile fetchers stay hermetic.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  runPreset: vi.fn(),
  runScreener: vi.fn(),
}))

import { runPreset, runScreener } from "@/lib/api"
import QuantPicksGrid from "@/components/home/v2/QuantPicksGrid"
import { QUANT_PRESETS } from "@/components/home/v2/quantPicksPresets"
import { SCREENER_PRESETS } from "@/lib/screenerFilters"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// Backend ScreenerStock — `score` / `margin_of_safety` / `verdict` are
// the fields the row renderer reads; everything else is filler so the
// type narrows correctly.
function mkStock(
  ticker: string,
  mos: number,
  verdict: string = "Undervalued",
) {
  return {
    ticker,
    company_name: ticker.replace(/\.(NS|BO)$/, ""),
    score: 70,
    fair_value: 1000,
    current_price: 700,
    margin_of_safety: mos,
    verdict,
    moat: "Wide",
    confidence: "High",
    sector: "IT",
  }
}

// Preset payload with N results — total > N when N == 3 so we can
// assert the "See K more →" footer.
function mkPresetResponse(
  stocks: ReturnType<typeof mkStock>[],
  total: number = stocks.length,
) {
  return {
    results: stocks,
    total,
    page: 1,
    page_size: 25,
    filter_applied: {},
  }
}

beforeEach(() => {
  vi.mocked(runPreset).mockReset()
  vi.mocked(runScreener).mockReset()
})

describe("QuantPicksGrid", () => {
  it("renders 3 ticker previews per card when the API returns >= 3 results", async () => {
    // Three named presets back the first three tiles + custom screener
    // backs the fourth. All four get an identical 3-stock + total=14
    // payload so we can confirm the "See N more →" footer math.
    const PAYLOAD = mkPresetResponse(
      [
        mkStock("BHARTIARTL.NS", 44),
        mkStock("LT.NS", 31),
        mkStock("WIPRO.NS", 28),
      ],
      14,
    )
    vi.mocked(runPreset).mockResolvedValue(PAYLOAD)
    vi.mocked(runScreener).mockResolvedValue(PAYLOAD)

    const { container } = renderWithClient(<QuantPicksGrid />)

    await waitFor(() => {
      // 4 tiles × 3 preview rows = 12 rows.
      expect(screen.getAllByTestId("quant-tile-row").length).toBe(12)
    })

    // Each row carries a TickerAvatar — image OR letter-mark fallback
    // both have stable data-testids on the TickerAvatar component.
    const avatars = container.querySelectorAll(
      "[data-testid='ticker-avatar-image'], [data-testid='ticker-avatar-monogram']",
    )
    expect(avatars.length).toBeGreaterThanOrEqual(12)

    // Each row's link points at /analysis/{ticker-without-suffix}.
    const rows = screen.getAllByTestId("quant-tile-row")
    expect(rows[0].getAttribute("href")).toBe("/analysis/BHARTIARTL")
    expect(rows[1].getAttribute("href")).toBe("/analysis/LT")
    expect(rows[2].getAttribute("href")).toBe("/analysis/WIPRO")

    // Footer shows "See {total - 3} more →" — here 14 - 3 = 11.
    expect(container.textContent).toContain("See 11 more")

    // MoS labels render with the "MoS +XX%" pattern (the previous design
    // showed just "+44%" which was ambiguous as a row signal).
    expect(container.textContent).toContain("MoS +44%")
    expect(container.textContent).toContain("MoS +31%")
  })

  it("shows 'Tap to refine filters →' when a preset returns < 3 results", async () => {
    // First preset returns just 1 stock — must render the refine
    // prompt instead of "See N more". Remaining presets return 3+ so
    // we can compare against the canonical footer.
    const SPARSE = mkPresetResponse([mkStock("INFY.NS", 12)], 1)
    const FULL = mkPresetResponse(
      [mkStock("BHARTIARTL.NS", 44), mkStock("LT.NS", 31), mkStock("WIPRO.NS", 28)],
      14,
    )
    vi.mocked(runPreset).mockImplementation((preset: string) => {
      if (preset === "buffett") return Promise.resolve(SPARSE)
      return Promise.resolve(FULL)
    })
    vi.mocked(runScreener).mockResolvedValue(FULL)

    const { container } = renderWithClient(<QuantPicksGrid />)

    await waitFor(() => {
      // Sparse tile's refine-filters prompt is keyed by preset name.
      expect(
        container.querySelector("[data-testid='quant-tile-refine-buffett']"),
      ).not.toBeNull()
    })

    // The refine prompt copy must match the SEBI-vetted phrasing.
    const refineLink = container.querySelector(
      "[data-testid='quant-tile-refine-buffett']",
    )
    expect(refineLink?.textContent).toContain("Tap to refine filters")

    // The other 3 tiles continue to render the "See N more →" footer.
    const moreLinks = container.querySelectorAll(
      "[data-testid^='quant-tile-more-']",
    )
    expect(moreLinks.length).toBeGreaterThanOrEqual(3)
  })

  it("shows the count number and SEBI-clean copy in every tile", async () => {
    const PAYLOAD = mkPresetResponse(
      [
        mkStock("BHARTIARTL.NS", 44),
        mkStock("LT.NS", 31),
        mkStock("WIPRO.NS", 28),
      ],
      14,
    )
    vi.mocked(runPreset).mockResolvedValue(PAYLOAD)
    vi.mocked(runScreener).mockResolvedValue(PAYLOAD)

    const { container } = renderWithClient(<QuantPicksGrid />)

    await waitFor(() => {
      expect(
        container.querySelector("[data-testid='quant-tile-count-buffett']"),
      ).not.toBeNull()
    })

    // Tile titles + sub-captions are untouched (SEBI-vetted strings).
    expect(container.textContent).toContain("Wide-Moat at Discount")
    expect(container.textContent).toContain("Deep Value")
    expect(container.textContent).toContain("High-Margin Growers")
    expect(container.textContent).toContain("Quality at a Discount")

    // No banned advisory words leak in from the new row markup.
    const text = (container.textContent || "").toLowerCase()
    expect(text).not.toContain("buy")
    expect(text).not.toContain("recommend") // sebi-allow: recommend
    expect(text).not.toContain("outperform") // sebi-allow: outperform
  })

  it("each tile href targets a frontend SCREENER_PRESETS key (deep-link bug fix)", () => {
    // Pins the P1 fix: tile hrefs MUST use canonical frontend preset
    // keys (high_quality / deep_value / ...) so /screener?preset=<key>
    // resolves directly via applyPreset without depending on the alias
    // map. The OLD hrefs used backend preset names (buffett /
    // deep-value / growth-quality) and one tile used loose ?min_score
    // / ?min_mos params that the screener page never read — every tile
    // was a dead-link by construction.
    const frontendKeys = new Set(SCREENER_PRESETS.map((p) => p.key))

    for (const tile of QUANT_PRESETS) {
      // href must be /screener?preset=<key> shape (no loose params).
      expect(tile.href).toMatch(/^\/screener\?preset=[a-z_]+$/)

      // The preset key portion must be a canonical frontend preset key.
      const url = new URL(tile.href, "http://localhost")
      const preset = url.searchParams.get("preset")
      expect(preset, `tile ${tile.key} href ${tile.href}`).not.toBeNull()
      expect(
        frontendKeys.has(preset as string),
        `tile ${tile.key} href preset "${preset}" must be a frontend SCREENER_PRESETS key`,
      ).toBe(true)
    }
  })
})

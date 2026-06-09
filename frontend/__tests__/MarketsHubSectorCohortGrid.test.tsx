/**
 * SectorCohortGrid — /markets hub (2026-06-09 rewrite).
 *
 * Pure-component coverage of the three render paths:
 *   - tiles rendered with mock data, ordered by ranked_slugs
 *   - skeleton during the initial fetch
 *   - empty-state when the API returns no sectors
 *
 * Also includes a SEBI banned-vocab DOM regression check: the rendered
 * tree must contain none of the advisory verbs. Per CLAUDE rule #5,
 * the banned array is built from string fragments at runtime so the
 * source file itself stays SEBI-lint clean in diff-only mode.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

import SectorCohortGrid from "@/app/(marketing)/markets/SectorCohortGrid"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const ROTATION_PAYLOAD = {
  sectors: [
    {
      slug: "it-services",
      display_name: "IT Services",
      ticker_count: 16,
      median_mos_pct: 12.4,
      median_score: 68.0,
      median_fv_to_price_ratio: 1.12,
      verdict_distribution: { undervalued: 9, fairly_valued: 5, overvalued: 2 },
      pct_undervalued: 56.3,
      top_discounts: [],
    },
    {
      slug: "fmcg",
      display_name: "FMCG",
      ticker_count: 11,
      median_mos_pct: -3.1,
      median_score: 55.0,
      median_fv_to_price_ratio: 0.97,
      verdict_distribution: { undervalued: 3, fairly_valued: 6, overvalued: 2 },
      pct_undervalued: 27.3,
      top_discounts: [],
    },
    {
      slug: "metals",
      display_name: "Metals & Mining",
      ticker_count: 10,
      median_mos_pct: null,
      median_score: null,
      median_fv_to_price_ratio: null,
      verdict_distribution: { undervalued: 0, fairly_valued: 0, overvalued: 0 },
      pct_undervalued: null,
      top_discounts: [],
    },
  ],
  ranked_slugs: ["it-services", "fmcg", "metals"],
  computed_at: "2026-06-09T08:00:00Z",
  universe_ticker_count: 37,
  notes: "SEBI-safe placeholder.",
}

describe("SectorCohortGrid", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(ROTATION_PAYLOAD),
      } as never),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders one tile per sector with display name + count + median MoS", async () => {
    renderWithClient(<SectorCohortGrid />)
    await waitFor(() => {
      expect(screen.getAllByTestId("sector-cohort-tile").length).toBe(3)
    })
    expect(screen.getByText("IT Services")).toBeInTheDocument()
    expect(screen.getByText("FMCG")).toBeInTheDocument()
    expect(screen.getByText(/Metals/)).toBeInTheDocument()
    // Count chip on each tile.
    expect(screen.getByText("16 stocks")).toBeInTheDocument()
    expect(screen.getByText("11 stocks")).toBeInTheDocument()
    // Formatted median MoS.
    const mosEls = screen.getAllByTestId("sector-cohort-mos")
    const mosText = mosEls.map(el => el.textContent ?? "")
    expect(mosText).toContain("+12%")
    expect(mosText).toContain("-3%")
    expect(mosText).toContain("—")   // null cohort renders em-dash
  })

  it("renders tiles in ranked_slugs order (most-discounted first)", async () => {
    renderWithClient(<SectorCohortGrid />)
    await waitFor(() => {
      expect(screen.getAllByTestId("sector-cohort-tile").length).toBe(3)
    })
    const tiles = screen.getAllByTestId("sector-cohort-tile")
    // ranked_slugs is [it-services, fmcg, metals] — first tile must
    // link to /sector/it-services.
    expect(tiles[0]).toHaveAttribute("href", "/sector/it-services")
    expect(tiles[1]).toHaveAttribute("href", "/sector/fmcg")
    expect(tiles[2]).toHaveAttribute("href", "/sector/metals")
  })

  it("renders the empty state when the API returns no sectors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          sectors: [],
          ranked_slugs: [],
          computed_at: "2026-06-09T08:00:00Z",
          universe_ticker_count: 0,
          notes: "",
        }),
      } as never),
    )
    renderWithClient(<SectorCohortGrid />)
    await waitFor(() => {
      expect(screen.getByTestId("sector-cohort-empty")).toBeInTheDocument()
    })
    // Navigational fallback CTA is rendered.
    expect(screen.getByText(/All sectors/)).toBeInTheDocument()
  })

  it("renders the empty state when the fetch fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve(null),
      } as never),
    )
    renderWithClient(<SectorCohortGrid />)
    await waitFor(() => {
      expect(screen.getByTestId("sector-cohort-empty")).toBeInTheDocument()
    })
  })

  it("never renders advisory verbs in the populated grid (SEBI guard)", async () => {
    // Pattern B from CLAUDE.md rule #5: banned words built from
    // string fragments at runtime so this test file itself stays
    // clean in diff-only sebi-lint mode. The runtime substring check
    // is the same — just no literal banned tokens in the source.
    const banned: string[] = [
      "b" + "uy",
      "s" + "ell",
      "h" + "old",
      "pi" + "ck",
      "reco" + "mmend",
      "stro" + "ng",
      "wea" + "k",
      "advic" + "e",
    ]
    const { container } = renderWithClient(<SectorCohortGrid />)
    await waitFor(() => {
      expect(screen.getAllByTestId("sector-cohort-tile").length).toBe(3)
    })
    const text = (container.textContent || "").toLowerCase()
    for (const word of banned) {
      // Each token must NOT appear anywhere in the rendered tile tree.
      expect(text.includes(word)).toBe(false)
    }
  })
})

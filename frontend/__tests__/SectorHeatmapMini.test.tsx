/**
 * SectorHeatmapMini tests.
 *
 * Pins these behaviours (sector-heatmap-mini, 2026-06-10):
 *   1. Renders one tile per cohort row from the API; subject tile is
 *      marked with the subject test-id and has the ring styling.
 *   2. Tile color reflects the MoS band (green for positive, red for
 *      negative, gray for the +/-5% neutral band).
 *   3. Click on a non-subject tile pushes /analysis/{bare_ticker} via
 *      next/navigation router.
 *   4. Soft-fail: when the endpoint returns null (503 / no cohort)
 *      the component renders nothing.
 *   5. Tooltip builder is SEBI-neutral — only verdictDisplayLabel
 *      output is used, never the raw advisory verbs the backend
 *      may carry on legacy rows. Banned vocab list is built from
 *      fragments at runtime so diff-only sebi-lint never flags
 *      this file (CLAUDE.md rule #5).
 */
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

const getSectorHeatmapMock = vi.fn()
const pushMock = vi.fn()

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    getSectorHeatmap: (...a: unknown[]) => getSectorHeatmapMock(...a),
  }
})

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}))

import SectorHeatmapMini, {
  buildTileTooltip,
} from "@/components/analysis/SectorHeatmapMini"
import type {
  SectorHeatmapResponse,
  SectorHeatmapTile,
} from "@/lib/api"

function tile(overrides: Partial<SectorHeatmapTile>): SectorHeatmapTile {
  return {
    ticker: "TCS",
    name: "Tata Consultancy Services",
    market_cap_cr: 1_400_000,
    mos_pct: 12.4,
    fair_value: 4200,
    current_price: 3700,
    verdict: "undervalued",
    industry: "IT Services",
    is_subject: false,
    ...overrides,
  }
}

const ITSERV_RESPONSE: SectorHeatmapResponse = {
  ticker: "INFY.NS",
  sector: "Technology",
  industry: "IT Services",
  subject_ticker: "INFY",
  tile_count: 4,
  caption: "4 Technology sector tickers; 4 share the IT Services industry",
  tiles: [
    tile({ ticker: "TCS", mos_pct: 18, market_cap_cr: 1_500_000 }),
    tile({
      ticker: "INFY",
      name: "Infosys",
      mos_pct: 8.1,
      market_cap_cr: 720_000,
      verdict: "undervalued",
      is_subject: true,
    }),
    tile({
      ticker: "WIPRO",
      name: "Wipro",
      mos_pct: -22,
      market_cap_cr: 250_000,
      verdict: "overvalued",
    }),
    tile({
      ticker: "TECHM",
      name: "Tech Mahindra",
      mos_pct: 0.2,
      market_cap_cr: 130_000,
      verdict: "fairly_valued",
    }),
  ],
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  )
}

describe("SectorHeatmapMini", () => {
  beforeEach(() => {
    getSectorHeatmapMock.mockReset()
    pushMock.mockReset()
  })

  it("renders a tile per cohort row and marks the subject tile", async () => {
    getSectorHeatmapMock.mockResolvedValueOnce(ITSERV_RESPONSE)
    renderWithClient(<SectorHeatmapMini ticker="INFY" />)

    await waitFor(() => {
      expect(screen.getByTestId("sector-heatmap-mini")).toBeInTheDocument()
    })
    // 4 cohort tiles total — 3 non-subject + 1 subject.
    const nonSubjectTiles = screen.getAllByTestId("sector-heatmap-tile")
    expect(nonSubjectTiles.length).toBe(3)
    const subjectTile = screen.getByTestId("sector-heatmap-tile-subject")
    expect(subjectTile).toBeInTheDocument()
    expect(subjectTile.getAttribute("data-ticker")).toBe("INFY")
    // Sector label is rendered in the header. (Multiple instances
    // are fine — caption also names the sector — so use getAllByText.)
    expect(screen.getAllByText(/Technology/).length).toBeGreaterThan(0)
    // Caption surfaces too.
    expect(screen.getByTestId("sector-heatmap-caption").textContent).toMatch(
      /4 Technology sector tickers/,
    )
  })

  it("colors each tile by MoS band", async () => {
    getSectorHeatmapMock.mockResolvedValueOnce(ITSERV_RESPONSE)
    renderWithClient(<SectorHeatmapMini ticker="INFY" />)

    await waitFor(() =>
      expect(screen.getByTestId("sector-heatmap-mini")).toBeInTheDocument(),
    )

    const byTicker = (t: string) =>
      screen.getByText(t).closest("button") as HTMLElement

    // TCS at +18 → mid-green class.
    expect(byTicker("TCS").className).toMatch(/bg-emerald-200/)
    // WIPRO at -22 → mid-red class.
    expect(byTicker("WIPRO").className).toMatch(/bg-rose-200/)
    // TECHM at +0.2 (within +/-5%) → neutral gray.
    expect(byTicker("TECHM").className).toMatch(/bg-slate-200/)
  })

  it("navigates to /analysis/{ticker} when a tile is clicked", async () => {
    getSectorHeatmapMock.mockResolvedValueOnce(ITSERV_RESPONSE)
    renderWithClient(<SectorHeatmapMini ticker="INFY" />)

    await waitFor(() =>
      expect(screen.getByTestId("sector-heatmap-mini")).toBeInTheDocument(),
    )
    const tcsTile = screen.getByText("TCS").closest("button") as HTMLElement
    fireEvent.click(tcsTile)
    expect(pushMock).toHaveBeenCalledWith("/analysis/TCS")
  })

  it("renders nothing when the endpoint returns null", async () => {
    getSectorHeatmapMock.mockResolvedValueOnce(null)
    const { container } = renderWithClient(
      <SectorHeatmapMini ticker="HDFCBANK" />,
    )
    await waitFor(() => {
      expect(
        screen.queryByTestId("sector-heatmap-mini"),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByTestId("sector-heatmap-skeleton"),
      ).not.toBeInTheDocument()
    })
    // Final state has neither the panel nor the skeleton — the
    // component returned null. We allow ANY transient section to
    // exist mid-resolution; the only invariant is "no
    // sector-heatmap-mini in the final tree".
    void container
  })

  it("renders nothing when the cohort is empty", async () => {
    getSectorHeatmapMock.mockResolvedValueOnce({
      ticker: "WHATEVER.NS",
      sector: "Technology",
      industry: null,
      subject_ticker: "WHATEVER",
      tile_count: 0,
      caption: null,
      tiles: [],
    } satisfies SectorHeatmapResponse)
    const { container } = renderWithClient(
      <SectorHeatmapMini ticker="WHATEVER" />,
    )
    await waitFor(() => {
      expect(
        screen.queryByTestId("sector-heatmap-mini"),
      ).not.toBeInTheDocument()
    })
    // Final state has neither the panel nor the skeleton — the
    // component returned null. We allow ANY transient section to
    // exist mid-resolution; the only invariant is "no
    // sector-heatmap-mini in the final tree".
    void container
  })

  it("buildTileTooltip emits SEBI-neutral copy via verdictDisplayLabel", () => {
    // Banned advisory verbs built from fragments at runtime so the
    // diff-only sebi-lint scan (which reads ADDED LINES) never flags
    // this test file. See CLAUDE.md standing rule #5.
    const BANNED = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "stro" + "ng b" + "uy",
      "stro" + "ng se" + "ll",
    ]
    const tooltip = buildTileTooltip(
      tile({ ticker: "TCS", name: "Tata Consultancy Services", verdict: "undervalued" }),
    )
    for (const word of BANNED) {
      expect(tooltip.toLowerCase()).not.toContain(word)
    }
    expect(tooltip).toMatch(/TCS/)
    expect(tooltip).toMatch(/MoS/)
  })
})

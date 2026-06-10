/**
 * SectorHeatmap (home v2) — sector-overview tile grid on /home.
 *
 * Pins the 2026-06-11 P0 fix: the panel used to render <Skeleton />
 * on both (isLoading) AND (!data), which meant a /api/v1/market/sectors
 * error left the pulsing gray bars on screen forever. The render path
 * now treats the error/empty case separately and surfaces an
 * <EmptyState /> tile with "Heatmap data unavailable" copy + a retry
 * button. A 5s loading-timeout also swaps the skeleton out so a hung
 * fetch never animates indefinitely.
 *
 * Mock surface: `@/lib/api.getSectorOverview` only — that's the sole
 * external dependency for this component.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

vi.mock("@/lib/api", () => ({
  getSectorOverview: vi.fn(),
}))

import { getSectorOverview } from "@/lib/api"
import SectorHeatmap from "@/components/home/v2/SectorHeatmap"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const POPULATED = [
  { name: "Technology", avg_score: 65, pct_undervalued: 55, trend: "up" },
  { name: "Financials", avg_score: 62, pct_undervalued: 60, trend: "up" },
  { name: "Healthcare", avg_score: 58, pct_undervalued: 45, trend: "flat" },
]

beforeEach(() => {
  vi.mocked(getSectorOverview).mockReset()
})

describe("SectorHeatmap (home)", () => {
  it("renders one tile per sector when the API resolves", async () => {
    vi.mocked(getSectorOverview).mockResolvedValue(POPULATED)
    renderWithClient(<SectorHeatmap />)

    await waitFor(() => {
      expect(screen.getByText("Technology")).toBeInTheDocument()
    })
    expect(screen.getByText("Financials")).toBeInTheDocument()
    expect(screen.getByText("Healthcare")).toBeInTheDocument()
    // Score number rendered as the headline tile signal.
    expect(screen.getByText("65")).toBeInTheDocument()
    // Empty state must NOT show on the success path.
    expect(screen.queryByTestId("sector-heatmap-empty")).not.toBeInTheDocument()
  })

  it("shows the EmptyState fallback when the endpoint errors", async () => {
    vi.mocked(getSectorOverview).mockRejectedValue(new Error("upstream 500"))
    renderWithClient(<SectorHeatmap />)

    // The component sets retry:2 with exponential backoff (1s, 2s,
    // 4s) — give the waitFor enough budget to clear all retries.
    // Bumped to 10s because react-query schedules the next attempt
    // off the previous attempt's settled time, not off mount.
    await waitFor(
      () => expect(screen.getByTestId("sector-heatmap-empty")).toBeInTheDocument(),
      { timeout: 10_000 },
    )
    // Empty state copy + retry handle.
    expect(screen.getByText("Heatmap data unavailable")).toBeInTheDocument()
    expect(screen.getByTestId("sector-heatmap-retry")).toBeInTheDocument()
    // The skeleton must not be left behind on the error path — that's
    // the regression this fallback closes.
    expect(screen.queryByTestId("sector-heatmap-skeleton")).not.toBeInTheDocument()
  }, 15_000)

  it("shows the EmptyState fallback when the API returns an empty array", async () => {
    vi.mocked(getSectorOverview).mockResolvedValue([])
    renderWithClient(<SectorHeatmap />)

    await waitFor(() =>
      expect(screen.getByTestId("sector-heatmap-empty")).toBeInTheDocument(),
    )
    expect(screen.getByText("Heatmap data unavailable")).toBeInTheDocument()
  })

  it("retry button re-invokes the fetcher", async () => {
    // First call (and 2 retries) all reject — react-query exhausts
    // retries before surfacing the error to the component. Subsequent
    // calls after the manual retry resolve.
    vi.mocked(getSectorOverview).mockRejectedValue(new Error("blip"))
    renderWithClient(<SectorHeatmap />)

    await waitFor(
      () => expect(screen.getByTestId("sector-heatmap-empty")).toBeInTheDocument(),
      { timeout: 10_000 },
    )
    // Flip to a resolved mock so the manual refetch surfaces data.
    vi.mocked(getSectorOverview).mockResolvedValue(POPULATED)
    fireEvent.click(screen.getByTestId("sector-heatmap-retry"))

    await waitFor(
      () => {
        expect(screen.getByText("Technology")).toBeInTheDocument()
        expect(screen.queryByTestId("sector-heatmap-empty")).not.toBeInTheDocument()
      },
      { timeout: 10_000 },
    )
  }, 20_000)
})

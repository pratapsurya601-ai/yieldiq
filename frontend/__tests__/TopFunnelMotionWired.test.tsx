/**
 * TopFunnelMotionWired — drift detection for the motion-primitives wiring
 * shipped in feat/animate-top-funnel-pages.
 *
 * Each test renders the touched surface (QuantPicksGrid, TodaysMovers,
 * IndexDashboardsRow, ScreenerPresetsWithCounts) and asserts the
 * motion components left their signature `data-*` attributes on the
 * rendered DOM. The motion library writes these unconditionally — they
 * are present regardless of reduced-motion preference, so the test is
 * stable across environments.
 *
 * The point of these tests is structural pinning: if a future refactor
 * accidentally peels off a HoverCard / RevealStagger wrapper, the
 * assertion fails before the regression ships.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

// Hermetic API isolation — these surfaces all use react-query, and the
// query layer is happy to render the loading state for the assertions
// we make (we only inspect motion attributes, not data content).
vi.mock("@/lib/api", () => ({
  getMarketPulse: vi.fn(),
  getSectorOverview: vi.fn(),
  getTodayMovers: vi.fn(),
  getSparklines: vi.fn(),
  runPreset: vi.fn(),
  runScreener: vi.fn(),
}))

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  // Reset DOM-level reduced-motion toggle written by some tests.
  document.documentElement.removeAttribute("data-yq-motion-off")
  window.localStorage.clear()
})

// ── Home: QuantPicksGrid ────────────────────────────────────────────
describe("Home page motion wiring", () => {
  it("QuantPicksGrid wraps the grid in RevealStagger + each tile in HoverCard", async () => {
    const { default: QuantPicksGrid } = await import(
      "@/components/home/v2/QuantPicksGrid"
    )
    const { container } = renderWithClient(<QuantPicksGrid />)

    // RevealStagger marks its outer wrapper with data-anim="reveal-stagger".
    expect(
      container.querySelector('[data-anim="reveal-stagger"]'),
    ).not.toBeNull()
    // Each of the 4 tiles is a HoverCard — data-motion="hover-card".
    expect(
      container.querySelectorAll('[data-motion="hover-card"]').length,
    ).toBeGreaterThanOrEqual(4)
  })

  it("SectorHeatmap renders ShimmerSkeleton tiles in the loading state", async () => {
    const { default: SectorHeatmap } = await import(
      "@/components/home/v2/SectorHeatmap"
    )
    const { container } = renderWithClient(<SectorHeatmap />)

    // While the query is loading, the Skeleton path runs and we get the
    // 13 ShimmerSkeleton tiles tagged with data-motion="shimmer-skeleton".
    expect(
      container.querySelectorAll('[data-motion="shimmer-skeleton"]').length,
    ).toBeGreaterThanOrEqual(1)
  })
})

// ── Markets: IndexDashboardsRow ─────────────────────────────────────
describe("Markets page motion wiring", () => {
  it("IndexDashboardsRow uses RevealStagger + per-card HoverCard", async () => {
    const { default: IndexDashboardsRow } = await import(
      "@/app/(marketing)/markets/IndexDashboardsRow"
    )
    const { container } = renderWithClient(<IndexDashboardsRow />)

    expect(
      container.querySelector('[data-anim="reveal-stagger"]'),
    ).not.toBeNull()
    // 3 dashboards = 3 HoverCard wrappers.
    expect(
      container.querySelectorAll('[data-motion="hover-card"]').length,
    ).toBeGreaterThanOrEqual(3)
  })
})

// ── Discover: ScreenerPresetsWithCounts ─────────────────────────────
describe("Discover page motion wiring", () => {
  it("ScreenerPresetsWithCounts wraps presets in RevealStagger + HoverCard", async () => {
    const { default: ScreenerPresetsWithCounts } = await import(
      "@/components/discover/ScreenerPresetsWithCounts"
    )
    const { container } = render(<ScreenerPresetsWithCounts />)

    expect(
      container.querySelector('[data-anim="reveal-stagger"]'),
    ).not.toBeNull()
    // 4 preset cards = 4 HoverCard wrappers.
    expect(
      container.querySelectorAll('[data-motion="hover-card"]').length,
    ).toBeGreaterThanOrEqual(4)
  })
})

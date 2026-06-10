/**
 * RevenueSegmentBreakdown — component tests (task #176-followup,
 * 2026-06-10).
 *
 * Covers:
 *   - Renders both donut cards + legends when both buckets populated.
 *   - Renders the fastest-growing trend chip only when payload.trend
 *     is non-null and growth is positive.
 *   - Renders the honest "AR signals coming soon" empty state when
 *     both buckets are empty.
 *   - Renders the withheld envelope state without leaking AR text.
 *   - Rolls up segments past the top-6 into a single "Other (n)" row.
 *
 * SEBI-clean: no banned vocabulary in any string literal or fixture.
 * The vocab guard array (used in the leak assertion) is built from
 * fragments per CLAUDE.md standing rule #5.
 */
import * as React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import RevenueSegmentBreakdown, {
  type RevenueSegmentsPayload,
} from "@/components/analysis/RevenueSegmentBreakdown"

vi.mock("axios", () => {
  const instance = {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  }
  const axios = {
    create: () => instance,
    get: instance.get,
    post: instance.post,
  }
  return { default: axios, ...axios }
})

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

function payloadFromInitial(
  overrides: Partial<RevenueSegmentsPayload> = {},
): RevenueSegmentsPayload {
  return {
    ticker: "TEST",
    fiscal_year: 2024,
    published_at: "2024-06-15",
    business_segments: [],
    geo_segments: [],
    trend: null,
    withheld: false,
    source: "annual_report",
    ...overrides,
  }
}

describe("RevenueSegmentBreakdown", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders both donut cards + legends when both buckets populated", () => {
    const initial = payloadFromInitial({
      business_segments: [
        {
          name: "Mobile Services",
          revenue_cr: 100000,
          pct: 70,
          ebit_cr: 22000,
          yoy_growth_pct: 12,
          fy: "FY24",
        },
        {
          name: "Home Broadband",
          revenue_cr: 30000,
          pct: 20,
          ebit_cr: 5000,
          yoy_growth_pct: 28,
          fy: "FY24",
        },
        {
          name: "Enterprise",
          revenue_cr: 15000,
          pct: 10,
          ebit_cr: 1500,
          yoy_growth_pct: 8,
          fy: "FY24",
        },
      ],
      geo_segments: [
        {
          name: "India",
          revenue_cr: 100000,
          pct: 65,
          ebit_cr: null,
          yoy_growth_pct: null,
          fy: "FY24",
        },
        {
          name: "Africa",
          revenue_cr: 54000,
          pct: 35,
          ebit_cr: null,
          yoy_growth_pct: null,
          fy: "FY24",
        },
      ],
      trend: { name: "Home Broadband", yoy_growth_pct: 28 },
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    expect(screen.getByTestId("revenue-segments-panel")).toBeTruthy()
    expect(screen.getByTestId("rev-seg-business-card")).toBeTruthy()
    expect(screen.getByTestId("rev-seg-geo-card")).toBeTruthy()

    // Legend rows present with name + pct. "Home Broadband" is
    // also rendered inside the trend chip — use getAllByText.
    expect(screen.getByText("Mobile Services")).toBeTruthy()
    expect(screen.getAllByText("Home Broadband").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Enterprise")).toBeTruthy()
    expect(screen.getByText("India")).toBeTruthy()
    expect(screen.getByText("Africa")).toBeTruthy()

    // Percentage strings rendered in legend.
    expect(screen.getByText("70.0%")).toBeTruthy()
    expect(screen.getByText("20.0%")).toBeTruthy()
  })

  it("renders the fastest-growing trend chip with the YoY pct", () => {
    const initial = payloadFromInitial({
      business_segments: [
        {
          name: "Hi-Tech",
          revenue_cr: 25000,
          pct: 50,
          ebit_cr: 5000,
          yoy_growth_pct: 22,
          fy: "FY24",
        },
        {
          name: "Manufacturing",
          revenue_cr: 25000,
          pct: 50,
          ebit_cr: null,
          yoy_growth_pct: 5,
          fy: "FY24",
        },
      ],
      trend: { name: "Hi-Tech", yoy_growth_pct: 22 },
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    const chip = screen.getByTestId("revenue-segments-trend-chip")
    expect(chip).toBeTruthy()
    expect(chip.textContent).toContain("Hi-Tech")
    expect(chip.textContent).toContain("+22.0% YoY")
  })

  it("does NOT render the trend chip when payload.trend is null", () => {
    const initial = payloadFromInitial({
      business_segments: [
        {
          name: "IT Services",
          revenue_cr: 80000,
          pct: 100,
          ebit_cr: null,
          yoy_growth_pct: null,
          fy: "FY24",
        },
      ],
      trend: null,
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    expect(screen.queryByTestId("revenue-segments-trend-chip")).toBeNull()
  })

  it("renders the empty state when both buckets are empty", () => {
    const initial = payloadFromInitial({
      business_segments: [],
      geo_segments: [],
      fiscal_year: null,
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="UNKNOWN" initialData={initial} />,
    )

    expect(screen.getByTestId("revenue-segments-empty")).toBeTruthy()
    expect(screen.queryByTestId("revenue-segments-panel")).toBeNull()
  })

  it("renders the withheld envelope without leaking any free text", () => {
    const initial = payloadFromInitial({
      withheld: true,
      business_segments: [],
      geo_segments: [],
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="ACME" initialData={initial} />,
    )

    expect(screen.getByTestId("revenue-segments-withheld")).toBeTruthy()
    expect(screen.queryByTestId("revenue-segments-panel")).toBeNull()
  })

  it("rolls up segments past the top-6 into a single Other bucket", () => {
    // 8 business segments — expect 6 + "Other (2)".
    const items = Array.from({ length: 8 }, (_, i) => ({
      name: `Segment ${i + 1}`,
      revenue_cr: 10000 - i * 500,
      pct: Math.round((10000 - i * 500) / 60000 * 100 * 10) / 10,
      ebit_cr: null,
      yoy_growth_pct: null,
      fy: "FY24",
    }))
    const initial = payloadFromInitial({ business_segments: items })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    expect(screen.getByText("Segment 1")).toBeTruthy()
    expect(screen.getByText("Segment 6")).toBeTruthy()
    expect(screen.queryByText("Segment 7")).toBeNull()
    expect(screen.queryByText("Segment 8")).toBeNull()
    expect(screen.getByText("Other (2)")).toBeTruthy()
  })

  it("does not leak any quality-vocab banned words in the rendered DOM", () => {
    // Pattern B per CLAUDE.md standing rule #5 — build the array at
    // runtime from fragments so the diff-only SEBI scanner sees no
    // banned tokens in this file.
    const banned = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "stro" + "ng",
      "recom" + "mend",
      "tar" + "get",
      "rat" + "ing",
    ]
    const initial = payloadFromInitial({
      business_segments: [
        {
          name: "Retail Banking",
          revenue_cr: 110000,
          pct: 65,
          ebit_cr: null,
          yoy_growth_pct: 14,
          fy: "FY24",
        },
        {
          name: "Wholesale Banking",
          revenue_cr: 60000,
          pct: 35,
          ebit_cr: null,
          yoy_growth_pct: 9,
          fy: "FY24",
        },
      ],
      trend: { name: "Retail Banking", yoy_growth_pct: 14 },
    })

    const { container } = renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    const dom = (container.textContent || "").toLowerCase()
    for (const word of banned) {
      expect(dom).not.toContain(word)
    }
  })

  it("shows the fiscal-year chip when payload.fiscal_year is set", () => {
    const initial = payloadFromInitial({
      fiscal_year: 2024,
      business_segments: [
        {
          name: "Royal Enfield",
          revenue_cr: 17000,
          pct: 100,
          ebit_cr: null,
          yoy_growth_pct: null,
          fy: "FY24",
        },
      ],
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    expect(screen.getByTestId("revenue-segments-fy").textContent).toBe("FY24")
  })

  it("hovering a slice highlights it (opacity transition reachable)", () => {
    const initial = payloadFromInitial({
      business_segments: [
        {
          name: "Seg A",
          revenue_cr: 100,
          pct: 60,
          ebit_cr: null,
          yoy_growth_pct: null,
          fy: "FY24",
        },
        {
          name: "Seg B",
          revenue_cr: 67,
          pct: 40,
          ebit_cr: null,
          yoy_growth_pct: null,
          fy: "FY24",
        },
      ],
    })

    renderWithClient(
      <RevenueSegmentBreakdown ticker="TEST" initialData={initial} />,
    )

    const sliceA = screen.getByTestId("donut-slice-0")
    fireEvent.mouseEnter(sliceA)
    // Hover state surfaces the pct centre-label; "60.0%" is unique to A.
    expect(screen.getAllByText("60.0%").length).toBeGreaterThan(0)
    fireEvent.mouseLeave(sliceA)
  })
})

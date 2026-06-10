/**
 * Tests for EarningsWaterfallChart — pure helpers + renderer smoke.
 *
 * Covers: quarter labelling (Indian FY), beat/miss classification at
 * the ±2% boundary, YoY computation against the same calendar quarter
 * one year prior, sparse-input degradation, chip strip focus, beat-
 * miss legend visibility, and loading / empty states.
 */
import * as React from "react"
import { describe, it, expect, beforeAll, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { FinancialYear, FinancialsResponse } from "@/lib/api"

// Mock getFinancials before importing the component.
const getFinancialsMock = vi.fn<
  (ticker: string, period?: "annual" | "quarterly", years?: number) => Promise<FinancialsResponse>
>()
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    getFinancials: (...args: Parameters<typeof actual.getFinancials>) =>
      getFinancialsMock(...args),
  }
})

import EarningsWaterfallChart, {
  buildChartRows,
  classifyBeatMiss,
  labelQuarter,
} from "@/components/analysis/EarningsWaterfallChart"

beforeAll(() => {
  const g = globalThis as unknown as { ResizeObserver?: unknown }
  if (typeof g.ResizeObserver === "undefined") {
    g.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

function mockQuarter(
  year: string,
  period_end: string | null,
  overrides: Partial<FinancialYear & { consensus_revenue?: number | null }> = {},
): FinancialYear & { consensus_revenue?: number | null } {
  return {
    year,
    period_end,
    revenue: null,
    revenue_growth_pct: null,
    gross_profit: null,
    gross_margin_pct: null,
    ebitda: null,
    operating_income: null,
    operating_margin_pct: null,
    net_income: null,
    net_income_growth_pct: null,
    net_margin_pct: null,
    eps_diluted: null,
    total_assets: null,
    total_equity: null,
    total_debt: null,
    cash: null,
    net_debt: null,
    debt_to_equity: null,
    book_value_per_share: null,
    operating_cash_flow: null,
    capex: null,
    free_cash_flow: null,
    fcf_margin_pct: null,
    ...overrides,
  }
}

function makeResponse(rows: FinancialYear[]): FinancialsResponse {
  return {
    ticker: "TEST.NS",
    currency: "INR",
    currency_unit: "Cr",
    period: "quarterly",
    years_available: rows.length,
    has_quarterly: true,
    data_source: "db",
    tier: "free",
    tier_limited: false,
    income: rows,
    balance_sheet: [],
    cash_flow: [],
    summary: {
      revenue_cagr_3y: null,
      avg_net_margin: null,
      avg_fcf_margin: null,
      latest_roe: null,
    },
  }
}

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// ────────────────────────────────────────────────────────────────────
// labelQuarter
// ────────────────────────────────────────────────────────────────────
describe("labelQuarter", () => {
  it("maps a June period_end to Q1 of the next FY", () => {
    expect(labelQuarter({ year: "2025Q1", period_end: "2025-06-30" })).toBe("Q1 FY26")
  })

  it("maps a December period_end to Q3 of the next FY", () => {
    expect(labelQuarter({ year: "2024Q3", period_end: "2024-12-31" })).toBe("Q3 FY25")
  })

  it("maps a March period_end to Q4 of the same FY", () => {
    expect(labelQuarter({ year: "2025Q4", period_end: "2025-03-31" })).toBe("Q4 FY25")
  })

  it("falls back to the raw year when period_end is null", () => {
    expect(labelQuarter({ year: "RAW-LABEL", period_end: null })).toBe("RAW-LABEL")
  })

  it("falls back when period_end is unparseable", () => {
    expect(labelQuarter({ year: "RAW", period_end: "garbage" })).toBe("RAW")
  })
})

// ────────────────────────────────────────────────────────────────────
// classifyBeatMiss
// ────────────────────────────────────────────────────────────────────
describe("classifyBeatMiss", () => {
  it("flags above-estimate when reported is > 2% over consensus", () => {
    expect(classifyBeatMiss(105, 100)).toBe("beat")
  })

  it("flags below-estimate when reported is > 2% under consensus", () => {
    expect(classifyBeatMiss(95, 100)).toBe("miss")
  })

  it("treats a ±2% band as in line", () => {
    expect(classifyBeatMiss(101, 100)).toBe("inline")
    expect(classifyBeatMiss(99, 100)).toBe("inline")
    expect(classifyBeatMiss(102, 100)).toBe("inline")
  })

  it("returns null when consensus is missing", () => {
    expect(classifyBeatMiss(100, null)).toBeNull()
    expect(classifyBeatMiss(100, undefined)).toBeNull()
  })

  it("returns null when reported is missing or NaN", () => {
    expect(classifyBeatMiss(null, 100)).toBeNull()
    expect(classifyBeatMiss(NaN, 100)).toBeNull()
  })

  it("returns null when consensus is zero or negative", () => {
    expect(classifyBeatMiss(100, 0)).toBeNull()
    expect(classifyBeatMiss(100, -5)).toBeNull()
  })
})

// ────────────────────────────────────────────────────────────────────
// buildChartRows
// ────────────────────────────────────────────────────────────────────
describe("buildChartRows", () => {
  it("returns an empty array for null / empty inputs", () => {
    expect(buildChartRows(null)).toEqual([])
    expect(buildChartRows([])).toEqual([])
  })

  it("reverses to oldest-first so the X-axis reads left-to-right", () => {
    const rows = [
      mockQuarter("Q2 FY26", "2025-09-30", { revenue: 200 }),
      mockQuarter("Q1 FY26", "2025-06-30", { revenue: 180 }),
    ]
    const out = buildChartRows(rows, 8)
    expect(out).toHaveLength(2)
    expect(out[0].period_end).toBe("2025-06-30") // oldest first after reverse
    expect(out[1].period_end).toBe("2025-09-30")
  })

  it("computes YoY revenue % against the row 4 quarters earlier", () => {
    // Index 0..4: most-recent..five-quarters-ago. Index 4 is the same
    // calendar quarter one year prior.
    const rows = [
      mockQuarter("Q3 FY26", "2025-12-31", { revenue: 120, net_income: 24 }), // latest
      mockQuarter("Q2 FY26", "2025-09-30", { revenue: 115 }),
      mockQuarter("Q1 FY26", "2025-06-30", { revenue: 110 }),
      mockQuarter("Q4 FY25", "2025-03-31", { revenue: 105 }),
      mockQuarter("Q3 FY25", "2024-12-31", { revenue: 100, net_income: 20 }), // YoY ref
    ]
    const out = buildChartRows(rows, 4)
    // After reverse, the latest is the LAST element of `out`.
    const latest = out[out.length - 1]
    expect(latest.period_end).toBe("2025-12-31")
    expect(latest.yoy_revenue_pct).toBeCloseTo(20, 6) // (120 - 100) / 100 * 100
    expect(latest.yoy_pat_pct).toBeCloseTo(20, 6) // (24 - 20) / 20 * 100
  })

  it("returns null YoY when the reference quarter is missing", () => {
    const rows = [mockQuarter("Q1 FY26", "2025-06-30", { revenue: 100 })]
    const out = buildChartRows(rows, 8)
    expect(out[0].yoy_revenue_pct).toBeNull()
  })

  it("propagates beat/miss when consensus_revenue is present", () => {
    const rows = [
      mockQuarter("Q1 FY26", "2025-06-30", {
        revenue: 110,
        consensus_revenue: 100,
      }),
    ]
    const out = buildChartRows(rows, 8)
    expect(out[0].beat_miss).toBe("beat")
    expect(out[0].consensus_revenue).toBe(100)
  })

  it("caps the output at visibleCount", () => {
    const rows = Array.from({ length: 12 }, (_, i) =>
      mockQuarter(`Qx-${i}`, `2025-0${(i % 9) + 1}-30`, { revenue: 100 + i }),
    )
    const out = buildChartRows(rows, 8)
    expect(out).toHaveLength(8)
  })
})

// ────────────────────────────────────────────────────────────────────
// EarningsWaterfallChart renderer
// ────────────────────────────────────────────────────────────────────
const eightQuarters: FinancialYear[] = [
  mockQuarter("Q3 FY26", "2025-12-31", { revenue: 1200, ebitda: 300, net_income: 200 }),
  mockQuarter("Q2 FY26", "2025-09-30", { revenue: 1180, ebitda: 290, net_income: 195 }),
  mockQuarter("Q1 FY26", "2025-06-30", { revenue: 1150, ebitda: 280, net_income: 190 }),
  mockQuarter("Q4 FY25", "2025-03-31", { revenue: 1100, ebitda: 270, net_income: 180 }),
  mockQuarter("Q3 FY25", "2024-12-31", { revenue: 1080, ebitda: 260, net_income: 175 }),
  mockQuarter("Q2 FY25", "2024-09-30", { revenue: 1050, ebitda: 250, net_income: 170 }),
  mockQuarter("Q1 FY25", "2024-06-30", { revenue: 1020, ebitda: 240, net_income: 165 }),
  mockQuarter("Q4 FY24", "2024-03-31", { revenue: 1000, ebitda: 230, net_income: 160 }),
]

describe("EarningsWaterfallChart renderer", () => {
  it("renders the main container and chip strip when data arrives", async () => {
    getFinancialsMock.mockResolvedValueOnce(makeResponse(eightQuarters))
    renderWithClient(<EarningsWaterfallChart ticker="TEST.NS" />)
    await waitFor(() =>
      expect(screen.getByTestId("earnings-waterfall-chart")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("earnings-waterfall-chip-strip")).toBeInTheDocument()
    expect(screen.getByTestId("earnings-waterfall-chip-all")).toBeInTheDocument()
  })

  it("renders the empty state when the income series is empty", async () => {
    getFinancialsMock.mockResolvedValueOnce(makeResponse([]))
    renderWithClient(<EarningsWaterfallChart ticker="TEST.NS" />)
    await waitFor(() =>
      expect(screen.getByTestId("earnings-waterfall-chart-empty")).toBeInTheDocument(),
    )
  })

  it("focuses a single quarter when its chip is clicked", async () => {
    getFinancialsMock.mockResolvedValueOnce(makeResponse(eightQuarters))
    renderWithClient(<EarningsWaterfallChart ticker="TEST.NS" />)
    const allChip = await screen.findByTestId("earnings-waterfall-chip-all")
    expect(allChip).toHaveAttribute("aria-selected", "true")
    // Latest quarter chip key = period_end of the most recent row.
    const latestChip = screen.getByTestId("earnings-waterfall-chip-2025-12-31")
    fireEvent.click(latestChip)
    expect(latestChip).toHaveAttribute("aria-selected", "true")
    expect(screen.getByTestId("earnings-waterfall-chip-all")).toHaveAttribute(
      "aria-selected",
      "false",
    )
  })

  it("does not render the beat/miss legend when no quarter has consensus", async () => {
    getFinancialsMock.mockResolvedValueOnce(makeResponse(eightQuarters))
    renderWithClient(<EarningsWaterfallChart ticker="TEST.NS" />)
    await screen.findByTestId("earnings-waterfall-chart")
    expect(screen.queryByTestId("earnings-waterfall-beatmiss-legend")).toBeNull()
  })

  it("renders the beat/miss legend when consensus is present on any quarter", async () => {
    const withConsensus = [...eightQuarters]
    const enriched = mockQuarter("Q3 FY26", "2025-12-31", {
      revenue: 1200,
      ebitda: 300,
      net_income: 200,
      consensus_revenue: 1100,
    })
    withConsensus[0] = enriched
    getFinancialsMock.mockResolvedValueOnce(makeResponse(withConsensus))
    renderWithClient(<EarningsWaterfallChart ticker="TEST.NS" />)
    await waitFor(() =>
      expect(
        screen.getByTestId("earnings-waterfall-beatmiss-legend"),
      ).toBeInTheDocument(),
    )
  })

  it("requests 12 quarters from the financials API to populate YoY for 8", async () => {
    getFinancialsMock.mockResolvedValueOnce(makeResponse(eightQuarters))
    renderWithClient(<EarningsWaterfallChart ticker="HDFCBANK.NS" />)
    await screen.findByTestId("earnings-waterfall-chart")
    expect(getFinancialsMock).toHaveBeenCalledWith("HDFCBANK.NS", "quarterly", 12)
  })
})

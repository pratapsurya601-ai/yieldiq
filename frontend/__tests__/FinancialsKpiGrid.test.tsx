/**
 * Tests for FinancialsKpiGrid.
 *
 * Verifies: the 6 cards render with mock financials, YoY trend chip
 * picks up direction, CAGR computation is correct, and a card with
 * no data shows the "Limited data" chip instead of a number.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import FinancialsKpiGrid, { deriveMetric } from "@/components/analysis/FinancialsKpiGrid"
import type { FinancialYear, FinancialsResponse } from "@/lib/api"

function mockYear(year: string, overrides: Partial<FinancialYear> = {}): FinancialYear {
  return {
    year,
    period_end: null,
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

// Backend returns newest-first. 5 years, all 6 metrics populated.
const HDFCBANK_LIKE: FinancialYear[] = [
  mockYear("FY24", {
    revenue: 240000, operating_income: 55000, net_income: 60000,
    eps_diluted: 78.5, operating_cash_flow: 70000, free_cash_flow: 65000,
  }),
  mockYear("FY23", {
    revenue: 215000, operating_income: 50000, net_income: 55000,
    eps_diluted: 71.0, operating_cash_flow: 64000, free_cash_flow: 59000,
  }),
  mockYear("FY22", {
    revenue: 180000, operating_income: 42000, net_income: 47000,
    eps_diluted: 60.0, operating_cash_flow: 55000, free_cash_flow: 51000,
  }),
  mockYear("FY21", {
    revenue: 150000, operating_income: 36000, net_income: 40000,
    eps_diluted: 52.0, operating_cash_flow: 46000, free_cash_flow: 42000,
  }),
  mockYear("FY20", {
    revenue: 125000, operating_income: 30000, net_income: 33000,
    eps_diluted: 43.0, operating_cash_flow: 38000, free_cash_flow: 35000,
  }),
]

const MOCK_RESPONSE: FinancialsResponse = {
  ticker: "HDFCBANK.NS",
  currency: "INR",
  currency_unit: "Cr",
  period: "annual",
  years_available: 5,
  has_quarterly: true,
  data_source: "db",
  tier: "free",
  tier_limited: false,
  income: HDFCBANK_LIKE,
  balance_sheet: HDFCBANK_LIKE,
  cash_flow: HDFCBANK_LIKE,
  summary: { revenue_cagr_3y: null, avg_net_margin: null, avg_fcf_margin: null, latest_roe: null },
}

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe("FinancialsKpiGrid", () => {
  it("renders all 6 KPI cards", () => {
    renderWithClient(
      <FinancialsKpiGrid ticker="HDFCBANK.NS" annual={MOCK_RESPONSE} currency="INR" />,
    )
    for (const k of [
      "revenue", "operating_income", "net_income",
      "eps_diluted", "operating_cash_flow", "free_cash_flow",
    ]) {
      expect(screen.getByTestId(`kpi-card-${k}`)).toBeInTheDocument()
    }
  })

  it("formats the Revenue value with Indian compaction (Lakh Cr or Cr)", () => {
    renderWithClient(
      <FinancialsKpiGrid ticker="HDFCBANK.NS" annual={MOCK_RESPONSE} currency="INR" />,
    )
    const val = screen.getByTestId("kpi-value-revenue").textContent ?? ""
    // 240,000 Cr → "2.40 Lakh Cr"
    expect(val).toMatch(/2\.40 Lakh Cr/)
  })

  it("formats EPS as per-share rupee value, not Cr-compacted", () => {
    renderWithClient(
      <FinancialsKpiGrid ticker="HDFCBANK.NS" annual={MOCK_RESPONSE} currency="INR" />,
    )
    const val = screen.getByTestId("kpi-value-eps_diluted").textContent ?? ""
    expect(val).toMatch(/^₹78\.50$/)
  })

  it("renders a positive YoY trend chip for growing revenue", () => {
    renderWithClient(
      <FinancialsKpiGrid ticker="HDFCBANK.NS" annual={MOCK_RESPONSE} currency="INR" />,
    )
    const chip = screen.getByTestId("kpi-yoy-revenue")
    expect(chip.textContent).toMatch(/\+/)
    expect(chip.textContent).toMatch(/↗/)
  })

  it("shows period toggle buttons (annual / quarterly / ttm)", () => {
    renderWithClient(
      <FinancialsKpiGrid ticker="HDFCBANK.NS" annual={MOCK_RESPONSE} currency="INR" />,
    )
    expect(screen.getByTestId("kpi-period-annual")).toBeInTheDocument()
    expect(screen.getByTestId("kpi-period-quarterly")).toBeInTheDocument()
    expect(screen.getByTestId("kpi-period-ttm")).toBeInTheDocument()
  })

  it("shows Limited data chip when a metric has no points", () => {
    const empty: FinancialsResponse = {
      ...MOCK_RESPONSE,
      income: [mockYear("FY24"), mockYear("FY23")],
      balance_sheet: [mockYear("FY24"), mockYear("FY23")],
      cash_flow: [mockYear("FY24"), mockYear("FY23")],
    }
    renderWithClient(
      <FinancialsKpiGrid ticker="HDFCBANK.NS" annual={empty} currency="INR" />,
    )
    const card = screen.getByTestId("kpi-card-revenue")
    expect(card.textContent).toMatch(/Limited data/)
  })
})

describe("deriveMetric (CAGR + YoY math)", () => {
  // Oldest→newest (chronological) — what deriveMetric expects after
  // the chronological() helper inside the component flips the array.
  const chrono = [...HDFCBANK_LIKE].reverse()

  it("YoY for revenue: FY24 240000 vs FY23 215000 ≈ +11.6%", () => {
    const d = deriveMetric(chrono, "revenue")
    expect(d.yoy).not.toBeNull()
    expect(d.yoy!).toBeGreaterThan(11)
    expect(d.yoy!).toBeLessThan(12)
  })

  it("3Y CAGR for revenue: (240000/150000)^(1/3) - 1 ≈ 16.96%", () => {
    const d = deriveMetric(chrono, "revenue")
    expect(d.cagr_3y).not.toBeNull()
    expect(d.cagr_3y!).toBeGreaterThan(16)
    expect(d.cagr_3y!).toBeLessThan(18)
  })

  it("10Y CAGR is null when we only have 5 years of data", () => {
    const d = deriveMetric(chrono, "revenue")
    expect(d.cagr_10y).toBeNull()
  })

  it("returns nulls everywhere when the series is empty", () => {
    const d = deriveMetric([], "revenue")
    expect(d.latest).toBeNull()
    expect(d.yoy).toBeNull()
    expect(d.cagr_3y).toBeNull()
    expect(d.spark).toEqual([])
  })
})

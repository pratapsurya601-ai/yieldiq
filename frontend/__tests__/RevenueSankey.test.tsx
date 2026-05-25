/**
 * Tests for RevenueSankey + buildSankey.
 *
 * Covers: graph derivation math, renderer smoke (nodes/links/tabs),
 * empty-data states, bank relabelling, missing-field aggregation.
 */
import * as React from "react"
import { describe, it, expect, beforeAll } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import RevenueSankey, { buildSankey } from "@/components/analysis/RevenueSankey"
import type { FinancialYear, FinancialsResponse } from "@/lib/api"

// jsdom doesn't ship ResizeObserver — d3-sankey doesn't need it but
// the component subscribes to one for the container width.
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

const HDFCBANK_LIKE = mockYear("FY24", {
  revenue: 240000,
  gross_profit: 180000,
  operating_income: 100000,
  net_income: 60000,
  interest_expense: 15000,
})

function makeResponse(rows: FinancialYear[]): FinancialsResponse {
  return {
    ticker: "TEST.NS",
    currency: "INR",
    currency_unit: "Cr",
    period: "annual",
    years_available: rows.length,
    has_quarterly: false,
    data_source: "db",
    tier: "free",
    tier_limited: false,
    income: rows,
    balance_sheet: rows,
    cash_flow: rows,
    summary: { revenue_cagr_3y: null, avg_net_margin: null, avg_fcf_margin: null, latest_roe: null },
  }
}

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe("buildSankey", () => {
  it("returns null when revenue is missing", () => {
    expect(buildSankey(mockYear("FY24"), { bank: false })).toBeNull()
  })

  it("returns null when revenue is zero or negative", () => {
    expect(buildSankey(mockYear("FY24", { revenue: 0 }), { bank: false })).toBeNull()
    expect(buildSankey(mockYear("FY24", { revenue: -100 }), { bank: false })).toBeNull()
  })

  it("derives cost_of_revenue as revenue − gross_profit", () => {
    const g = buildSankey(HDFCBANK_LIKE, { bank: false })!
    const cogs = g.links.find(l => l.target === "cogs")
    expect(cogs).toBeDefined()
    expect(cogs!.value).toBe(60000) // 240000 - 180000
  })

  it("derives operating_expenses as gross_profit − operating_income", () => {
    const g = buildSankey(HDFCBANK_LIKE, { bank: false })!
    const opex = g.links.find(l => l.target === "opex")
    expect(opex).toBeDefined()
    expect(opex!.value).toBe(80000) // 180000 - 100000
  })

  it("derives tax_and_other as op_income − interest − net_income", () => {
    const g = buildSankey(HDFCBANK_LIKE, { bank: false })!
    const tax = g.links.find(l => l.target === "tax_other")
    expect(tax).toBeDefined()
    // 100000 - 15000 - 60000 = 25000
    expect(tax!.value).toBe(25000)
  })

  it("includes a net_income outflow with profit role", () => {
    const g = buildSankey(HDFCBANK_LIKE, { bank: false })!
    const ni = g.links.find(l => l.target === "net_income")
    expect(ni).toBeDefined()
    expect(ni!.role).toBe("profit")
    expect(ni!.value).toBe(60000)
  })

  it("skips legs whose derived value is zero or negative", () => {
    // Revenue == gross_profit → cogs = 0, skipped.
    const row = mockYear("FY24", {
      revenue: 100, gross_profit: 100, operating_income: 80, net_income: 60,
    })
    const g = buildSankey(row, { bank: false })!
    expect(g.links.find(l => l.target === "cogs")).toBeUndefined()
    expect(g.links.find(l => l.target === "opex")).toBeDefined() // 100-80=20
  })

  it("relabels for banks (Total Income / Interest Expense / Other Op Ex)", () => {
    const g = buildSankey(HDFCBANK_LIKE, { bank: true })!
    const revenue = g.nodes.find(n => n.id === "revenue")!
    const cogs = g.nodes.find(n => n.id === "cogs")
    const opex = g.nodes.find(n => n.id === "opex")
    expect(revenue.label).toBe("Total Income")
    expect(cogs?.label).toBe("Interest Expense")
    expect(opex?.label).toBe("Other Operating Expenses")
  })

  it("aggregates missing breakdown into Tax & Other (no interest field)", () => {
    const row = mockYear("FY24", {
      revenue: 100, gross_profit: 60, operating_income: 40, net_income: 25,
      // interest_expense omitted
    })
    const g = buildSankey(row, { bank: false })!
    const tax = g.links.find(l => l.target === "tax_other")
    expect(tax!.value).toBe(15) // 40 - 0 - 25
    expect(g.links.find(l => l.target === "interest")).toBeUndefined()
  })

  it("returns null when no outflow can be derived", () => {
    // Revenue only — no gross / op / net → nothing to fan out to.
    const row = mockYear("FY24", { revenue: 100 })
    expect(buildSankey(row, { bank: false })).toBeNull()
  })
})

describe("RevenueSankey renderer", () => {
  it("renders the SVG + the period toggle", () => {
    renderWithClient(
      <RevenueSankey ticker="HDFCBANK.NS" annual={makeResponse([HDFCBANK_LIKE])} currency="INR" />,
    )
    expect(screen.getByTestId("revenue-sankey-svg")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-period-quarter")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-period-ttm")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-period-fy")).toBeInTheDocument()
  })

  it("renders one node per derived bucket", () => {
    renderWithClient(
      <RevenueSankey ticker="HDFCBANK.NS" annual={makeResponse([HDFCBANK_LIKE])} currency="INR" />,
    )
    expect(screen.getByTestId("sankey-node-revenue")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-node-cogs")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-node-opex")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-node-interest")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-node-tax_other")).toBeInTheDocument()
    expect(screen.getByTestId("sankey-node-net_income")).toBeInTheDocument()
  })

  it("renders the empty-state when no revenue is available", () => {
    renderWithClient(
      <RevenueSankey ticker="UNKNOWN" annual={makeResponse([mockYear("FY24")])} currency="INR" />,
    )
    expect(screen.getByTestId("revenue-sankey-empty")).toBeInTheDocument()
  })

  it("flips the period toggle (smoke)", () => {
    renderWithClient(
      <RevenueSankey ticker="HDFCBANK.NS" annual={makeResponse([HDFCBANK_LIKE])} currency="INR" />,
    )
    const fyTab = screen.getByTestId("sankey-period-fy")
    fireEvent.click(fyTab)
    expect(fyTab).toHaveAttribute("aria-selected", "true")
  })
})

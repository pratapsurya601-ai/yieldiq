/**
 * Tests for EarningsWaterfall + buildWaterfall.
 *
 * Covers: step derivation, subtotal placement, sign handling,
 * bank labelling, missing-field fallthrough, renderer smoke.
 */
import * as React from "react"
import { describe, it, expect, beforeAll } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import EarningsWaterfall, { buildWaterfall } from "@/components/analysis/EarningsWaterfall"
import type { FinancialYear, FinancialsResponse } from "@/lib/api"

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

const FULL = mockYear("FY24", {
  revenue: 318000,
  gross_profit: 217000,
  operating_income: 149000,
  net_income: 125000,
  interest_expense: 10000,
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

describe("buildWaterfall", () => {
  it("returns null without revenue", () => {
    expect(buildWaterfall(mockYear("FY24"), { bank: false })).toBeNull()
  })

  it("starts with Revenue at the reported value", () => {
    const s = buildWaterfall(FULL, { bank: false })!
    expect(s[0].key).toBe("revenue")
    expect(s[0].cumulative).toBe(318000)
    expect(s[0].kind).toBe("start")
  })

  it("walks down through cost_of_revenue → gross_profit", () => {
    const s = buildWaterfall(FULL, { bank: false })!
    const cor = s.find(x => x.key === "cost_of_revenue")!
    const gp = s.find(x => x.key === "gross_profit")!
    expect(cor.delta).toBe(-(318000 - 217000)) // -101000
    expect(gp.cumulative).toBe(217000)
    expect(gp.kind).toBe("subtotal")
  })

  it("walks through operating_expenses → operating_income subtotal", () => {
    const s = buildWaterfall(FULL, { bank: false })!
    const opex = s.find(x => x.key === "operating_expenses")!
    const oi = s.find(x => x.key === "operating_income")!
    expect(opex.delta).toBe(-(217000 - 149000)) // -68000
    expect(oi.cumulative).toBe(149000)
  })

  it("emits an interest decrement when interest_expense is present (non-bank)", () => {
    const s = buildWaterfall(FULL, { bank: false })!
    const i = s.find(x => x.key === "interest")
    expect(i).toBeDefined()
    expect(i!.delta).toBe(-10000)
  })

  it("ends on net_income with the reported value (forced reconciliation)", () => {
    const s = buildWaterfall(FULL, { bank: false })!
    const last = s[s.length - 1]
    expect(last.key).toBe("net_income")
    expect(last.cumulative).toBe(125000)
    expect(last.kind).toBe("end")
  })

  it("relabels for banks (Total Income / Net Interest Income / Other Op Ex)", () => {
    const s = buildWaterfall(FULL, { bank: true })!
    expect(s[0].label).toBe("Total Income")
    expect(s.some(x => x.label === "−Interest Expense")).toBe(true)
    expect(s.some(x => x.key === "gross_profit" && x.label === "Net Interest Income")).toBe(true)
    expect(s.some(x => x.label === "−Other Operating Expenses")).toBe(true)
    // Bank path doesn't double-count interest — no standalone "−Interest" step.
    expect(s.find(x => x.key === "interest")).toBeUndefined()
  })

  it("omits the tax step when there's no residual", () => {
    // op_income == interest + net_income → tax_other == 0.
    const row = mockYear("FY24", {
      revenue: 100, gross_profit: 80, operating_income: 60, net_income: 50,
      interest_expense: 10,
    })
    const s = buildWaterfall(row, { bank: false })!
    expect(s.find(x => x.key === "tax_other")).toBeUndefined()
    expect(s[s.length - 1].cumulative).toBe(50)
  })

  it("returns null when too few steps can be derived", () => {
    // Revenue only — no gross/op/net.
    const row = mockYear("FY24", { revenue: 100 })
    expect(buildWaterfall(row, { bank: false })).toBeNull()
  })
})

describe("EarningsWaterfall renderer", () => {
  it("renders chart container + period toggle", () => {
    renderWithClient(
      <EarningsWaterfall ticker="HDFCBANK.NS" annual={makeResponse([FULL])} currency="INR" />,
    )
    expect(screen.getByTestId("earnings-waterfall")).toBeInTheDocument()
    expect(screen.getByTestId("waterfall-period-quarter")).toBeInTheDocument()
    expect(screen.getByTestId("waterfall-period-ttm")).toBeInTheDocument()
    expect(screen.getByTestId("waterfall-period-fy")).toBeInTheDocument()
  })

  it("renders the empty state when revenue is missing", () => {
    renderWithClient(
      <EarningsWaterfall ticker="UNKNOWN" annual={makeResponse([mockYear("FY24")])} currency="INR" />,
    )
    expect(screen.getByTestId("earnings-waterfall-empty")).toBeInTheDocument()
  })

  it("flips the period toggle (smoke)", () => {
    renderWithClient(
      <EarningsWaterfall ticker="HDFCBANK.NS" annual={makeResponse([FULL])} currency="INR" />,
    )
    const fy = screen.getByTestId("waterfall-period-fy")
    fireEvent.click(fy)
    expect(fy).toHaveAttribute("aria-selected", "true")
  })
})

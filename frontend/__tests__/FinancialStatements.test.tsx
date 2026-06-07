/**
 * FinancialStatements panel — row-schema pins.
 *
 * Two invariants, both added in feat/financials-empty-row-hide-bank-rows
 * (cosmetic half of the financials-coverage fix; sibling backend PR
 * surfaces the bank-format columns the new schema reads from):
 *
 *   1. **All-null row hiding.** A row whose `value(y)` returns null
 *      for EVERY rendered period must not appear in the DOM. This is
 *      the "em-dash wall" guard described in
 *      `redesign/followups/financial-statements-bugs-phase0.md` Bug 3.
 *
 *   2. **Bank-aware row schema.** For tickers in `isPureBank`, the
 *      Income tab swaps to Schedule III Div III row labels (Interest
 *      Earned / Interest Expended / NII / Non-Interest Income / Total
 *      Income / Operating Expenses) INSTEAD of the generic
 *      Revenue / Gross Profit / EBITDA / Operating Income schema.
 *      Even when the backend hasn't populated the new fields yet, the
 *      labels must be correct — the rows just show em-dashes until
 *      the data lands. After the all-null filter passes, only the
 *      rows backed by populated fields stay in the DOM.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type React from "react"

import type { FinancialYear, FinancialsResponse } from "@/lib/api"

// jsdom doesn't ship IntersectionObserver; the panel uses it to defer
// the query until the card scrolls into view. Stub it to fire
// immediately so the component skips the deferred-fetch path.
class ImmediateIO {
  constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
    // Fire on the next microtask so React has finished mounting.
    queueMicrotask(() => cb([{ isIntersecting: true }]))
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}
vi.stubGlobal("IntersectionObserver", ImmediateIO)

const getFinancialsMock = vi.fn()
vi.mock("@/lib/api", async () => {
  // Re-export the real types but stub the network call.
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return {
    ...actual,
    getFinancials: (...args: unknown[]) => getFinancialsMock(...args),
  }
})

import FinancialStatements from "@/components/analysis/FinancialStatements"

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

function buildResponse(income: FinancialYear[], ticker = "TCS"): FinancialsResponse {
  return {
    ticker,
    currency: "INR",
    currency_unit: "Cr",
    period: "annual",
    years_available: income.length,
    has_quarterly: true,
    data_source: "db",
    tier: "free",
    tier_limited: false,
    income,
    balance_sheet: income,
    cash_flow: income,
    summary: {
      revenue_cagr_3y: null,
      avg_net_margin: null,
      avg_fcf_margin: null,
      latest_roe: null,
    },
  }
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  getFinancialsMock.mockReset()
})

describe("FinancialStatements — all-null row hiding", () => {
  it("hides the Gross Profit row when every period returns null for gross_profit", async () => {
    // Revenue / net_income / eps populated so OTHER rows still render
    // — this isolates the gross_profit-specific filter.
    const years = [
      mockYear("FY24", { revenue: 240000, net_income: 60000, eps_diluted: 78.5 }),
      mockYear("FY23", { revenue: 215000, net_income: 55000, eps_diluted: 71.0 }),
      mockYear("FY22", { revenue: 180000, net_income: 47000, eps_diluted: 60.0 }),
    ]
    getFinancialsMock.mockResolvedValue(buildResponse(years, "TCS"))

    renderWithClient(<FinancialStatements ticker="TCS" currency="INR" />)

    // Revenue row must appear (non-null in every period).
    await waitFor(() => {
      expect(screen.getByText("Revenue")).toBeInTheDocument()
    })
    // Gross Profit row must NOT appear — all-null filter dropped it.
    expect(screen.queryByText("Gross Profit")).not.toBeInTheDocument()
    // EBITDA and Operating Income are also all-null in this fixture —
    // same filter, same outcome. Pinning at least one to keep the
    // assertion explicit about the em-dash wall it prevents.
    expect(screen.queryByText("EBITDA")).not.toBeInTheDocument()
  })
})

describe("FinancialStatements — bank-aware row schema", () => {
  it("renders Interest Earned / NII row labels for a bank ticker and hides Gross Profit", async () => {
    // Backend has not yet shipped the new bank fields, so they're
    // undefined here. Interest Earned is populated to prove the row
    // label switches even with a partial response; NII / Total Income
    // /etc are undefined and get hidden by the all-null filter, which
    // is the expected interim state until the backend lands.
    const years = [
      mockYear("FY24", {
        net_income: 60000,
        eps_diluted: 78.5,
        interest_earned: 195000,
      } as Partial<FinancialYear>),
      mockYear("FY23", {
        net_income: 55000,
        eps_diluted: 71.0,
        interest_earned: 168000,
      } as Partial<FinancialYear>),
    ]
    getFinancialsMock.mockResolvedValue(buildResponse(years, "HDFCBANK"))

    renderWithClient(<FinancialStatements ticker="HDFCBANK" currency="INR" />)

    // Bank schema label IS in the DOM.
    await waitFor(() => {
      expect(screen.getByText("Interest Earned")).toBeInTheDocument()
    })
    // Non-bank schema labels MUST NOT be in the DOM for banks.
    expect(screen.queryByText("Revenue")).not.toBeInTheDocument()
    expect(screen.queryByText("Gross Profit")).not.toBeInTheDocument()
    expect(screen.queryByText("EBITDA")).not.toBeInTheDocument()
    expect(screen.queryByText("Operating Income")).not.toBeInTheDocument()
  })
})

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getFinancials, type FinancialYear, type FinancialsResponse } from "@/lib/api"
import { cn } from "@/lib/utils"

type Period = "annual" | "quarterly"
type Tab = "income" | "balance" | "cashflow"

interface Props {
  ticker: string
  currency?: string
}

/* ------------------------------------------------------------------ */
/* Cell formatters                                                     */
/* ------------------------------------------------------------------ */
function fmtCurrency(v: number | null, currency: string): string {
  if (v === null || v === undefined) return "—"
  const abs = Math.abs(v)
  const sign = v < 0 ? "-" : ""
  // Values arrive in Cr (INR) or M (USD).
  if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(2)}K`
  if (abs >= 1) return `${sign}${abs.toLocaleString(currency === "INR" ? "en-IN" : "en-US", { maximumFractionDigits: 0 })}`
  return `${sign}${abs.toFixed(2)}`
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}%`
}

function fmtPerShare(v: number | null, currency: string): string {
  if (v === null || v === undefined) return "—"
  const sym = currency === "INR" ? "₹" : "$"
  return `${sym}${v.toFixed(2)}`
}

function fmtCapex(v: number | null, currency: string): string {
  if (v === null || v === undefined) return "—"
  // Capex is typically reported negative in cashflow stmt; show parens.
  const abs = Math.abs(v)
  return `(${fmtCurrency(abs, currency)})`
}

function fmtRatio(v: number | null): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}x`
}

function GrowthArrow({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-caption">—</span>
  }
  if (value > 0) {
    return (
      <span className="text-green-600 font-medium">
        ▲ {value.toFixed(1)}%
      </span>
    )
  }
  if (value < 0) {
    return (
      <span className="text-red-600 font-medium">
        ▼ {value.toFixed(1)}%
      </span>
    )
  }
  return <span className="text-caption">0.0%</span>
}

/* ------------------------------------------------------------------ */
/* Row builders per tab                                                */
/* ------------------------------------------------------------------ */
type RowDef = {
  label: string
  render: (y: FinancialYear) => React.ReactNode
  emphasis?: boolean
}

function incomeRows(currency: string): RowDef[] {
  return [
    { label: "Revenue", emphasis: true, render: y => fmtCurrency(y.revenue, currency) },
    { label: "  YoY Growth", render: y => <GrowthArrow value={y.revenue_growth_pct} /> },
    { label: "Gross Profit", render: y => fmtCurrency(y.gross_profit, currency) },
    { label: "  Gross Margin", render: y => fmtPct(y.gross_margin_pct) },
    { label: "EBITDA", render: y => fmtCurrency(y.ebitda, currency) },
    { label: "Operating Income", render: y => fmtCurrency(y.operating_income, currency) },
    { label: "  Operating Margin", render: y => fmtPct(y.operating_margin_pct) },
    { label: "Net Income", emphasis: true, render: y => fmtCurrency(y.net_income, currency) },
    { label: "  YoY Growth", render: y => <GrowthArrow value={y.net_income_growth_pct} /> },
    { label: "  Net Margin", render: y => fmtPct(y.net_margin_pct) },
    { label: "EPS (Diluted)", render: y => fmtPerShare(y.eps_diluted, currency) },
  ]
}

function balanceRows(currency: string): RowDef[] {
  return [
    { label: "Total Assets", render: y => fmtCurrency(y.total_assets, currency) },
    { label: "Total Equity", emphasis: true, render: y => fmtCurrency(y.total_equity, currency) },
    { label: "Total Debt", render: y => fmtCurrency(y.total_debt, currency) },
    { label: "Cash & Equivalents", render: y => fmtCurrency(y.cash, currency) },
    { label: "Net Debt", render: y => fmtCurrency(y.net_debt, currency) },
    { label: "Debt / Equity", render: y => fmtRatio(y.debt_to_equity) },
    { label: "Book Value / Share", render: y => fmtPerShare(y.book_value_per_share, currency) },
  ]
}

function cashflowRows(currency: string): RowDef[] {
  return [
    { label: "Operating Cash Flow", render: y => fmtCurrency(y.operating_cash_flow, currency) },
    { label: "Capital Expenditure",
      render: y => <span className="text-red-600">{fmtCapex(y.capex, currency)}</span> },
    { label: "Free Cash Flow", emphasis: true, render: y => fmtCurrency(y.free_cash_flow, currency) },
    { label: "  FCF Margin", render: y => fmtPct(y.fcf_margin_pct) },
  ]
}

/* ------------------------------------------------------------------ */
/* Skeleton                                                            */
/* ------------------------------------------------------------------ */
function Skeleton() {
  return (
    <div className="bg-surface rounded-2xl border border-border p-5 space-y-3">
      <div className="h-5 w-48 bg-border rounded animate-pulse" />
      <div className="flex gap-2">
        <div className="h-6 w-20 bg-bg rounded-full animate-pulse" />
        <div className="h-6 w-24 bg-bg rounded-full animate-pulse" />
      </div>
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-6 bg-bg rounded animate-pulse" />
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */
export default function FinancialStatements({ ticker, currency = "INR" }: Props) {
  const [period, setPeriod] = useState<Period>("annual")
  const [tab, setTab] = useState<Tab>("income")
  const [visible, setVisible] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (visible) return
    const el = containerRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true)
          obs.disconnect()
        }
      },
      { rootMargin: "300px" }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [visible])

  const { data, isLoading, isError, refetch } = useQuery<FinancialsResponse>({
    queryKey: ["financials", ticker, period],
    queryFn: () => getFinancials(ticker, period, 5),
    enabled: visible && !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const years = data?.income ?? []
  const rows: RowDef[] = useMemo(() => {
    if (tab === "income") return incomeRows(currency)
    if (tab === "balance") return balanceRows(currency)
    return cashflowRows(currency)
  }, [tab, currency])

  /* ---------- Render states ---------- */
  if (!visible || isLoading) {
    return (
      <div ref={containerRef}>
        <Skeleton />
      </div>
    )
  }

  if (isError) {
    return (
      <div ref={containerRef} className="bg-surface rounded-2xl border border-border p-5">
        <h2 className="text-sm font-semibold text-ink mb-2">Financial Statements</h2>
        <p className="text-sm text-caption text-center py-6">Financial data unavailable</p>
        <div className="text-center">
          <button
            onClick={() => refetch()}
            className="text-xs font-medium text-brand hover:underline"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const emptyQuarterly = period === "quarterly" && years.length === 0
  const emptyAnnual = period === "annual" && years.length === 0

  const unitLabel = data?.currency_unit ?? (currency === "INR" ? "Cr" : "M")
  const currencySym = currency === "INR" ? "₹" : "$"

  return (
    <div ref={containerRef} className="bg-surface rounded-2xl border border-border p-5 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">Financial Statements</h2>
        <div className="flex gap-1.5">
          {(["annual", "quarterly"] as const).map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "text-xs px-2.5 py-1 rounded-lg font-medium transition-colors",
                period === p
                  ? "bg-brand text-white"
                  : "bg-bg text-caption hover:bg-border"
              )}
            >
              {p === "annual" ? "Annual" : "Quarterly"}
            </button>
          ))}
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-4 border-b border-border -mx-1 px-1">
        {([
          ["income", "Income"],
          ["balance", "Balance Sheet"],
          ["cashflow", "Cash Flow"],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "py-2 text-xs font-medium whitespace-nowrap transition-colors border-b-2",
              tab === key
                ? "border-brand text-brand"
                : "border-transparent text-caption hover:text-body"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Summary pills (non-null only) */}
      {data?.summary && (
        <div className="flex flex-wrap gap-1.5">
          {data.summary.revenue_cagr_3y !== null && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg text-body">
              Rev CAGR 3Y: {data.summary.revenue_cagr_3y >= 0 ? "+" : ""}
              {data.summary.revenue_cagr_3y}%
            </span>
          )}
          {data.summary.avg_net_margin !== null && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg text-body">
              Net Margin: {data.summary.avg_net_margin}%
            </span>
          )}
          {data.summary.avg_fcf_margin !== null && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg text-body">
              FCF Margin: {data.summary.avg_fcf_margin}%
            </span>
          )}
          {data.summary.latest_roe !== null && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg text-body">
              ROE: {data.summary.latest_roe}%
            </span>
          )}
        </div>
      )}

      {/* Empty states */}
      {emptyQuarterly && (
        <p className="text-sm text-caption text-center py-8">
          Quarterly financial data is not available for this stock yet.
        </p>
      )}
      {emptyAnnual && (
        <p className="text-sm text-caption text-center py-8">
          No financial data available for this stock.
        </p>
      )}

      {/* Table */}
      {years.length > 0 && (
        <>
          <div className="text-[11px] text-caption">
            Values in {currencySym} {unitLabel}
            {data?.data_source === "yfinance_fallback" && " · source: yfinance"}
          </div>

          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="sticky left-0 bg-surface z-10 text-left font-medium text-caption py-2 pl-1 pr-3 min-w-[140px]">
                    Metric
                  </th>
                  {years.map(y => (
                    <th
                      key={y.year + (y.period_end ?? "")}
                      className="text-right font-medium text-caption py-2 px-2 min-w-[80px]"
                    >
                      {y.year}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => {
                  const isSubRow = row.label.startsWith("  ")
                  return (
                    <tr key={i} className="border-b border-border last:border-0">
                      <td
                        className={cn(
                          "sticky left-0 bg-surface z-10 py-2 pl-1 pr-3",
                          isSubRow ? "text-caption pl-4" : "text-ink",
                          row.emphasis && "font-semibold"
                        )}
                      >
                        {row.label.trim()}
                      </td>
                      {years.map(y => (
                        <td
                          key={y.year + (y.period_end ?? "")}
                          className={cn(
                            "text-right py-2 px-2 font-mono tabular-nums",
                            row.emphasis && "font-semibold"
                          )}
                        >
                          {row.render(y)}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Footnote */}
      {data?.data_source && data.data_source !== "none" && (
        <p className="text-[10px] text-caption">
          Data source: {data.data_source === "db" ? "NSE/BSE filings" : "yfinance"}
          {data.years_available > 0 && ` · ${data.years_available} period${data.years_available === 1 ? "" : "s"}`}
        </p>
      )}

      {/* Tier CTA */}
      {data?.tier_limited && period === "annual" && years.length > 0 && (
        <div className="border border-blue-100 bg-blue-50 rounded-xl p-3 flex items-center justify-between gap-3">
          <p className="text-xs text-blue-700">🔒 Unlock 5-year history with Starter</p>
          <a
            href="/pricing"
            className="text-xs font-semibold text-blue-600 whitespace-nowrap hover:underline"
          >
            Upgrade →
          </a>
        </div>
      )}
    </div>
  )
}

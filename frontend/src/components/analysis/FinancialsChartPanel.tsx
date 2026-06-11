"use client"

// FinancialsChartPanel — 10-year Revenue / Net Profit / Free Cash Flow
// grouped bar chart for the analysis Summary tab.
//
// Closes the Visual Richness gap identified in the 2026-05-27 competitor
// walk: every peer surface (AlphaSpread, Tijori, Screener) leads with a
// 10-year financials bar chart; YieldIQ surfaced statement numbers only
// as a buried table on the Financials tab. This panel mirrors the
// existing /api/v1/analysis/{ticker}/financials data pull used by
// FinancialStatements + FinancialsKpiGrid (no new backend, no new
// endpoint, no CACHE_VERSION bump).
//
// Rendering rules:
//   * Annual tab is default; up to 10 trailing years (less when the
//     backend has fewer filings).
//   * 3 grouped bars per year: Revenue (blue), Net Profit (green),
//     Free Cash Flow (amber).
//   * Y-axis values are reported in INR Cr for India-listed names and
//     USD M for foreign filers — matches FinancialStatements unit logic.
//   * Quarterly tab renders an empty-state notice for now; quarterly
//     statement plumbing lives in a separate task.
//   * Empty payload renders a neutral notice (no banned vocabulary).

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import QuarterlyResultsTable from "@/components/analysis/QuarterlyResultsTable"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts"
import { getFinancials, type FinancialYear, type FinancialsResponse } from "@/lib/api"
import { formatCompactCount } from "@/lib/formatNumbers"
import {
  getDisplayRevenue,
  getDisplayRevenueLabel,
  getFCFNotApplicableNote,
  isFinancialCohort,
} from "@/lib/sectorFinancials"

type Period = "annual" | "quarterly"

interface Props {
  ticker: string
  currency?: string | null
  /** Sector hint — when present, drives bank-cohort revenue
   * fall-back (interest income) and hides the FCF series. */
  sector?: string | null
}

interface ChartRow {
  year: string
  revenue: number | null
  net_profit: number | null
  fcf: number | null
}

const FOREIGN_RE = /^(USD|EUR|GBP|JPY|CNY|SGD|HKD|AUD|CAD|CHF)$/i
function isForeignCurrency(c?: string | null, ticker?: string): boolean {
  if (ticker && (ticker.endsWith(".NS") || ticker.endsWith(".BO"))) return false
  return !!c && FOREIGN_RE.test(c.trim())
}

// Values arrive already normalised to Cr (INR) or M (USD) from the
// financials endpoint, so we only collapse magnitudes (e.g. 1234 Cr →
// "1,234 Cr", 12345 Cr → "12.3K Cr"). Keep the unit suffix on the axis
// label, not on every tick, to avoid axis-width creep.
function formatTick(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : ""
  if (abs >= 100000) return `${sign}${(abs / 1000).toFixed(0)}K`
  if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(1)}K`
  return `${sign}${Math.round(abs).toLocaleString("en-IN")}`
}

function formatTooltip(value: number | null, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—"
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : ""
  // Canonical Indian-grouping count formatter (lib/formatNumbers) for
  // the whole-number tier; sub-1000 values keep one decimal of detail.
  if (abs >= 1000) return `${sign}${formatCompactCount(abs)} ${unit}`
  return `${sign}${abs.toLocaleString("en-IN", { maximumFractionDigits: 1 })} ${unit}`
}

const COLOR_REVENUE = "#3b82f6"
const COLOR_PROFIT = "#10b981"
const COLOR_FCF = "#f59e0b"

function Skeleton() {
  return (
    <div className="bg-bg rounded-2xl border border-border p-4 space-y-3">
      <div className="h-5 w-56 bg-border rounded animate-pulse" />
      <div className="h-3 w-72 bg-border/70 rounded animate-pulse" />
      <div className="h-[280px] bg-surface rounded-xl animate-pulse" />
    </div>
  )
}

function pickRows(years: FinancialYear[]): ChartRow[] {
  // The endpoint returns rows latest-first or latest-last depending on
  // tier; normalise to ascending year so the chart reads left → right.
  const sorted = [...years].sort((a, b) => a.year.localeCompare(b.year))
  // Cap at the trailing 10 years even when the backend returns more.
  const trimmed = sorted.slice(Math.max(0, sorted.length - 10))
  return trimmed.map((y) => ({
    year: y.year,
    revenue: y.revenue,
    net_profit: y.net_income,
    fcf: y.free_cash_flow,
  }))
}

export default function FinancialsChartPanel({ ticker, currency, sector }: Props) {
  // `userPeriod` is null until the user clicks a tab themselves. Once
  // set we honour that choice forever. Before that, the active tab is
  // derived from has_quarterly (auto-promote Quarterly when the
  // backend confirms coverage — Tickertape density trick #3 from the
  // 2026-05-27 audit). This avoids a setState-in-effect cascade.
  const [userPeriod, setUserPeriod] = useState<Period | null>(null)

  // Ask for 10 years upfront. The endpoint will tier-limit free users
  // to fewer rows, in which case we render whatever it returns and the
  // chart adapts down to (n) trailing periods.
  const { data, isLoading, isError } = useQuery<FinancialsResponse>({
    queryKey: ["financials", ticker, "annual", 10, "chart-panel"],
    queryFn: () => getFinancials(ticker, "annual", 10),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const incomeYears = data?.income ?? []
  const cashflowYears = data?.cash_flow ?? []

  const period: Period = userPeriod ?? (data?.has_quarterly ? "quarterly" : "annual")

  // Sector-aware bank-cohort gating. For banks the "revenue" bar is
  // backfilled with interest_earned / net_interest_income / total_income
  // via getDisplayRevenue(); the FCF bar is hidden entirely so the
  // legend doesn't carry a series that's all nulls.
  const isFin = isFinancialCohort(sector, ticker)
  const revenueLabel = getDisplayRevenueLabel(sector, ticker)
  const fcfNote = getFCFNotApplicableNote(sector, ticker)

  // The income payload carries revenue + net_income; cash flow carries
  // FCF. Merge by `year` so a name with mismatched coverage (e.g. FCF
  // missing for the latest period) still plots the rows it does have.
  const rows: ChartRow[] = useMemo(() => {
    if (!incomeYears.length && !cashflowYears.length) return []
    const byYear = new Map<string, ChartRow>()
    for (const y of incomeYears) {
      byYear.set(y.year, {
        year: y.year,
        // Bank fall-back: interest_earned / NII / total_income when
        // the generic `revenue` field is null. This is the load-
        // bearing line that turns flat-zero bars on HDFCBANK into
        // populated bars.
        revenue: getDisplayRevenue(y, sector, ticker),
        net_profit: y.net_income,
        fcf: null,
      })
    }
    for (const y of cashflowYears) {
      const existing = byYear.get(y.year)
      if (existing) {
        // Suppress FCF for the financial cohort — see fcfNote below.
        existing.fcf = isFin ? null : y.free_cash_flow
      } else {
        byYear.set(y.year, {
          year: y.year,
          revenue: null,
          net_profit: null,
          fcf: isFin ? null : y.free_cash_flow,
        })
      }
    }
    return pickRows(Array.from(byYear.values()) as unknown as FinancialYear[])
  }, [incomeYears, cashflowYears, isFin, sector, ticker])

  if (isLoading) return <Skeleton />

  const isForeign = isForeignCurrency(currency, ticker)
  const unit = data?.currency_unit ?? (isForeign ? "M" : "Cr")
  const currencyCode = data?.currency ?? currency ?? "INR"
  const unitLabel = `${currencyCode} ${unit}`

  const hasRows =
    rows.length > 0 &&
    rows.some((r) => r.revenue !== null || r.net_profit !== null || r.fcf !== null)

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-4"
      aria-label={`Financial history chart for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Financial statements — 10-year
          </h2>
          <p className="text-xs text-caption mt-1">
            Revenue, profit, and free cash flow.
          </p>
        </div>
        <div
          role="tablist"
          aria-label="Financial statements period"
          className="flex gap-1.5"
        >
          {(["annual", "quarterly"] as const).map((p) => (
            <button
              key={p}
              role="tab"
              aria-selected={period === p}
              onClick={() => setUserPeriod(p)}
              className={
                period === p
                  ? "text-xs px-2.5 py-1 rounded-lg font-medium bg-brand text-white"
                  : "text-xs px-2.5 py-1 rounded-lg font-medium bg-surface text-caption hover:text-ink"
              }
            >
              {p === "annual" ? "Annual" : "Quarterly"}
            </button>
          ))}
        </div>
      </div>

      {period === "quarterly" && (
        <QuarterlyResultsTable ticker={ticker} currency={currency} />
      )}

      {period === "annual" && isError && (
        // P0 empty-state fix (2026-06-11 continuation of PR #901) —
        // previously a single-line text orphaned the "FINANCIAL
        // STATEMENTS — 10-YEAR" CollapsibleSection header on tickers
        // where the financials endpoint 5xx'd. Now we render a full
        // empty-state card with a recovery hint so the slot never
        // reads as broken.
        <div
          role="status"
          className="rounded-xl border border-dashed border-border bg-surface/40 p-5 text-center"
          data-testid="financials-chart-error"
        >
          <p className="text-sm font-medium text-ink mb-1">
            Financial history is being computed
          </p>
          <p className="text-xs text-caption max-w-md mx-auto leading-relaxed">
            We pull income statement and cash flow rows from BSE / NSE XBRL
            filings and merge them with yfinance fall-backs. The endpoint
            returned an error for this ticker — refresh in a few moments,
            or check the calibration page for ingestion-coverage details.
          </p>
        </div>
      )}

      {period === "annual" && !isError && !hasRows && (
        // P0 empty-state fix (2026-06-11) — the cache-warm path may
        // leave a ticker without any FY rows during a recompute window
        // (POWERGRID + similar utility names hit this between
        // CACHE_VERSION bumps). Upgraded from a single-line italic to
        // a full empty-state card matching the rest of the section
        // empty-state vocabulary.
        <div
          role="status"
          className="rounded-xl border border-dashed border-border bg-surface/40 p-5 text-center"
          data-testid="financials-chart-empty"
        >
          <p className="text-sm font-medium text-ink mb-1">
            10-year history will appear here as we backfill
          </p>
          <p className="text-xs text-caption max-w-md mx-auto leading-relaxed">
            Most NIFTY 500 names already have a full 10-year window. Newer
            listings, ADRs, and a handful of utilities are still being
            backfilled from BSE XBRL filings.
          </p>
          <a
            href="/calibration"
            className="inline-flex items-center mt-3 px-3 py-1.5 text-[11px] font-semibold text-brand bg-brand-50 dark:bg-brand/10 rounded-full hover:opacity-90 transition"
          >
            See coverage on the calibration page &rarr;
          </a>
        </div>
      )}

      {period === "annual" && hasRows && (
        <>
          <div className="text-[11px] text-caption mb-1">Values in {unitLabel}</div>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={rows}
                margin={{ top: 8, right: 12, bottom: 0, left: 0 }}
                barCategoryGap="18%"
              >
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="year"
                  tick={{ fontSize: 11, fill: "#6b7280" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#6b7280" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={formatTick}
                  width={52}
                />
                <Tooltip
                  cursor={{ fill: "rgba(148, 163, 184, 0.12)" }}
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: "1px solid #e5e7eb",
                  }}
                  formatter={(value, name) => {
                    const numeric =
                      typeof value === "number" ? value : Number(value as unknown as string)
                    return [
                      formatTooltip(Number.isFinite(numeric) ? numeric : null, unit),
                      name as string,
                    ]
                  }}
                />
                <Legend
                  iconType="circle"
                  wrapperStyle={{ fontSize: 12, paddingTop: 4 }}
                />
                <Bar
                  dataKey="revenue"
                  name={revenueLabel}
                  fill={COLOR_REVENUE}
                  radius={[3, 3, 0, 0]}
                />
                <Bar dataKey="net_profit" name="Net Profit" fill={COLOR_PROFIT} radius={[3, 3, 0, 0]} />
                {!isFin && (
                  <Bar
                    dataKey="fcf"
                    name="Free Cash Flow"
                    fill={COLOR_FCF}
                    radius={[3, 3, 0, 0]}
                  />
                )}
              </BarChart>
            </ResponsiveContainer>
          </div>
          {isFin && fcfNote && (
            <p
              className="text-[11px] text-caption mt-2"
              data-testid="financials-chart-fcf-not-applicable"
            >
              {fcfNote}
            </p>
          )}
          <p className="text-[11px] text-caption mt-3">
            {rows.length} period{rows.length === 1 ? "" : "s"} shown
            {data?.data_source === "yfinance_fallback" ? " · source: yfinance" : ""}
            {data?.tier_limited ? " · upgrade for full 10-year history" : ""}
          </p>
        </>
      )}
    </section>
  )
}

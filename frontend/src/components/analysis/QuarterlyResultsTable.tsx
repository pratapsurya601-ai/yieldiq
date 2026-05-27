"use client"

// QuarterlyResultsTable — dense P&L grid for the analysis Financials
// panel's Quarterly sub-tab.
//
// Closes Tickertape density gap #3 from the 2026-05-27 audit
// (`.audit/tickertape-deep-walk-2026-05-27.md`): peer surfaces ship an
// 8-10 quarter × 10-line-item table that lets a reader eyeball
// seasonality and margin compression in a single viewport. YieldIQ's
// FinancialsChartPanel previously rendered only an annual bar chart
// and an empty-state notice for the Quarterly tab.
//
// Data path: reuses the existing /api/v1/analysis/{ticker}/financials
// endpoint with period=quarterly (returns up to 8 quarters from the
// company_financials table; no backend changes, no CACHE_VERSION
// bump). Quarter labels arrive as "Q3FY25"-style strings from
// _format_period; we render them as column headers in ascending
// chronological order so the latest quarter sits on the right.
//
// Rendering rules:
//   * Rows: Revenue, Gross Profit, EBITDA, Operating Income, Interest,
//     Net Income, EPS, Net Margin. Cells we don't have are rendered
//     as "—" — we never fabricate a missing line item.
//   * Cells right-aligned, neutral foreground.
//   * Final column is a YoY delta (current quarter vs the same quarter
//     four periods earlier when available, otherwise vs the oldest in
//     the window) — coloured: green for positive, red for negative,
//     neutral for unavailable. Net Margin row uses pp delta.
//   * Currency / unit ("INR Cr") read off the endpoint payload to
//     match FinancialStatements + FinancialsChartPanel.

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  getFinancials,
  type FinancialYear,
  type FinancialsResponse,
} from "@/lib/api"

interface Props {
  ticker: string
  currency?: string | null
}

interface RowSpec {
  key: string
  label: string
  // Selector returns either a numeric value (rendered via fmtNumber)
  // or null when the underlying field is missing.
  pick: (q: FinancialYear) => number | null
  // Formatter for the row's cells; pp rows render deltas as ppt
  // rather than percent.
  fmt: (v: number | null) => string
  // Delta semantics:
  //   "pct"     → relative change ((curr - prev)/|prev| * 100)
  //   "pp"      → absolute change (curr - prev), formatted as pp
  pct: "pct" | "pp"
}

// Group integers with the Indian thousand-separator convention without
// going through .toLocaleString() (the project-wide lint rule pushes
// callers to the formatters in @/lib/utils — none of those round-trip
// raw Cr values without prefixing a currency glyph, which we don't
// want inside table cells where the unit label sits in the caption).
function groupIndianDigits(n: number): string {
  const intStr = String(Math.trunc(n))
  if (intStr.length <= 3) return intStr
  const head = intStr.slice(0, -3)
  const tail = intStr.slice(-3)
  const groupedHead = head.replace(/(\d)(?=(\d\d)+$)/g, "$1,")
  return `${groupedHead},${tail}`
}

function fmtNumber(v: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—"
  const abs = Math.abs(v)
  const sign = v < 0 ? "-" : ""
  if (abs >= 100000) return `${sign}${(abs / 1000).toFixed(0)}K`
  if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(1)}K`
  if (abs >= 1) return `${sign}${groupIndianDigits(abs)}`
  return `${sign}${abs.toFixed(2)}`
}

function fmtPerShare(v: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—"
  return v.toFixed(2)
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—"
  return `${v.toFixed(1)}%`
}

const ROW_SPECS: RowSpec[] = [
  { key: "revenue", label: "Revenue", pick: (q) => q.revenue, fmt: fmtNumber, pct: "pct" },
  { key: "gross_profit", label: "Gross Profit", pick: (q) => q.gross_profit, fmt: fmtNumber, pct: "pct" },
  { key: "ebitda", label: "EBITDA", pick: (q) => q.ebitda, fmt: fmtNumber, pct: "pct" },
  { key: "operating_income", label: "Operating Income", pick: (q) => q.operating_income, fmt: fmtNumber, pct: "pct" },
  { key: "interest_expense", label: "Interest", pick: (q) => q.interest_expense ?? null, fmt: fmtNumber, pct: "pct" },
  { key: "net_income", label: "Net Income", pick: (q) => q.net_income, fmt: fmtNumber, pct: "pct" },
  { key: "eps_diluted", label: "EPS (diluted)", pick: (q) => q.eps_diluted, fmt: fmtPerShare, pct: "pct" },
  { key: "net_margin_pct", label: "Net Margin", pick: (q) => q.net_margin_pct, fmt: fmtPct, pct: "pp" },
]

function deltaPct(curr: number | null, prev: number | null): number | null {
  if (curr === null || prev === null || !Number.isFinite(curr) || !Number.isFinite(prev) || prev === 0) {
    return null
  }
  return ((curr - prev) / Math.abs(prev)) * 100
}

function deltaPp(curr: number | null, prev: number | null): number | null {
  if (curr === null || prev === null || !Number.isFinite(curr) || !Number.isFinite(prev)) {
    return null
  }
  return curr - prev
}

function DeltaCell({ value, mode }: { value: number | null; mode: "pct" | "pp" }) {
  if (value === null || !Number.isFinite(value)) {
    return <span className="text-caption">—</span>
  }
  const positive = value > 0
  const negative = value < 0
  const suffix = mode === "pp" ? " pp" : "%"
  const arrow = positive ? "▲" : negative ? "▼" : "•"
  const tone = positive
    ? "text-green-600"
    : negative
      ? "text-red-600"
      : "text-caption"
  return (
    <span className={`${tone} font-medium`}>
      {arrow} {Math.abs(value).toFixed(1)}{suffix}
    </span>
  )
}

export default function QuarterlyResultsTable({ ticker, currency }: Props) {
  const { data, isLoading, isError } = useQuery<FinancialsResponse>({
    queryKey: ["financials", ticker, "quarterly", 10, "quarterly-table"],
    queryFn: () => getFinancials(ticker, "quarterly", 10),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  // Backend returns quarters newest-first; render oldest-on-the-left so
  // the eye scans left-to-right as time advances (matches Tickertape).
  const quarters: FinancialYear[] = useMemo(() => {
    const rows = data?.income ?? []
    if (!rows.length) return []
    // Sort by period_end ascending; fall back to the year label string
    // when period_end is missing (rare — every DB row carries it).
    return [...rows].sort((a, b) => {
      const ae = a.period_end ?? ""
      const be = b.period_end ?? ""
      if (ae && be) return ae.localeCompare(be)
      return a.year.localeCompare(b.year)
    })
  }, [data?.income])

  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true">
        <div className="h-4 w-44 bg-border rounded animate-pulse" />
        <div className="h-[260px] bg-surface rounded-xl animate-pulse" />
      </div>
    )
  }

  if (isError || quarters.length === 0) {
    return (
      <p className="text-sm text-caption text-center py-10">
        Quarterly data not available for this ticker.
      </p>
    )
  }

  const currencyCode = data?.currency ?? currency ?? "INR"
  const unit = data?.currency_unit ?? "Cr"
  const unitLabel = `${currencyCode} ${unit}`

  // YoY delta = latest quarter vs the matching quarter four periods
  // earlier. Falls back to the oldest quarter in the window when we
  // don't have four trailing quarters.
  const latestIdx = quarters.length - 1
  const yoyIdx = latestIdx - 4 >= 0 ? latestIdx - 4 : 0
  const yoyAvailable = yoyIdx !== latestIdx
  const yoyHeader = yoyAvailable ? `YoY (${quarters[latestIdx].year} vs ${quarters[yoyIdx].year})` : "Δ"

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-[11px] text-caption">Values in {unitLabel} (EPS in {currencyCode}/share)</p>
        <p className="text-[11px] text-caption">{quarters.length} quarter{quarters.length === 1 ? "" : "s"}</p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="min-w-full text-xs">
          <thead className="bg-surface">
            <tr>
              <th
                scope="col"
                className="text-left font-medium text-caption px-3 py-2 sticky left-0 bg-surface z-10"
              >
                Line item
              </th>
              {quarters.map((q) => (
                <th
                  key={q.year + (q.period_end ?? "")}
                  scope="col"
                  className="text-right font-medium text-caption px-3 py-2 whitespace-nowrap"
                >
                  {q.year}
                </th>
              ))}
              <th
                scope="col"
                className="text-right font-medium text-caption px-3 py-2 whitespace-nowrap"
                title={yoyAvailable ? "Year-over-year change" : "Change vs oldest quarter shown"}
              >
                {yoyHeader}
              </th>
            </tr>
          </thead>
          <tbody>
            {ROW_SPECS.map((spec, rowIdx) => {
              const cells = quarters.map((q) => spec.pick(q))
              const currVal = cells[latestIdx] ?? null
              const prevVal = cells[yoyIdx] ?? null
              const deltaVal = spec.pct === "pp" ? deltaPp(currVal, prevVal) : deltaPct(currVal, prevVal)
              return (
                <tr
                  key={spec.key}
                  className={rowIdx % 2 === 0 ? "bg-bg" : "bg-surface/40"}
                >
                  <td className="text-left text-ink px-3 py-1.5 sticky left-0 bg-inherit z-10 font-medium whitespace-nowrap">
                    {spec.label}
                  </td>
                  {cells.map((v, i) => (
                    <td
                      key={i}
                      className="text-right text-ink px-3 py-1.5 tabular-nums whitespace-nowrap"
                    >
                      {spec.fmt(v)}
                    </td>
                  ))}
                  <td className="text-right px-3 py-1.5 tabular-nums whitespace-nowrap">
                    <DeltaCell value={deltaVal} mode={spec.pct} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-caption">
        Source: {data?.data_source === "yfinance_fallback" ? "yfinance" : "exchange filings"}.
        Quarter labels follow the Indian fiscal year (Q1 = Apr-Jun).
      </p>
    </div>
  )
}

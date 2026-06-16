"use client"

/**
 * NAV-vs-benchmark line chart for /funds/[scheme_code].
 *
 * Both series are indexed to 100 on the first visible point so they
 * share a y-axis. The window-toggle (1Y / 3Y / 5Y / 10Y) is purely
 * client-side filtering over the full daily series the backend ships —
 * keeps the payload to one round trip per page load.
 *
 * IMPORTANT: the backend ships ~daily NAV points (≈125 trading-day rows
 * per year, ~600 over a 5y history), NOT one row per month. The window
 * filter therefore selects by CALENDAR DATE (lastDate − N years), never
 * by a fixed count of trailing rows. An earlier version used
 * `slice(-WINDOW_MONTHS[key])` which, on daily data, rendered only the
 * last ~3 months for 5Y and ~6 months for 10Y. (bit: chart-window)
 *
 * 10Y degrades to "Since inception (X yrs)" when the held history is
 * shorter than 10 years, rather than rendering a near-empty 10Y panel.
 *
 * Renders cleanly with benchmark_history empty (scheme-only line),
 * which is the most common shape today: only a small subset of TRI
 * benchmark codes are ingested in Phase 1. Benchmark data gaps (e.g. a
 * backfill hole) render as a break in the line — `connectNulls={false}`
 * plus per-date null filling means no misleading straight-line
 * interpolation across missing dates.
 */

import { useMemo, useState } from "react"
import {
  Line,
  LineChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { FundBenchmarkPoint, FundNavPoint } from "@/types/api"

export type WindowKey = "1Y" | "3Y" | "5Y" | "10Y"

const WINDOW_YEARS: Record<WindowKey, number> = {
  "1Y": 1,
  "3Y": 3,
  "5Y": 5,
  "10Y": 10,
}

interface Props {
  navHistory: FundNavPoint[]
  benchmarkHistory: FundBenchmarkPoint[]
}

export interface MergedPoint {
  date: string
  scheme: number
  benchmark: number | null
}

export interface ChartData {
  data: MergedPoint[]
  hasBenchmark: boolean
  /** Effective span of the rendered window, in years (rounded to 0.1). */
  spanYears: number
  /**
   * True when the requested window (e.g. 10Y) exceeds the held history,
   * so the chart is showing everything we have ("since inception").
   */
  truncatedToInception: boolean
}

/**
 * Subtract `years` whole calendar years from an ISO `YYYY-MM-DD` date and
 * return the cutoff as an ISO string. String comparison on ISO dates is
 * lexicographically correct, so callers can filter with `d >= cutoff`.
 */
export function isoYearsBefore(iso: string, years: number): string {
  // Parse as UTC to avoid local-timezone day-shifts.
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCFullYear(d.getUTCFullYear() - years)
  return d.toISOString().slice(0, 10)
}

function indexToHundred(series: { date: string; value: number }[]): {
  date: string
  value: number
}[] {
  if (series.length === 0) return []
  const base = series[0].value
  if (!base || base === 0) return series.map((p) => ({ ...p, value: 100 }))
  return series.map((p) => ({ date: p.date, value: (p.value / base) * 100 }))
}

/**
 * Pure window-filter + rebase + merge. Exported for unit testing.
 *
 * - Filters BOTH series to [lastNavDate − years, lastNavDate] by date.
 * - Rebases each series to 100 at the FIRST point inside the window
 *   (so the toggle re-anchors the index to the start of the window).
 * - Merges on date with the scheme series as the spine; dates without a
 *   benchmark row get `benchmark: null` (rendered as a gap).
 */
export function buildChartData(
  navHistory: FundNavPoint[],
  benchmarkHistory: FundBenchmarkPoint[],
  years: number,
): ChartData {
  if (navHistory.length === 0) {
    return {
      data: [],
      hasBenchmark: false,
      spanYears: 0,
      truncatedToInception: false,
    }
  }

  const navSorted = [...navHistory].sort((a, b) =>
    a.nav_date.localeCompare(b.nav_date),
  )
  const firstDate = navSorted[0].nav_date
  const lastDate = navSorted[navSorted.length - 1].nav_date
  const cutoff = isoYearsBefore(lastDate, years)

  // If the requested window reaches before the first held NAV, we are
  // effectively showing the whole series ("since inception").
  const truncatedToInception = cutoff < firstDate
  const effectiveCutoff = truncatedToInception ? firstDate : cutoff

  const navWindow = navSorted.filter((p) => p.nav_date >= effectiveCutoff)

  const navIdx = indexToHundred(
    navWindow.map((p) => ({ date: p.nav_date, value: p.nav })),
  )

  // Span of what we actually render, in years (for the "since inception"
  // caption). Based on the first/last dates of the visible window.
  const spanYears =
    navWindow.length >= 2
      ? Math.round(
          ((new Date(`${navWindow[navWindow.length - 1].nav_date}T00:00:00Z`).getTime() -
            new Date(`${navWindow[0].nav_date}T00:00:00Z`).getTime()) /
            (365.25 * 24 * 3600 * 1000)) *
            10,
        ) / 10
      : 0

  let benchIdx: { date: string; value: number }[] = []
  if (benchmarkHistory.length > 0 && navWindow.length > 0) {
    const benchInWindow = benchmarkHistory.filter(
      (b) => b.nav_date >= effectiveCutoff,
    )
    if (benchInWindow.length > 0) {
      benchIdx = indexToHundred(
        benchInWindow.map((p) => ({ date: p.nav_date, value: p.tri_value })),
      )
    }
  }

  // Merge on date — scheme is the spine, benchmark is filled where a row
  // exists for that exact date. Missing dates → null → gap in the line.
  const benchMap = new Map(benchIdx.map((p) => [p.date, p.value]))
  const data: MergedPoint[] = navIdx.map((p) => ({
    date: p.date,
    scheme: p.value,
    benchmark: benchMap.get(p.date) ?? null,
  }))

  return {
    data,
    hasBenchmark: benchIdx.length > 0,
    spanYears,
    truncatedToInception,
  }
}

export default function NavBenchmarkChart({
  navHistory,
  benchmarkHistory,
}: Props) {
  const [windowKey, setWindowKey] = useState<WindowKey>("5Y")

  const { data, hasBenchmark, spanYears, truncatedToInception } = useMemo(
    () =>
      buildChartData(navHistory, benchmarkHistory, WINDOW_YEARS[windowKey]),
    [navHistory, benchmarkHistory, windowKey],
  )

  if (navHistory.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500">
        NAV history is not available yet for this scheme.
      </div>
    )
  }

  // When a long window (typically 10Y) reaches past inception, label it
  // honestly as the held span rather than implying a full 10Y of data.
  const showInceptionNote = truncatedToInception && spanYears > 0

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">
          NAV vs Benchmark
        </h2>
        <div className="flex gap-1" role="tablist" aria-label="Chart window">
          {(Object.keys(WINDOW_YEARS) as WindowKey[]).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setWindowKey(k)}
              className={
                "rounded-md px-2.5 py-1 text-xs font-medium transition " +
                (windowKey === k
                  ? "bg-gray-900 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200")
              }
              aria-pressed={windowKey === k}
            >
              {k}
            </button>
          ))}
        </div>
      </div>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickFormatter={(d: string) => d.slice(0, 7)}
              minTickGap={32}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => v.toFixed(0)}
            />
            <Tooltip
              formatter={(value) =>
                typeof value === "number" ? value.toFixed(2) : String(value)
              }
              labelFormatter={(label) => String(label ?? "")}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="scheme"
              name="Scheme NAV (indexed)"
              stroke="#2563eb"
              strokeWidth={2}
              dot={false}
            />
            {hasBenchmark ? (
              <Line
                type="monotone"
                dataKey="benchmark"
                name="Benchmark TRI (indexed)"
                stroke="#16a34a"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {showInceptionNote ? (
        <p className="mt-2 text-xs text-gray-500">
          Showing full history since inception ({spanYears} yrs) — less than
          the selected window.
        </p>
      ) : null}
      {!hasBenchmark ? (
        <p className="mt-2 text-xs text-gray-500">
          Benchmark TRI series is not available for this scheme yet.
        </p>
      ) : null}
    </div>
  )
}

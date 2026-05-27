"use client"

/**
 * NAV-vs-benchmark line chart for /funds/[scheme_code].
 *
 * Both series are indexed to 100 on the first visible point so they
 * share a y-axis. Window-toggle (1Y / 3Y / 5Y / 10Y) is purely client-
 * side filtering over the 5y window the backend ships — keeps the
 * payload small and avoids a second round trip per click.
 *
 * Renders cleanly with benchmark_history empty (scheme-only line),
 * which is the most common shape today: only a small subset of TRI
 * benchmark codes are ingested in Phase 1.
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

type WindowKey = "1Y" | "3Y" | "5Y" | "10Y"

const WINDOW_MONTHS: Record<WindowKey, number> = {
  "1Y": 12,
  "3Y": 36,
  "5Y": 60,
  "10Y": 120,
}

interface Props {
  navHistory: FundNavPoint[]
  benchmarkHistory: FundBenchmarkPoint[]
}

interface MergedPoint {
  date: string
  scheme: number
  benchmark: number | null
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

export default function NavBenchmarkChart({
  navHistory,
  benchmarkHistory,
}: Props) {
  const [windowKey, setWindowKey] = useState<WindowKey>("5Y")

  const { data, hasBenchmark } = useMemo(() => {
    if (navHistory.length === 0) return { data: [], hasBenchmark: false }
    // Filter to the chosen window. Backend ships ~5y monthly, so 10Y
    // gracefully truncates to whatever we have rather than padding.
    const months = WINDOW_MONTHS[windowKey]
    const navSorted = [...navHistory].sort((a, b) =>
      a.nav_date.localeCompare(b.nav_date),
    )
    const navWindow = navSorted.slice(-months)

    const navIdx = indexToHundred(
      navWindow.map((p) => ({ date: p.nav_date, value: p.nav })),
    )

    let benchIdx: { date: string; value: number }[] = []
    const benchInWindow =
      benchmarkHistory.length > 0 && navWindow.length > 0
        ? benchmarkHistory.filter((b) => b.nav_date >= navWindow[0].nav_date)
        : []
    if (benchInWindow.length > 0) {
      benchIdx = indexToHundred(
        benchInWindow.map((p) => ({ date: p.nav_date, value: p.tri_value })),
      )
    }

    // Merge on date — scheme is the spine, benchmark is filled where
    // available. Months without a benchmark row render as a gap, which
    // Recharts handles natively when `connectNulls` is false.
    const benchMap = new Map(benchIdx.map((p) => [p.date, p.value]))
    const merged: MergedPoint[] = navIdx.map((p) => ({
      date: p.date,
      scheme: p.value,
      benchmark: benchMap.get(p.date) ?? null,
    }))

    return { data: merged, hasBenchmark: benchIdx.length > 0 }
  }, [navHistory, benchmarkHistory, windowKey])

  if (navHistory.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500">
        NAV history is not available yet for this scheme.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">
          NAV vs Benchmark
        </h2>
        <div className="flex gap-1" role="tablist" aria-label="Chart window">
          {(Object.keys(WINDOW_MONTHS) as WindowKey[]).map((k) => (
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
      {!hasBenchmark ? (
        <p className="mt-2 text-xs text-gray-500">
          Benchmark TRI series is not available for this scheme yet.
        </p>
      ) : null}
    </div>
  )
}

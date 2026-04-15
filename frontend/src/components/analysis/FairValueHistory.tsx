"use client"

import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceDot,
} from "recharts"
import { getFVHistory, type FVHistoryPoint, type FVHistoryResponse } from "@/lib/api"
import { cn, formatCurrency } from "@/lib/utils"

interface Props {
  ticker: string
  companyName: string
  currency?: string
}

interface ChartPoint extends FVHistoryPoint {
  displayDate: string
}

/* ------------------------------------------------------------------ */
/* Loading skeleton                                                    */
/* ------------------------------------------------------------------ */
function FVHistorySkeleton() {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
      <div className="h-5 w-48 bg-gray-200 rounded animate-pulse" />
      <div className="h-[220px] bg-gray-100 rounded-xl animate-pulse" />
      <div className="h-4 w-64 bg-gray-200 rounded animate-pulse" />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Tooltip                                                             */
/* ------------------------------------------------------------------ */
function FVTooltip({
  active,
  payload,
  currency,
}: {
  active?: boolean
  payload?: Array<{ payload: ChartPoint }>
  currency: string
}) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  const undervalued = d.price < d.fair_value
  return (
    <div className="rounded-xl bg-gray-900 px-3 py-2 text-xs text-white shadow-lg min-w-[180px]">
      <p className="text-gray-400 mb-1">
        {new Date(d.date).toLocaleDateString("en-IN", {
          day: "numeric",
          month: "short",
          year: "numeric",
        })}
      </p>
      <p className="font-medium">
        Price: <span className="font-mono">{formatCurrency(d.price, currency)}</span>
      </p>
      <p className="font-medium text-green-300">
        Fair value: <span className="font-mono">{formatCurrency(d.fair_value, currency)}</span>
      </p>
      <p className={cn("mt-1 font-semibold", undervalued ? "text-green-300" : "text-red-300")}>
        MoS: {d.mos_pct > 0 ? "+" : ""}
        {d.mos_pct.toFixed(1)}%{" "}
        <span className="opacity-80">({undervalued ? "Undervalued" : "Overvalued"})</span>
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */
export default function FairValueHistory({ ticker, companyName, currency = "INR" }: Props) {
  const [years, setYears] = useState<number>(3)
  const [visible, setVisible] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  /* Lazy-load on scroll */
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

  const { data, isLoading, isError } = useQuery<FVHistoryResponse>({
    queryKey: ["fv-history", ticker, years],
    queryFn: () => getFVHistory(ticker, years),
    enabled: visible && !!ticker,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  /* ---------- Render states ---------- */
  if (!visible || isLoading) {
    return (
      <div ref={containerRef}>
        <FVHistorySkeleton />
      </div>
    )
  }

  if (isError) {
    return (
      <div ref={containerRef} className="bg-white rounded-2xl border border-gray-100 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Historical Fair Value</h2>
        <p className="text-sm text-gray-400 text-center py-6">
          Fair value history unavailable
        </p>
      </div>
    )
  }

  /* First-time / not-enough-data state */
  if (!data?.has_data || !data.data.length) {
    return (
      <div ref={containerRef} className="bg-white rounded-2xl border border-gray-100 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Historical Fair Value</h2>
        <div className="py-6 text-center space-y-2">
          <p className="text-2xl">📈</p>
          <p className="text-sm text-gray-700 font-medium">History is building up</p>
          <p className="text-xs text-gray-400 max-w-xs mx-auto">
            {data?.message ??
              "Analyse this stock regularly to grow your fair value chart."}
          </p>
        </div>
      </div>
    )
  }

  /* ---------- Shape chart data ---------- */
  const chartData: ChartPoint[] = data.data.map((d) => ({
    ...d,
    displayDate: new Date(d.date).toLocaleDateString("en-IN", {
      month: "short",
      year: "2-digit",
    }),
  }))

  const tickInterval = Math.max(0, Math.floor(chartData.length / 6))
  const latest = chartData[chartData.length - 1]
  const summary = data.summary

  /* Y-axis domain with a little breathing room */
  const allValues = chartData.flatMap((d) => [d.price, d.fair_value])
  const minY = Math.min(...allValues) * 0.95
  const maxY = Math.max(...allValues) * 1.05

  return (
    <div ref={containerRef} className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">Historical Fair Value</h2>
        <div className="flex gap-1.5">
          {[1, 2, 3].map((y) => {
            const locked = data.tier === "free" && y > 1
            const active = years === y
            return (
              <button
                key={y}
                onClick={() => !locked && setYears(y)}
                disabled={locked}
                className={cn(
                  "text-xs px-2.5 py-1 rounded-lg font-medium transition-colors",
                  active
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200",
                  locked && "opacity-40 cursor-not-allowed hover:bg-gray-100"
                )}
                aria-label={locked ? `${y} year (upgrade required)` : `${y} year`}
              >
                {y}Y{locked ? " 🔒" : ""}
              </button>
            )
          })}
        </div>
      </div>

      {/* Chart */}
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
            <XAxis
              dataKey="displayDate"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              interval={tickInterval}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={[minY, maxY]}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => formatCurrency(v, currency)}
              width={60}
            />
            <Tooltip content={<FVTooltip currency={currency} />} />

            <Line
              type="monotone"
              dataKey="fair_value"
              name="Fair Value"
              stroke="#16a34a"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="price"
              name="Price"
              stroke="#185FA5"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />

            {latest && (
              <ReferenceDot
                x={latest.displayDate}
                y={latest.price}
                r={5}
                fill="#185FA5"
                stroke="#fff"
                strokeWidth={2}
              />
            )}

            <Legend iconType="line" iconSize={16} wrapperStyle={{ fontSize: 11 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Summary caption */}
      {summary.has_data && summary.pct_undervalued !== null && (
        <div className="bg-gray-50 rounded-xl p-3 space-y-1">
          <p className="text-xs text-gray-600 leading-relaxed">
            In the tracked period,{" "}
            <span className="font-semibold text-green-700">
              {companyName} traded below our fair value estimate {summary.pct_undervalued}% of the
              time.
            </span>
          </p>
          {summary.data_start_date && (
            <p className="text-[11px] text-gray-400">
              History begins{" "}
              {new Date(summary.data_start_date).toLocaleDateString("en-IN", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}{" "}
              · {summary.total_points} data point{summary.total_points === 1 ? "" : "s"}
            </p>
          )}
        </div>
      )}

      {/* Tier upgrade CTA */}
      {data.tier_limited && (
        <div className="border border-blue-100 bg-blue-50 rounded-xl p-3 flex items-center justify-between gap-3">
          <p className="text-xs text-blue-700">🔒 Unlock 3-year history with Starter</p>
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

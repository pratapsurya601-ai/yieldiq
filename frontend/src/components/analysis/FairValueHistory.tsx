"use client"

import { useState } from "react"
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
        MoS: {d.mos_pct != null ? `${d.mos_pct > 0 ? "+" : ""}${d.mos_pct.toFixed(1)}%` : "\u2014"}{" "}
        {d.mos_pct != null && <span className="opacity-80">({undervalued ? "Below Fair Value" : "Above Fair Value"})</span>}
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */
/* Shared placeholder — used for loading, error, AND empty-data states.
   Keeping one component ensures the card occupies the right slot in
   the layout no matter which async state the query is in. No more
   blank gaps. */
function FVPlaceholder({ variant }: { variant: "loading" | "empty" | "error" }) {
  return (
    <div className="bg-surface rounded-2xl border border-border p-5">
      <h2 className="text-sm font-semibold text-ink mb-3">Historical Fair Value</h2>
      {variant === "loading" ? (
        <div className="space-y-3">
          <div className="h-[220px] bg-bg rounded-xl animate-pulse" />
          <div className="h-4 w-64 bg-border rounded animate-pulse" />
        </div>
      ) : (
        <div className="py-8 text-center flex flex-col items-center gap-2">
          <svg
            className="h-8 w-8 text-caption"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 3v18h18" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 14l4-4 3 3 5-6" />
          </svg>
          <p className="text-sm text-body font-medium">
            {variant === "error" ? "Fair value history unavailable" : "No history yet"}
          </p>
          <p className="text-xs text-caption max-w-xs">
            {variant === "error"
              ? "Try again in a moment."
              : "Fair value history will appear here after your first analysis runs."}
          </p>
        </div>
      )}
    </div>
  )
}

export default function FairValueHistory({ ticker, companyName, currency = "INR" }: Props) {
  const [years, setYears] = useState<number>(3)

  // Eager fetch — the lazy-load-on-scroll pattern caused the component
  // to render nothing when IntersectionObserver timing lost races with
  // Next 16 hydration. Payload is tiny; just fetch immediately.
  const { data, isLoading, isError } = useQuery<FVHistoryResponse>({
    queryKey: ["fv-history", ticker, years],
    queryFn: () => getFVHistory(ticker, years),
    enabled: !!ticker,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  /* ---------- Render states (every branch returns SOMETHING) ---------- */
  if (isLoading) return <FVPlaceholder variant="loading" />
  if (isError) return <FVPlaceholder variant="error" />

  const hasRows = !!data?.has_data && !!data.data?.length
  if (!hasRows) return <FVPlaceholder variant="empty" />

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
    <div className="bg-surface rounded-2xl border border-border p-5 space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">Historical Fair Value</h2>
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
                    ? "bg-brand text-white"
                    : "bg-bg text-caption hover:bg-border",
                  locked && "opacity-40 cursor-not-allowed hover:bg-bg"
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
        <div className="bg-bg rounded-xl p-3 space-y-1">
          <p className="text-xs text-body leading-relaxed">
            In the tracked period,{" "}
            <span className="font-semibold text-green-700">
              {companyName} traded below our fair value estimate {summary.pct_undervalued}% of the
              time.
            </span>
          </p>
          {summary.data_start_date && (
            <p className="text-[11px] text-caption">
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
        <div className="border border-blue-100 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/30 rounded-xl p-3 flex items-center justify-between gap-3">
          <p className="text-xs text-blue-700 dark:text-blue-300">🔒 Unlock 3-year history with Starter</p>
          <a
            href="/pricing"
            className="text-xs font-semibold text-blue-600 dark:text-blue-400 whitespace-nowrap hover:underline"
          >
            Upgrade →
          </a>
        </div>
      )}
    </div>
  )
}

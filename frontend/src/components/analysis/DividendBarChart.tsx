"use client"

/**
 * DividendBarChart — Visual Richness #2
 *
 * 10-year dividend-per-share bar chart with an optional payout-ratio
 * overlay (currently a single horizontal reference line — backend does
 * not yet return per-year payout history).
 *
 * Replaces the previous collapsed "Dividend History" details panel in
 * the analysis page. The 3 KPI tiles (Yield / Payout / Consecutive
 * Years) rendered as a TrustStrip remain above this chart.
 *
 * Data source: `insights.dividend.fy_history` from `/api/analysis`.
 * No new network calls are made.
 */

import { useMemo } from "react"
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Legend,
} from "recharts"
import { currencySymbol } from "@/lib/currency"
import type { DividendData } from "@/types/api"

interface Props {
  dividend?: DividendData | null
  currency?: string | null
  ticker?: string | null
}

interface Row {
  fy: string
  dps: number
  payout: number | null
}

const MAX_YEARS = 10

export default function DividendBarChart({ dividend, currency, ticker }: Props) {
  const sym = currencySymbol(currency, ticker)

  const rows: Row[] = useMemo(() => {
    if (!dividend?.fy_history?.length) return []
    // fy_history is already FY-keyed; sort ascending and take the
    // most recent 10 entries.
    const sorted = [...dividend.fy_history].sort((a, b) =>
      a.fy.localeCompare(b.fy)
    )
    const sliced = sorted.slice(-MAX_YEARS)
    return sliced.map((item) => ({
      fy: item.fy,
      dps: item.total_per_share,
      // Backend doesn't return per-year payout — we draw a single
      // reference line from the latest payout_ratio_pct instead.
      payout: null,
    }))
  }, [dividend])

  const payoutOverlay =
    dividend?.payout_ratio_pct !== null &&
    dividend?.payout_ratio_pct !== undefined &&
    Number.isFinite(dividend.payout_ratio_pct)
      ? dividend.payout_ratio_pct
      : null

  const noHistory = !dividend?.has_dividends || rows.length === 0

  if (noHistory) {
    return (
      <div className="bg-surface rounded-2xl border border-border p-4">
        <h3 className="text-sm font-semibold text-ink">
          Dividend per share — 10 year history
        </h3>
        <p className="mt-2 text-xs text-caption">
          No dividend history available — this stock has not paid
          dividends in our window.
        </p>
      </div>
    )
  }

  // Pad the y-axis a touch so the tallest bar doesn't kiss the top.
  const maxDps = Math.max(...rows.map((r) => r.dps))
  const yMax = maxDps > 0 ? maxDps * 1.15 : 1

  return (
    <div className="bg-surface rounded-2xl border border-border p-4">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h3 className="text-sm font-semibold text-ink">
          Dividend per share — 10 year history
        </h3>
        <span className="text-[11px] text-caption">
          {rows.length} {rows.length === 1 ? "year" : "years"} shown
        </span>
      </div>

      <div className="h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 12, bottom: 0, left: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#e5e7eb"
              vertical={false}
            />
            <XAxis
              dataKey="fy"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="dps"
              domain={[0, yMax]}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) =>
                `${sym}${v >= 100 ? v.toFixed(0) : v.toFixed(1)}`
              }
              width={56}
            />
            <YAxis
              yAxisId="payout"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              width={40}
            />
            <Tooltip
              cursor={{ fill: "rgba(24,95,165,0.06)" }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const dpsVal = payload.find((p) => p.dataKey === "dps")
                  ?.value as number | undefined
                return (
                  <div className="rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg">
                    <p className="text-gray-400">{label}</p>
                    {dpsVal !== undefined && (
                      <p className="font-semibold">
                        {sym}
                        {dpsVal.toFixed(2)} / share
                      </p>
                    )}
                    {payoutOverlay !== null && (
                      <p className="text-gray-300 mt-0.5">
                        Payout (latest): {payoutOverlay.toFixed(0)}%
                      </p>
                    )}
                  </div>
                )
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, paddingTop: 4 }}
              iconSize={10}
            />
            <Bar
              yAxisId="dps"
              dataKey="dps"
              name={`DPS (${sym})`}
              fill="#185FA5"
              radius={[3, 3, 0, 0]}
              maxBarSize={42}
            />
            {payoutOverlay !== null && (
              <>
                <ReferenceLine
                  yAxisId="payout"
                  y={payoutOverlay}
                  stroke="#F59E0B"
                  strokeDasharray="4 4"
                  ifOverflow="extendDomain"
                />
                {/* Invisible line entry so the legend explains the dashed line. */}
                <Line
                  yAxisId="payout"
                  type="monotone"
                  dataKey="payout"
                  name={`Payout ratio (latest ${payoutOverlay.toFixed(0)}%)`}
                  stroke="#F59E0B"
                  strokeDasharray="4 4"
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-2 text-[11px] text-caption">
        Bars: dividend per share by financial year. Dashed line: most
        recent payout ratio (per-year payout history not yet available).
      </p>
    </div>
  )
}

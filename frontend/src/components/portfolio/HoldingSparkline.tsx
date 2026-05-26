"use client"
/**
 * Holdings-table mini sparkline (P0 #5, 2026-05-25).
 *
 * 100×24 px Recharts LineChart showing 1y of actual price (solid red)
 * vs YieldIQ fair value (dashed gray). No axes, no gridlines, no
 * tooltip — this lives inside a tight holdings row and any extra
 * chrome would dominate the cell.
 *
 * Data is fed in from the parent's batched
 * `/analysis/fv-history/batch` query so we never make a per-row
 * network request.
 */
import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts"
import type { FVHistoryPoint } from "@/lib/api"

interface Props {
  data: FVHistoryPoint[] | undefined
  loading?: boolean
}

export default function HoldingSparkline({ data, loading }: Props) {
  if (loading) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading sparkline"
        data-testid="sparkline-skeleton"
        className="skeleton h-8 w-24 rounded"
      />
    )
  }

  // FIX portfolio-hotfix-#4: no data → render nothing. The previous
  // em-dash stub left a visible empty box in the row that read as
  // broken. Sparkline absence should be silent.
  if (!data || data.length < 2) {
    return null
  }

  // FIX portfolio-hotfix-#4: explicit min-max normalisation via
  // Recharts `domain={["dataMin","dataMax"]}` (with a small pad)
  // so the line uses the full vertical range instead of collapsing
  // to a flat 1px streak when the y-axis defaults to including 0.
  // Bumped to h-8 w-24 so the resulting curve is actually readable
  // inside the holdings row.
  return (
    <div
      data-testid="sparkline"
      className="h-8 w-24"
      aria-label="1 year price vs fair value sparkline"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <YAxis
            hide
            domain={[
              (dataMin: number) => dataMin * 0.98,
              (dataMax: number) => dataMax * 1.02,
            ]}
          />
          <Line
            type="monotone"
            dataKey="price"
            stroke="#dc2626"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="fair_value"
            stroke="#9ca3af"
            strokeWidth={1}
            strokeDasharray="3 2"
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

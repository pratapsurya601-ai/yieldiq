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
import { LineChart, Line, ResponsiveContainer } from "recharts"
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
        className="skeleton h-[24px] w-[100px] rounded"
      />
    )
  }

  if (!data || data.length < 2) {
    return (
      <div
        data-testid="sparkline-empty"
        className="h-[24px] w-[100px] flex items-center justify-end"
      >
        <span className="text-[10px] text-caption">—</span>
      </div>
    )
  }

  // Recharts handles nulls in `data` gracefully (line breaks), so we
  // don't need to scrub here. Keep dataKey strings stable for tests.
  return (
    <div
      data-testid="sparkline"
      className="h-[24px] w-[100px]"
      aria-label="1 year price vs fair value sparkline"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <Line
            type="monotone"
            dataKey="price"
            stroke="#dc2626"
            strokeWidth={1.25}
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

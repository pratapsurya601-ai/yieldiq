"use client"

// Day-89 — small client chart for the YIQ50 backtest marketing page.
// Server component renders the page; this file owns the Recharts island.
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts"

interface CurvePoint {
  label: string
  yiq50: number
  nifty: number
}

export default function BacktestChart({ data }: { data: CurvePoint[] }) {
  return (
    <div className="w-full h-[320px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis
            dataKey="label"
            tick={{ fill: "var(--color-caption)", fontSize: 12 }}
            stroke="var(--color-border)"
          />
          <YAxis
            tick={{ fill: "var(--color-caption)", fontSize: 12 }}
            stroke="var(--color-border)"
            tickFormatter={(v: number) => `${v.toFixed(0)}`}
            label={{
              value: "Indexed (100 = start)",
              angle: -90,
              position: "insideLeft",
              style: { fill: "var(--color-caption)", fontSize: 11 },
            }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              color: "var(--color-ink)",
              fontSize: 12,
            }}
            formatter={(v: number) => v.toFixed(2)}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--color-body)" }} />
          <Line
            type="monotone"
            dataKey="yiq50"
            name="YieldIQ-50 top 5"
            stroke="var(--color-brand)"
            strokeWidth={2.5}
            dot={{ r: 3, fill: "var(--color-brand)" }}
          />
          <Line
            type="monotone"
            dataKey="nifty"
            name="Nifty proxy"
            stroke="var(--color-caption)"
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={{ r: 3, fill: "var(--color-caption)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

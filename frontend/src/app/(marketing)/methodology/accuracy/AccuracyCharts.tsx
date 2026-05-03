"use client"

/**
 * Client-only charts for /methodology/accuracy.
 *
 * Two charts:
 *   1. ReturnAttributionBars — mean 12mo return per verdict band.
 *   2. CalibrationScatter — MoS bucket midpoint vs mean realized return.
 *
 * Kept as a separate client component so the parent page stays an RSC
 * (recharts pulls in DOM-only code).
 *
 * Conventions:
 *   - SEBI vocabulary throughout (below_fair_value / near_fair_value /
 *     above_fair_value). No "undervalued"/"overvalued" anywhere.
 *   - Semantic color tokens via CSS variables (no hardcoded hex);
 *     recharts unfortunately needs explicit fill props so we use
 *     currentColor + className wrappers where possible, plus a small
 *     palette resolved from the chart container.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

const BAND_LABELS: Record<string, string> = {
  below_fair_value: "Below FV",
  near_fair_value: "Near FV",
  above_fair_value: "Above FV",
}

// Semantic-ish palette. Greens/reds carry direction; we deliberately
// use muted tones rather than saturated alarm colours.
const BAND_COLOR: Record<string, string> = {
  below_fair_value: "#16a34a", // green-600 — model expects to rise
  near_fair_value: "#64748b",  // slate-500
  above_fair_value: "#dc2626", // red-600 — model expects to fall
}

export type ReturnAttributionDatum = {
  band: string
  count: number
  mean_return_pct: number | null
  median_return_pct: number | null
}

export type CalibrationBucket = {
  label: string
  mos_midpoint_pct: number
  count: number
  mean_return_pct: number | null
  median_return_pct: number | null
}

// ─────────────────────────────────────────────────────────────────
// 1. Return attribution bars
// ─────────────────────────────────────────────────────────────────
export function ReturnAttributionBars({
  data,
}: {
  data: ReturnAttributionDatum[]
}) {
  const chart = data
    .filter((d) => d.mean_return_pct !== null && d.count > 0)
    .map((d) => ({
      band: BAND_LABELS[d.band] ?? d.band,
      bandKey: d.band,
      mean: d.mean_return_pct ?? 0,
      median: d.median_return_pct ?? 0,
      count: d.count,
    }))

  if (chart.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
        Not enough data yet to compute return attribution.
      </div>
    )
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chart} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="band" tick={{ fontSize: 12 }} />
          <YAxis
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => `${v}%`}
            width={50}
          />
          <ReferenceLine y={0} stroke="#9ca3af" />
          <Tooltip
            formatter={(value: any, name: any) => [
              typeof value === "number" ? `${value.toFixed(1)}%` : String(value),
              name === "mean" ? "Mean 12mo return" : String(name),
            ]}
            labelFormatter={(label, payload) => {
              const n = payload?.[0]?.payload?.count
              return `${label}${n ? `  (n=${n})` : ""}`
            }}
          />
          <Bar dataKey="mean" name="mean">
            {chart.map((d, i) => (
              <Cell key={i} fill={BAND_COLOR[d.bandKey] ?? "#64748b"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// 2. Calibration scatter (MoS bucket midpoint -> mean actual return)
// ─────────────────────────────────────────────────────────────────
export function CalibrationScatter({ data }: { data: CalibrationBucket[] }) {
  const populated = data.filter(
    (d) => d.count > 0 && d.mean_return_pct !== null,
  )
  const chart = populated.map((d) => ({
    x: d.mos_midpoint_pct,
    y: d.mean_return_pct ?? 0,
    label: d.label,
    count: d.count,
  }))

  if (chart.length < 2) {
    return (
      <div className="flex h-56 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
        Need at least 2 populated MoS buckets to plot calibration.
        Currently {chart.length}.
      </div>
    )
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 24, bottom: 36, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[-60, 60]}
            ticks={[-50, -30, -10, 10, 30, 50]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fontSize: 12 }}
          >
            <Label
              value="Margin of safety at T-12mo"
              position="insideBottom"
              offset={-12}
              style={{ fontSize: 12, fill: "#6b7280" }}
            />
          </XAxis>
          <YAxis
            type="number"
            dataKey="y"
            tickFormatter={(v) => `${v}%`}
            tick={{ fontSize: 12 }}
            width={56}
          >
            <Label
              value="Mean realized 12mo return"
              angle={-90}
              position="insideLeft"
              style={{ fontSize: 12, fill: "#6b7280", textAnchor: "middle" }}
            />
          </YAxis>
          <ReferenceLine y={0} stroke="#9ca3af" />
          <ReferenceLine x={0} stroke="#9ca3af" />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            formatter={(value: any, name: any) => {
              if (typeof value !== "number") return [String(value), String(name)]
              if (name === "y") return [`${value.toFixed(1)}%`, "Mean return"]
              if (name === "x") return [`${value.toFixed(0)}%`, "MoS midpoint"]
              return [value, String(name)]
            }}
            labelFormatter={() => ""}
            content={({ payload }) => {
              const p = payload?.[0]?.payload as
                | { label: string; x: number; y: number; count: number }
                | undefined
              if (!p) return null
              return (
                <div className="rounded border border-border bg-background p-2 text-xs shadow-sm">
                  <div className="font-semibold">{p.label}</div>
                  <div>MoS midpoint: {p.x.toFixed(0)}%</div>
                  <div>Mean realized return: {p.y.toFixed(1)}%</div>
                  <div className="text-muted-foreground">n = {p.count}</div>
                </div>
              )
            }}
          />
          <Scatter data={chart} fill="#0f766e" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

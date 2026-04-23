"use client"

import { useEffect } from "react"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts"
import type { SparklinePoint } from "@/components/analysis/Sparkline"

export interface RatioTrendSeriesPoint {
  period_end: string   // ISO, "2024-03-31"
  value: number | null
}

interface Props {
  open: boolean
  onClose: () => void
  title: string
  /** Suffix shown next to the value ("%" | "x" | ""). */
  suffix: string
  /** Number of decimals for tooltip/axis formatting. */
  decimals: number
  /** Oldest → newest. */
  series: RatioTrendSeriesPoint[]
  /** Stroke colour for the line (hex or named alias). */
  color: "green" | "amber" | "red" | "neutral"
  /** Optional "good if above/below" threshold to overlay as a reference line. */
  threshold?: number
}

const COLOR_MAP: Record<string, string> = {
  green: "#16a34a",
  amber: "#d97706",
  red: "#dc2626",
  neutral: "#2563eb",
}

function fmtLabel(iso: string): string {
  // "2024-03-31" → "FY24" when month is March (Indian FY convention), else
  // fall back to "YYYY-MM".
  if (!iso || iso.length < 7) return iso
  const [y, m] = iso.split("-")
  if (m === "03") return `FY${y.slice(2)}`
  return `${y}-${m}`
}

function fmtValue(v: number | null | undefined, suffix: string, decimals: number): string {
  if (v === null || v === undefined || isNaN(v)) return "\u2014"
  return `${v.toFixed(decimals)}${suffix}`
}

export function seriesToSparkline(series: RatioTrendSeriesPoint[]): SparklinePoint[] {
  return series.map(p =>
    p.value === null || p.value === undefined || isNaN(p.value) ? null : p.value,
  )
}

export default function RatioTrendModal({
  open,
  onClose,
  title,
  suffix,
  decimals,
  series,
  color,
  threshold,
}: Props) {
  // ESC to close.
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [open, onClose])

  if (!open) return null

  const data = series.map(p => ({
    label: fmtLabel(p.period_end),
    period_end: p.period_end,
    value: p.value,
  }))
  const stroke = COLOR_MAP[color] ?? COLOR_MAP.neutral
  const numeric = series.map(p => p.value).filter((v): v is number => typeof v === "number")
  const latest = numeric.length > 0 ? numeric[numeric.length - 1] : null
  const min = numeric.length > 0 ? Math.min(...numeric) : null
  const max = numeric.length > 0 ? Math.max(...numeric) : null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ratio-trend-modal-title"
      onClick={onClose}
    >
      <div
        className="bg-surface rounded-2xl border border-border shadow-xl w-full max-w-xl max-h-[90vh] overflow-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between p-5 border-b border-border">
          <div>
            <h3 id="ratio-trend-modal-title" className="text-base font-semibold text-ink">
              {title}
            </h3>
            <p className="text-[11px] text-caption mt-0.5">
              {series.length} annual period{series.length === 1 ? "" : "s"}
              {latest !== null && (
                <> &middot; latest <span className="font-mono tabular-nums">{fmtValue(latest, suffix, decimals)}</span></>
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-caption hover:text-ink transition-colors -mt-1 -mr-1 p-1"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5">
          {series.length < 2 ? (
            <p className="text-sm text-caption py-8 text-center">
              Not enough historical data to plot a trend.
            </p>
          ) : (
            <>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#e5e7eb" strokeDasharray="2 4" vertical={false} />
                    <XAxis
                      dataKey="label"
                      tick={{ fontSize: 11, fill: "#6b7280" }}
                      tickLine={false}
                      axisLine={{ stroke: "#e5e7eb" }}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: "#6b7280" }}
                      tickLine={false}
                      axisLine={false}
                      width={40}
                      tickFormatter={(v: number) => v.toFixed(decimals)}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "#111827",
                        border: "none",
                        borderRadius: 8,
                        fontSize: 12,
                        color: "white",
                      }}
                      labelStyle={{ color: "#9ca3af" }}
                      formatter={(v) =>
                        typeof v === "number" ? fmtValue(v, suffix, decimals) : String(v ?? "\u2014")
                      }
                    />
                    {threshold !== undefined && (
                      <ReferenceLine
                        y={threshold}
                        stroke="#9ca3af"
                        strokeDasharray="3 3"
                        label={{
                          value: `${fmtValue(threshold, suffix, decimals)}`,
                          position: "right",
                          fontSize: 10,
                          fill: "#6b7280",
                        }}
                      />
                    )}
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke={stroke}
                      strokeWidth={2}
                      dot={{ r: 3, fill: stroke }}
                      activeDot={{ r: 5 }}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div className="grid grid-cols-3 gap-3 mt-4 text-xs">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-caption">Min</p>
                  <p className="font-mono tabular-nums text-ink">
                    {fmtValue(min, suffix, decimals)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-caption">Latest</p>
                  <p className="font-mono tabular-nums text-ink">
                    {fmtValue(latest, suffix, decimals)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-caption">Max</p>
                  <p className="font-mono tabular-nums text-ink">
                    {fmtValue(max, suffix, decimals)}
                  </p>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

"use client"

// CompoundedGrowthSparklines — Visual Richness #3 (2026-05-27).
//
// Adds a 4-tile sparkline row above the existing Compounded Growth
// table. Each tile shows the headline CAGR as the big number with a
// minimal trend curve derived from the trailing 3y / 5y / 10y CAGR
// values themselves — no new network calls, no new payload.
//
// The implied-trajectory trick: we already publish CAGR for three
// windows. A compounded series of value 1.0 today implies prior values
// of (1 + cagr)^-n. Plotting those four points (t = -10, -5, -3, 0)
// recovers the curvature of the underlying series without needing the
// raw revenue / profit history — enough to convey "rising fast",
// "flatlining" or "drawdown" at a glance.
//
// Falls back to whichever window is available (10y → 5y → 3y) for
// both the headline number and the sparkline.
//
// SEBI-safe: no advisory language; tiles describe the metric, not
// what action to take.

import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts"
import type { CompoundedGrowthPanel as PanelData } from "@/lib/api"

interface Props {
  panel: PanelData
}

type RowKey = "revenue" | "profit" | "roe_avg" | "stock"

interface TileSpec {
  key: RowKey
  label: string
  // Positive-trend stroke colour. Negative trend always uses the
  // danger token so a drawdown reads the same way across metrics.
  positiveColor: string
}

const TILES: TileSpec[] = [
  { key: "revenue", label: "Revenue", positiveColor: "#2563EB" },
  { key: "profit", label: "Profit", positiveColor: "#2563EB" },
  { key: "roe_avg", label: "ROE (avg)", positiveColor: "#16A34A" },
  { key: "stock", label: "Stock CAGR", positiveColor: "#16A34A" },
]

const NEGATIVE_COLOR = "#DC2626"

interface Headline {
  cagr: number
  windowYears: number
  windowLabel: string
}

function pickHeadline(metric: {
  "3y": number | null
  "5y": number | null
  "10y": number | null
}): Headline | null {
  if (metric["10y"] != null && Number.isFinite(metric["10y"])) {
    return { cagr: metric["10y"]!, windowYears: 10, windowLabel: "10y" }
  }
  if (metric["5y"] != null && Number.isFinite(metric["5y"])) {
    return { cagr: metric["5y"]!, windowYears: 5, windowLabel: "5y" }
  }
  if (metric["3y"] != null && Number.isFinite(metric["3y"])) {
    return { cagr: metric["3y"]!, windowYears: 3, windowLabel: "3y" }
  }
  return null
}

// Build a 4-point implied trajectory from the three CAGR windows. We
// anchor "today" at 1.0 and back-cast to year -3 / -5 / -10 using
// (1 + cagr)^-n. Missing windows are skipped; if only one window is
// available we draw a straight line through the two end-points.
function buildSeries(metric: {
  "3y": number | null
  "5y": number | null
  "10y": number | null
}): { x: number; y: number }[] {
  const points: { x: number; y: number }[] = []
  const ten = metric["10y"]
  const five = metric["5y"]
  const three = metric["3y"]
  if (ten != null && Number.isFinite(ten)) {
    points.push({ x: -10, y: Math.pow(1 + ten / 100, -10) })
  }
  if (five != null && Number.isFinite(five)) {
    points.push({ x: -5, y: Math.pow(1 + five / 100, -5) })
  }
  if (three != null && Number.isFinite(three)) {
    points.push({ x: -3, y: Math.pow(1 + three / 100, -3) })
  }
  points.push({ x: 0, y: 1 })
  // Deduplicate / sort just in case.
  points.sort((a, b) => a.x - b.x)
  return points
}

function formatCagr(value: number): string {
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}%`
}

function Tile({ spec, metric }: { spec: TileSpec; metric: {
  "3y": number | null
  "5y": number | null
  "10y": number | null
  status?: string | null
} | undefined }) {
  const headline = metric ? pickHeadline(metric) : null

  if (!headline) {
    // 2026-06-09 fix/analysis-ux-fixbatch: the stock-CAGR tile carries
    // a `status` field from the backend (cagr_service.py). When the
    // backend signals "rebuild_pending" or "db_unavailable", the
    // generic "Insufficient history" caption is misleading — it reads
    // as "this stock hasn't existed long enough" when the truth is
    // "the adj_close backfill hasn't covered this ticker yet". Show
    // an honest empty-state instead. Other tiles (revenue / profit /
    // roe_avg) keep the original "Insufficient history" copy because
    // those genuinely come from filing history.
    const status = metric?.status
    const isPending = status === "rebuild_pending" || status === "db_unavailable"
    const subLabel = isPending
      ? "Awaiting data backfill"
      : "Insufficient history"
    const tileTitle = isPending
      ? "Stock CAGR is awaiting the daily-prices adj_close backfill for this ticker."
      : undefined
    return (
      <div className="rounded-xl border border-border bg-bg p-3" title={tileTitle}>
        <div className="text-[10px] uppercase tracking-wider text-caption">
          {spec.label}
        </div>
        <div className="mt-1 text-xl font-semibold text-caption font-mono">—</div>
        <div className="mt-2 h-10" aria-hidden />
        <div className="text-[10px] text-caption">{subLabel}</div>
      </div>
    )
  }

  const isPositive = headline.cagr >= 0
  const stroke = isPositive ? spec.positiveColor : NEGATIVE_COLOR
  const arrow = isPositive ? "↗" : "↘"
  const arrowClass = isPositive ? "text-success" : "text-danger"
  const numberClass = isPositive ? "text-ink" : "text-danger"

  const series = buildSeries(metric!)
  // Pad the y-domain a touch so flat series still draw a visible line.
  const ys = series.map((p) => p.y)
  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)
  const pad = (yMax - yMin) * 0.15 || yMax * 0.05 || 0.05

  // First/last dot indices for emphasis.
  const firstIdx = 0
  const lastIdx = series.length - 1

  return (
    <div className="rounded-xl border border-border bg-bg p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-[10px] uppercase tracking-wider text-caption">
          {spec.label}
        </div>
        <div className="text-[10px] text-caption font-mono">
          {headline.windowLabel}
        </div>
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <div className={`text-xl font-semibold font-mono tabular-nums ${numberClass}`}>
          {formatCagr(headline.cagr)}
        </div>
        <div className={`text-sm ${arrowClass}`} aria-hidden>
          {arrow}
        </div>
      </div>
      <div className="mt-1 h-10" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={series}
            margin={{ top: 4, right: 6, bottom: 2, left: 6 }}
          >
            <YAxis hide domain={[yMin - pad, yMax + pad]} />
            <Line
              type="monotone"
              dataKey="y"
              stroke={stroke}
              strokeWidth={1.75}
              isAnimationActive={false}
              dot={(props: { cx?: number; cy?: number; index?: number }) => {
                const { cx, cy, index } = props
                if (cx == null || cy == null) {
                  return <g />
                }
                if (index === firstIdx || index === lastIdx) {
                  return (
                    <circle
                      key={`pt-${index}`}
                      cx={cx}
                      cy={cy}
                      r={2.5}
                      fill={stroke}
                    />
                  )
                }
                return <g key={`pt-${index}`} />
              }}
              activeDot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="text-[10px] text-caption">
        Implied trend over {headline.windowYears}y
      </div>
    </div>
  )
}

export default function CompoundedGrowthSparklines({ panel }: Props) {
  // If every tile would be empty, render nothing — the parent will
  // still show the textual section header.
  const anyValue = TILES.some((t) => {
    const m = panel[t.key]
    return (
      m &&
      ((m["3y"] != null && Number.isFinite(m["3y"])) ||
        (m["5y"] != null && Number.isFinite(m["5y"])) ||
        (m["10y"] != null && Number.isFinite(m["10y"])))
    )
  })
  if (!anyValue) return null

  return (
    <div
      className="grid grid-cols-2 md:grid-cols-4 gap-3"
      aria-label="Compounded growth sparkline tiles"
    >
      {TILES.map((t) => (
        <Tile key={t.key} spec={t} metric={panel[t.key]} />
      ))}
    </div>
  )
}

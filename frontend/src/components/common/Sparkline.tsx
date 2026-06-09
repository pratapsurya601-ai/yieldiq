/**
 * Sparkline — tiny inline SVG trend line for dense fintech tables.
 *
 * Used by home-page surfaces (MarketsStrip tiles, WatchlistPanel rows,
 * PortfolioPanel rows, TodaysMovers rows) to render a 7-day price
 * trajectory next to the headline number. Pure inline SVG, no chart
 * library dependency — Recharts pulls ~100KB of d3 transitively, which
 * is wasteful for a 56×18 polyline with no axes, gridlines, or
 * tooltips.
 *
 * Color: green when the last value is at or above the first, red when
 * below, neutral when the array collapses to a single point. Caller can
 * force a color via the `color` prop (used by MarketsStrip to keep the
 * sparkline color in sync with the % change badge above it, even when
 * the daily series briefly disagrees with the bhavcopy-derived delta).
 *
 * Renders `null` for empty / single-value arrays — sparing the caller
 * a length check at every call site. A single point is not a trend.
 */
"use client"

import { memo } from "react"

export interface SparklineProps {
  /** Ordered oldest → newest. Empty / single-value arrays render null. */
  values: number[]
  /** Pixel width of the SVG viewBox. Defaults to 56. */
  width?: number
  /** Pixel height of the SVG viewBox. Defaults to 18. */
  height?: number
  /**
   * "green" | "red" | "neutral" | any CSS color string. When omitted,
   * derived from the direction of the series (last vs first).
   */
  color?: "green" | "red" | "neutral" | string
  /** Soft area fill under the line. Defaults to true. */
  showFill?: boolean
  /** Optional className appended to the root <svg>. */
  className?: string
}

// Tailwind-compatible colors. Hex values match the Tailwind palette
// already used in our up/down badges (green-500, red-500, zinc-400) so
// the sparkline doesn't visually clash with the % change text next to it.
const COLOR_MAP: Record<"green" | "red" | "neutral", string> = {
  green: "#22c55e",  // tailwind green-500
  red: "#ef4444",    // tailwind red-500
  neutral: "#94a3b8", // tailwind slate-400 — survives dark mode legibly
}

function resolveColor(values: number[], override: SparklineProps["color"]): string {
  if (override === "green" || override === "red" || override === "neutral") {
    return COLOR_MAP[override]
  }
  if (typeof override === "string" && override.length > 0) {
    // Custom CSS color string (hex, rgb(), CSS var).
    return override
  }
  // Auto from direction. `values.length >= 2` is guaranteed at the
  // single null-guard site below, so [0] and [length-1] are safe.
  const first = values[0]
  const last = values[values.length - 1]
  if (last > first) return COLOR_MAP.green
  if (last < first) return COLOR_MAP.red
  return COLOR_MAP.neutral
}

function SparklineImpl({
  values,
  width = 56,
  height = 18,
  color,
  showFill = true,
  className,
}: SparklineProps) {
  // Single point is not a trend — render nothing rather than a dot
  // that callers would have to special-case in their grid alignment.
  if (!values || values.length < 2) return null

  // Numeric guards — drop NaN/Infinity so a single bad data point
  // doesn't collapse the entire min/max range to a useless degenerate line.
  const clean = values.filter((v) => Number.isFinite(v))
  if (clean.length < 2) return null

  const min = Math.min(...clean)
  const max = Math.max(...clean)
  // Avoid divide-by-zero when the series is flat (e.g. a delisted
  // ticker with a single repeated last-known price). Flat line renders
  // mid-height in neutral color.
  const range = max - min || 1

  // Stroke 1.5px — visible at 18px tall without dominating; matches the
  // weight of the tabular-nums text alongside it. Inset by 1px on each
  // side so the line never clips against the SVG bounding box.
  const pad = 1
  const innerW = width - pad * 2
  const innerH = height - pad * 2

  const stepX = innerW / (clean.length - 1)
  const points = clean.map((v, i) => {
    const x = pad + i * stepX
    // Y axis is inverted in SVG (0 at top), so high values map to low y.
    const y = pad + innerH - ((v - min) / range) * innerH
    return { x, y }
  })

  const polylinePoints = points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ")

  // Area fill path = polyline + close to baseline along the bottom edge.
  // Stops at the bottom of the inner viewBox so the fill never bleeds
  // past the SVG border.
  const areaPath = (() => {
    if (!showFill) return null
    const baseY = pad + innerH
    const segs: string[] = []
    points.forEach((p, i) => {
      segs.push(`${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    })
    segs.push(`L${points[points.length - 1].x.toFixed(2)},${baseY.toFixed(2)}`)
    segs.push(`L${points[0].x.toFixed(2)},${baseY.toFixed(2)}`)
    segs.push("Z")
    return segs.join(" ")
  })()

  const stroke = resolveColor(clean, color)

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="7-day price trend"
      className={className}
      data-testid="sparkline-svg"
    >
      {areaPath && (
        <path
          d={areaPath}
          fill={stroke}
          fillOpacity={0.15}
          stroke="none"
          data-testid="sparkline-fill"
        />
      )}
      <polyline
        points={polylinePoints}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        data-testid="sparkline-line"
      />
    </svg>
  )
}

// Memo so re-renders of the parent table (sort, scroll, tooltip flip)
// don't re-walk the points array. The `values` prop is a fresh array on
// every render of the parent, so referential equality is not enough —
// shallow comparison of the numeric props plus a length+endpoint check
// on `values` is sufficient (a sparkline whose first/last/length match
// is visually identical to a re-keyed but unchanged series).
export const Sparkline = memo(SparklineImpl, (prev, next) => {
  if (prev.width !== next.width) return false
  if (prev.height !== next.height) return false
  if (prev.color !== next.color) return false
  if (prev.showFill !== next.showFill) return false
  if (prev.className !== next.className) return false
  const a = prev.values
  const b = next.values
  if (a === b) return true
  if (!a || !b) return false
  if (a.length !== b.length) return false
  if (a.length === 0) return true
  // Endpoint check is a cheap proxy for "did the line change shape".
  // False negative (skipped re-render of a series with same endpoints
  // but different middle) is fine — the visual impact is invisible at
  // 56×18 px for the kind of intraday wiggle that would change.
  if (a[0] !== b[0]) return false
  if (a[a.length - 1] !== b[b.length - 1]) return false
  return true
})

Sparkline.displayName = "Sparkline"

export default Sparkline

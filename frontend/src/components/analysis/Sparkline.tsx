"use client"

/**
 * Inline sparkline for ratio cards. Custom SVG — intentionally no chart lib
 * dependency for a 10-pt line. Accepts (number | null)[] where nulls become
 * line discontinuities so missing periods never render as a fake "0".
 *
 * Behavioural rules (per spec):
 *   - Auto-scale to the data range (min-max normalisation).
 *   - Gaps on null values — polyline breaks, not interpolated.
 *   - Latest-5-year recent direction → ↗ / → / ↘ arrow (hidden when <2 pts).
 *   - Sparkline hidden entirely (returns null) when fewer than 2 numeric pts.
 */

export type SparklinePoint = number | null

interface Props {
  points: SparklinePoint[]
  /** Stroke color — "green" | "amber" | "red" | "neutral" or any CSS color. */
  color?: "green" | "amber" | "red" | "neutral" | string
  /** Rendered pixel height. Width is always 100% of container. */
  height?: number
  /** Hide the directional arrow. */
  hideArrow?: boolean
  /** Accessible label for the SVG. */
  ariaLabel?: string
}

const COLOR_MAP: Record<string, string> = {
  green: "#16a34a",
  amber: "#d97706",
  red: "#dc2626",
  neutral: "#6b7280",
}

function resolveColor(c: Props["color"]): string {
  if (!c) return COLOR_MAP.neutral
  return COLOR_MAP[c] ?? c
}

/** Recent-5-year direction (or full window if fewer points). */
export function trendDirection(points: SparklinePoint[]): "up" | "flat" | "down" | null {
  const numeric = points.filter((p): p is number => typeof p === "number" && !isNaN(p))
  if (numeric.length < 2) return null
  const recent = numeric.slice(-5)
  const first = recent[0]
  const last = recent[recent.length - 1]
  if (first === 0) {
    // Avoid divide-by-zero; fall back to absolute compare.
    if (last > first) return "up"
    if (last < first) return "down"
    return "flat"
  }
  const pctChange = (last - first) / Math.abs(first)
  if (pctChange > 0.03) return "up"
  if (pctChange < -0.03) return "down"
  return "flat"
}

export function TrendArrow({ direction }: { direction: "up" | "flat" | "down" | null }) {
  if (direction === null) return null
  const symbol = direction === "up" ? "\u2197" : direction === "down" ? "\u2198" : "\u2192"
  const cls =
    direction === "up" ? "text-green-600"
    : direction === "down" ? "text-red-600"
    : "text-caption"
  return (
    <span
      className={`text-[11px] font-mono leading-none ${cls}`}
      aria-label={`trend ${direction}`}
    >
      {symbol}
    </span>
  )
}

export default function Sparkline({
  points,
  color = "neutral",
  height = 40,
  hideArrow = false,
  ariaLabel,
}: Props) {
  // Count numeric points first — <2 means we have nothing to draw.
  let numericCount = 0
  for (const p of points) {
    if (typeof p === "number" && !isNaN(p)) numericCount++
  }
  if (numericCount < 2) return null

  const W = 100
  const H = 30 // viewBox height; CSS `height` prop controls final pixels.

  // Min/max over numeric-only
  let min = Infinity
  let max = -Infinity
  for (const p of points) {
    if (typeof p === "number" && !isNaN(p)) {
      if (p < min) min = p
      if (p > max) max = p
    }
  }
  const range = max - min || 1

  const n = points.length
  // Build segment paths — null values break the line.
  const segments: string[] = []
  let current: string[] = []
  points.forEach((p, i) => {
    if (typeof p === "number" && !isNaN(p)) {
      const x = n === 1 ? W / 2 : (i / (n - 1)) * W
      const y = H - ((p - min) / range) * H
      current.push(`${x.toFixed(2)},${y.toFixed(2)}`)
    } else if (current.length > 0) {
      segments.push(current.join(" "))
      current = []
    }
  })
  if (current.length > 0) segments.push(current.join(" "))

  const stroke = resolveColor(color)
  const direction = trendDirection(points)

  // Find the last numeric point for the end-cap dot.
  let lastCoord: [number, number] | null = null
  for (let i = points.length - 1; i >= 0; i--) {
    const p = points[i]
    if (typeof p === "number" && !isNaN(p)) {
      const x = n === 1 ? W / 2 : (i / (n - 1)) * W
      const y = H - ((p - min) / range) * H
      lastCoord = [x, y]
      break
    }
  }

  return (
    <div className="flex items-center gap-1 w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="flex-1 block"
        style={{ height }}
        preserveAspectRatio="none"
        role={ariaLabel ? "img" : undefined}
        aria-label={ariaLabel}
        aria-hidden={ariaLabel ? undefined : true}
      >
        {segments.map((seg, idx) => (
          <polyline
            key={idx}
            fill="none"
            stroke={stroke}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={seg}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {lastCoord && (
          <circle cx={lastCoord[0]} cy={lastCoord[1]} r="1.8" fill={stroke} />
        )}
      </svg>
      {!hideArrow && <TrendArrow direction={direction} />}
    </div>
  )
}

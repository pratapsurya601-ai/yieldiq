"use client"

// MetricWithContext — Phase-3 (2026-05-25), Design Manifesto rule 2.
// Wraps a single metric value with an inline 120×14 px comparison
// slider showing where it sits vs the peer median (and optionally
// vs the company's own 5-year average).
//
// Backend feeds this via AnalysisResponse.peer_context — see
// backend/services/analysis/peer_context.py. When percentile data is
// thin (n < 3 peers) the slider falls back to a naked value display.

import { useEffect, useMemo, useRef, useState } from "react"
import { cn } from "@/lib/utils"

export interface MetricWithContextProps {
  /** Short label, e.g. "ROE", "PE". */
  label: string
  /** The company's own value for this metric. */
  value: number | null | undefined
  /** Formatter, e.g. (n) => `${n.toFixed(1)}%`. */
  format: (n: number) => string
  /** Peer median; null disables the slider entirely. */
  peerMedian: number | null | undefined
  /** 5th and 95th percentile of peer values — used to scale the slider track. */
  peerP5?: number | null
  peerP95?: number | null
  /** Own historical average (e.g. 5y). Shown as small tick on the slider. */
  historicalAvg?: number | null
  /** "Higher is better" or "Lower is better" — controls only the tooltip copy. */
  direction?: "higher_is_better" | "lower_is_better"
  className?: string
}

// Slider geometry.
const W = 120
const H = 14
const PAD_X = 4         // breathing room so the marker doesn't clip
const TRACK_Y = H / 2

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

export default function MetricWithContext({
  label,
  value,
  format,
  peerMedian,
  peerP5,
  peerP95,
  historicalAvg,
  direction,
  className,
}: MetricWithContextProps) {
  const [hovered, setHovered] = useState(false)
  // Flip the tooltip ABOVE the row when there isn't enough room below
  // (mobile audit issue #7 — KPI tiles near the viewport bottom would
  // render the tooltip off-screen on small viewports).
  const [flipUp, setFlipUp] = useState(false)
  const rowRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!hovered) return
    const row = rowRef.current
    if (!row) return
    const rect = row.getBoundingClientRect()
    // Single-line tooltip; conservative height includes padding +
    // wrap on narrow phones.
    const TOOLTIP_HEIGHT = 40
    const COLLISION_PAD = 12
    const viewportH =
      typeof window !== "undefined" ? window.innerHeight : 768
    const spaceBelow = viewportH - rect.bottom - COLLISION_PAD
    const spaceAbove = rect.top - COLLISION_PAD
    setFlipUp(spaceBelow < TOOLTIP_HEIGHT && spaceAbove > spaceBelow)
  }, [hovered])

  // Derive the slider range. If P5/P95 aren't supplied, pad the median
  // by ±60% so the marker still moves visibly.
  const range = useMemo(() => {
    if (peerMedian == null) return null
    let lo = peerP5 ?? peerMedian * 0.4
    let hi = peerP95 ?? peerMedian * 1.6
    if (value != null) {
      // Make sure the marker is always visible — extend the range to
      // include it with a 5% pad.
      const span = Math.max(hi - lo, Math.abs(peerMedian) * 0.5, 0.1)
      const pad = span * 0.05
      lo = Math.min(lo, value - pad)
      hi = Math.max(hi, value + pad)
    }
    if (hi <= lo) hi = lo + 1
    return { lo, hi }
  }, [peerMedian, peerP5, peerP95, value])

  // No value AND no median → just render an em-dash row.
  if (value == null && peerMedian == null) {
    return (
      <div className={cn("flex items-baseline justify-between gap-3 text-sm", className)}>
        <span className="text-caption">{label}</span>
        <span className="text-caption tabular-nums">—</span>
      </div>
    )
  }

  // Have a value but no peer context → render naked value.
  if (peerMedian == null || range == null) {
    return (
      <div className={cn("flex items-baseline justify-between gap-3 text-sm", className)}>
        <span className="text-caption">{label}</span>
        <span className="font-bold tabular-nums text-ink">
          {value == null ? "—" : format(value)}
        </span>
      </div>
    )
  }

  const toX = (v: number): number => {
    const t = (v - range.lo) / (range.hi - range.lo)
    return PAD_X + clamp(t, 0, 1) * (W - 2 * PAD_X)
  }

  const valueX = value == null ? null : toX(value)
  const medianX = toX(peerMedian)
  const histX = historicalAvg == null ? null : toX(historicalAvg)

  // Filled bar runs from track start to the value position (always
  // forward — purely visual). Skip when no value.
  const barW = valueX == null ? 0 : Math.max(0, valueX - PAD_X)

  const tooltipParts: string[] = []
  if (value != null) tooltipParts.push(`Your value: ${format(value)}`)
  tooltipParts.push(`Sector median: ${format(peerMedian)}`)
  if (historicalAvg != null)
    tooltipParts.push(`Your 5y avg: ${format(historicalAvg)}`)
  const tooltip = tooltipParts.join(" · ")

  // Tone of the value marker vs median (purely visual cue).
  let tone: "good" | "neutral" | "bad" = "neutral"
  if (value != null) {
    const delta = value - peerMedian
    const sig = Math.abs(delta) > Math.abs(peerMedian) * 0.05
    if (sig) {
      if (direction === "lower_is_better") {
        tone = delta < 0 ? "good" : "bad"
      } else if (direction === "higher_is_better") {
        tone = delta > 0 ? "good" : "bad"
      }
    }
  }
  const markerFill =
    tone === "good"   ? "fill-emerald-600" :
    tone === "bad"    ? "fill-orange-600"  :
    "fill-ink"
  const barFill =
    tone === "good"   ? "fill-emerald-200" :
    tone === "bad"    ? "fill-orange-200"  :
    "fill-border"

  return (
    <div
      ref={rowRef}
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 text-sm group relative",
        className,
      )}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      tabIndex={0}
      aria-label={`${label}: ${tooltip}`}
    >
      <span className="text-caption shrink-0 w-16">{label}</span>
      <span className="font-bold font-mono tabular-nums text-ink shrink-0 w-16">
        {value == null ? "—" : format(value)}
      </span>
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="shrink-0"
        aria-hidden
      >
        {/* Track */}
        <rect
          x={PAD_X}
          y={TRACK_Y - 1.5}
          width={W - 2 * PAD_X}
          height={3}
          rx={1.5}
          className="fill-border"
        />
        {/* Filled bar from start to value */}
        {valueX != null && (
          <rect
            x={PAD_X}
            y={TRACK_Y - 1.5}
            width={barW}
            height={3}
            rx={1.5}
            className={barFill}
          />
        )}
        {/* Historical avg tick (smaller) */}
        {histX != null && (
          <line
            x1={histX} x2={histX}
            y1={TRACK_Y - 4} y2={TRACK_Y + 4}
            strokeWidth={1}
            className="stroke-caption"
          />
        )}
        {/* Peer median tick (taller) */}
        <line
          x1={medianX} x2={medianX}
          y1={TRACK_Y - 6} y2={TRACK_Y + 6}
          strokeWidth={1.5}
          className="stroke-ink"
        />
        {/* Value marker */}
        {valueX != null && (
          <circle
            cx={valueX}
            cy={TRACK_Y}
            r={4}
            className={markerFill}
          />
        )}
      </svg>
      <span className="text-[11px] text-caption">
        sector median {format(peerMedian)}
      </span>

      {/* Hover tooltip — flips ABOVE the row when the viewport bottom
          is too close (mobile audit issue #7). */}
      {hovered && (
        <div
          role="tooltip"
          data-flip={flipUp ? "up" : "down"}
          className={cn(
            "absolute left-0 z-10 bg-ink text-bg text-[11px] px-2 py-1",
            "rounded shadow whitespace-nowrap",
            flipUp ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          {tooltip}
        </div>
      )}
    </div>
  )
}

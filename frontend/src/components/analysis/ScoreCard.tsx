"use client"

/**
 * ScoreCard — the dark right-column of the editorial hero.
 *
 *   YIELDIQ SCORE
 *   58          B (pill)
 *   /100
 *   (sparkline, 12M)
 *   Sector rank: 8 / 47     ▓▓▓▓▓▓▓░░
 *   REFRACTION 2.3          higher = more opinionated
 *   Market cap: ₹1.24 Lakh Cr
 *
 * Uses design tokens so it auto-inverts in dark mode. The card background
 * is `bg-ink` (ink-on-bg contrast) which gives us a near-black surface in
 * light mode and a near-white surface in dark mode — in both cases the
 * body text is the opposite (`text-bg`) so contrast works.
 */

import { useId } from "react"
import { formatMarketCap } from "@/lib/formatters"

interface SectorRank {
  rank: number
  total: number
}

interface ScoreCardProps {
  score100: number
  grade: string
  /** 12 monthly score points — oldest first. Length ≤ 12 tolerated. */
  trend12m?: number[]
  sectorRank?: SectorRank | null
  /** 0..5 dispersion metric from the Prism payload. */
  refractionIndex: number
  /** Market cap in crores (INR). */
  marketCapCr?: number | null
}

function gradeGradient(grade: string): string {
  // Stop colors drive the small grade pill. "A" tier = success, "B" = warning,
  // "C"/"D"/"F" = danger. Slight gradient keeps it feeling premium vs flat.
  const g = grade.toUpperCase()
  if (g.startsWith("A")) {
    return "linear-gradient(135deg, var(--color-success), color-mix(in oklab, var(--color-success) 70%, var(--color-warning)))"
  }
  if (g.startsWith("B")) {
    return "linear-gradient(135deg, color-mix(in oklab, var(--color-success) 50%, var(--color-warning)), var(--color-warning))"
  }
  return "linear-gradient(135deg, var(--color-warning), var(--color-danger))"
}

// Canonical market-cap formatter lives in `@/lib/formatters`. We delegate
// here so the tokenised "Lakh Cr" copy stays consistent across the app.
const fmtMarketCap = formatMarketCap

/** Tiny inline sparkline, 100×24. Last point gets a dot. */
function Sparkline({ points }: { points: number[] }) {
  const uid = useId()
  if (!points || points.length < 2) {
    return (
      <svg width={100} height={24} aria-hidden>
        <line
          x1={0}
          y1={12}
          x2={100}
          y2={12}
          stroke="currentColor"
          strokeOpacity={0.25}
          strokeDasharray="2 3"
        />
      </svg>
    )
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const stepX = 100 / (points.length - 1)
  const coords = points.map((p, i) => {
    const x = i * stepX
    const y = 22 - ((p - min) / span) * 20
    return [x, y] as const
  })
  const path = coords
    .map(([x, y], i) => (i === 0 ? `M${x.toFixed(2)},${y.toFixed(2)}` : `L${x.toFixed(2)},${y.toFixed(2)}`))
    .join(" ")
  const [lx, ly] = coords[coords.length - 1]
  return (
    <svg width={100} height={24} aria-label="12-month score trend" role="img">
      <defs>
        <linearGradient id={`spark-${uid}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="currentColor" stopOpacity={0.4} />
          <stop offset="100%" stopColor="currentColor" stopOpacity={1} />
        </linearGradient>
      </defs>
      <path d={path} fill="none" stroke={`url(#spark-${uid})`} strokeWidth={1.5} strokeLinecap="round" />
      <circle cx={lx} cy={ly} r={2.2} fill="currentColor" />
    </svg>
  )
}

export default function ScoreCard({
  score100,
  grade,
  trend12m,
  sectorRank,
  refractionIndex,
  marketCapCr,
}: ScoreCardProps) {
  const rankPct = sectorRank
    ? Math.max(0, Math.min(1, 1 - (sectorRank.rank - 1) / Math.max(1, sectorRank.total - 1)))
    : 0

  return (
    <aside
      className="rounded-2xl bg-ink text-bg p-5 flex flex-col gap-4 h-full"
      aria-label="YieldIQ score summary"
    >
      {/* Header label */}
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-caption">
        YieldIQ Score
      </p>

      {/* Score + grade pill */}
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-1">
          <span
            className="font-editorial text-5xl leading-none font-semibold text-bg tabular-nums"
            style={{ fontVariationSettings: "'opsz' 72" }}
          >
            {score100}
          </span>
          <span className="text-sm text-caption tabular-nums">/100</span>
        </div>
        <span
          className="inline-flex items-center justify-center min-w-[42px] h-[28px] rounded-md px-2 text-sm font-bold text-white tracking-wide"
          style={{ background: gradeGradient(grade) }}
          aria-label={`Grade ${grade}`}
        >
          {grade || "—"}
        </span>
      </div>

      {/* 12M trend sparkline */}
      <div className="flex items-center justify-between text-caption">
        <span className="text-[10px] uppercase tracking-[0.15em]">12M trend</span>
        <span className="text-bg">
          <Sparkline points={trend12m ?? []} />
        </span>
      </div>

      {/* Sector rank */}
      {sectorRank && sectorRank.total > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-caption uppercase tracking-[0.15em]">Sector rank</span>
            <span className="tabular-nums text-bg font-semibold">
              {sectorRank.rank} / {sectorRank.total}
            </span>
          </div>
          <div
            className="h-1 w-full rounded-full bg-bg/15 overflow-hidden"
            role="progressbar"
            aria-valuenow={sectorRank.rank}
            aria-valuemin={1}
            aria-valuemax={sectorRank.total}
          >
            <div
              className="h-full bg-bg"
              style={{ width: `${(rankPct * 100).toFixed(1)}%` }}
            />
          </div>
        </div>
      )}

      {/* Refraction Index — signature YieldIQ metric */}
      <div className="space-y-0.5">
        <div className="flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-[0.18em] text-caption">
            Refraction
          </span>
          <span className="font-editorial text-xl tabular-nums text-bg">
            {refractionIndex.toFixed(1)}
          </span>
        </div>
        <p className="text-[10px] text-caption leading-tight">
          Higher = pillars disagree more. The stock refracts light more sharply.
        </p>
      </div>

      {/* Market cap footer */}
      {marketCapCr && marketCapCr > 0 && (
        <div className="mt-auto pt-2 border-t border-bg/10 flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-[0.15em] text-caption">Market cap</span>
          <span className="tabular-nums text-sm text-bg">{fmtMarketCap(marketCapCr)}</span>
        </div>
      )}
    </aside>
  )
}

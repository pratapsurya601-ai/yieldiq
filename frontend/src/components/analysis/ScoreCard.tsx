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
import MetricTooltip from "@/components/analysis/MetricTooltip"

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
  /**
   * fix/data-quality-gate (2026-04-27): backend-authored structured
   * red flags. Used purely as a presentation-layer cap on the grade
   * pill — when financial-distress signals are present the displayed
   * grade is clamped to "B" so the hero cannot show "Grade A" while
   * RedFlagInsights below lists "Consecutive Losses" / declining
   * revenue / debt spike / negative equity. Underlying score100 is
   * untouched; this is a label-only correction so the page stops
   * lying about itself while the score formula is retuned.
   */
  redFlags?: Array<{ flag: string; severity?: string }>
}

// Flags that are unambiguous financial-distress signals. Any one of
// them present in the structured red-flag list is sufficient to clamp
// the displayed grade. Ids mirror the canonical `flag=` strings emitted
// by `backend/services/analysis/utils.py::_add_flags` —
//   loss_making        → "Consecutive Losses" (≥2y net losses)
//   negative_equity    → liabilities exceed assets (going-concern proxy)
//   declining_revenue  → revenue down 3 consecutive years
//   high_debt          → debt spike / over-leveraged balance sheet
const DISTRESS_FLAGS: ReadonlySet<string> = new Set([
  "loss_making",
  "negative_equity",
  "declining_revenue",
  "high_debt",
])

function hasDistressFlag(
  flags: ReadonlyArray<{ flag: string; severity?: string }> | undefined,
): boolean {
  if (!flags || flags.length === 0) return false
  return flags.some(f => DISTRESS_FLAGS.has(f.flag))
}

/** Presentation-layer grade cap. Clamps "A" / "A+" / "A-" → "B" when
 *  any financial-distress flag is present. Never raises a grade. */
function capGrade(grade: string, distress: boolean): string {
  if (!distress) return grade
  const g = (grade || "").toUpperCase()
  if (g.startsWith("A")) return "B"
  return grade
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

/** Filters a candidate trend series down to its usable numeric subset.
 *  Defence-in-depth against payloads where prism.ts's adapter wasn't run
 *  (e.g. a future caller bypassing `adaptPrismResponse` and handing us
 *  the raw API array). Drops `null`/`undefined`/`NaN`/`Infinity` so the
 *  hide-when-empty gate downstream can rely on the cleaned length. */
function usableTrend(points: number[] | null | undefined): number[] {
  if (!Array.isArray(points)) return []
  return points.filter(
    (n): n is number => typeof n === "number" && Number.isFinite(n),
  )
}

/** A series is "renderable" only if we have ≥2 finite points AND at least
 *  some variance — a flat all-identical series (commonly all-zeros from a
 *  backfill cron that hasn't populated real scores yet) draws a 1px line
 *  at the SVG baseline which, against the dark `bg-ink` surface with the
 *  `text-bg` stroke matching the background contrast, can render as
 *  visually empty content next to the "12M TREND" label. Task #190
 *  follow-up: gate on usable variance, not just length. */
function hasRenderableTrend(points: number[] | null | undefined): boolean {
  const clean = usableTrend(points)
  if (clean.length < 2) return false
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  return max - min > 0
}

/** Tiny inline sparkline, 100×24. Last point gets a dot. Returns null
 *  for < 2 points — callers are expected to gate the surrounding chip
 *  on `hasRenderableTrend` so the "12M trend" label doesn't render against
 *  an empty value. Earlier this rendered an italic "Insufficient history"
 *  caption, but on the dark `bg-ink` card the low-contrast caption
 *  colour made it look like an empty chip (task #190). */
function Sparkline({ points }: { points: number[] }) {
  const uid = useId()
  if (!points || points.length < 2) return null
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
  redFlags,
}: ScoreCardProps) {
  const rankPct = sectorRank
    ? Math.max(0, Math.min(1, 1 - (sectorRank.rank - 1) / Math.max(1, sectorRank.total - 1)))
    : 0

  const distress = hasDistressFlag(redFlags)
  const displayGrade = capGrade(grade, distress)
  const gradeAriaLabel = distress && displayGrade !== grade
    ? `Grade ${displayGrade} (capped from ${grade} due to financial-distress flags)`
    : `Grade ${displayGrade}`

  return (
    <aside
      className="rounded-2xl bg-ink text-bg p-5 flex flex-col gap-4 h-full"
      aria-label="YieldIQ score summary"
    >
      {/* Header label */}
      <MetricTooltip metricKey="yieldiq_score">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-caption">
          YieldIQ Score
        </p>
      </MetricTooltip>

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
        <MetricTooltip metricKey="grade">
          <span
            className="inline-flex items-center justify-center min-w-[42px] h-[28px] rounded-md px-2 text-sm font-bold text-white tracking-wide"
            style={{ background: gradeGradient(displayGrade) }}
            aria-label={gradeAriaLabel}
            title={
              distress && displayGrade !== grade
                ? `Capped from ${grade} — financial-distress flags present`
                : undefined
            }
          >
            {displayGrade || "—"}
          </span>
        </MetricTooltip>
      </div>

      {/* 12M trend sparkline — hidden entirely when we don't have at
          least 2 monthly buckets of score history WITH variance. Avoids a
          labelled chip with empty content (task #190 + P0 follow-up:
          "12M TREND" label was still rendering next to invisible content
          on HDFCBANK because a flat all-equal series cleared the prior
          length-only gate but the resulting baseline-only sparkline was
          visually empty against the dark `bg-ink` surface). When a
          backfill cron accumulates ≥2 monthly samples with real movement
          in fair_value_history, the chip reappears automatically. */}
      {hasRenderableTrend(trend12m) && (
        <div className="flex items-center justify-between text-caption">
          <span className="text-[10px] uppercase tracking-[0.15em]">12M trend</span>
          <span className="text-bg">
            <Sparkline points={usableTrend(trend12m)} />
          </span>
        </div>
      )}

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

      {/* Refraction Index — temporarily hidden from the user-facing
          Score card. Audit found the value sits flat at 0.3–0.4 across
          every stock, so it has no discriminating power and just adds
          chrome. Kept in the payload (`refractionIndex` prop) for
          internal use until we make it actually informative.
          TODO(yieldiq-ux): restore once Refraction has been recalibrated
          to spread across its 0–1 range. Tracking issue: fix-refraction-flatness. */}
      {false && (
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
            How much the underlying signals disagree. Low = consistent picture; high = mixed.
          </p>
        </div>
      )}

      {/* Market cap footer */}
      {marketCapCr && marketCapCr > 0 && (
        <div className="mt-auto pt-2 border-t border-bg/10 flex items-baseline justify-between">
          <MetricTooltip metricKey="market_cap">
            <span className="text-[10px] uppercase tracking-[0.15em] text-caption">Market cap</span>
          </MetricTooltip>
          <span className="tabular-nums text-sm text-bg">{fmtMarketCap(marketCapCr)}</span>
        </div>
      )}
    </aside>
  )
}

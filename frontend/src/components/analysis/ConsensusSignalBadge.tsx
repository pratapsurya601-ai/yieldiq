"use client"

/**
 * ConsensusSignalBadge
 * --------------------
 * Renders the cross-engine consensus signal produced by the backend
 * `cross_engine_consensus` field (see
 * backend/services/consensus_signal_service.py and the
 * `_inject_consensus_signal_*` helpers in
 * backend/routers/analysis.py).
 *
 * The signal answers a different question from the Composite IV
 * card and the Estimator Clustering card: HOW MANY of the seven
 * standalone estimators (DCF / Multiples / Wall Street /
 * Three-stage / DDM / EPV / Probability-weighted) point in the
 * SAME DIRECTION vs the live price. When N of M agree, that is a
 * stronger directional read than any individual estimator and a
 * distinct surface from the weighted-magnitude composite.
 *
 * Rendering rules
 * ---------------
 * - When `signal` is null/undefined OR no estimators were
 *   available, the component renders nothing — legacy cached
 *   payloads pre-dating this PR surface as no badge.
 * - The headline string is taken verbatim from the backend so the
 *   wire stays the single source of truth for the descriptive
 *   text. The frontend only owns colors and layout.
 * - SEBI vocab posture mirrors the backend service: descriptive
 *   level / direction language only; no advisory verbs.
 * - The estimator breakdown is collapsible — collapsed by default
 *   to keep the badge compact near the verdict; expanded reveals
 *   per-estimator direction chips.
 *
 * Mount point
 * -----------
 * Near the hero / verdict on the analysis page. See
 * AnalysisBody.tsx for the mount call. The badge is intentionally
 * full-width so it reads as a "look here" surface rather than a
 * footnote.
 */

import { useState, type ReactElement } from "react"
import { cn } from "@/lib/utils"


// ─────────────────────────────────────────────────────────────────
// Types — mirror backend/services/consensus_signal_service.py
// ─────────────────────────────────────────────────────────────────
export type ConsensusLevel =
  | "very_high"
  | "high"
  | "moderate"
  | "low"
  | "dispersed"

export type ConsensusDirection =
  | "above_price"
  | "below_price"
  | "near_price"
  | "split"

export interface EstimatorBreakdownItem {
  name: string
  slot: string
  value: number
  direction: Exclude<ConsensusDirection, "split">
}

export interface ConsensusSignal {
  direction_agreement_count: number
  total_estimators: number
  direction_agreement_pct: number
  magnitude_clustering_cv: number | null
  consensus_level: ConsensusLevel
  consensus_direction: ConsensusDirection | null
  headline: string
  sanity_warnings: string[]
  estimator_breakdown: EstimatorBreakdownItem[]
}


// ─────────────────────────────────────────────────────────────────
// Display helpers
// ─────────────────────────────────────────────────────────────────

/**
 * Tone — color band keyed by (level, direction).
 *
 * The four tones map to the design-system tokens already used by
 * the hero / verdict surfaces so the badge sits visually next to
 * them without inventing new colors:
 *
 *   - positive : high-conviction agreement that estimators sit
 *                above price (valuation gap below price).
 *   - negative : high-conviction agreement that estimators sit
 *                below price (valuation gap above price).
 *   - neutral  : high-conviction agreement near price OR a
 *                moderate result that doesn't lean either way.
 *   - muted    : dispersed / split / no data — descriptive only.
 */
type Tone = "positive" | "negative" | "neutral" | "muted"

function toneFor(
  level: ConsensusLevel,
  direction: ConsensusDirection | null,
): Tone {
  if (level === "dispersed" || direction === null || direction === "split") {
    return "muted"
  }
  // Very-high + high are the conviction tiers. Moderate is honest
  // but not a conviction read — surface neutral so the badge
  // does not over-signal on a near-price tie.
  const isConviction = level === "very_high" || level === "high"
  if (!isConviction) return "neutral"
  if (direction === "above_price") return "positive"
  if (direction === "below_price") return "negative"
  return "neutral" // near_price + conviction tier
}

const TONE_CLASSES: Record<Tone, { wrap: string; pill: string; label: string }> = {
  positive: {
    wrap: "border-[color:var(--color-success)]/40 bg-[color:var(--color-success)]/10",
    pill: "bg-[color:var(--color-success)] text-white",
    label: "text-[color:var(--color-success)]",
  },
  negative: {
    wrap: "border-[color:var(--color-danger)]/40 bg-[color:var(--color-danger)]/10",
    pill: "bg-[color:var(--color-danger)] text-white",
    label: "text-[color:var(--color-danger)]",
  },
  neutral: {
    wrap: "border-[color:var(--color-warning)]/40 bg-[color:var(--color-warning)]/10",
    pill: "bg-[color:var(--color-warning)] text-white",
    label: "text-[color:var(--color-warning)]",
  },
  muted: {
    wrap: "border-ink/15 bg-ink/5",
    pill: "bg-ink/60 text-white",
    label: "text-ink/70",
  },
}

const LEVEL_LABEL: Record<ConsensusLevel, string> = {
  very_high: "Very high consensus",
  high: "High consensus",
  moderate: "Moderate consensus",
  low: "Low consensus",
  dispersed: "Dispersed",
}

const DIRECTION_CHIP_LABEL: Record<EstimatorBreakdownItem["direction"], string> = {
  above_price: "above price",
  below_price: "below price",
  near_price: "near price",
}

const DIRECTION_CHIP_TONE: Record<EstimatorBreakdownItem["direction"], string> = {
  above_price:
    "bg-[color:var(--color-success)]/15 text-[color:var(--color-success)]",
  below_price:
    "bg-[color:var(--color-danger)]/15 text-[color:var(--color-danger)]",
  near_price:
    "bg-[color:var(--color-warning)]/15 text-[color:var(--color-warning)]",
}


// ─────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────
export interface ConsensusSignalBadgeProps {
  signal: ConsensusSignal | null | undefined
  className?: string
}

export default function ConsensusSignalBadge(
  { signal, className }: ConsensusSignalBadgeProps,
): ReactElement | null {
  const [expanded, setExpanded] = useState(false)

  // Hide on missing signal, on payloads pre-dating this PR, or when
  // no estimator returned a usable value.
  if (!signal) return null
  if (
    typeof signal !== "object"
    || typeof signal.total_estimators !== "number"
    || signal.total_estimators <= 0
  ) {
    return null
  }

  const tone = toneFor(signal.consensus_level, signal.consensus_direction)
  const toneClasses = TONE_CLASSES[tone]
  const levelLabel = LEVEL_LABEL[signal.consensus_level] ?? "Consensus"
  const headline = signal.headline || levelLabel
  const breakdown = Array.isArray(signal.estimator_breakdown)
    ? signal.estimator_breakdown
    : []
  const hasBreakdown = breakdown.length > 0

  // Compact summary chips — agreement count, total, and (when
  // present) the CV as a magnitude-clustering tightness signal.
  const summaryChips: { label: string; value: string }[] = [
    {
      label: "Agreement",
      value: `${signal.direction_agreement_count}/${signal.total_estimators}`,
    },
    {
      label: "Share",
      value: `${Math.round(signal.direction_agreement_pct)}%`,
    },
  ]
  if (
    typeof signal.magnitude_clustering_cv === "number"
    && Number.isFinite(signal.magnitude_clustering_cv)
  ) {
    const cv = signal.magnitude_clustering_cv
    summaryChips.push({
      label: "Magnitude CV",
      value: cv < 0.01 ? "<0.01" : cv.toFixed(2),
    })
  }

  // Tooltip-style explainer — descriptive, no advisory verbs.
  const explainer =
    "Counts how many of the seven standalone valuation estimators "
    + "(DCF, Multiples, Wall Street, Three-stage, DDM, EPV, "
    + "Probability-weighted) sit above, below, or near the current "
    + "price. Higher agreement on direction is a stronger "
    + "directional signal than any one estimator alone."

  return (
    <section
      data-testid="consensus-signal-badge"
      aria-label="Cross-engine consensus signal"
      title={explainer}
      className={cn(
        "rounded-2xl border px-4 py-3 md:px-5 md:py-4 transition-colors",
        toneClasses.wrap,
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              data-testid="consensus-level-pill"
              className={cn(
                "inline-flex items-center rounded-full px-2.5 py-0.5",
                "text-[11px] font-semibold uppercase tracking-wide",
                toneClasses.pill,
              )}
            >
              {levelLabel}
            </span>
            <span className="text-[11px] uppercase tracking-wide text-ink/60">
              Cross-engine consensus
            </span>
          </div>
          <p
            data-testid="consensus-headline"
            className={cn(
              "mt-2 text-base md:text-lg font-semibold leading-snug",
              toneClasses.label,
            )}
          >
            {headline}
          </p>
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink/70">
            {summaryChips.map((chip) => (
              <div key={chip.label} className="flex items-baseline gap-1">
                <dt className="uppercase tracking-wide text-ink/50">
                  {chip.label}
                </dt>
                <dd className="font-medium tabular-nums text-ink/80">
                  {chip.value}
                </dd>
              </div>
            ))}
          </dl>
          {signal.sanity_warnings.length > 0 && (
            <ul
              data-testid="consensus-warnings"
              className="mt-2 space-y-0.5 text-[11px] text-ink/60"
            >
              {signal.sanity_warnings.map((w) => (
                <li key={w}>• {w}</li>
              ))}
            </ul>
          )}
        </div>
        {hasBreakdown && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className={cn(
              "shrink-0 self-start rounded-full border border-ink/15",
              "px-3 py-1 text-[11px] font-medium uppercase tracking-wide",
              "text-ink/70 hover:text-ink hover:border-ink/30 transition-colors",
            )}
            aria-expanded={expanded}
            aria-controls="consensus-breakdown-list"
          >
            {expanded ? "Hide details" : "Show details"}
          </button>
        )}
      </div>
      {hasBreakdown && expanded && (
        <ul
          id="consensus-breakdown-list"
          data-testid="consensus-breakdown"
          className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-1.5 border-t border-ink/10 pt-3"
        >
          {breakdown.map((item) => (
            <li
              key={item.slot}
              className="flex items-center justify-between gap-2 text-[12px]"
            >
              <span className="truncate text-ink/80">{item.name}</span>
              <div className="flex items-center gap-2 shrink-0">
                <span className="tabular-nums text-ink/70">
                  {Number(item.value).toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide",
                    DIRECTION_CHIP_TONE[item.direction],
                  )}
                >
                  {DIRECTION_CHIP_LABEL[item.direction]}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

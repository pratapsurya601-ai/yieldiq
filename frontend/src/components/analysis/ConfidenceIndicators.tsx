"use client"

/**
 * ConfidenceIndicators
 * --------------------
 * Surfaces the three 0–100 scores produced by the Layer C
 * Confidence Framework (backend/services/confidence_service.py,
 * landed in PRs #340 + #342):
 *
 *   - data_quality_score        — completeness/freshness of inputs
 *   - model_confidence_score    — engine fit for this kind of business
 *   - valuation_stability_score — variance of FV over recent weeks
 *
 * Plus the defense-PSU `analyst_opinion_required` caveat (PR #333),
 * rendered as a prominent banner above the score chips when set.
 *
 * Rendering rules
 * ---------------
 * - If all three scores are null/undefined AND analyst_opinion_required
 *   is not true, the component renders nothing (no heading, no empty
 *   state). Legacy cached payloads pre-PR-340 won't see this band.
 * - Score colour bands:
 *     ≥ 80   → green
 *     50-79  → amber
 *     < 50   → red
 * - Each chip has a tooltip explaining what the score measures.
 * - The analyst-opinion-required banner cites the relevant
 *   `data_issues` string when one is present (defense-PSU caveat from
 *   `docs/design/defense-psu-dcf-fix.md` Approach D — NO-FIX).
 */

import type { ReactElement } from "react"
import { cn } from "@/lib/utils"

export type ConfidenceTone = "green" | "amber" | "red"

export function toneForScore(score: number): ConfidenceTone {
  if (score >= 80) return "green"
  if (score >= 50) return "amber"
  return "red"
}

const TONE_STYLES: Record<ConfidenceTone, string> = {
  green:
    "bg-green-50 text-green-800 border-green-200 dark:bg-green-900/20 dark:text-green-100 dark:border-green-800",
  amber:
    "bg-tone-warn-bg text-amber-800 border-tone-warn-bd dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-800",
  red:
    "bg-tone-bad-bg text-red-800 border-tone-bad-bd dark:bg-red-900/20 dark:text-red-100 dark:border-red-800",
}

interface ScoreSpec {
  key: "data_quality" | "model_confidence" | "valuation_stability"
  label: string
  tooltip: string
}

const SCORE_SPECS: ScoreSpec[] = [
  {
    key: "data_quality",
    label: "Data Quality",
    tooltip:
      "How complete and fresh the financial inputs are (filings, " +
      "price feeds, ratio history). Higher is better.",
  },
  {
    key: "model_confidence",
    label: "Model Confidence",
    tooltip:
      "How well the valuation engine (DCF / P/B / Residual Income) " +
      "fits this kind of business. Lower for cyclicals, conglomerates, " +
      "and order-book-driven names.",
  },
  {
    key: "valuation_stability",
    label: "Valuation Stability",
    tooltip:
      "Variance of the fair-value estimate over the last several " +
      "weeks. Lower scores mean the FV has been swinging — treat the " +
      "headline number as a range rather than a point estimate.",
  },
]

export interface ConfidenceIndicatorsProps {
  dataQualityScore?: number | null
  modelConfidenceScore?: number | null
  valuationStabilityScore?: number | null
  analystOpinionRequired?: boolean | null
  /**
   * Optional list of backend `data_issues` strings — used to find a
   * defense-PSU caveat to cite verbatim inside the analyst-opinion
   * banner. If none match, the banner falls back to a generic
   * explainer.
   */
  dataIssues?: string[] | null
  className?: string
}

/** Find the most relevant data-issues string to cite. */
function findCaveat(issues?: string[] | null): string | null {
  if (!issues || issues.length === 0) return null
  // Prefer the defense-PSU NO-FIX caveat. Match loosely so backend
  // wording changes don't break the citation.
  const preferred = issues.find((s) => {
    const lower = (s || "").toLowerCase()
    return (
      lower.includes("defense") ||
      lower.includes("analyst opinion") ||
      lower.includes("order book") ||
      lower.includes("make in india")
    )
  })
  if (preferred) return preferred
  return null
}

export default function ConfidenceIndicators({
  dataQualityScore,
  modelConfidenceScore,
  valuationStabilityScore,
  analystOpinionRequired,
  dataIssues,
  className,
}: ConfidenceIndicatorsProps): ReactElement | null {
  const scores: Record<ScoreSpec["key"], number | null | undefined> = {
    data_quality: dataQualityScore,
    model_confidence: modelConfidenceScore,
    valuation_stability: valuationStabilityScore,
  }

  const hasAnyScore =
    dataQualityScore != null ||
    modelConfidenceScore != null ||
    valuationStabilityScore != null

  const showAnalystBanner = analystOpinionRequired === true

  // Nothing to render — bail before producing a section heading.
  if (!hasAnyScore && !showAnalystBanner) return null

  const caveat = showAnalystBanner ? findCaveat(dataIssues) : null

  return (
    <section
      className={cn("space-y-3", className)}
      aria-label="Confidence indicators"
      data-testid="confidence-indicators"
    >
      <h2 className="text-sm font-semibold text-ink">Confidence indicators</h2>

      {showAnalystBanner && (
        <div
          data-testid="analyst-opinion-banner"
          role="note"
          className={cn(
            "rounded-2xl border border-l-4 px-4 py-3.5 sm:px-4 sm:py-4",
            "bg-tone-warn-bg border-tone-warn-bd border-l-amber-500",
            "dark:bg-amber-900/20 dark:border-amber-800 dark:border-l-amber-400",
          )}
        >
          <div className="flex items-center gap-2 mb-1">
            <span
              aria-hidden
              className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500"
            />
            <span className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-tone-warn-fg dark:text-amber-300">
              Analyst Opinion Required
            </span>
          </div>
          <p className="text-sm font-semibold text-amber-900 dark:text-amber-100 leading-snug">
            Trailing-financials DCF may understate this name.
          </p>
          <p className="mt-1 text-sm font-normal text-amber-900/90 dark:text-amber-100/90 leading-relaxed">
            {caveat ??
              "This ticker's forward earning power is driven by a " +
                "regime change (order-book, policy, or capacity ramp) " +
                "that trailing financials don't yet reflect. Treat the " +
                "headline fair value as a floor and consult forward " +
                "analyst estimates before acting."}
          </p>
        </div>
      )}

      {hasAnyScore && (
        <div
          data-testid="confidence-score-chips"
          className="flex flex-wrap gap-2"
        >
          {SCORE_SPECS.map((spec) => {
            const score = scores[spec.key]
            if (score == null) return null
            const tone = toneForScore(score)
            return (
              <span
                key={spec.key}
                data-testid={`confidence-chip-${spec.key}`}
                data-tone={tone}
                title={`${spec.label}: ${score}/100 — ${spec.tooltip}`}
                aria-label={`${spec.label} ${score} out of 100. ${spec.tooltip}`}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border px-3 py-1",
                  "text-xs font-medium leading-none",
                  TONE_STYLES[tone],
                )}
              >
                <span className="font-semibold">{spec.label}</span>
                <span className="font-mono tabular-nums font-bold">
                  {score}
                  <span className="opacity-60">/100</span>
                </span>
              </span>
            )
          })}
        </div>
      )}
    </section>
  )
}

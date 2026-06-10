"use client"

/**
 * ConfidenceRadar — 5-axis snowflake-style confidence visualization.
 *
 * Competitor audit #5 — Simply Wall St's snowflake is their most
 * screenshotted asset. We ship the same primitive but route every
 * axis to a *statistically computed* pillar instead of qualitative
 * checklists. The differentiator is the calibration story; the
 * radar is the social-share / SEO surface that carries it.
 *
 * Five axes (all 0–100, higher is better):
 *
 *   • Data Quality        — completeness + freshness of inputs
 *                           (filings, price feeds, ratio history).
 *   • Model Fit           — how well the active engine (DCF /
 *                           residual income / multiples composite)
 *                           fits this kind of business.
 *   • FV Stability        — variance of the fair-value estimate over
 *                           the last several weeks; low = swinging.
 *   • Sensitivity         — fraction of 200 Monte Carlo perturbations
 *                           that preserve the base verdict (T2.7).
 *   • Agreement           — clustering vs. spread among composite-IV
 *                           constituent estimators (T1.6).
 *
 * Rendering rules
 * ---------------
 * - All five pillars null → empty state copy + null return for the
 *   chart shell. Nothing surfaces to screen readers as a numeric
 *   axis until at least one pillar is non-null.
 * - The overall score is the simple mean of the *non-null* pillars,
 *   rounded to an integer. Pillars left null (banks / holdcos / etc.)
 *   are excluded so they don't pull the average down.
 * - Tone bands inside the breakdown follow the same thresholds as
 *   <ConfidenceIndicators>: ≥80 green, 50–79 amber, <50 red.
 * - SEBI-clean: never name a verdict, never use directional vocab
 *   from the banned list (see scripts/check_sebi_words.py).
 *   Copy is bounded to data-pedigree + methodology language.
 */

import type { ReactElement } from "react"
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Tooltip,
  ResponsiveContainer,
} from "recharts"
import { cn } from "@/lib/utils"

export interface ConfidenceRadarPillars {
  data_quality: number | null
  model_confidence: number | null
  valuation_stability: number | null
  sensitivity: number | null
  composite_agreement: number | null
}

export interface ConfidenceRadarProps {
  ticker: string
  pillars: ConfidenceRadarPillars
  className?: string
}

interface AxisRow {
  axis: string
  key: keyof ConfidenceRadarPillars
  value: number
  /** True when the pillar arrived non-null; false when we substituted 0. */
  present: boolean
  /** Reference ring at 100 — Recharts uses this for the outer band. */
  full: number
}

const AXIS_SPECS: Array<{
  key: keyof ConfidenceRadarPillars
  axis: string
  explainer: string
}> = [
  {
    key: "data_quality",
    axis: "Data Quality",
    explainer:
      "How complete and fresh the financial inputs are " +
      "(filings, price feeds, ratio history). Higher is better.",
  },
  {
    key: "model_confidence",
    axis: "Model Fit",
    explainer:
      "How well the active engine (DCF / residual income / " +
      "multiples composite) fits this kind of business.",
  },
  {
    key: "valuation_stability",
    axis: "FV Stability",
    explainer:
      "Variance of the fair-value estimate over the last several " +
      "weeks. Lower scores mean the FV has been swinging — treat " +
      "the headline number as a range rather than a point estimate.",
  },
  {
    key: "sensitivity",
    axis: "Sensitivity",
    explainer:
      "Fraction of 200 Monte Carlo perturbations that preserve " +
      "the base verdict. Higher means the headline is robust to " +
      "small input changes (WACC, FCF, terminal growth, tax).",
  },
  {
    key: "composite_agreement",
    axis: "Agreement",
    explainer:
      "How tightly the composite-IV constituent estimators " +
      "cluster. High = estimators agree. Low = wide spread, so " +
      "the composite is averaging a noisy band.",
  },
]

/** ≥80 green, 50–79 amber, <50 red — mirrors ConfidenceIndicators. */
function toneFor(score: number): "green" | "amber" | "red" {
  if (score >= 80) return "green"
  if (score >= 50) return "amber"
  return "red"
}

const TONE_CLASS: Record<"green" | "amber" | "red", string> = {
  green:
    "bg-green-50 text-green-800 border-green-200 " +
    "dark:bg-green-900/20 dark:text-green-100 dark:border-green-800",
  amber:
    "bg-tone-warn-bg text-amber-800 border-tone-warn-bd " +
    "dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-800",
  red:
    "bg-tone-bad-bg text-red-800 border-tone-bad-bd " +
    "dark:bg-red-900/20 dark:text-red-100 dark:border-red-800",
}

interface TooltipItemPayload {
  payload?: AxisRow
}

interface TooltipProps {
  active?: boolean
  payload?: TooltipItemPayload[]
}

function RadarTooltip({ active, payload }: TooltipProps): ReactElement | null {
  if (!active || !payload || payload.length === 0) return null
  const row = payload[0]?.payload
  if (!row) return null
  return (
    <div
      data-testid="radar-tooltip"
      className={cn(
        "rounded-md border border-border bg-raised px-3 py-2",
        "shadow-md text-xs",
      )}
    >
      <div className="font-semibold text-ink">{row.axis}</div>
      <div className="font-mono tabular-nums text-body">
        {row.present ? `${Math.round(row.value)}/100` : "Not applicable"}
      </div>
    </div>
  )
}

function PillarBreakdown({
  pillars,
}: {
  pillars: ConfidenceRadarPillars
}): ReactElement {
  return (
    <details
      className="mt-3 rounded-lg border border-border bg-surface"
      data-testid="radar-pillar-explainers"
    >
      <summary
        className={cn(
          "cursor-pointer select-none px-3 py-2 text-xs font-semibold",
          "text-ink",
        )}
      >
        What each pillar measures
      </summary>
      <dl className="px-3 pb-3 pt-1 space-y-2 text-xs">
        {AXIS_SPECS.map((spec) => {
          const raw = pillars[spec.key]
          const present = raw != null
          const score = present ? (raw as number) : null
          const tone = score != null ? toneFor(score) : null
          return (
            <div
              key={spec.key}
              className="grid grid-cols-[8rem_1fr_auto] gap-x-3 gap-y-1 items-start"
              data-testid={`radar-explainer-${spec.key}`}
            >
              <dt className="font-semibold text-ink capitalize">{spec.axis}</dt>
              <dd className="text-body leading-snug">{spec.explainer}</dd>
              <dd>
                {tone && score != null ? (
                  <span
                    data-testid={`radar-pillar-chip-${spec.key}`}
                    data-tone={tone}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border",
                      "px-2 py-0.5 text-[10px] font-mono tabular-nums",
                      "font-bold leading-none",
                      TONE_CLASS[tone],
                    )}
                  >
                    {score}
                    <span className="opacity-60">/100</span>
                  </span>
                ) : (
                  <span
                    data-testid={`radar-pillar-na-${spec.key}`}
                    className={cn(
                      "inline-flex items-center rounded-full border px-2",
                      "py-0.5 text-[10px] font-medium leading-none",
                      "bg-tone-neutral-bg text-tone-neutral-fg",
                      "border-tone-neutral-bd",
                    )}
                  >
                    n/a
                  </span>
                )}
              </dd>
            </div>
          )
        })}
      </dl>
    </details>
  )
}

export function ConfidenceRadar({
  ticker,
  pillars,
  className,
}: ConfidenceRadarProps): ReactElement | null {
  // Row order matches AXIS_SPECS so the polygon vertices line up
  // with the labels users read clockwise from the top.
  const rows: AxisRow[] = AXIS_SPECS.map((spec) => {
    const raw = pillars[spec.key]
    const present = raw != null
    return {
      axis: spec.axis,
      key: spec.key,
      // Null pillars render as a 0-radius vertex so the polygon
      // still closes — the explainer panel below carries the "n/a"
      // label so users don't read 0 as a score.
      value: present ? Math.max(0, Math.min(100, raw as number)) : 0,
      present,
      full: 100,
    }
  })

  const presentRows = rows.filter((r) => r.present)

  // All-null payload — render an honest empty state instead of an
  // all-zero polygon that would read as "every pillar failed".
  if (presentRows.length === 0) {
    return (
      <section
        className={cn(
          "rounded-xl border border-border bg-raised p-4",
          className,
        )}
        data-testid="confidence-radar"
        data-empty="true"
        aria-label="Confidence radar — no pillars available"
      >
        <header className="flex items-baseline justify-between gap-3 mb-2">
          <h3 className="text-sm font-semibold text-ink">Confidence radar</h3>
        </header>
        <p className="text-xs text-caption leading-relaxed">
          Confidence pillars are not yet available for {ticker}. The
          radar will appear once the engine emits at least one of
          data quality, model fit, FV stability, sensitivity, or
          composite agreement.
        </p>
      </section>
    )
  }

  const overallScore = Math.round(
    presentRows.reduce((sum, r) => sum + r.value, 0) / presentRows.length,
  )
  const overallTone = toneFor(overallScore)

  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-raised p-4",
        className,
      )}
      data-testid="confidence-radar"
      aria-label={`Confidence radar for ${ticker}`}
    >
      <header className="flex items-baseline justify-between gap-3 mb-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">Confidence radar</h3>
          <p className="text-[11px] text-caption mt-0.5">
            Five statistically computed pillars, 0–100 each.
          </p>
        </div>
        <div
          className="text-right shrink-0"
          data-testid="radar-overall-score"
          data-tone={overallTone}
        >
          <div className="font-mono tabular-nums">
            <span className="text-2xl font-bold text-ink">
              {overallScore}
            </span>
            <span className="text-sm text-caption">/100</span>
          </div>
          <div className="text-[10px] uppercase tracking-wider text-caption">
            overall
          </div>
        </div>
      </header>

      <div data-testid="radar-chart-wrap" className="w-full">
        <ResponsiveContainer width="100%" height={320}>
          <RadarChart
            data={rows}
            margin={{ top: 20, right: 30, bottom: 20, left: 30 }}
          >
            <PolarGrid stroke="var(--radar-grid-color)" />
            <PolarAngleAxis
              dataKey="axis"
              tick={{ fontSize: 12, fill: "var(--color-body)" }}
            />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 100]}
              tickCount={5}
              tick={{ fontSize: 10, fill: "var(--color-caption)" }}
              stroke="var(--radar-grid-color)"
            />
            <Radar
              name={ticker}
              dataKey="value"
              stroke="var(--radar-stroke-color)"
              fill="var(--radar-fill-color)"
              fillOpacity={1}
              isAnimationActive={false}
            />
            <Tooltip content={<RadarTooltip />} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      <PillarBreakdown pillars={pillars} />

      <p
        className="mt-3 text-[11px] text-caption leading-relaxed"
        data-testid="radar-caveat"
      >
        Unlike qualitative competitor frameworks, each pillar is
        statistically computed from filings, price history, and Monte
        Carlo perturbations of the valuation engine. Scores update
        every time the analysis is recomputed.
      </p>
    </section>
  )
}

export default ConfidenceRadar

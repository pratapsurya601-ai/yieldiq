"use client"

/**
 * DerivedInsightsPanel
 * --------------------
 * Renders the 4 derived insights produced by the T5.3 backend
 * service (backend/services/derived_insights_service.py, surfaced
 * via the `derived_insights` field on the analysis payload):
 *
 *   1. ConfidenceCard    — 5-pillar synthesis ("YieldIQ HIGHLY
 *                          CONFIDENT") + per-pillar breakdown.
 *   2. ClusteringCard    — "N of M estimators cluster within X%
 *                          of <value>" + per-estimator deltas.
 *   3. FloorCeilingCard  — Graham liquidation floor + Tobin
 *                          replacement ceiling vs. live price.
 *   4. CalibrationCard   — published sector calibration accuracy.
 *
 * Rendering rules
 * ---------------
 * - When `insights` is null/undefined OR all four slots are null,
 *   the component renders nothing — legacy cached payloads pre-
 *   T5.3 surface as no panel.
 * - Each card is independent: a single populated slot renders
 *   just that card; siblings stay hidden.
 * - SEBI vocabulary discipline mirrors the backend service —
 *   descriptive frames only ("confidence", "cluster", "anchor"),
 *   no advisory words.
 * - Lead with the backend `headline` string per spec; supporting
 *   details surface in compact rows beneath.
 */

import type { ReactElement } from "react"
import { cn } from "@/lib/utils"

// ─────────────────────────────────────────────────────────────────
// Types — mirror backend/services/derived_insights_service.py
// ─────────────────────────────────────────────────────────────────
export type ConfidenceLevel =
  | "very_high"
  | "high"
  | "moderate"
  | "low"
  | "very_low"

export interface ConfidenceSummaryInsight {
  overall_level: ConfidenceLevel
  overall_score: number
  pillar_breakdown: Record<string, { score: number; label: string }>
  headline: string
  pillars_present: number
}

export interface EstimatorDetail {
  name: string
  slot: string
  value: number
  delta_pct: number
  in_cluster: boolean
}

export interface EstimatorClusteringInsight {
  cluster_center: number
  cluster_count: number
  total_estimators: number
  cluster_pct: number
  estimator_details: EstimatorDetail[]
  headline: string
}

export interface FloorCeilingInsight {
  liquidation_per_share: number | null
  replacement_per_share: number | null
  current_price: number
  dcf_fv: number | null
  composite_iv: number | null
  floor_distance_pct: number | null
  ceiling_distance_pct: number | null
  headline: string
  distress_flag: boolean
}

export interface SectorCalibrationInsight {
  sector: string
  median_abs_error_pct: number | null
  direction_accuracy_pct: number | null
  observation_count: number | null
  headline: string
}

export interface DerivedInsights {
  confidence_summary: ConfidenceSummaryInsight | null
  estimator_clustering: EstimatorClusteringInsight | null
  floor_ceiling: FloorCeilingInsight | null
  sector_calibration: SectorCalibrationInsight | null
}

export interface DerivedInsightsPanelProps {
  insights: DerivedInsights | null | undefined
  className?: string
}

// ─────────────────────────────────────────────────────────────────
// Tone tokens — match design-system semantic palette.
// ─────────────────────────────────────────────────────────────────
const LEVEL_TONE: Record<ConfidenceLevel, string> = {
  very_high:
    "bg-green-50 text-green-900 border-green-200 dark:bg-green-900/20 dark:text-green-100 dark:border-green-800",
  high:
    "bg-green-50 text-green-900 border-green-200 dark:bg-green-900/15 dark:text-green-100 dark:border-green-800",
  moderate:
    "bg-tone-warn-bg text-amber-900 border-tone-warn-bd dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-800",
  low:
    "bg-tone-bad-bg text-red-900 border-tone-bad-bd dark:bg-red-900/20 dark:text-red-100 dark:border-red-800",
  very_low:
    "bg-tone-bad-bg text-red-900 border-tone-bad-bd dark:bg-red-900/25 dark:text-red-100 dark:border-red-800",
}

const LEVEL_DOT: Record<ConfidenceLevel, string> = {
  very_high: "bg-green-500",
  high: "bg-green-500",
  moderate: "bg-amber-500",
  low: "bg-red-500",
  very_low: "bg-red-600",
}

// Format a numeric value as currency-free 2dp; the analysis page
// already provides per-stock currency context above this panel.
function fmtNumber(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—"
  return n.toLocaleString(undefined, {
    minimumFractionDigits: n >= 100 ? 0 : 1,
    maximumFractionDigits: 2,
  })
}

function fmtSignedPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(1)}%`
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—"
  return `${n.toFixed(1)}%`
}

// ─────────────────────────────────────────────────────────────────
// Card 1 — Confidence summary
// ─────────────────────────────────────────────────────────────────
function ConfidenceCard({
  insight,
}: {
  insight: ConfidenceSummaryInsight
}): ReactElement {
  const tone = LEVEL_TONE[insight.overall_level] ?? LEVEL_TONE.moderate
  const dot = LEVEL_DOT[insight.overall_level] ?? LEVEL_DOT.moderate
  // Build a stable iteration order from the slots the backend
  // declares as canonical (see _PILLAR_LABELS in the service).
  const canonicalOrder = [
    "data_quality",
    "model_fit",
    "stability",
    "sensitivity",
    "estimator_agreement",
  ]
  const pillars = canonicalOrder
    .filter((k) => insight.pillar_breakdown && insight.pillar_breakdown[k])
    .map((k) => ({
      slot: k,
      ...insight.pillar_breakdown[k],
    }))
  return (
    <article
      data-testid="derived-insight-confidence"
      data-level={insight.overall_level}
      className={cn(
        "rounded-2xl border p-4 sm:p-5",
        tone,
      )}
    >
      <header className="flex items-center gap-2 mb-3">
        <span aria-hidden className={cn("h-2 w-2 rounded-full", dot)} />
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] opacity-80">
          Engine confidence
        </span>
        <span
          className="ml-auto text-xs font-semibold tabular-nums"
          aria-label={`overall confidence score ${insight.overall_score} of 100`}
        >
          {insight.overall_score}/100
        </span>
      </header>
      <p className="text-sm font-semibold leading-snug">{insight.headline}</p>
      {pillars.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {pillars.map((p) => (
            <li
              key={p.slot}
              data-testid={`derived-insight-confidence-pillar-${p.slot}`}
              className="flex items-center justify-between text-xs leading-tight"
            >
              <span className="opacity-90">{p.label}</span>
              <span className="tabular-nums font-medium">{p.score}/100</span>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  )
}

// ─────────────────────────────────────────────────────────────────
// Card 2 — Estimator clustering
// ─────────────────────────────────────────────────────────────────
function ClusteringCard({
  insight,
}: {
  insight: EstimatorClusteringInsight
}): ReactElement {
  const inClusterTone =
    "text-green-700 dark:text-green-300"
  const outClusterTone =
    "text-ink-2 dark:text-ink-2"
  return (
    <article
      data-testid="derived-insight-clustering"
      className={cn(
        "rounded-2xl border border-default p-4 sm:p-5",
        "bg-surface text-ink",
      )}
    >
      <header className="flex items-center gap-2 mb-3">
        <span aria-hidden className="h-2 w-2 rounded-full bg-sky-500" />
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] opacity-80">
          Estimator clustering
        </span>
        <span
          className="ml-auto text-xs font-semibold tabular-nums"
          aria-label={`${insight.cluster_count} of ${insight.total_estimators} estimators in cluster`}
        >
          {insight.cluster_count}/{insight.total_estimators}
        </span>
      </header>
      <p className="text-sm font-semibold leading-snug">{insight.headline}</p>
      {insight.estimator_details.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {insight.estimator_details.map((est) => (
            <li
              key={est.slot}
              data-testid={`derived-insight-estimator-${est.slot}`}
              data-in-cluster={est.in_cluster ? "true" : "false"}
              className="flex items-center justify-between text-xs leading-tight"
            >
              <span
                className={cn(
                  est.in_cluster ? inClusterTone : outClusterTone,
                  "font-medium",
                )}
              >
                {est.name}
              </span>
              <span className="tabular-nums font-medium">
                {fmtNumber(est.value)}{" "}
                <span className="opacity-70">({fmtSignedPct(est.delta_pct)})</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  )
}

// ─────────────────────────────────────────────────────────────────
// Card 3 — Floor + ceiling anchor
// ─────────────────────────────────────────────────────────────────
function FloorCeilingCard({
  insight,
}: {
  insight: FloorCeilingInsight
}): ReactElement {
  const distress = insight.distress_flag
  const tone = distress
    ? "bg-tone-bad-bg text-red-900 border-tone-bad-bd dark:bg-red-900/20 dark:text-red-100 dark:border-red-800"
    : "bg-surface text-ink border-default"
  const dot = distress ? "bg-red-500" : "bg-violet-500"
  const label = distress ? "Distress signal" : "Anchor frame"
  return (
    <article
      data-testid="derived-insight-floor-ceiling"
      data-distress={distress ? "true" : "false"}
      className={cn(
        "rounded-2xl border p-4 sm:p-5",
        tone,
      )}
    >
      <header className="flex items-center gap-2 mb-3">
        <span aria-hidden className={cn("h-2 w-2 rounded-full", dot)} />
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] opacity-80">
          {label}
        </span>
      </header>
      <p className="text-sm font-semibold leading-snug">{insight.headline}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs leading-tight">
        {insight.liquidation_per_share != null ? (
          <>
            <dt className="opacity-80">Liquidation</dt>
            <dd className="tabular-nums text-right font-medium">
              {fmtNumber(insight.liquidation_per_share)}
            </dd>
          </>
        ) : null}
        {insight.replacement_per_share != null ? (
          <>
            <dt className="opacity-80">Replacement</dt>
            <dd className="tabular-nums text-right font-medium">
              {fmtNumber(insight.replacement_per_share)}
            </dd>
          </>
        ) : null}
        <dt className="opacity-80">Current price</dt>
        <dd className="tabular-nums text-right font-medium">
          {fmtNumber(insight.current_price)}
        </dd>
        {insight.dcf_fv != null ? (
          <>
            <dt className="opacity-80">DCF fair value</dt>
            <dd className="tabular-nums text-right font-medium">
              {fmtNumber(insight.dcf_fv)}
            </dd>
          </>
        ) : null}
        {insight.composite_iv != null ? (
          <>
            <dt className="opacity-80">Composite IV</dt>
            <dd className="tabular-nums text-right font-medium">
              {fmtNumber(insight.composite_iv)}
            </dd>
          </>
        ) : null}
      </dl>
    </article>
  )
}

// ─────────────────────────────────────────────────────────────────
// Card 4 — Sector calibration
// ─────────────────────────────────────────────────────────────────
function CalibrationCard({
  insight,
}: {
  insight: SectorCalibrationInsight
}): ReactElement {
  return (
    <article
      data-testid="derived-insight-calibration"
      className={cn(
        "rounded-2xl border border-default p-4 sm:p-5",
        "bg-surface text-ink",
      )}
    >
      <header className="flex items-center gap-2 mb-3">
        <span aria-hidden className="h-2 w-2 rounded-full bg-indigo-500" />
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] opacity-80">
          Sector calibration
        </span>
      </header>
      <p className="text-sm font-semibold leading-snug">{insight.headline}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs leading-tight">
        <dt className="opacity-80">Sector</dt>
        <dd className="text-right font-medium">{insight.sector}</dd>
        {insight.median_abs_error_pct != null ? (
          <>
            <dt className="opacity-80">Median absolute error</dt>
            <dd className="tabular-nums text-right font-medium">
              {fmtPct(insight.median_abs_error_pct)}
            </dd>
          </>
        ) : null}
        {insight.direction_accuracy_pct != null ? (
          <>
            <dt className="opacity-80">Direction accuracy</dt>
            <dd className="tabular-nums text-right font-medium">
              {fmtPct(insight.direction_accuracy_pct)}
            </dd>
          </>
        ) : null}
        {insight.observation_count != null ? (
          <>
            <dt className="opacity-80">Observations</dt>
            <dd className="tabular-nums text-right font-medium">
              {insight.observation_count}
            </dd>
          </>
        ) : null}
      </dl>
    </article>
  )
}

// ─────────────────────────────────────────────────────────────────
// Public panel
// ─────────────────────────────────────────────────────────────────
export default function DerivedInsightsPanel({
  insights,
  className,
}: DerivedInsightsPanelProps): ReactElement | null {
  if (!insights) return null
  const slots = [
    insights.confidence_summary,
    insights.estimator_clustering,
    insights.floor_ceiling,
    insights.sector_calibration,
  ]
  const renderableCount = slots.filter((s) => s != null).length
  if (renderableCount === 0) return null
  return (
    <section
      data-testid="derived-insights-panel"
      aria-label="Key insights"
      className={cn("space-y-3", className)}
    >
      <h2 className="text-sm font-semibold text-ink">Key insights</h2>
      <div
        className={cn(
          "grid grid-cols-1 gap-3",
          "sm:grid-cols-2",
        )}
      >
        {insights.confidence_summary ? (
          <ConfidenceCard insight={insights.confidence_summary} />
        ) : null}
        {insights.estimator_clustering ? (
          <ClusteringCard insight={insights.estimator_clustering} />
        ) : null}
        {insights.floor_ceiling ? (
          <FloorCeilingCard insight={insights.floor_ceiling} />
        ) : null}
        {insights.sector_calibration ? (
          <CalibrationCard insight={insights.sector_calibration} />
        ) : null}
      </div>
    </section>
  )
}

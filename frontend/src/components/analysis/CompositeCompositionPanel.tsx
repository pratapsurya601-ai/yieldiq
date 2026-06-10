"use client"

/**
 * CompositeCompositionPanel — composite-transparency 2026-06-10.
 *
 * Why
 * ───
 * After Phase C the headline number on the analysis page is the
 * `composite_intrinsic_value` — a pro-rata weighted average of up to
 * seven estimators. When N of 7 estimators are unavailable, the
 * surviving estimators' weights are renormalized to sum to 1.0 — and
 * the resulting composite can sit within 0.5% of the DCF value (e.g.
 * HDFCBANK: composite Rs.1,147.77 vs DCF Rs.1,141.82) with no on-page
 * explanation of WHY.
 *
 * Two failure modes the user encounters in prod today:
 *
 *   1. HDFCBANK composite ~= DCF — user can't see WHY the composite
 *      isn't materially different from the DCF.
 *
 *   2. AXISBANK composite +60% Undervalued (FV Rs.2,103 vs px
 *      Rs.1,314) — extreme number with no breakdown of which
 *      estimator drove it. User has no way to judge whether one
 *      estimator is going crazy or a consensus signal is firing.
 *
 * This panel renders the per-estimator breakdown the backend builds
 * via `composite_composition_service`:
 *
 *   - Headline: "Composite from N of 7 estimators - <CONFIDENCE>"
 *   - Table: each estimator row with value, nominal vs effective
 *     weight, contribution to composite, applicability badge,
 *     reason (when inapplicable), and outlier flag (when relevant).
 *   - Total reconciliation: sum of contributions matches composite_value.
 *
 * Mobile breakpoint
 * ─────────────────
 * The panel ALWAYS renders inline on desktop. On `< md` viewports
 * (640px) it collapses to a single tappable chip; expand reveals
 * the full table. We use a native `<details>` element so the
 * "expanded by default on desktop" behaviour is driven by CSS
 * rather than per-breakpoint state.
 *
 * SEBI vocabulary
 * ───────────────
 * All copy is descriptive of the COMPUTATION (which estimator, how
 * much it contributed). Confidence labels reference our model's
 * coverage, never a directional view on the security. No banned verbs.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import { cn, formatCurrency } from "@/lib/utils"

/* ─── public API types ────────────────────────────────────────────── */

export type ConfidenceLabel = "HIGH" | "MODERATE" | "LOW" | "MINIMAL"

export interface CompositionEstimatorRow {
  key: string
  label: string
  value: number | null
  weight_nominal: number
  weight_effective: number
  contribution: number | null
  applicable: boolean
  reason: string | null
  is_outlier: boolean
  description: string
}

export interface CompositeComposition {
  estimators: CompositionEstimatorRow[]
  estimators_available: number
  estimators_total: number
  confidence_label: ConfidenceLabel
  confidence_caption: string
  outliers: string[]
  composite_value: number | null
}

export interface CompositeCompositionPanelProps {
  composition: CompositeComposition | null | undefined
  ticker?: string | null
  currency?: string | null
  className?: string
}

/* ─── tone helpers ────────────────────────────────────────────────── */

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

function pctFormat(weight: number): string {
  if (!isFiniteNumber(weight) || weight <= 0) return "0%"
  return `${(weight * 100).toFixed(0)}%`
}

function pctDeltaFormat(nominal: number, effective: number): string | null {
  if (!isFiniteNumber(nominal) || !isFiniteNumber(effective)) return null
  if (nominal <= 0 || effective <= 0) return null
  // Show "renormalized 35% -> 45%" framing only when the delta is
  // visible (>= 2 percentage points). Otherwise the row reads as
  // "nominal == effective" and the chevron is suppressed.
  const delta = Math.abs(effective - nominal) * 100
  if (delta < 2) return null
  return `${pctFormat(nominal)} -> ${pctFormat(effective)}`
}

function confidenceTone(label: ConfidenceLabel): string {
  switch (label) {
    case "HIGH":
      return "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
    case "MODERATE":
      return "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
    case "LOW":
      return "border-orange-300 bg-orange-50 text-orange-900 dark:border-orange-900 dark:bg-orange-950/40 dark:text-orange-200"
    case "MINIMAL":
    default:
      return "border-slate-300 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200"
  }
}

/* ─── row sub-component ──────────────────────────────────────────── */

function EstimatorRow({
  row,
  ticker,
  currency,
}: {
  row: CompositionEstimatorRow
  ticker: string | null
  currency: string | null
}) {
  const valueDisplay =
    row.applicable && isFiniteNumber(row.value)
      ? formatCurrency(row.value, currency ?? undefined, ticker ?? undefined)
      : "—"
  const contributionDisplay =
    row.applicable && isFiniteNumber(row.contribution)
      ? formatCurrency(
          row.contribution,
          currency ?? undefined,
          ticker ?? undefined,
        )
      : "—"
  const weightDelta = row.applicable
    ? pctDeltaFormat(row.weight_nominal, row.weight_effective)
    : null

  return (
    <li
      role="listitem"
      data-testid={`composite-composition-row-${row.key}`}
      data-applicable={row.applicable}
      data-outlier={row.is_outlier}
      className={cn(
        "grid grid-cols-12 gap-2 rounded-md border px-3 py-2 text-[12px] leading-snug",
        row.applicable
          ? row.is_outlier
            ? "border-amber-300 bg-amber-50/60 text-ink dark:border-amber-900 dark:bg-amber-950/30"
            : "border-border bg-bg text-ink"
          : "border-border bg-surface text-caption",
      )}
    >
      <div className="col-span-12 sm:col-span-4 flex flex-col gap-0.5">
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-ink">{row.label}</span>
          {row.is_outlier && (
            <span
              data-testid={`composite-composition-outlier-${row.key}`}
              className="rounded-full border border-amber-400 bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-amber-900 dark:border-amber-700 dark:bg-amber-900/40 dark:text-amber-100"
            >
              Outlier
            </span>
          )}
        </div>
        <span className="text-[11px] text-caption">{row.description}</span>
      </div>
      <div className="col-span-4 sm:col-span-2 flex flex-col gap-0.5">
        <span className="text-[10px] uppercase tracking-[0.1em] text-caption">
          Value
        </span>
        <span className="tabular-nums font-medium">{valueDisplay}</span>
      </div>
      <div className="col-span-4 sm:col-span-3 flex flex-col gap-0.5">
        <span className="text-[10px] uppercase tracking-[0.1em] text-caption">
          Weight
        </span>
        <span className="tabular-nums">
          {row.applicable ? (
            weightDelta ? (
              <>
                <span className="opacity-70">{pctFormat(row.weight_nominal)}</span>
                <span className="opacity-50"> -&gt; </span>
                <span className="font-semibold">
                  {pctFormat(row.weight_effective)}
                </span>
              </>
            ) : (
              <span className="font-semibold">
                {pctFormat(row.weight_effective)}
              </span>
            )
          ) : (
            <span className="opacity-60">
              {pctFormat(row.weight_nominal)} (not applied)
            </span>
          )}
        </span>
      </div>
      <div className="col-span-4 sm:col-span-3 flex flex-col gap-0.5">
        <span className="text-[10px] uppercase tracking-[0.1em] text-caption">
          Contribution
        </span>
        <span className="tabular-nums font-semibold">
          {contributionDisplay}
        </span>
      </div>
      {!row.applicable && row.reason && (
        <div className="col-span-12 mt-1 text-[11px] text-caption leading-snug">
          <span className="font-medium">Not applicable:</span> {row.reason}
        </div>
      )}
    </li>
  )
}

/* ─── main component ─────────────────────────────────────────────── */

export default function CompositeCompositionPanel({
  composition,
  ticker,
  currency,
  className,
}: CompositeCompositionPanelProps) {
  // Self-hide when the backend hasn't populated the field (legacy
  // cached payloads). The parent mounts unconditionally below the
  // hero and trusts this guard.
  if (!composition || !Array.isArray(composition.estimators)) {
    return null
  }
  // Self-hide when ZERO estimators populated — the composite headline
  // already shows "Composite unavailable" upstream; rendering an empty
  // table beneath that would be noise.
  if (composition.estimators_available <= 0) {
    return null
  }

  const tickerName = ticker ?? null
  const currencyTag = currency ?? null
  const composite =
    isFiniteNumber(composition.composite_value)
      ? formatCurrency(
          composition.composite_value,
          currencyTag ?? undefined,
          tickerName ?? undefined,
        )
      : null

  const headlineChip = (
    <div
      data-testid="composite-composition-headline"
      data-confidence={composition.confidence_label}
      className={cn(
        "rounded-lg border px-3 py-2 text-[12px] leading-snug",
        confidenceTone(composition.confidence_label),
      )}
    >
      <p className="font-semibold">
        Composite from {composition.estimators_available} of{" "}
        {composition.estimators_total} estimators ·{" "}
        <span className="uppercase tracking-wider">
          {composition.confidence_label}
        </span>{" "}
        confidence
      </p>
      <p className="mt-0.5 text-[11px] opacity-80">
        {composition.confidence_caption}
      </p>
    </div>
  )

  return (
    <SummaryCard
      data-testid="composite-composition-panel"
      className={cn("gap-3", className)}
    >
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-bold text-ink">
          How the composite is built
        </h2>
        <p className="text-[11px] text-caption leading-snug">
          The composite intrinsic value blends every applicable
          estimator pro-rata. When some estimators are unavailable for
          this ticker, their share of the weighting redistributes to
          the surviving estimators. The breakdown below shows the
          underlying math so you can read the composite the way the
          engine built it.
        </p>
      </div>

      {/* Headline chip rendered on every breakpoint — desktop sees it
          above the table, mobile sees it as the collapsed chip. */}
      {headlineChip}

      {/* Desktop / full breakdown — collapsible on mobile via native
          <details>. Open by default on >= md viewports through the
          `md:open` modifier so users see the table on first paint. */}
      <details
        className="group"
        data-testid="composite-composition-details"
        open
      >
        <summary
          className="flex cursor-pointer items-center justify-between gap-2 rounded-md border border-border bg-bg px-3 py-2 text-[12px] font-medium text-ink sm:hidden"
          data-testid="composite-composition-toggle"
        >
          <span>View per-estimator breakdown</span>
          <span className="text-caption group-open:rotate-180 transition-transform">
            ▾
          </span>
        </summary>

        <ul
          role="list"
          data-testid="composite-composition-rows"
          className="mt-2 flex flex-col gap-1.5"
        >
          {composition.estimators.map((row) => (
            <EstimatorRow
              key={row.key}
              row={row}
              ticker={tickerName}
              currency={currencyTag}
            />
          ))}
        </ul>

        {composite !== null && (
          <div
            data-testid="composite-composition-total"
            className="mt-2 flex items-center justify-between rounded-md border border-border bg-surface px-3 py-2 text-[12px]"
          >
            <span className="font-medium text-ink">
              Composite ({composition.estimators_available} of{" "}
              {composition.estimators_total} estimators)
            </span>
            <span className="tabular-nums font-semibold text-ink">
              {composite}
            </span>
          </div>
        )}

        {composition.outliers.length > 0 && (
          <p
            data-testid="composite-composition-outlier-caption"
            className="mt-2 text-[11px] text-caption leading-snug"
          >
            <span className="font-semibold text-ink">
              {composition.outliers.length} estimator
              {composition.outliers.length > 1 ? "s" : ""} flagged as
              outlier
              {composition.outliers.length > 1 ? "s" : ""}.
            </span>{" "}
            An estimator is flagged when its value sits more than 40%
            from the median of the available estimators. Outlier rows
            still contribute to the composite — the flag is
            informational so you can judge whether the composite is a
            consensus signal or an outlier-driven number.
          </p>
        )}
      </details>
    </SummaryCard>
  )
}

export { confidenceTone, pctFormat, pctDeltaFormat }

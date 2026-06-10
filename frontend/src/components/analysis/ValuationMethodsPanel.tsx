/**
 * ValuationMethodsPanel — T5.10 (engine-refinement roadmap, trust +
 * transparency play).
 *
 * Surfaces EVERY valuation estimate the YieldIQ engine has produced for
 * the current ticker — Composite IV, DCF, Peer Multiples, Wall Street
 * consensus, plus the Phase B additions (Three-stage DCF, DDM, EPV,
 * Liquidation, Probability-weighted) once those land in the payload.
 *
 * Design intent:
 *   - Single grid. Each row carries: label, value (₹), gap-vs-price
 *     percent, method tag (when present), one-line description, a
 *     semantic badge (primary / supporting / floor / consensus).
 *   - Render only methods whose `value` is non-null. The rest collapse
 *     into a `<details>` footnote so the reader knows the engine
 *     considered them but they did not apply.
 *   - Empty state when ZERO methods have a value (warming cache / fresh
 *     listing / data-limited ticker).
 *
 * Composition:
 *   - Pure RSC-safe (no client hooks, no `"use client"`) — the
 *     component reads pre-fetched payload data only.
 *   - Reuses PR-B `SummaryCard` for the outer surface and
 *     `MetricTooltip` for hover-explainers on each method tag so the
 *     visual idiom matches HonestHero / ValuationGrid / TransparencyStrip.
 *
 * SEBI lens:
 *   - All copy is descriptive. The gap-vs-price line reads as
 *     "MoS +24% vs current price" (when FV > CP) or "-12% vs current
 *     price" (when FV < CP). No imperative verbs, no buy/sell/hold/
 *     recommend/cheap/expensive/attractive vocabulary.
 *   - The "not applicable" footnotes explain WHY each method was
 *     skipped (e.g. "DDM needs payout >= 30% and a 5+ year dividend
 *     streak") without implying directionality.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import MetricTooltip from "@/components/common/MetricTooltip"
import { cn, formatCurrency } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"

type BadgeKind = "primary" | "supporting" | "floor" | "consensus"

interface MethodEntry {
  key: string
  label: string
  value: number | null
  method?: string | null
  description: string
  badge: BadgeKind
  applicable: boolean
  reasonIfNotApplicable?: string
}

export interface ValuationMethodsPanelProps {
  data: AnalysisResponse
  className?: string
}

/* ─── public API ───────────────────────────────────────────────────── */

export default function ValuationMethodsPanel({
  data,
  className,
}: ValuationMethodsPanelProps) {
  const methods = buildMethodEntries(data)
  const applicableMethods = methods.filter((m) => m.applicable)
  const skippedMethods = methods.filter((m) => !m.applicable)

  if (applicableMethods.length === 0) {
    return (
      <SummaryCard
        data-testid="valuation-methods-panel-empty"
        className={cn("gap-3", className)}
      >
        <h2 className="text-lg font-bold text-ink">
          Valuation methods
        </h2>
        <p className="text-sm text-caption">
          Valuation methods are still computing for this ticker. Check
          back shortly.
        </p>
      </SummaryCard>
    )
  }

  const currentPrice =
    typeof data.valuation?.current_price === "number" &&
    Number.isFinite(data.valuation.current_price) &&
    data.valuation.current_price > 0
      ? data.valuation.current_price
      : null

  const currency = data.company?.currency ?? "INR"
  const ticker = data.company?.ticker ?? data.ticker ?? null
  const displayTicker = ticker ?? "this ticker"

  return (
    <SummaryCard
      data-testid="valuation-methods-panel"
      className={cn("gap-4", className)}
    >
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-bold text-ink">
          How we value {displayTicker}
        </h2>
        <p className="text-xs text-caption leading-snug">
          YieldIQ surfaces multiple independent estimates. Look for
          clustering OR divergence as a confidence signal — when several
          methods agree the centre of gravity is firmer; when they
          disagree the spread tells you the model uncertainty.
        </p>
      </div>

      <div
        role="list"
        className="grid grid-cols-1 md:grid-cols-2 gap-3"
        data-testid="valuation-methods-grid"
      >
        {applicableMethods.map((entry) => (
          <MethodRow
            key={entry.key}
            entry={entry}
            currentPrice={currentPrice}
            currency={currency}
            ticker={ticker}
          />
        ))}
      </div>

      {skippedMethods.length > 0 && (
        <details
          className="rounded-lg border border-border bg-surface px-3 py-2"
          data-testid="valuation-methods-skipped"
        >
          <summary className="cursor-pointer text-[12px] text-caption select-none">
            {skippedMethods.length} method
            {skippedMethods.length === 1 ? "" : "s"} not applicable for
            this ticker
          </summary>
          <ul className="mt-2 space-y-1.5 text-[12px] text-body">
            {skippedMethods.map((m) => (
              <li key={m.key} className="leading-snug">
                <span className="font-semibold text-ink">{m.label}</span>
                <span className="text-caption">
                  {" "}
                  — {m.reasonIfNotApplicable ?? "Data not available for this ticker."}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </SummaryCard>
  )
}

/* ─── method-entry construction ────────────────────────────────────── */

function buildMethodEntries(data: AnalysisResponse): MethodEntry[] {
  const compositeValue = numericOrNull(data.composite_intrinsic_value)
  const dcfValue = numericOrNull(data.valuation?.fair_value)
  const multiplesValue = numericOrNull(data.multiples_based_fv)
  const wallStreetValue =
    numericOrNull(data.analyst_consensus?.price_target?.mean) ??
    numericOrNull(data.insights?.wall_street_avg_target)
  const threeStageValue = numericOrNull(data.three_stage_fv)
  const ddmValue = numericOrNull(data.ddm_fv)
  const epvValue = numericOrNull(data.epv_per_share)
  const liquidationValue = numericOrNull(data.liquidation_per_share)
  const probValue = numericOrNull(data.probability_weighted_fv)

  return [
    {
      key: "composite",
      label: "Composite Intrinsic Value",
      value: compositeValue,
      method: data.composite_components?.method ?? null,
      description:
        "Weighted average of DCF, Peer Multiples, and Wall Street consensus — the headline figure on the hero.",
      badge: "primary",
      applicable: compositeValue !== null,
    },
    {
      key: "dcf",
      label: "DCF Fair Value",
      value: dcfValue,
      method: data.valuation?.valuation_engine_used ?? null,
      description:
        "Two-stage discounted cash flow — projects FCF for 5 years then a terminal value at the long-run growth rate.",
      badge: "supporting",
      applicable: dcfValue !== null && dcfValue > 0,
    },
    {
      key: "multiples",
      label: "Peer Multiples",
      value: multiplesValue,
      method: data.multiples_method ?? null,
      description:
        "Re-prices the stock at the sector-median PE / PB / EV-EBITDA — what would the price be at peer-typical multiples.",
      badge: "supporting",
      applicable: multiplesValue !== null && multiplesValue > 0,
    },
    {
      key: "wall_street",
      label: "Wall Street Consensus",
      value: wallStreetValue,
      method: null,
      description:
        "Mean of published analyst 12-month price targets (Finnhub feed). Third-party reference, not a YieldIQ model output.",
      badge: "consensus",
      applicable: wallStreetValue !== null && wallStreetValue > 0,
    },
    {
      key: "three_stage",
      label: "Three-stage Growth DCF",
      value: threeStageValue,
      method: data.three_stage_method ?? null,
      description:
        "Explicit high-growth phase, then a linear fade, then terminal — Damodaran framework. Useful when growth normalises gradually rather than abruptly.",
      badge: "supporting",
      applicable: threeStageValue !== null && threeStageValue > 0,
      reasonIfNotApplicable:
        "Three-stage DCF activates for tickers with a credible multi-phase growth profile; the two-stage DCF above is the default.",
    },
    {
      key: "ddm",
      label: "Dividend Discount Model",
      value: ddmValue,
      method: data.ddm_method ?? null,
      description:
        "Gordon, two-stage, or H-model — values the stock as the present value of expected future dividends. Built for high-payout businesses.",
      badge: "supporting",
      applicable: ddmValue !== null && ddmValue > 0,
      reasonIfNotApplicable:
        "DDM needs payout >= 30% and a 5+ year dividend streak. Skipped for non-dividend or low-payout businesses.",
    },
    {
      key: "epv",
      label: "Earnings Power Value",
      value: epvValue,
      method: null,
      description:
        "Greenwald no-growth baseline — capitalises normalised earnings without crediting any future growth. The gap to DCF is the value attributable to growth.",
      badge: "supporting",
      applicable: epvValue !== null && epvValue > 0,
      reasonIfNotApplicable:
        "EPV needs 5+ years of stable EBIT to normalise the earnings base. Skipped when the operating history is too short or too volatile.",
    },
    {
      key: "liquidation",
      label: "Liquidation Floor",
      value: liquidationValue,
      method: null,
      description:
        "Graham-style asset recovery floor — what each share would receive if the business wound up its operations and sold its assets. A bottom anchor, not a fair value.",
      badge: "floor",
      applicable: liquidationValue !== null && liquidationValue > 0,
      reasonIfNotApplicable:
        "Liquidation framework not meaningful for asset-light or financial businesses where balance-sheet assets do not represent recoverable value.",
    },
    {
      key: "probability_weighted",
      label: "Probability-weighted FV",
      value: probValue,
      method: data.probability_weighted_method ?? null,
      description:
        "Bull, base, and bear scenarios combined with calibrated probabilities — captures the full distribution of outcomes rather than a single point estimate.",
      badge: "supporting",
      applicable: probValue !== null && probValue > 0,
      reasonIfNotApplicable:
        "Probability-weighted FV activates when the three scenarios are individually credible and have a defensible probability mix.",
    },
  ]
}

/* ─── single method row ────────────────────────────────────────────── */

interface MethodRowProps {
  entry: MethodEntry
  currentPrice: number | null
  currency: string
  ticker: string | null
}

function MethodRow({
  entry,
  currentPrice,
  currency,
  ticker,
}: MethodRowProps) {
  const palette = BADGE_PALETTE[entry.badge]
  const valueText =
    entry.value != null
      ? formatCurrency(entry.value, currency, ticker)
      : "—"
  const gap = computeGapPct(entry.value, currentPrice)
  const gapText = formatGap(gap)
  const gapTone = toneForGap(gap)
  const methodTag = entry.method ? prettifyMethodTag(entry.method) : null

  return (
    <div
      role="listitem"
      data-testid={`valuation-method-${entry.key}`}
      className={cn(
        "rounded-xl border bg-bg p-3 flex flex-col gap-2",
        palette.border,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.15em] text-caption">
            {palette.kicker}
          </p>
          <p className="text-sm font-semibold text-ink leading-tight mt-0.5">
            {entry.label}
          </p>
        </div>
        <span
          aria-label={`${palette.kicker} method`}
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap",
            palette.badge,
          )}
        >
          {palette.kicker}
        </span>
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <MetricTooltip
          label={entry.label}
          showLabel={false}
          title={entry.label}
          description={entry.description}
          ariaValueText={valueText}
          value={
            <span
              className={cn(
                "font-mono tabular-nums text-xl font-semibold",
                palette.value,
              )}
            >
              {valueText}
            </span>
          }
        />
        {gapText && (
          <span
            data-testid={`valuation-method-${entry.key}-gap`}
            className={cn(
              "font-mono tabular-nums text-[12px]",
              gapTone,
            )}
          >
            {gapText}
          </span>
        )}
      </div>

      <p className="text-[12px] text-body leading-snug">{entry.description}</p>

      {methodTag && (
        <p
          data-testid={`valuation-method-${entry.key}-method-tag`}
          className="text-[11px] text-caption"
        >
          Method: <span className="font-mono">{methodTag}</span>
        </p>
      )}
    </div>
  )
}

/* ─── helpers ──────────────────────────────────────────────────────── */

const BADGE_PALETTE: Record<
  BadgeKind,
  { kicker: string; border: string; badge: string; value: string }
> = {
  primary: {
    kicker: "Primary",
    border: "border-tone-info-bd dark:border-blue-900",
    badge:
      "bg-tone-info-bg text-tone-info-fg border-tone-info-bd dark:bg-blue-950/40 dark:text-blue-200 dark:border-blue-900",
    value: "text-ink",
  },
  supporting: {
    kicker: "Supporting",
    border: "border-border",
    badge:
      "bg-tone-neutral-bg text-slate-700 border-tone-neutral-bd dark:bg-slate-800/60 dark:text-slate-200 dark:border-slate-700",
    value: "text-ink",
  },
  floor: {
    kicker: "Floor",
    border: "border-amber-300 dark:border-amber-900",
    badge:
      "bg-tone-warn-bg text-amber-900 border-amber-300 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900",
    value: "text-amber-900 dark:text-amber-200",
  },
  consensus: {
    kicker: "Consensus",
    border: "border-tone-good-bd dark:border-emerald-900",
    badge:
      "bg-tone-good-bg text-tone-good-fg border-tone-good-bd dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900",
    value: "text-ink",
  },
}

function numericOrNull(value: unknown): number | null {
  if (typeof value !== "number") return null
  if (!Number.isFinite(value)) return null
  return value
}

function computeGapPct(value: number | null, currentPrice: number | null): number | null {
  if (value == null || currentPrice == null) return null
  if (!Number.isFinite(value) || !Number.isFinite(currentPrice)) return null
  if (currentPrice <= 0) return null
  return ((value - currentPrice) / currentPrice) * 100
}

/**
 * Descriptive gap line. Positive values frame as "MoS +N% vs current
 * price" (the engine's estimate sits above current); negative values
 * read as "-N% vs current price". Never imperative — no buy/sell verbs.
 */
function formatGap(gap: number | null): string | null {
  if (gap == null || !Number.isFinite(gap)) return null
  const rounded = Math.round(gap * 10) / 10
  if (rounded >= 0) {
    return `MoS +${rounded.toFixed(1)}% vs current price`
  }
  return `${rounded.toFixed(1)}% vs current price`
}

function toneForGap(gap: number | null): string {
  if (gap == null || !Number.isFinite(gap)) return "text-caption"
  if (gap >= 0) return "text-emerald-700 dark:text-emerald-300"
  return "text-rose-700 dark:text-rose-300"
}

function prettifyMethodTag(method: string): string {
  // "two_stage" -> "two stage", "h_model" -> "h model", preserves
  // already-pretty values like "Damodaran fade".
  return method.replace(/_/g, " ")
}

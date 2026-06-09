"use client"

/**
 * DcfMultiplesChip — Sprint A2 (2026-06-09).
 *
 * DCF + Multiples cross-confirmation pill row. Mounted under the
 * headline Fair Value figure in <HonestHero /> so users can read the
 * DCF estimate side-by-side with a peer-relative multiples estimate
 * — closes AlphaSpread's #1 positioning win (their landing page sells
 * "DCF Value + Multiples-Based Value" as the single differentiator).
 *
 * Rendering rules
 * ───────────────
 *   * `multiplesValue == null`        → render nothing (no row, no callout).
 *     Triggered when the ticker has no peer cohort, when the ticker's
 *     own PE/PB is missing or non-positive, or when the cohort median
 *     is missing (banks special case, fresh listings).
 *   * `multiplesValue` present + both methods agree above price
 *                                     → "Both methods estimate fair value above the current Rs.X."
 *   * Both methods agree below price  → "Both methods estimate fair value below the current Rs.X."
 *   * Methods disagree (split)        → "Methods disagree — DCF and sector-median P/E
 *                                       point in different directions."
 *
 * SEBI lens — every visible string is observational / describes the
 * COMPUTATION, never a verdict ("Both methods estimate fair value
 * above the current price." vs the banned "the stock is undervalued").
 * Vocabulary lint owned by scripts/check_sebi_words.py.
 *
 * Dark mode native — pill backgrounds use the design-token slots
 * (bg-tone-*-bg / text-tone-*-fg) which already adapt; borders use
 * neutral / brand tokens so the row reads identically in both themes.
 *
 * Layout — single horizontal row that wraps at narrow widths. The two
 * pills sit side-by-side; the agreement line sits below. No sticky,
 * no portal, no popover — the tooltip on the multiples pill is the
 * existing <MetricTooltip /> primitive so the open/close behaviour
 * matches every other inline tooltip on the page.
 */

import * as React from "react"

import MetricTooltip from "@/components/common/MetricTooltip"
import { cn, formatCurrency } from "@/lib/utils"

export type MultiplesMethod = "pe" | "pb" | "ev_ebitda"

export interface DcfMultiplesChipProps {
  /** Used by formatCurrency for the INR ticker-prefix routing. */
  ticker: string
  /** DCF fair value — the headline number the page already shows. */
  dcfValue: number
  /**
   * Peer-relative multiples fair value. When null the entire pill row
   * does not render — caller can mount this unconditionally.
   */
  multiplesValue: number | null
  /** Which multiple drove the multiples FV. Null mirrors multiplesValue. */
  multiplesMethod: MultiplesMethod | null
  /** Used by the summary line and by the formatCurrency routing. */
  currentPrice: number
  /** Backend currency tag, e.g. "INR". */
  currency: string
  /** Sector-median PE/PB if available — feeds the multiples-pill tooltip. */
  sectorMedianMultiple?: number | null
}

const METHOD_LABEL: Record<MultiplesMethod, string> = {
  pe: "Sector-median P/E",
  pb: "Sector-median P/B",
  ev_ebitda: "Sector-median EV/EBITDA",
}

const METHOD_TOOLTIP_SUFFIX: Record<MultiplesMethod, string> = {
  pe: "applied to current earnings per share.",
  pb: "applied to current book value per share.",
  ev_ebitda: "applied to current EBITDA.",
}

export default function DcfMultiplesChip({
  ticker,
  dcfValue,
  multiplesValue,
  multiplesMethod,
  currentPrice,
  currency,
  sectorMedianMultiple,
}: DcfMultiplesChipProps) {
  // Self-hide when there's no peer cohort / no usable multiple. Render
  // path returns null so the caller doesn't need a wrapper guard.
  if (
    multiplesValue == null ||
    multiplesMethod == null ||
    !Number.isFinite(multiplesValue) ||
    !Number.isFinite(dcfValue) ||
    !Number.isFinite(currentPrice) ||
    currentPrice <= 0
  ) {
    return null
  }

  const dcfDisplay = formatCurrency(dcfValue, currency, ticker)
  const multiplesDisplay = formatCurrency(multiplesValue, currency, ticker)
  const priceDisplay = formatCurrency(currentPrice, currency, ticker)
  const methodLabel = METHOD_LABEL[multiplesMethod]

  const dcfAbove = dcfValue > currentPrice
  const multiplesAbove = multiplesValue > currentPrice
  const bothAbove = dcfAbove && multiplesAbove
  const bothBelow = !dcfAbove && !multiplesAbove
  const agreementText = bothAbove
    ? `Both methods estimate fair value above the current ${priceDisplay}.`
    : bothBelow
      ? `Both methods estimate fair value below the current ${priceDisplay}.`
      : `Methods disagree — DCF and ${methodLabel.toLowerCase()} point in different directions.`

  // Tooltip body for the multiples pill — describes the computation,
  // not a verdict. Inline copy stays under the MetricTooltip's
  // description-line budget so it reads as a single sentence.
  const medianStr =
    sectorMedianMultiple != null && Number.isFinite(sectorMedianMultiple)
      ? sectorMedianMultiple.toFixed(1)
      : null
  const multiplesTooltipDescription = medianStr
    ? `${methodLabel} ${medianStr} ${METHOD_TOOLTIP_SUFFIX[multiplesMethod]}`
    : `${methodLabel} ${METHOD_TOOLTIP_SUFFIX[multiplesMethod]}`

  return (
    <div
      className="mt-3"
      data-testid="dcf-multiples-chip"
      aria-label="DCF and multiples cross-check"
    >
      <p className="text-[10px] uppercase tracking-[0.15em] text-caption">
        Cross-check
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span
          data-testid="dcf-multiples-chip-dcf"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium",
            "border-sky-200 bg-sky-50 text-sky-900",
            "dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-200",
          )}
        >
          <span className="font-mono tabular-nums text-[11px] uppercase tracking-wider opacity-70">
            DCF
          </span>
          <span className="font-mono tabular-nums">{dcfDisplay}</span>
        </span>

        <MetricTooltip
          label="Multiples-based fair value"
          showLabel={false}
          title={methodLabel}
          description={multiplesTooltipDescription}
          formula={
            multiplesMethod === "pe"
              ? "Current Price x (Sector-Median P/E / Ticker P/E)"
              : multiplesMethod === "pb"
                ? "Current Price x (Sector-Median P/B / Ticker P/B)"
                : "Current Price x (Sector-Median EV/EBITDA / Ticker EV/EBITDA)"
          }
          caveat="A peer-relative re-pricing of the current quote, not a separate valuation model. Reads alongside the DCF figure as a second reference."
          value={
            <span
              data-testid="dcf-multiples-chip-multiples"
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium",
                "border-slate-200 bg-slate-50 text-slate-800",
                "dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200",
              )}
            >
              <span className="font-mono tabular-nums text-[11px] uppercase tracking-wider opacity-70">
                {multiplesMethod.toUpperCase().replace("_", "/")}
              </span>
              <span className="font-mono tabular-nums">{multiplesDisplay}</span>
            </span>
          }
        />
      </div>
      <p
        data-testid="dcf-multiples-chip-summary"
        className="mt-1.5 text-[12px] text-caption leading-snug"
      >
        {agreementText}
      </p>
    </div>
  )
}

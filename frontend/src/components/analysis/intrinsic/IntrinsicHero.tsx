"use client"

/**
 * IntrinsicHero — the headline insight card of "1. INTRINSIC VALUE"
 * (feat/intrinsic-value-thesis-redesign).
 *
 * Answers the 5-second question: is the stock priced under or over the
 * model's estimate, and by how much? Composition:
 *
 *   Line 1 (display type):  "{Company} trades"
 *   Line 2 (huge numeral):  "53.7%"  ← count-up via <NumberFlip>
 *                           + "below intrinsic value" in display type
 *                           + a compact confidence badge
 *   Line 3 (supporting):    the SEBI-templated narrative sentence with
 *                           the exact rupee figures in bold ink.
 *
 * Direction handling:
 *   price < IV  → "below intrinsic value", emerald accent (Discount)
 *   price > IV  → "above intrinsic value", rose accent (Premium)
 *   |gap| < 5%  → "within {pct}% of intrinsic value", neutral ink
 *   data-limited → template [D] copy only, no numerals fabricated
 *
 * Vocabulary discipline: descriptive verbs only (trades / reads / sits).
 * The verdict chip itself rides the section heading slot, not this card.
 *
 * BUG-2 regression note (prod "53.7% belowthe"): the direction word and
 * the text after it are joined inside ONE template literal so no JSX
 * line-break can ever swallow the space again. Pinned by the
 * "below the model" assertion in IntrinsicValueSection.test.tsx.
 */

import * as React from "react"

import { NumberFlip } from "@/components/motion"
import { cn, formatCurrency } from "@/lib/utils"

/** |gap| under this % reads as parity (template C). */
export const PARITY_BAND_PCT = 5

/**
 * Signed gap of IV vs price as % of price; null when not computable.
 * (Moved here from the retired IntrinsicValueCard.)
 */
export function intrinsicValueGapPct(
  intrinsicValue: number | null,
  currentPrice: number | null,
): number | null {
  if (
    intrinsicValue == null ||
    currentPrice == null ||
    !Number.isFinite(intrinsicValue) ||
    !Number.isFinite(currentPrice) ||
    intrinsicValue <= 0 ||
    currentPrice <= 0
  ) {
    return null
  }
  return ((intrinsicValue - currentPrice) / currentPrice) * 100
}

export interface IntrinsicHeroProps {
  /** Canonical ticker (suffix ok) — INR override for formatCurrency. */
  ticker: string
  /** Bare display ticker for prose. */
  displayTicker: string
  companyName: string
  currency: string
  /** Canonical headline FV (composite-or-DCF). Null on data-limited. */
  intrinsicValue: number | null
  currentPrice: number | null
  /** Overall model confidence 0-100 for the compact badge. */
  confidence?: number | null
  dataLimited?: boolean
  className?: string
}

function Em({ children }: { children: React.ReactNode }) {
  return <span className="font-semibold text-ink">{children}</span>
}

export default function IntrinsicHero({
  ticker,
  displayTicker,
  companyName,
  currency,
  intrinsicValue,
  currentPrice,
  confidence,
  dataLimited = false,
  className,
}: IntrinsicHeroProps) {
  const fmt = (v: number) => formatCurrency(v, currency, ticker)
  const gap = dataLimited
    ? null
    : intrinsicValueGapPct(intrinsicValue, currentPrice)

  // ── Template [D] — data-limited / unpublished IV ──────────────────
  if (gap == null || intrinsicValue == null || currentPrice == null) {
    return (
      <div data-testid="iv-hero" data-direction="data-limited" className={className}>
        <p
          data-testid="iv-narrative"
          data-template="data-limited"
          className="text-sm md:text-base leading-relaxed text-body"
        >
          An intrinsic value for <Em>{companyName}</Em> ({displayTicker}) is
          not published yet — the model does not have enough reliable data to
          produce a base-case figure. Check back after the next data refresh.
        </p>
      </div>
    )
  }

  const pct = Math.abs(gap)
  const pctText = pct.toFixed(1)
  const parity = pct < PARITY_BAND_PCT
  const below = currentPrice < intrinsicValue
  const direction = below ? "below" : "above"

  const accent = parity
    ? "text-ink"
    : below
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400"

  const confBadge =
    confidence != null && Number.isFinite(confidence) ? (
      <span
        data-testid="iv-hero-confidence"
        className="inline-flex items-center gap-1 rounded-full border border-border bg-surface/60 px-2.5 py-1 text-[11px] font-medium text-caption align-middle"
      >
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand" />
        conf {Math.round(confidence)}%
      </span>
    ) : null

  return (
    <div
      data-testid="iv-hero"
      data-direction={parity ? "parity" : direction}
      className={cn("text-center", className)}
    >
      <p className="text-lg md:text-2xl font-medium tracking-tight text-body">
        {companyName} trades
      </p>

      <div className="mt-1 flex flex-wrap items-baseline justify-center gap-x-3 gap-y-2">
        {parity && (
          <span className="text-lg md:text-2xl font-medium tracking-tight text-ink">
            within
          </span>
        )}
        <span
          data-testid="iv-hero-pct"
          data-direction={below ? "discount" : "premium"}
          className={cn(
            "font-mono tabular-nums font-bold leading-none tracking-tight",
            "text-5xl md:text-7xl",
            accent,
          )}
        >
          <NumberFlip
            value={pct}
            duration={1.4}
            format={(n) => `${n.toFixed(1)}%`}
          />
        </span>
        <span className="text-lg md:text-2xl font-medium tracking-tight text-ink">
          {parity
            ? "of intrinsic value"
            : `${direction} intrinsic value`}
        </span>
        {confBadge}
      </div>

      {parity ? (
        <p
          data-testid="iv-narrative"
          data-template="parity"
          className="mx-auto mt-4 max-w-prose text-[13px] md:text-sm leading-relaxed text-body"
        >
          The intrinsic value of <Em>{companyName}</Em> ({displayTicker}) under
          the base case is <Em>{fmt(intrinsicValue)}</Em>. The current market
          price of <Em>{fmt(currentPrice)}</Em> sits within <Em>{pctText}%</Em>{" "}
          of that figure — close to parity under this model.
        </p>
      ) : (
        <p
          data-testid="iv-narrative"
          data-template={below ? "trades-below" : "trades-above"}
          className="mx-auto mt-4 max-w-prose text-[13px] md:text-sm leading-relaxed text-body"
        >
          The intrinsic value of <Em>{companyName}</Em> ({displayTicker}) under
          the base case is <Em>{fmt(intrinsicValue)}</Em>. Compared with the
          current market price of <Em>{fmt(currentPrice)}</Em>, the stock
          trades <Em>{pctText}%</Em>{" "}
          {`${direction} the model’s intrinsic value.`}
        </p>
      )}
    </div>
  )
}

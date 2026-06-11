"use client"

/**
 * IntrinsicValueCard — AlphaSpread-style right-rail card for the
 * "1. INTRINSIC VALUE" section (feat/alphaspread-style-opening).
 *
 * Composition (top to bottom):
 *   1. "{TICKER} Intrinsic Value" caption
 *   2. Huge canonical IV figure (NumberFlip — acknowledges recomputes)
 *   3. DISCOUNT / PREMIUM badge — flips by sign of (IV − price).
 *      Vocabulary: "Discount to FV" / "Premium to FV" are the
 *      SEBI-cleared descriptive terms this product already uses
 *      (HonestHero dl labels, scripts/check_sebi_words.py allowlist),
 *      so the badge reuses them verbatim.
 *   4. Two-bar IV-vs-Price comparison, proportional widths, grow-from-
 *      left on first paint (≤ 480ms ease-out, no bounce; instant under
 *      prefers-reduced-motion).
 *
 * Data contract: `intrinsicValue` MUST be the canonical headline FV
 * (signals.headlineFairValue / payload.headline_fair_value). This card
 * never reads the DCF-only field.
 *
 * data_limited: the figure renders as an em dash, the badge and the
 * bars are suppressed entirely (no fake zeros, no empty-bar skeleton).
 */

import * as React from "react"
import { motion, useReducedMotion } from "framer-motion"

import { NumberFlip } from "@/components/motion"
import { cn, formatCurrency } from "@/lib/utils"

export interface IntrinsicValueCardProps {
  /** Canonical ticker (suffix ok) — forces INR formatting for .NS/.BO. */
  ticker: string
  /** Bare display ticker for the card caption. */
  displayTicker: string
  currency: string
  /** Canonical headline FV (composite-or-DCF). Null on data-limited. */
  intrinsicValue: number | null
  currentPrice: number | null
  /** Suppresses figure / badge / bars when the model published nothing. */
  dataLimited?: boolean
  className?: string
}

/** Signed gap of IV vs price as % of price; null when not computable. */
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

export default function IntrinsicValueCard({
  ticker,
  displayTicker,
  currency,
  intrinsicValue,
  currentPrice,
  dataLimited = false,
  className,
}: IntrinsicValueCardProps) {
  const usable = !dataLimited && intrinsicValue != null && intrinsicValue > 0
  const gapPct = usable ? intrinsicValueGapPct(intrinsicValue, currentPrice) : null
  // price < IV → the stock trades at a discount to the model's IV.
  const isDiscount = gapPct != null && gapPct >= 0

  return (
    <div
      data-testid="iv-card"
      className={cn(
        "rounded-2xl border border-border bg-surface/60 px-5 py-5 text-center",
        className,
      )}
    >
      <p className="text-[10px] uppercase tracking-[0.15em] text-caption">
        {displayTicker} Intrinsic Value
      </p>

      <p className="mt-2 font-mono tabular-nums text-3xl md:text-4xl font-semibold text-ink leading-none">
        {usable ? (
          <NumberFlip
            value={intrinsicValue}
            format={(n) => formatCurrency(n, currency, ticker)}
          />
        ) : (
          <span aria-label="Intrinsic value unavailable">—</span>
        )}
      </p>

      {gapPct != null && (
        <span
          data-testid="iv-card-badge"
          data-direction={isDiscount ? "discount" : "premium"}
          className={cn(
            "mt-3 inline-flex items-center gap-1.5 rounded-full border px-3 py-1",
            "text-[11px] font-semibold uppercase tracking-wider",
            isDiscount
              ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
              : "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              isDiscount ? "bg-emerald-500" : "bg-rose-500",
            )}
          />
          {isDiscount ? "Discount" : "Premium"} {Math.abs(gapPct).toFixed(1)}%
        </span>
      )}

      {usable && currentPrice != null && currentPrice > 0 && (
        <ComparisonBars
          intrinsicValue={intrinsicValue}
          currentPrice={currentPrice}
          currency={currency}
          ticker={ticker}
        />
      )}

      {!usable && (
        <p className="mt-3 text-[11px] text-caption leading-snug">
          The model does not have enough reliable data to publish an
          intrinsic value for this ticker yet.
        </p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Horizontal IV-vs-Price comparison bars                             */
/* ------------------------------------------------------------------ */

interface ComparisonBarsProps {
  intrinsicValue: number
  currentPrice: number
  currency: string
  ticker: string
}

function ComparisonBars({
  intrinsicValue,
  currentPrice,
  currency,
  ticker,
}: ComparisonBarsProps) {
  const reduceMotion = useReducedMotion()
  const max = Math.max(intrinsicValue, currentPrice)
  if (!(max > 0)) return null

  const rows: Array<{
    key: string
    label: string
    value: number
    barClass: string
  }> = [
    {
      key: "iv",
      label: "Intrinsic Value",
      value: intrinsicValue,
      barClass: "bg-brand",
    },
    {
      key: "price",
      label: "Price",
      value: currentPrice,
      barClass: "bg-slate-400 dark:bg-slate-500",
    },
  ]

  return (
    <div data-testid="iv-card-bars" className="mt-4 space-y-2.5 text-left">
      {rows.map((row) => {
        const widthPct = Math.max(2, (row.value / max) * 100)
        return (
          <div key={row.key} data-testid={`iv-bar-${row.key}`}>
            <div className="flex items-baseline justify-between gap-3 text-[11px]">
              <span className="text-caption">{row.label}</span>
              <span className="font-mono tabular-nums font-semibold text-ink">
                {formatCurrency(row.value, currency, ticker)}
              </span>
            </div>
            <div className="mt-1 h-2 rounded-full bg-border/50 overflow-hidden">
              {/* Grow-from-left draw-in. Width-only transition (no
                  translate) keeps total movement well under the 20px
                  budget; ease-out, never a spring. */}
              <motion.div
                className={cn("h-full rounded-full", row.barClass)}
                initial={reduceMotion ? false : { width: 0 }}
                animate={{ width: `${widthPct}%` }}
                transition={
                  reduceMotion
                    ? { duration: 0 }
                    : { duration: 0.48, ease: [0.4, 0, 0.2, 1] }
                }
                style={reduceMotion ? { width: `${widthPct}%` } : undefined}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

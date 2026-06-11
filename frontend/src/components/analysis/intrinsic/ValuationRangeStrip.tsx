"use client"

/**
 * ValuationRangeStrip — the single large bear→bull range visualization
 * of "1. INTRINSIC VALUE" (feat/intrinsic-value-thesis-redesign).
 *
 * Replaces the old two-bar IV-vs-price card with one horizontal strip:
 *   - a soft gradient band spanning bear → bull (the fair-value range),
 *   - an Intrinsic Value (base case) marker INSIDE the band,
 *   - a distinct Market Price marker that may sit OUTSIDE the band —
 *     the strip's coordinate domain always includes the price so the
 *     marker stays in view, and an "outside bear–bull range" chip
 *     renders as the edge indicator.
 *
 * Motion: the band grows left→right (~600ms ease-out), then the
 * markers drop in with an 80ms stagger. All of it snap-cuts under
 * reduced motion. Max translation 8px — well under the 20px budget.
 *
 * The marker math lives in the exported pure `rangeStripLayout` so the
 * positioning (including the price-outside-band case) is unit-testable
 * without a DOM.
 */

import * as React from "react"
import { motion, useReducedMotion } from "framer-motion"

import { cn, formatCurrency } from "@/lib/utils"

export interface RangeStripLayoutInput {
  bear: number
  bull: number
  /** Canonical headline IV (base-case marker inside the band). */
  intrinsicValue: number
  price: number
}

export interface RangeStripLayout {
  /** Left edge of the gradient band, % of strip width. */
  bandLeftPct: number
  /** Width of the gradient band, % of strip width. */
  bandWidthPct: number
  /** Intrinsic Value marker position, % of strip width. */
  ivPct: number
  /** Market price marker position, % of strip width. */
  pricePct: number
  /** Set when the price sits outside the bear–bull band. */
  priceOutside: "under" | "over" | null
}

const EDGE_PAD_PCT = 2

function clampPct(v: number): number {
  return Math.min(100 - EDGE_PAD_PCT, Math.max(EDGE_PAD_PCT, v))
}

/**
 * Pure marker math. Returns null when any input is non-finite or
 * non-positive (the strip self-hides rather than fabricating zeros).
 * The domain spans every value (bear, bull, IV, price) plus 6%
 * breathing room, so a price under bear / over bull is still placed
 * proportionally inside the visible strip.
 */
export function rangeStripLayout(
  input: RangeStripLayoutInput,
): RangeStripLayout | null {
  const { intrinsicValue, price } = input
  let { bear, bull } = input
  const all = [bear, bull, intrinsicValue, price]
  if (all.some((v) => v == null || !Number.isFinite(v) || v <= 0)) return null
  if (bear > bull) [bear, bull] = [bull, bear]

  const rawMin = Math.min(bear, intrinsicValue, price)
  const rawMax = Math.max(bull, intrinsicValue, price)
  const span = rawMax - rawMin
  const pad = span > 0 ? span * 0.06 : rawMax * 0.06
  const lo = rawMin - pad
  const hi = rawMax + pad
  const width = hi - lo
  if (!(width > 0)) return null

  const pos = (v: number) => clampPct(((v - lo) / width) * 100)

  const bandLeftPct = pos(bear)
  const bandRightPct = pos(bull)
  return {
    bandLeftPct,
    bandWidthPct: Math.max(0, bandRightPct - bandLeftPct),
    ivPct: pos(intrinsicValue),
    pricePct: pos(price),
    priceOutside: price < bear ? "under" : price > bull ? "over" : null,
  }
}

export interface ValuationRangeStripProps {
  ticker: string
  currency: string
  bear: number | null | undefined
  bull: number | null | undefined
  /** Canonical headline IV — the "Base" marker inside the band. */
  intrinsicValue: number | null | undefined
  currentPrice: number | null | undefined
  className?: string
}

const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1]

export default function ValuationRangeStrip({
  ticker,
  currency,
  bear,
  bull,
  intrinsicValue,
  currentPrice,
  className,
}: ValuationRangeStripProps) {
  const reduceMotion = useReducedMotion()
  const layout =
    bear != null && bull != null && intrinsicValue != null && currentPrice != null
      ? rangeStripLayout({
          bear,
          bull,
          intrinsicValue,
          price: currentPrice,
        })
      : null
  if (!layout) return null

  const fmt = (v: number) => formatCurrency(v, currency, ticker)
  const lowEnd = Math.min(bear!, bull!)
  const highEnd = Math.max(bear!, bull!)

  const markerTransition = (order: number) =>
    reduceMotion
      ? { duration: 0 }
      : { duration: 0.4, ease: EASE_OUT, delay: 0.6 + order * 0.08 }

  return (
    <div
      data-testid="iv-range-strip"
      role="img"
      aria-label={`Fair-value range from ${fmt(lowEnd)} (bear) to ${fmt(
        highEnd,
      )} (bull); intrinsic value ${fmt(intrinsicValue!)}; market price ${fmt(
        currentPrice!,
      )}.`}
      className={cn("select-none", className)}
    >
      <div className="relative h-32 md:h-36">
        {/* ── IV marker label (above the band) ─────────────────────── */}
        <motion.div
          data-testid="iv-range-marker-iv"
          className="absolute top-0 z-10 -translate-x-1/2 text-center"
          style={{ left: `${layout.ivPct}%` }}
          initial={reduceMotion ? false : { opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={markerTransition(0)}
        >
          <p className="text-[10px] uppercase tracking-[0.12em] text-caption whitespace-nowrap">
            Intrinsic Value
          </p>
          <p className="font-mono tabular-nums text-[13px] md:text-sm font-semibold text-brand whitespace-nowrap">
            {fmt(intrinsicValue!)}
          </p>
        </motion.div>

        {/* ── Track + gradient band ─────────────────────────────────── */}
        <div className="absolute inset-x-0 top-1/2 h-7 -translate-y-1/2 rounded-full bg-subtle/60 overflow-hidden">
          <motion.div
            data-testid="iv-range-band"
            className={cn(
              "absolute inset-y-0 rounded-full",
              "bg-gradient-to-r from-rose-200/80 via-amber-100/80 to-emerald-200/80",
              "dark:from-rose-900/40 dark:via-amber-900/30 dark:to-emerald-900/40",
            )}
            style={{ left: `${layout.bandLeftPct}%` }}
            initial={reduceMotion ? false : { width: 0 }}
            animate={{ width: `${layout.bandWidthPct}%` }}
            transition={
              reduceMotion ? { duration: 0 } : { duration: 0.6, ease: EASE_OUT }
            }
          />
        </div>

        {/* ── IV tick line through the band ─────────────────────────── */}
        <motion.span
          aria-hidden
          className="absolute top-1/2 z-10 h-10 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand"
          style={{ left: `${layout.ivPct}%` }}
          initial={reduceMotion ? false : { opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={markerTransition(0)}
        />

        {/* ── Price marker (line + label below the band) ────────────── */}
        <motion.span
          aria-hidden
          className="absolute top-1/2 z-10 h-10 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-500 dark:bg-slate-300"
          style={{ left: `${layout.pricePct}%` }}
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={markerTransition(1)}
        />
        <motion.div
          data-testid="iv-range-marker-price"
          className="absolute bottom-0 z-10 -translate-x-1/2 text-center"
          style={{ left: `${layout.pricePct}%` }}
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={markerTransition(1)}
        >
          <p className="font-mono tabular-nums text-[13px] md:text-sm font-semibold text-ink whitespace-nowrap">
            {fmt(currentPrice!)}
          </p>
          <p className="text-[10px] uppercase tracking-[0.12em] text-caption whitespace-nowrap">
            Price
            {layout.priceOutside && (
              <span
                data-testid="iv-range-price-outside"
                className="ml-1 inline-flex items-center rounded-full border border-border bg-surface/80 px-1.5 py-px text-[9px] normal-case tracking-normal text-caption"
              >
                {layout.priceOutside === "under" ? "◂ " : ""}
                outside bear–bull range
                {layout.priceOutside === "over" ? " ▸" : ""}
              </span>
            )}
          </p>
        </motion.div>

        {/* ── Bear / Bull end labels ────────────────────────────────── */}
        <motion.div
          data-testid="iv-range-label-bear"
          className="absolute top-[calc(50%+20px)] -translate-x-1/2 text-center"
          style={{ left: `${layout.bandLeftPct}%` }}
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={markerTransition(2)}
        >
          <p className="text-[10px] uppercase tracking-[0.12em] text-caption">
            Bear
          </p>
          <p className="font-mono tabular-nums text-[12px] text-body">
            {fmt(lowEnd)}
          </p>
        </motion.div>
        <motion.div
          data-testid="iv-range-label-bull"
          className="absolute top-[calc(50%+20px)] -translate-x-1/2 text-center"
          style={{ left: `${layout.bandLeftPct + layout.bandWidthPct}%` }}
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={markerTransition(3)}
        >
          <p className="text-[10px] uppercase tracking-[0.12em] text-caption">
            Bull
          </p>
          <p className="font-mono tabular-nums text-[12px] text-body">
            {fmt(highEnd)}
          </p>
        </motion.div>
      </div>
    </div>
  )
}

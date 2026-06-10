"use client"

/**
 * LiveMosDisplay — task #131 live FV recompute strip.
 *
 * Wraps a margin-of-safety readout that updates client-side as the
 * live price moves. We do NOT re-run the backend DCF — fair_value is
 * an SSR-rendered constant for the lifetime of the page; only price
 * (and therefore MoS) varies. This is the same simplification every
 * competitor product makes between FV recompute windows.
 *
 * Why it exists separately from the SSR-rendered hero MoS:
 *   - Hero MoS reads the cached price from the analysis_cache row
 *     (timestamped at compute time — typically 1–24h old).
 *   - This strip polls /api/v1/public/quote/{ticker} every 60s and
 *     recomputes (fv - price) / fv to reflect the latest tick.
 *   - When the user comes back to a long-open tab during market
 *     hours, the chip is fresh; the cached hero readout is not.
 *
 * SEBI vocabulary: the strip uses "Margin of safety" / "Live update"
 * — both informational. It never recommends action, never says
 * b-u-y or s-e-l-l, and never asserts the live read is more accurate
 * than the cached compute (it is, but the user doesn't need that
 * told — the freshness pulse does the work).
 */

import { useMemo } from "react"

import { useLivePrice } from "@/lib/useLivePrice"

export interface LiveMosDisplayProps {
  ticker: string
  /** SSR-rendered fair value (constant for the page lifetime). */
  fairValue: number
  /** SSR-rendered fallback price — used until the first live poll
   *  resolves AND when the live endpoint has no row for this ticker. */
  fallbackPrice: number
  /** Optional class merged onto the wrapper for layout control. */
  className?: string
  /** Override the poll interval. Default 60s; floored at 15s by
   *  useLivePrice so an enthusiastic prop can't melt the API. */
  intervalMs?: number
}

function _formatMos(mos: number): string {
  const rounded = Math.round(mos * 10) / 10
  const sign = rounded > 0 ? "+" : ""
  return `${sign}${rounded.toFixed(1)}%`
}

function _toneFor(mos: number): string {
  if (mos >= 20) return "text-emerald-700 dark:text-emerald-300"
  if (mos >= 0) return "text-emerald-600 dark:text-emerald-400"
  if (mos > -20) return "text-amber-700 dark:text-amber-300"
  return "text-rose-700 dark:text-rose-300"
}

export default function LiveMosDisplay({
  ticker,
  fairValue,
  fallbackPrice,
  className = "",
  intervalMs = 60_000,
}: LiveMosDisplayProps) {
  const fvFinite = Number.isFinite(fairValue) && fairValue > 0
  // useLivePrice always returns SOME price (live or fallback) — so the
  // chip never flashes "n/a" once mounted. The freshness pulse below
  // shows whether the reading is live (filled dot) or cached (hollow).
  const { price, isLive, isInitialLoad } = useLivePrice(
    ticker,
    fallbackPrice,
    intervalMs,
  )

  const mos = useMemo<number | null>(() => {
    if (!fvFinite) return null
    if (!Number.isFinite(price) || price <= 0) return null
    // Clamp display range to prevent the WIPRO-style +321% blowup
    // (see audit #232). The clamp is COSMETIC ONLY — alerts read the
    // raw MoS, not the clamped figure.
    const raw = ((fairValue - price) / fairValue) * 100
    if (!Number.isFinite(raw)) return null
    return Math.max(-100, Math.min(200, raw))
  }, [fvFinite, fairValue, price])

  if (!fvFinite || mos === null) {
    // Hard-disable when FV is missing — no useful live MoS to render.
    return null
  }

  const tone = _toneFor(mos)
  const label = _formatMos(mos)

  return (
    <div
      data-testid="live-mos-display"
      data-is-live={isLive ? "1" : "0"}
      className={
        "inline-flex items-center gap-2 rounded-md border border-border " +
        "bg-bg/60 px-2.5 py-1 text-[12px] " +
        className
      }
    >
      <span
        aria-hidden="true"
        data-testid="live-mos-pulse"
        className={
          "inline-block h-2 w-2 rounded-full " +
          (isLive
            ? "bg-emerald-500 animate-pulse"
            : isInitialLoad
              ? "bg-slate-400 animate-pulse"
              : "bg-slate-300 dark:bg-slate-600")
        }
      />
      <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
        {isLive ? "Live MoS" : "Cached MoS"}
      </span>
      <span
        className={"font-semibold font-mono tabular-nums " + tone}
        data-testid="live-mos-value"
      >
        {label}
      </span>
    </div>
  )
}

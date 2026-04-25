"use client"

import Link from "next/link"
import type { LiveHolding } from "@/lib/api"

// Small compositions rendered ABOVE the Holdings/Watchlist/Alerts tabs
// on the portfolio page. None of these fetch their own data — the parent
// page already has it from React Query.

// ---- P&L sparkline placeholder -------------------------------------------
// HIDDEN as of 2026-04-22: the backend doesn't expose /portfolio/history,
// and the gradient Total-Value header on the portfolio page already shows
// current value + cumulative P&L abs/%. A dashed "coming soon" card in
// that slot was pure noise — per SEBI guidance we never fake chart data,
// and per product discipline we don't ship empty placeholders.
//
// To restore once GET /portfolio/history ships:
//   1. Re-enable this component body (render a real <svg> sparkline from
//      the returned [{date, value}] series).
//   2. Un-hide the render site in
//      frontend/src/app/(app)/portfolio/page.tsx (search for
//      "PnLSparklinePlaceholder").
export function PnLSparklinePlaceholder() {
  return null
}

// ---- Below-fair-value banner ---------------------------------------------
// SEBI compliance note: factual copy only. We say "trading below our model
// fair value" — NEVER "buy" or "bargain". Threshold is a plain MoS % check
// on positions where fair_value is known.
interface BelowFairValueBannerProps {
  holdings: LiveHolding[]
}

export function BelowFairValueBanner({ holdings }: BelowFairValueBannerProps) {
  // mos_pct > 15 means price is > 15% below the modelled fair value.
  // Positions without a fair-value number are skipped (can't be factual
  // about something the model hasn't produced).
  const below = holdings.filter((h) => h.fair_value != null && h.mos_pct != null && h.mos_pct > 15)
  if (below.length === 0) return null

  const first = below[0]
  const count = below.length
  return (
    <Link
      href={`/analysis/${first.ticker}`}
      className="flex items-center justify-between gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 hover:bg-amber-100 dark:bg-amber-950/30 dark:border-amber-900 dark:hover:bg-amber-950/50 active:scale-[0.99] transition"
    >
      <div className="flex items-start gap-2 min-w-0">
        <svg className="w-4 h-4 mt-0.5 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-amber-900 dark:text-amber-200 truncate">
            {count} holding{count === 1 ? "" : "s"} trading below our model fair value
          </p>
          <p className="text-[11px] text-amber-700 dark:text-amber-300 truncate">
            Starting with {first.display_ticker || first.ticker.replace(".NS", "")} &middot; Model estimate
          </p>
        </div>
      </div>
      <span className="text-xs font-semibold text-amber-700 shrink-0">Review &rarr;</span>
    </Link>
  )
}

"use client"

import Link from "next/link"
import type { LiveHolding } from "@/lib/api"

// Small compositions rendered ABOVE the Holdings/Watchlist/Alerts tabs
// on the portfolio page. None of these fetch their own data — the parent
// page already has it from React Query.

// ---- P&L sparkline placeholder -------------------------------------------
// The backend doesn't expose /portfolio/history yet. Per SEBI guidance we
// never fake chart data, so this is an explicit "coming soon" card rather
// than a generative placeholder. When the endpoint ships, swap the inner
// body for a real <svg> path.
export function PnLSparklinePlaceholder() {
  return (
    <div className="bg-surface rounded-xl border border-dashed border-border p-4">
      <div className="flex items-center justify-between mb-1">
        <p className="text-[10px] font-bold text-caption uppercase tracking-widest">P&amp;L trend (30d)</p>
        <span className="text-[9px] text-caption uppercase tracking-wider">Model estimate</span>
      </div>
      <p className="text-sm text-caption">Performance history coming soon.</p>
    </div>
  )
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
      className="flex items-center justify-between gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 hover:bg-amber-100 active:scale-[0.99] transition"
    >
      <div className="flex items-start gap-2 min-w-0">
        <svg className="w-4 h-4 mt-0.5 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-amber-900 truncate">
            {count} holding{count === 1 ? "" : "s"} trading below our model fair value
          </p>
          <p className="text-[11px] text-amber-700 truncate">
            Starting with {first.display_ticker || first.ticker.replace(".NS", "")} &middot; Model estimate
          </p>
        </div>
      </div>
      <span className="text-xs font-semibold text-amber-700 shrink-0">Review &rarr;</span>
    </Link>
  )
}

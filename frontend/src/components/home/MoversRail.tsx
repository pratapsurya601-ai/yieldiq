"use client"
// TODO: swap to design tokens
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getHoldingsLive, getWatchlist } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import UnlockBadge from "@/components/payg/UnlockBadge"

// Horizontal rail of the user's tracked tickers with today's move. Shows
// holdings if present, otherwise watchlist. If neither, a single skeleton
// card nudges the user to save something.
export default function MoversRail() {
  const token = useAuthStore((s) => s.token)

  const { data: holdingsData } = useQuery({
    queryKey: ["holdings-live-home"],
    queryFn: getHoldingsLive,
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
  const { data: watchlist } = useQuery({
    queryKey: ["watchlist-home"],
    queryFn: getWatchlist,
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const holdings = holdingsData?.holdings ?? []

  type Card = {
    ticker: string
    display: string
    name: string
    /** Today's move in rupees (per-holding, quantity-weighted). Null when live_quote missing. */
    dayAbs: number | null
    /** Today's move in %. Null when live_quote missing. Used for color + fallback display. */
    dayPct: number | null
  }

  let cards: Card[] = []
  if (holdings.length > 0) {
    cards = holdings.slice(0, 8).map((h) => {
      // Clamp absurd daily %s (> ±25% on a single day is almost always
      // a stale-quote bug, e.g. an ex-bonus/ex-split that hasn't been
      // price-adjusted yet). Hiding is safer than misleading a user
      // into thinking their Infy just moved -40% today.
      const rawPct = typeof h.day_change_pct === "number" && Number.isFinite(h.day_change_pct) ? h.day_change_pct : null
      const pctOk = rawPct !== null && Math.abs(rawPct) <= 25
      const rawAbs = typeof h.day_change_abs === "number" && Number.isFinite(h.day_change_abs) ? h.day_change_abs : null
      return {
        ticker: h.display_ticker,
        display: h.display_ticker,
        name: h.company_name,
        dayAbs: pctOk ? rawAbs : null,
        dayPct: pctOk ? rawPct : null,
      }
    })
  } else if (watchlist && watchlist.length > 0) {
    cards = watchlist.slice(0, 8).map((w) => ({
      ticker: w.ticker,
      display: w.ticker,
      name: w.company_name,
      dayAbs: null,
      dayPct: null,
    }))
  }

  // Compact ₹ formatter — mirrors portfolio page so home + full tab
  // use the same units. Signs the output so "+₹1.2K" / "-₹450" format.
  function fmtRsCompact(n: number): string {
    const abs = Math.abs(n)
    const sign = n < 0 ? "-" : "+"
    if (abs >= 10_000_000) return `${sign}\u20B9${(abs / 10_000_000).toFixed(2)}Cr`
    if (abs >= 100_000) return `${sign}\u20B9${(abs / 100_000).toFixed(2)}L`
    if (abs >= 1_000) return `${sign}\u20B9${(abs / 1_000).toFixed(1)}K`
    return `${sign}\u20B9${abs.toFixed(0)}`
  }

  return (
    <section>
      <div className="flex items-baseline justify-between px-4 mb-2">
        {/* Badge semantics: today's P&L (rupees), coloured by direction.
            Source is live_quotes.change_pct applied to current_value —
            wired 2026-04-23 after user feedback that the lifetime-%
            reading on this rail was misleading. Falls back to % only
            when rupee amount isn't derivable. */}
        <h2 className="font-display text-sm font-bold text-ink uppercase tracking-wider">
          Your positions
        </h2>
        {cards.length > 0 && (
          <Link href="/portfolio" className="text-xs font-semibold text-brand">
            See all
          </Link>
        )}
      </div>
      {/* TODO(PR-B, SEBI-compliance): render <PriceTimestamp
           as_of={holdingsData?.as_of ?? null} /> once on the rail
           header row (the cards share one snapshot, so a single
           header-level timestamp is enough). Blocked on
           /api/v1/holdings/live surfacing `as_of`; the underlying
           market_data_service row already has it. */}
      {cards.length === 0 ? (
        <div className="px-4">
          <div className="rounded-xl border border-dashed border-border bg-surface p-4 text-sm text-body">
            Your watchlist will live here. Tap <span aria-hidden>⭐</span> on any
            analysis page to save a stock.
          </div>
        </div>
      ) : (
        <div className="flex gap-2 overflow-x-auto pb-2 snap-x snap-mandatory px-4 scroll-px-4">
          {cards.map((c) => (
            <Link
              key={c.ticker}
              href={`/analysis/${c.ticker}`}
              className="flex-shrink-0 snap-start bg-surface rounded-xl border border-border px-4 py-3 min-w-[150px] hover:border-brand transition"
            >
              <div className="flex items-center gap-1.5">
                <p className="text-xs font-bold text-ink">{c.display}</p>
                <UnlockBadge ticker={c.ticker} size="sm" />
              </div>
              {/* Only render the subtitle when we actually have a company
                  name distinct from the ticker. Some holdings rows come
                  back with company_name == ticker (or empty), which used
                  to render "TATSILV / TATSILV" — ugly and redundant. */}
              {c.name && c.name !== c.ticker && c.name !== c.display ? (
                <p className="text-[10px] text-caption truncate max-w-[130px]">
                  {c.name}
                </p>
              ) : null}
              {c.dayAbs !== null || c.dayPct !== null ? (
                <>
                  <p
                    className={`text-sm font-bold font-mono mt-1 ${
                      (c.dayAbs ?? c.dayPct ?? 0) >= 0 ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {c.dayAbs !== null
                      ? fmtRsCompact(c.dayAbs)
                      : `${(c.dayPct ?? 0) >= 0 ? "+" : ""}${(c.dayPct ?? 0).toFixed(2)}%`}
                  </p>
                  <p className="text-[9px] text-caption uppercase tracking-wider mt-0.5">
                    Today
                  </p>
                </>
              ) : (
                <p className="text-[10px] text-caption font-mono mt-1">
                  Watching
                </p>
              )}
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}

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
    /** Holding's lifetime P&L %, NOT today's move. Null when unknown. */
    pnlPct: number | null
  }

  let cards: Card[] = []
  if (holdings.length > 0) {
    cards = holdings.slice(0, 8).map((h) => {
      // Sanity-clamp absurd values (e.g. cost_basis ≈ 0 producing
      // five-figure pcts, or a stale snapshot showing -50% on a blue
      // chip). Anything beyond ±500% is almost certainly bad data —
      // hide rather than mislead.
      const raw = typeof h.pnl_pct === "number" && Number.isFinite(h.pnl_pct) ? h.pnl_pct : null
      const safe = raw !== null && Math.abs(raw) <= 500 ? raw : null
      return {
        ticker: h.display_ticker,
        display: h.display_ticker,
        name: h.company_name,
        pnlPct: safe,
      }
    })
  } else if (watchlist && watchlist.length > 0) {
    cards = watchlist.slice(0, 8).map((w) => ({
      ticker: w.ticker,
      display: w.ticker,
      name: w.company_name,
      pnlPct: null,
    }))
  }

  return (
    <section>
      <div className="flex items-baseline justify-between px-4 mb-2">
        {/* Renamed from "Your movers" (2026-04-22): the numeric badge is
            holding-period P&L, not today's % move. "Movers" universally
            means intraday change — which we don't have a data source for
            yet. Re-rename to "Your movers" only after wiring a
            daily-change feed. */}
        <h2 className="font-display text-sm font-bold text-ink uppercase tracking-wider">
          Your positions
        </h2>
        {cards.length > 0 && (
          <Link href="/portfolio" className="text-xs font-semibold text-brand">
            See all
          </Link>
        )}
      </div>
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
              {c.pnlPct !== null ? (
                <>
                  <p
                    className={`text-sm font-bold font-mono mt-1 ${
                      c.pnlPct >= 0 ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {c.pnlPct >= 0 ? "+" : ""}
                    {c.pnlPct.toFixed(2)}%
                  </p>
                  <p className="text-[9px] text-caption uppercase tracking-wider mt-0.5">
                    P&amp;L
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

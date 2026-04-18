"use client"
// TODO: swap to design tokens
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getHoldingsLive, getWatchlist } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

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
    changePct: number | null
  }

  let cards: Card[] = []
  if (holdings.length > 0) {
    cards = holdings.slice(0, 8).map((h) => ({
      ticker: h.display_ticker,
      display: h.display_ticker,
      name: h.company_name,
      // holdings-live doesn't ship today's change — use P&L % as the signal
      // until a dedicated "today" field exists.
      changePct: h.pnl_pct,
    }))
  } else if (watchlist && watchlist.length > 0) {
    cards = watchlist.slice(0, 8).map((w) => ({
      ticker: w.ticker,
      display: w.ticker,
      name: w.company_name,
      changePct: null,
    }))
  }

  return (
    <section>
      <div className="flex items-baseline justify-between px-4 mb-2">
        <h2 className="font-display text-sm font-bold text-ink uppercase tracking-wider">
          Your movers
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
              <p className="text-xs font-bold text-ink">{c.display}</p>
              <p className="text-[10px] text-caption truncate max-w-[130px]">
                {c.name}
              </p>
              {c.changePct !== null ? (
                <p
                  className={`text-sm font-bold font-mono mt-1 ${
                    c.changePct >= 0 ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {c.changePct >= 0 ? "+" : ""}
                  {c.changePct.toFixed(2)}%
                </p>
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

"use client"
// Your Watchlist — top 5-8 watched tickers.
// API gap: /api/v1/watchlist/ returns only tickers (and partial metadata
// from the SQLite fallback). FV/MoS for arbitrary watchlist tickers
// would require per-ticker /analysis lookups, which would be slow on
// the home page. v1 renders the symbol list and links to the full
// watchlist page where each row already enriches with FV/MoS.
// Follow-up: a /watchlist/enriched endpoint that joins against
// analysis_cache (mirroring portfolio/holdings-live) would let us
// show FV/MoS inline here without per-row fetches.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getSparklines, getWatchlist } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { Eye, Plus } from "lucide-react"
import TickerAvatar from "@/components/common/TickerAvatar"
import { Sparkline } from "@/components/common/Sparkline"
import PressScale from "@/components/motion/PressScale"

// Refresh cadence mirrors MarketsStrip: 5min during NSE hours, frozen
// after-hours. Daily closes don't change intraday — the only intra-day
// movement happens on the current trading day's row, which the
// bhavcopy ingest doesn't refresh more often than ~15min anyway.
function isMarketHoursIST(): boolean {
  const now = new Date()
  const istMs = now.getTime() + (now.getTimezoneOffset() + 330) * 60 * 1000
  const ist = new Date(istMs)
  const day = ist.getUTCDay()
  if (day === 0 || day === 6) return false
  const hour = ist.getUTCHours()
  return hour >= 9 && hour < 16
}

function Skeleton() {
  return (
    <div className="bg-surface border border-border rounded-2xl p-4 min-h-[260px]">
      <div className="h-4 w-32 bg-border rounded animate-pulse mb-3" />
      {[...Array(5)].map((_, i) => (
        <div key={i} className="h-8 bg-border/60 rounded animate-pulse mb-1.5" />
      ))}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="bg-surface border border-border rounded-2xl p-6 text-center">
      <Eye className="w-5 h-5 text-caption mx-auto mb-2" />
      <h3 className="text-sm font-semibold text-ink mb-1">Your Watchlist</h3>
      <p className="text-xs text-body mb-4">
        Track stocks you don&apos;t own yet. Get alerts when MoS crosses your threshold.
      </p>
      <PressScale>
        <Link
          href="/screener"
          className="inline-flex items-center gap-1.5 bg-bg border border-border text-ink text-xs font-semibold px-3 py-1.5 rounded-lg hover:border-brand transition"
        >
          <Plus className="w-3.5 h-3.5" />
          Find stocks
        </Link>
      </PressScale>
    </div>
  )
}

export default function WatchlistPanel() {
  const token = useAuthStore(s => s.token)
  const { data, isLoading } = useQuery({
    queryKey: ["watchlist-home-v2"],
    queryFn: getWatchlist,
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const items = data ?? []
  // Sparkline batch — one round-trip on mount per watchlist composition.
  // We strip suffixes so the cache key collapses across the .NS / bare
  // duality the backend already handles; staleTime keeps a re-render
  // from refetching, and the in-market-hours refetchInterval keeps the
  // 7-day series live across the trading day without burning the API
  // when no one would benefit anyway.
  const watchlistTickers = items.slice(0, 8).map(w => w.ticker.replace(/\.(NS|BO)$/, ""))
  const { data: sparklinesResp } = useQuery({
    queryKey: ["watchlist-sparklines", watchlistTickers.sort().join(",")],
    queryFn: () => getSparklines(watchlistTickers, "7d"),
    enabled: watchlistTickers.length > 0,
    staleTime: 60 * 1000,
    refetchInterval: () => (isMarketHoursIST() ? 5 * 60 * 1000 : false),
    refetchIntervalInBackground: false,
    retry: 1,
  })
  const sparkSeries = sparklinesResp?.series ?? {}

  if (isLoading) return <Skeleton />
  if (items.length === 0) return <EmptyState />

  return (
    <div className="bg-surface border border-border rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold text-ink">Your Watchlist</h3>
          <p className="text-[11px] text-caption mt-0.5">{items.length} tracked</p>
        </div>
        <Link href="/watchlist" className="text-xs font-semibold text-brand hover:underline">
          See all →
        </Link>
      </div>
      <ul className="divide-y divide-border">
        {items.slice(0, 8).map(w => {
          const display = w.ticker.replace(/\.(NS|BO)$/, "")
          const series = sparkSeries[display]
          return (
            <li key={w.ticker}>
              <Link
                href={`/analysis/${display}`}
                className="flex items-center justify-between px-4 py-2.5 hover:bg-bg/50 transition"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <TickerAvatar ticker={w.ticker} size="md" />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-ink truncate">{display}</p>
                    {w.company_name && (
                      <p className="text-[10px] text-caption truncate">{w.company_name}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 ml-2">
                  {series && series.length >= 2 && (
                    <Sparkline values={series} width={56} height={18} />
                  )}
                  <span className="text-[11px] text-brand font-semibold whitespace-nowrap">View →</span>
                </div>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

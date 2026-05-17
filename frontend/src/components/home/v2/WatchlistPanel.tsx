"use client"
// Your Watchlist — top 5-8 watched tickers.
// API gap: /api/v1/watchlist/ returns only tickers (and partial metadata
// from the SQLite fallback). FV/MoS for arbitrary watchlist tickers
// would require per-ticker /analysis lookups, which would be slow on
// the home page. v1 renders the symbol list and links to the full
// watchlist page where each row already enriches with FV/MoS.
// TODO: backend should expose a /watchlist/enriched endpoint that
// joins against analysis_cache, mirroring portfolio/holdings-live.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getWatchlist } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { Eye, Plus } from "lucide-react"

function Skeleton() {
  return (
    <div className="bg-surface border border-border rounded-2xl p-4">
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
      <Link
        href="/screener"
        className="inline-flex items-center gap-1.5 bg-bg border border-border text-ink text-xs font-semibold px-3 py-1.5 rounded-lg hover:border-brand transition"
      >
        <Plus className="w-3.5 h-3.5" />
        Find stocks
      </Link>
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

  if (isLoading) return <Skeleton />
  const items = data ?? []
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
          return (
            <li key={w.ticker}>
              <Link
                href={`/analysis/${display}`}
                className="flex items-center justify-between px-4 py-2.5 hover:bg-bg/50 transition"
              >
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-ink truncate">{display}</p>
                  {w.company_name && (
                    <p className="text-[10px] text-caption truncate">{w.company_name}</p>
                  )}
                </div>
                <span className="text-[11px] text-brand font-semibold">View →</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

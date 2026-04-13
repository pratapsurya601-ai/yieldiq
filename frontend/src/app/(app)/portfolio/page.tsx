"use client"
import { useQuery } from "@tanstack/react-query"
import { getHoldings, getPortfolioHealth, getWatchlist } from "@/lib/api"
import HealthScore from "@/components/portfolio/HealthScore"
import PortfolioEmpty from "@/components/empty-states/PortfolioEmpty"
import WatchlistEmpty from "@/components/empty-states/WatchlistEmpty"
import { formatCurrency, formatPct } from "@/lib/utils"
import { useState } from "react"
import Link from "next/link"

export default function PortfolioPage() {
  const [tab, setTab] = useState<"holdings" | "watchlist">("holdings")
  const { data: holdings } = useQuery({ queryKey: ["holdings"], queryFn: getHoldings })
  const { data: health } = useQuery({ queryKey: ["portfolio-health"], queryFn: getPortfolioHealth })
  const { data: watchlist } = useQuery({ queryKey: ["watchlist"], queryFn: getWatchlist })

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5 pb-20">
      {/* Health Score */}
      {health && health.score > 0 && (
        <HealthScore score={health.score} grade={health.grade} summary={health.summary} issues={health.issues} strengths={health.strengths} />
      )}

      {/* Tabs — iOS segmented control style */}
      <div className="flex bg-gray-100 rounded-xl p-1">
        <button onClick={() => setTab("holdings")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "holdings" ? "bg-white text-gray-900 shadow-sm ring-1 ring-black/5" : "text-gray-500 hover:text-gray-700"}`}>
          Holdings
        </button>
        <button onClick={() => setTab("watchlist")}
          className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all ${tab === "watchlist" ? "bg-white text-gray-900 shadow-sm ring-1 ring-black/5" : "text-gray-500 hover:text-gray-700"}`}>
          Watchlist
        </button>
      </div>

      {tab === "holdings" && (
        holdings && holdings.length > 0 ? (
          <div className="space-y-2">
            {holdings.map((h: { ticker: string; entry_price: number; mos_pct: number; signal: string; sector: string }) => (
              <Link key={h.ticker} href={`/analysis/${h.ticker}`}
                className="flex items-center justify-between bg-white rounded-xl border border-gray-100 p-4 hover:border-blue-200 transition">
                <div>
                  <p className="font-medium text-gray-900">{h.ticker.replace(".NS", "")}</p>
                  <p className="text-xs text-gray-400">{h.sector}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-mono">{formatCurrency(h.entry_price, "INR")}</p>
                  <p className={`text-xs font-mono ${h.mos_pct > 0 ? "text-blue-700" : "text-amber-600"}`}>
                    {formatPct(h.mos_pct)}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <div className="w-20 h-20 mx-auto mb-4 text-gray-200 animate-pulse">
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75a23.978 23.978 0 01-7.577-1.22 2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
            </div>
            <p className="text-base font-semibold text-gray-700 mb-1">No holdings yet</p>
            <p className="text-sm text-gray-400 mb-4">Your portfolio is empty. Analyse a stock and add it to track your investments.</p>
            <Link href="/search" className="text-sm text-blue-600 font-medium hover:underline">Analyse a stock</Link>
          </div>
        )
      )}

      {tab === "watchlist" && (
        watchlist && watchlist.length > 0 ? (
          <div className="space-y-2">
            {watchlist.map((w: { ticker: string; company_name: string; target_price: number }) => (
              <Link key={w.ticker} href={`/analysis/${w.ticker}`}
                className="flex items-center justify-between bg-white rounded-xl border border-gray-100 p-4 hover:border-blue-200 transition">
                <div>
                  <p className="font-medium text-gray-900">{w.ticker.replace(".NS", "")}</p>
                  <p className="text-xs text-gray-400">{w.company_name}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-mono text-gray-500">Target: {formatCurrency(w.target_price, "INR")}</p>
                </div>
              </Link>
            ))}
          </div>
        ) : <WatchlistEmpty />
      )}
    </div>
  )
}

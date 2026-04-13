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
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
      {/* Health Score */}
      {health && health.score > 0 && (
        <HealthScore score={health.score} grade={health.grade} summary={health.summary} issues={health.issues} strengths={health.strengths} />
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
        <button onClick={() => setTab("holdings")}
          className={`flex-1 py-2 rounded-md text-sm font-medium transition ${tab === "holdings" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>
          Holdings
        </button>
        <button onClick={() => setTab("watchlist")}
          className={`flex-1 py-2 rounded-md text-sm font-medium transition ${tab === "watchlist" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>
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
        ) : <PortfolioEmpty />
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

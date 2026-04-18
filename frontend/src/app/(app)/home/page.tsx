"use client"
import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { getMarketPulse, getTopPick, getMacroSummary } from "@/lib/api"
import TopPickCard from "@/components/discover/TopPickCard"
import HomeEmpty from "@/components/empty-states/HomeEmpty"
import MacroDashboard from "@/components/home/MacroDashboard"
import { formatPct } from "@/lib/utils"
import Link from "next/link"

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  return "Good evening"
}

export default function HomePage() {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const greeting = mounted ? getGreeting() : "Welcome back"

  const { data: pulse } = useQuery({ queryKey: ["market-pulse"], queryFn: () => getMarketPulse(true), staleTime: 4 * 60 * 1000 })
  const { data: macroSummary } = useQuery({
    queryKey: ["macro-summary"],
    queryFn: () => getMacroSummary(),
    staleTime: 24 * 60 * 60 * 1000,
    retry: 1,
  })
  const { data: topPick } = useQuery({ queryKey: ["top-pick"], queryFn: getTopPick, staleTime: 86400000 })
  const hasData = !!topPick

  return (
    <div className="max-w-2xl md:max-w-4xl lg:max-w-5xl mx-auto pb-20">
      {/* Gradient header */}
      <div className="bg-gradient-to-b from-blue-50 to-white px-4 pt-6 pb-4">
        <h1 className="text-lg font-bold text-gray-900">{greeting}</h1>
        <p className="text-xs text-gray-500 mt-0.5">Here is your market overview</p>
      </div>

      <div className="px-4 space-y-6">
        {/* Macro Dashboard — FII/DII, FX, commodities, risk-free rate */}
        {pulse && (
          <MacroDashboard
            pulse={pulse}
            ai_summary={macroSummary?.summary ?? null}
          />
        )}

        {/* Market Pulse */}
        {pulse && pulse.indices && pulse.indices.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-2">
            {pulse.indices.map((idx) => (
              <div
                key={idx.name}
                className={`flex-shrink-0 bg-white rounded-xl border border-gray-100 px-4 py-3 text-center min-w-[140px] border-l-[3px] ${idx.change_pct >= 0 ? "border-l-green-500" : "border-l-red-500"}`}
              >
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">{idx.name}</p>
                <p className="text-lg font-bold text-gray-900">{idx.price.toLocaleString()}</p>
                <p className={`text-xs font-bold ${idx.change_pct >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {idx.change_pct >= 0 ? "\u25b2" : "\u25bc"} {formatPct(idx.change_pct)}
                </p>
              </div>
            ))}
            {pulse.fear_greed_label && (
              <div className="flex-shrink-0 bg-white rounded-xl border border-gray-100 border-l-[3px] border-l-amber-500 px-4 py-3 text-center min-w-[140px]">
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">Sentiment</p>
                <p className="text-lg font-bold text-gray-900">{pulse.fear_greed_index}</p>
                <p className="text-xs font-bold text-amber-600">{pulse.fear_greed_label}</p>
              </div>
            )}
          </div>
        )}

        {hasData && topPick && topPick.score > 0 ? (
          <>
            <div>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Highest YieldIQ score today</p>
              <TopPickCard
                ticker={topPick.ticker}
                companyName={topPick.company_name || topPick.ticker}
                score={topPick.score}
                mos={topPick.mos}
                moat={topPick.moat || "Narrow"}
                summary={topPick.summary || ""}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Link href="/search" className="flex items-center justify-center bg-blue-600 text-white rounded-xl py-3 font-medium text-sm hover:bg-blue-700 transition">
                Analyse a stock
              </Link>
              <Link href="/discover" className="flex items-center justify-center bg-white border border-gray-200 rounded-xl py-3 font-medium text-sm text-gray-700 hover:bg-gray-50 transition">
                View YieldIQ 50
              </Link>
            </div>
          </>
        ) : (
          <HomeEmpty />
        )}
      </div>
    </div>
  )
}

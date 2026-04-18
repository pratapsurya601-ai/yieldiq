"use client"
import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { getMarketPulse, getTopPick, getMacroSummary } from "@/lib/api"
import TopPickCard from "@/components/discover/TopPickCard"
import HomeEmpty from "@/components/empty-states/HomeEmpty"
import MacroDashboard from "@/components/home/MacroDashboard"
import { formatPct } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"
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

  const tier = useAuthStore((s) => s.tier)
  const analysesToday = useAuthStore((s) => s.analysesToday)
  const rawLimit = TIER_LIMITS[tier]
  const dailyLimit = typeof rawLimit === "number" ? rawLimit : null
  const remaining = dailyLimit !== null ? Math.max(0, dailyLimit - analysesToday) : null
  const showQuotaWarning = tier === "free" && remaining !== null && remaining <= 1

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
        {/* Proactive quota warning — avoids the 429-surprise on the
            analysis page when a free user is about to burn their last one. */}
        {showQuotaWarning && mounted && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center">
              <svg className="w-4 h-4 text-amber-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-900">
                {remaining === 0 ? "You\u2019ve used all 5 analyses today" : "1 analysis left today"}
              </p>
              <p className="text-xs text-amber-800 mt-0.5">
                {remaining === 0
                  ? "Daily quota resets at midnight IST. Upgrade to Pro for unlimited analyses."
                  : "Make it count \u2014 or upgrade to Pro for unlimited analyses (\u20B9299/mo)."}
              </p>
            </div>
            <Link
              href="/pricing"
              className="flex-shrink-0 bg-amber-600 text-white text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-amber-700 transition"
            >
              Upgrade
            </Link>
          </div>
        )}

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

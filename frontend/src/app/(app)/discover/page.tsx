"use client"
import { useQuery } from "@tanstack/react-query"
import { getYieldIQ50, getTopPick } from "@/lib/api"
import TopPickCard from "@/components/discover/TopPickCard"
import ScreenerPresetsWithCounts from "@/components/discover/ScreenerPresetsWithCounts"
import { SectorLeaders, NearLowsRail, LowestPERail } from "@/components/discover/DiscoverRails"
import { useAuthStore } from "@/store/authStore"
import Link from "next/link"

const RANK_COLORS = ["bg-yellow-500", "bg-gray-400", "bg-amber-600"]

export default function DiscoverPage() {
  const { tier } = useAuthStore()
  const { data: topPick } = useQuery({ queryKey: ["top-pick"], queryFn: getTopPick, staleTime: 86400000 })
  const { data: yiq50 } = useQuery({ queryKey: ["yieldiq50"], queryFn: getYieldIQ50, staleTime: 86400000 })

  return (
    <div className="max-w-2xl md:max-w-4xl lg:max-w-5xl mx-auto px-4 py-6 space-y-8 pb-20">
      {/* Highest-scored stock today */}
      {topPick && (
        <section>
          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">Highest YieldIQ score today</p>
          <TopPickCard
            ticker={topPick.ticker}
            companyName={topPick.company_name || topPick.ticker}
            score={topPick.score}
            mos={topPick.mos}
            moat={topPick.moat || "Narrow"}
            summary={topPick.summary || ""}
          />
          <p className="text-[10px] text-gray-500 mt-1">Updated daily. Based on YieldIQ 50 model. Not investment advice.</p>
        </section>
      )}

      {/* YieldIQ 50 */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">YieldIQ 50</p>
          <p className="text-[10px] text-gray-500">Updated daily</p>
        </div>
        {yiq50 && yiq50.results.length > 0 ? (
          <>
            <div className="grid grid-cols-3 gap-2 mb-3">
              {yiq50.results.slice(0, 3).map((s, i) => (
                <Link key={s.ticker} href={`/analysis/${s.ticker}`}
                  className="relative bg-white rounded-xl border border-gray-100 p-4 min-h-[96px] text-center hover:border-blue-300 hover:shadow-sm active:scale-[0.98] transition">
                  {/* Rank badge */}
                  <span className={`absolute -top-2 -left-2 w-6 h-6 rounded-full ${RANK_COLORS[i]} text-white text-[10px] font-bold flex items-center justify-center shadow-sm`}>
                    #{i + 1}
                  </span>
                  <p className="text-sm font-bold text-gray-900 truncate">{s.ticker.replace(".NS", "")}</p>
                  <p className="text-lg font-bold text-blue-700 font-mono">{s.margin_of_safety > 0 ? "+" : ""}{s.margin_of_safety.toFixed(0)}%</p>
                  <p className="text-[10px] text-gray-500">Score: {s.score}</p>
                </Link>
              ))}
            </div>
            {tier !== "free" && yiq50.results.length > 3 && (
              <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-[10px] text-gray-400 uppercase">
                      <th className="text-left px-3 py-2">#</th>
                      <th className="text-left px-3 py-2">Ticker</th>
                      <th className="text-right px-3 py-2">Score</th>
                      <th className="text-right px-3 py-2">MoS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {yiq50.results.map((s, i) => (
                      <tr key={s.ticker} className={`border-b border-gray-50 hover:bg-blue-50 transition-colors ${i % 2 === 1 ? "bg-gray-50/50" : ""}`}>
                        <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                        <td className="px-3 py-2 font-medium">
                          <Link href={`/analysis/${s.ticker}`} className="text-blue-700 hover:underline">
                            {s.ticker.replace(".NS", "")}
                          </Link>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{s.score}</td>
                        <td className="px-3 py-2 text-right font-mono">{s.margin_of_safety > 0 ? "+" : ""}{s.margin_of_safety.toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {tier === "free" && (
              <div className="bg-gray-50 rounded-xl border border-gray-100 p-4 text-center">
                <p className="text-lg font-bold text-gray-400">+{Math.max(0, yiq50.total - 3)} more</p>
                <p className="text-xs text-gray-400 mb-2">Starter plan</p>
                <Link href="/account" className="text-xs text-blue-600 font-medium hover:underline">Unlock all 50</Link>
              </div>
            )}
          </>
        ) : (
          <div className="bg-white border border-gray-100 rounded-xl p-6 text-center">
            <div className="mx-auto h-12 w-12 rounded-full bg-blue-50 flex items-center justify-center mb-3">
              <svg className="h-6 w-6 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-gray-900 mb-1">YieldIQ 50 is warming up</p>
            <p className="text-xs text-gray-500 mb-4 max-w-xs mx-auto">The daily ranking rebuilds as stocks are analysed. Run an analysis to seed the index.</p>
            <Link href="/search" className="inline-flex items-center justify-center min-h-[40px] px-5 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 active:scale-[0.98] transition">
              Analyse a stock
            </Link>
          </div>
        )}
      </section>

      {/* Sector leaders — top ticker per sector from YieldIQ 50 */}
      {yiq50 && yiq50.results.length > 0 && (
        <SectorLeaders stocks={yiq50.results} />
      )}

      {/* 52-week lows with strong fundamentals — placeholder until data ships */}
      <NearLowsRail />

      {/* Lowest P/E in YieldIQ 50 — placeholder until multiple fields land */}
      {yiq50 && <LowestPERail stocks={yiq50.results} />}

      {/* Screener Presets */}
      <section>
        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3">Screener</p>
        <ScreenerPresetsWithCounts />
      </section>
    </div>
  )
}

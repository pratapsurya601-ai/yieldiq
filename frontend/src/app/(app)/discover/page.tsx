"use client"
import { useQuery } from "@tanstack/react-query"
import { getYieldIQ50, getTopPick } from "@/lib/api"
import TopPickCard from "@/components/discover/TopPickCard"
import ScreenerPresets from "@/components/discover/ScreenerPresets"
import { useAuthStore } from "@/store/authStore"
import Link from "next/link"

const RANK_COLORS = ["bg-yellow-500", "bg-gray-400", "bg-amber-600"]

export default function DiscoverPage() {
  const { tier } = useAuthStore()
  const { data: topPick } = useQuery({ queryKey: ["top-pick"], queryFn: getTopPick, staleTime: 86400000 })
  const { data: yiq50 } = useQuery({ queryKey: ["yieldiq50"], queryFn: getYieldIQ50, staleTime: 86400000 })

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-8 pb-20">
      {/* Highest-scored stock today */}
      {topPick && (
        <section>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Highest YieldIQ score today</p>
          <TopPickCard
            ticker={topPick.ticker}
            companyName={topPick.company_name || topPick.ticker}
            score={topPick.score}
            mos={topPick.mos}
            moat={topPick.moat || "Narrow"}
            summary={topPick.summary || ""}
          />
          <p className="text-[10px] text-gray-400 mt-1">Updated daily. Based on YieldIQ 50 model. Not investment advice.</p>
        </section>
      )}

      {/* YieldIQ 50 */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">YieldIQ 50</p>
          <p className="text-[10px] text-gray-400">Updated daily</p>
        </div>
        {yiq50 && yiq50.results.length > 0 ? (
          <>
            <div className="grid grid-cols-3 gap-2 mb-3">
              {yiq50.results.slice(0, 3).map((s, i) => (
                <Link key={s.ticker} href={`/analysis/${s.ticker}`}
                  className="relative bg-white rounded-xl border border-gray-100 p-3 text-center hover:border-blue-200 transition">
                  {/* Rank badge */}
                  <span className={`absolute -top-2 -left-2 w-6 h-6 rounded-full ${RANK_COLORS[i]} text-white text-[10px] font-bold flex items-center justify-center shadow-sm`}>
                    #{i + 1}
                  </span>
                  <p className="text-sm font-bold text-gray-900">{s.ticker.replace(".NS", "")}</p>
                  <p className="text-lg font-bold text-blue-700 font-mono">{s.margin_of_safety > 0 ? "+" : ""}{s.margin_of_safety.toFixed(0)}%</p>
                  <p className="text-[10px] text-gray-400">Score: {s.score}</p>
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
          <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-center text-sm text-blue-700">
            Index building in progress. Analyse stocks to populate the YieldIQ 50.
          </div>
        )}
      </section>

      {/* Screener Presets */}
      <section>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Screener</p>
        <ScreenerPresets />
      </section>
    </div>
  )
}

"use client"

import { useState, useMemo } from "react"
import Link from "next/link"
import MarketingTopNav from "@/components/marketing/MarketingTopNav"

interface Stock {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string
  current_price: number
  fair_value: number
  mos: number
  verdict: string
  score: number
  grade: string
  moat: string
  market_cap: number
}

interface DashboardData {
  index_id: string
  index_name: string
  description: string
  total_stocks: number
  available_stocks: number
  stocks: Stock[]
  summary: {
    undervalued: number
    fairly_valued: number
    overvalued: number
    most_undervalued: Stock | null
    most_overvalued: Stock | null
  }
}

type SortKey = "score" | "mos" | "current_price" | "fair_value" | "company_name"
type SortDir = "asc" | "desc"

function fmt(n: number): string {
  return n ? `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "\u2014"
}

function verdictBadge(v: string) {
  // SEBI-safe: "avoid" → "High Risk" (descriptive, not advice)
  const label = v === "avoid" ? "High Risk" : v.replace(/_/g, " ")
  if (v === "undervalued") return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-green-50 text-green-700 capitalize">{label}</span>
  if (v === "overvalued" || v === "avoid") return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-50 text-red-700 capitalize">{label}</span>
  return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 capitalize">{label}</span>
}

function rowBg(mos: number): string {
  if (mos > 20) return "bg-green-50/50"
  if (mos < -20) return "bg-red-50/50"
  return ""
}

export default function IndexDashboardClient({ data }: { data: DashboardData }) {
  const [sortKey, setSortKey] = useState<SortKey>("score")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const [sectorFilter, setSectorFilter] = useState("")

  const sectors = useMemo(() => {
    const s = new Set(data.stocks.map(st => st.sector).filter(Boolean))
    return Array.from(s).sort()
  }, [data.stocks])

  const sorted = useMemo(() => {
    let filtered = data.stocks
    if (sectorFilter) filtered = filtered.filter(s => s.sector === sectorFilter)
    return [...filtered].sort((a, b) => {
      const aVal = a[sortKey] ?? 0
      const bVal = b[sortKey] ?? 0
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
      }
      return sortDir === "asc" ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number)
    })
  }, [data.stocks, sortKey, sortDir, sectorFilter])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc")
    else { setSortKey(key); setSortDir("desc") }
  }

  const arrow = (key: SortKey) => sortKey === key ? (sortDir === "desc" ? " \u25BC" : " \u25B2") : ""

  const { summary } = data

  return (
    <div className="min-h-screen bg-white">
      <MarketingTopNav />

      {/* Header */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12 sm:py-16">
        <div className="max-w-6xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">{data.index_name}</h1>
          <p className="text-gray-400 mb-6">{data.description} &middot; Updated daily &middot; Powered by DCF</p>

          {/* Summary stats */}
          <div className="flex flex-wrap justify-center gap-4 sm:gap-8">
            <div className="bg-white/5 border border-white/10 rounded-xl px-5 py-3 text-center">
              <p className="text-2xl font-black text-green-400">{summary.undervalued}</p>
              <p className="text-xs text-gray-400">Undervalued</p>
            </div>
            <div className="bg-white/5 border border-white/10 rounded-xl px-5 py-3 text-center">
              <p className="text-2xl font-black text-blue-400">{summary.fairly_valued}</p>
              <p className="text-xs text-gray-400">Fairly Valued</p>
            </div>
            <div className="bg-white/5 border border-white/10 rounded-xl px-5 py-3 text-center">
              <p className="text-2xl font-black text-red-400">{summary.overvalued}</p>
              <p className="text-xs text-gray-400">Overvalued</p>
            </div>
          </div>

          {summary.most_undervalued && (
            <p className="text-sm text-gray-400 mt-4">
              Most undervalued: <span className="text-green-400 font-semibold">{summary.most_undervalued.display_ticker}</span> (+{summary.most_undervalued.mos.toFixed(1)}%)
              {summary.most_overvalued && (
                <> &middot; Most overvalued: <span className="text-red-400 font-semibold">{summary.most_overvalued.display_ticker}</span> ({summary.most_overvalued.mos.toFixed(1)}%)</>
              )}
            </p>
          )}
        </div>
      </section>

      {/* Table */}
      <section className="max-w-6xl mx-auto px-4 py-8">
        {/* Filter */}
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-gray-500">
            Showing {sorted.length} of {data.available_stocks} stocks
            {data.available_stocks < data.total_stocks && (
              <span className="text-gray-400"> (cache warming — {data.total_stocks - data.available_stocks} remaining)</span>
            )}
          </p>
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700"
          >
            <option value="">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-500 w-10">#</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggleSort("company_name")}>
                  Company{arrow("company_name")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggleSort("current_price")}>
                  Price{arrow("current_price")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggleSort("fair_value")}>
                  Fair Value{arrow("fair_value")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggleSort("mos")}>
                  MoS%{arrow("mos")}
                </th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggleSort("score")}>
                  Score{arrow("score")}
                </th>
                <th className="text-center px-4 py-3 font-semibold text-gray-500">Verdict</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-500 hidden sm:table-cell">Sector</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, i) => (
                <tr key={s.ticker} className={`border-b border-gray-100 hover:bg-gray-50 transition cursor-pointer ${rowBg(s.mos)}`}>
                  <td className="px-4 py-3 text-gray-500 text-xs">{i + 1}</td>
                  <td className="px-4 py-3">
                    <Link href={`/stocks/${s.display_ticker}/fair-value`} className="hover:text-blue-600 transition">
                      <p className="font-semibold text-gray-900">{s.display_ticker}</p>
                      <p className="text-xs text-gray-600 truncate max-w-[180px]">{s.company_name}</p>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-900">{fmt(s.current_price)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-900">{fmt(s.fair_value)}</td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${s.mos >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {s.mos >= 0 ? "+" : ""}{s.mos.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-right font-bold text-gray-900">{s.score}</td>
                  <td className="px-4 py-3 text-center">{verdictBadge(s.verdict)}</td>
                  <td className="px-4 py-3 text-xs text-gray-600 hidden sm:table-cell">{s.sector}</td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-gray-600">
                    No data available yet. Cache is warming up — check back in a few minutes.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-gray-50 border-t border-gray-100 py-12">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h2 className="text-2xl font-black text-gray-900 mb-3">Want full DCF analysis for any stock?</h2>
          <p className="text-gray-500 mb-6">YieldIQ analyses 2,900+ Indian stocks with interactive DCF, sensitivity heatmap, and AI insights.</p>
          <Link href="/auth/signup" className="inline-block bg-blue-600 text-white font-bold px-8 py-4 rounded-xl text-lg hover:bg-blue-700 transition shadow-lg shadow-blue-500/20">
            Start Free &rarr;
          </Link>
        </div>
      </section>

      {/* Disclaimer */}
      <footer className="py-6 border-t border-gray-100">
        <p className="text-xs text-gray-600 text-center max-w-2xl mx-auto px-4 leading-relaxed">
          Model estimates using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser or research analyst.
        </p>
        <div className="flex justify-center gap-4 mt-3 text-xs text-gray-600">
          <Link href="/" className="hover:text-gray-600">&copy; 2026 YieldIQ</Link>
          <Link href="/terms" className="hover:text-gray-600">Terms</Link>
          <Link href="/privacy" className="hover:text-gray-600">Privacy</Link>
        </div>
      </footer>
    </div>
  )
}

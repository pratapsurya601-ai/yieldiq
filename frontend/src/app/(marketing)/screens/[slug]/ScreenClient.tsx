"use client"

import Link from "next/link"
import { useState, useMemo } from "react"

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
  piotroski: number
  roe: number | null
  roce: number | null
  de_ratio: number | null
  pe_ratio: number | null
  market_cap: number
}

interface ScreenData {
  slug: string
  name: string
  description: string
  h1: string
  intro: string
  total: number
  stocks: Stock[]
}

const SCREENS_LIST = [
  { slug: "high-roce", name: "High ROCE" },
  { slug: "low-pe-quality", name: "Low P/E + Quality" },
  { slug: "debt-free", name: "Debt-Free" },
  { slug: "undervalued-quality", name: "Undervalued Quality" },
  { slug: "wide-moat", name: "Wide Moat" },
  { slug: "high-piotroski", name: "High Piotroski" },
]

function fmt(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "\u2014"
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function verdictBadge(v: string) {
  const label = (v || "").replace(/_/g, " ")
  if (v === "undervalued") return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-green-50 text-green-700 capitalize">{label}</span>
  if (v === "overvalued" || v === "avoid") return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-50 text-red-700 capitalize">{label}</span>
  return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 capitalize">{label}</span>
}

type SortKey = "score" | "mos" | "current_price" | "roe" | "roce" | "piotroski" | "de_ratio" | "pe_ratio"

export default function ScreenClient({ data, slug }: { data: ScreenData; slug: string }) {
  const [sortKey, setSortKey] = useState<SortKey>("score")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [sectorFilter, setSectorFilter] = useState("")

  const sectors = useMemo(() => {
    const s = new Set(data.stocks.map(st => st.sector).filter(Boolean))
    return Array.from(s).sort()
  }, [data.stocks])

  const sorted = useMemo(() => {
    let filtered = data.stocks
    if (sectorFilter) filtered = filtered.filter(s => s.sector === sectorFilter)
    return [...filtered].sort((a, b) => {
      const av = (a[sortKey] as number) ?? 0
      const bv = (b[sortKey] as number) ?? 0
      return sortDir === "desc" ? bv - av : av - bv
    })
  }, [data.stocks, sortKey, sortDir, sectorFilter])

  const toggle = (k: SortKey) => {
    if (sortKey === k) setSortDir(d => d === "asc" ? "desc" : "asc")
    else { setSortKey(k); setSortDir("desc") }
  }
  const arrow = (k: SortKey) => sortKey === k ? (sortDir === "desc" ? " \u25BC" : " \u25B2") : ""

  return (
    <div className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-white border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-7 h-7 rounded-lg" />
            <span className="font-bold text-gray-900">YieldIQ</span>
          </Link>
          <Link href="/auth/signup" className="bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition">
            Start Free &rarr;
          </Link>
        </div>
      </nav>

      {/* Header */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <p className="text-blue-300 text-xs font-bold tracking-wider uppercase mb-2">Pre-built Filter</p>
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">{data.h1}</h1>
          <p className="text-gray-400 max-w-2xl mx-auto">{data.intro}</p>
          <p className="text-blue-400 text-sm font-semibold mt-3">{data.total} stocks match this filter</p>
        </div>
      </section>

      {/* Other screens nav */}
      <section className="border-b border-gray-100 py-3 overflow-x-auto">
        <div className="max-w-6xl mx-auto px-4 flex gap-2 whitespace-nowrap">
          {SCREENS_LIST.map(s => (
            <Link
              key={s.slug}
              href={`/screens/${s.slug}`}
              className={`text-xs font-semibold px-3 py-1.5 rounded-full border transition ${
                s.slug === slug
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
              }`}
            >
              {s.name}
            </Link>
          ))}
        </div>
      </section>

      {/* Filter */}
      <section className="max-w-6xl mx-auto px-4 py-4 border-b border-gray-100">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-gray-500">Showing {sorted.length} stocks</p>
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700"
          >
            <option value="">All Sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </section>

      {/* Table */}
      <section className="max-w-6xl mx-auto px-4 py-6">
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-500 w-10">#</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-500">Company</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggle("current_price")}>Price{arrow("current_price")}</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggle("score")}>Score{arrow("score")}</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none" onClick={() => toggle("mos")}>MoS%{arrow("mos")}</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none hidden sm:table-cell" onClick={() => toggle("roce")}>ROCE{arrow("roce")}</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none hidden md:table-cell" onClick={() => toggle("pe_ratio")}>P/E{arrow("pe_ratio")}</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500 cursor-pointer hover:text-gray-900 select-none hidden md:table-cell" onClick={() => toggle("piotroski")}>F-Score{arrow("piotroski")}</th>
                <th className="text-center px-4 py-3 font-semibold text-gray-500">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, i) => (
                <tr key={s.ticker} className="border-b border-gray-100 hover:bg-gray-50 transition">
                  <td className="px-4 py-3 text-gray-400 text-xs">{i + 1}</td>
                  <td className="px-4 py-3">
                    <Link href={`/stocks/${s.display_ticker}/fair-value`} className="hover:text-blue-600 transition">
                      <p className="font-semibold text-gray-900">{s.display_ticker}</p>
                      <p className="text-xs text-gray-400 truncate max-w-[180px]">{s.company_name}</p>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-900">{fmt(s.current_price)}</td>
                  <td className="px-4 py-3 text-right font-bold text-gray-900">{s.score}</td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${s.mos >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {s.mos >= 0 ? "+" : ""}{s.mos.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-900 hidden sm:table-cell">
                    {s.roce != null ? `${s.roce.toFixed(1)}%` : "\u2014"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-900 hidden md:table-cell">
                    {s.pe_ratio != null ? s.pe_ratio.toFixed(1) : "\u2014"}
                  </td>
                  <td className="px-4 py-3 text-right font-bold text-gray-900 hidden md:table-cell">{s.piotroski}/9</td>
                  <td className="px-4 py-3 text-center">{verdictBadge(s.verdict)}</td>
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-gray-400">
                    No stocks match this filter right now. Cache is warming \u2014 check back in a few minutes.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-gray-50 border-t border-gray-100 py-12">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <h2 className="text-2xl font-black text-gray-900 mb-3">Want custom filters?</h2>
          <p className="text-gray-500 mb-6">Build your own screener with 50+ filters across 2,900+ Indian stocks.</p>
          <Link href="/auth/signup" className="inline-block bg-blue-600 text-white font-bold px-8 py-4 rounded-xl text-lg hover:bg-blue-700 transition shadow-lg shadow-blue-500/20">
            Start Free &rarr;
          </Link>
        </div>
      </section>

      <footer className="py-6 border-t border-gray-100">
        <p className="text-[10px] text-gray-400 text-center max-w-2xl mx-auto px-4">
          This is a factor-based filter, not a stock recommendation. Model estimates only \u2014 not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </footer>
    </div>
  )
}

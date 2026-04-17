"use client"

import Link from "next/link"
import { useState } from "react"
import { useRouter } from "next/navigation"

interface StockData {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string
  price: number
  fair_value: number
  mos: number
  verdict: string
  score: number
  piotroski: number
  moat: string
  moat_score: number
  wacc: number
  fcf_growth: number | null
  confidence: number
  roe: number | null
  de_ratio: number | null
}

interface CompareData {
  stock1: StockData
  stock2: StockData
  winner: { score: string; value: string; quality: string; moat: string }
  overall_winner: string
}

function fmt(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "\u2014"
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function pct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "\u2014"
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`
}

function verdictBadge(v: string) {
  // SEBI-safe: "avoid" → "High Risk"
  const label = v === "avoid" ? "High Risk" : (v || "").replace(/_/g, " ")
  if (v === "undervalued") return <span className="px-3 py-1 rounded-full text-xs font-bold bg-green-50 text-green-700 capitalize">{label}</span>
  if (v === "overvalued" || v === "avoid") return <span className="px-3 py-1 rounded-full text-xs font-bold bg-red-50 text-red-700 capitalize">{label}</span>
  return <span className="px-3 py-1 rounded-full text-xs font-bold bg-blue-50 text-blue-700 capitalize">{label}</span>
}

function WinnerBadge() {
  return <span className="ml-2 text-[10px] font-bold text-green-600 bg-green-50 px-2 py-0.5 rounded-full">WINNER</span>
}

export default function CompareClient({ data, slug }: { data: CompareData; slug: string }) {
  const { stock1: s1, stock2: s2, winner, overall_winner } = data
  const router = useRouter()
  const [t1Input, setT1Input] = useState("")
  const [t2Input, setT2Input] = useState("")

  const overallName = overall_winner === "stock1" ? s1.display_ticker
    : overall_winner === "stock2" ? s2.display_ticker : null

  const metrics = [
    { label: "YieldIQ Score", v1: `${s1.score}/100`, v2: `${s2.score}/100`, cat: "score" },
    { label: "Fair Value", v1: fmt(s1.fair_value), v2: fmt(s2.fair_value), cat: null },
    { label: "Margin of Safety", v1: pct(s1.mos), v2: pct(s2.mos), cat: "value" },
    { label: "Piotroski F-Score", v1: `${s1.piotroski}/9`, v2: `${s2.piotroski}/9`, cat: "quality" },
    { label: "Economic Moat", v1: s1.moat, v2: s2.moat, cat: "moat" },
    { label: "ROE", v1: s1.roe != null ? `${s1.roe.toFixed(1)}%` : "\u2014", v2: s2.roe != null ? `${s2.roe.toFixed(1)}%` : "\u2014", cat: null },
    { label: "Debt/Equity", v1: s1.de_ratio != null ? s1.de_ratio.toFixed(2) : "\u2014", v2: s2.de_ratio != null ? s2.de_ratio.toFixed(2) : "\u2014", cat: null },
    { label: "WACC", v1: `${(s1.wacc * 100).toFixed(1)}%`, v2: `${(s2.wacc * 100).toFixed(1)}%`, cat: null },
    { label: "Confidence", v1: `${s1.confidence}%`, v2: `${s2.confidence}%`, cat: null },
  ]

  const handleCompare = () => {
    const a = t1Input.trim().toUpperCase()
    const b = t2Input.trim().toUpperCase()
    if (a && b && a !== b) router.push(`/compare/${a}-vs-${b}`)
  }

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

      <div className="max-w-4xl mx-auto px-4 py-8 sm:py-12">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-black text-gray-900 mb-2">
            {s1.display_ticker} vs {s2.display_ticker}
          </h1>
          <p className="text-gray-500">Head-to-head DCF comparison &middot; Which is more undervalued?</p>
        </div>

        {/* Two-column header cards */}
        <div className="grid grid-cols-2 gap-4 mb-8">
          {[s1, s2].map((s, idx) => (
            <div key={s.ticker} className={`rounded-2xl p-5 border ${overall_winner === (idx === 0 ? "stock1" : "stock2") ? "border-green-300 bg-green-50/30" : "border-gray-200 bg-gray-50"}`}>
              <Link href={`/stocks/${s.display_ticker}/fair-value`} className="hover:opacity-80 transition">
                <p className="text-lg sm:text-xl font-black text-gray-900">{s.display_ticker}</p>
                <p className="text-xs text-gray-400 truncate">{s.company_name}</p>
                <p className="text-xs text-gray-400">{s.sector}</p>
              </Link>
              <div className="mt-3 space-y-1">
                <p className="text-2xl font-black font-mono text-gray-900">{fmt(s.price)}</p>
                <div className="flex items-center gap-2">
                  {verdictBadge(s.verdict)}
                  {overall_winner === (idx === 0 ? "stock1" : "stock2") && <WinnerBadge />}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Overall Winner */}
        {overallName && (
          <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center mb-8">
            <p className="text-sm text-green-800">
              By DCF analysis, <span className="font-bold">{overallName}</span> appears more undervalued across score, value, quality, and moat.
            </p>
          </div>
        )}

        {/* Comparison Table */}
        <div className="rounded-xl border border-gray-200 overflow-hidden mb-8">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-500">Metric</th>
                <th className="text-center px-4 py-3 font-semibold text-gray-900">{s1.display_ticker}</th>
                <th className="text-center px-4 py-3 font-semibold text-gray-900">{s2.display_ticker}</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map(m => {
                const w = m.cat ? winner[m.cat as keyof typeof winner] : null
                return (
                  <tr key={m.label} className="border-b border-gray-100">
                    <td className="px-4 py-3 text-gray-600">{m.label}</td>
                    <td className={`px-4 py-3 text-center font-mono font-semibold ${w === "stock1" ? "bg-green-50 text-green-700" : "text-gray-900"}`}>
                      {m.v1}
                    </td>
                    <td className={`px-4 py-3 text-center font-mono font-semibold ${w === "stock2" ? "bg-green-50 text-green-700" : "text-gray-900"}`}>
                      {m.v2}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Compare other stocks */}
        <div className="bg-gray-50 rounded-xl border border-gray-200 p-6 mb-8">
          <h2 className="text-sm font-bold text-gray-900 mb-3">Compare other stocks</h2>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              placeholder="e.g. ITC"
              value={t1Input}
              onChange={e => setT1Input(e.target.value)}
              className="flex-1 px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white"
            />
            <span className="text-gray-400 font-bold text-center self-center">vs</span>
            <input
              type="text"
              placeholder="e.g. BRITANNIA"
              value={t2Input}
              onChange={e => setT2Input(e.target.value)}
              className="flex-1 px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white"
            />
            <button
              onClick={handleCompare}
              className="bg-blue-600 text-white font-semibold px-6 py-2.5 rounded-lg hover:bg-blue-700 transition text-sm"
            >
              Compare
            </button>
          </div>
        </div>

        {/* CTA */}
        <div className="text-center mb-8">
          <p className="text-gray-500 text-sm mb-3">Want the full interactive analysis?</p>
          <Link
            href="/auth/signup"
            className="inline-block bg-blue-600 text-white font-bold px-8 py-3 rounded-xl hover:bg-blue-700 transition"
          >
            Start Free &rarr;
          </Link>
        </div>

        {/* Disclaimer */}
        <p className="text-[10px] text-gray-400 text-center">
          Model estimates only. Not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </div>
    </div>
  )
}

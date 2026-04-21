"use client"

import Link from "next/link"
import { useState } from "react"
import { useRouter } from "next/navigation"
import { formatMarketCap } from "@/lib/formatters"

export interface StockData {
  ticker: string
  display_ticker: string
  company_name: string
  sector: string
  price: number
  current_price: number
  fair_value: number
  mos: number
  verdict: string
  score: number
  grade: string
  piotroski: number
  moat: string
  moat_score: number
  wacc: number
  fcf_growth: number | null
  confidence: number
  roe: number | null
  de_ratio: number | null
  ev_ebitda: number | null
  market_cap: number | null
}

type WinnerKey = "score" | "value" | "quality" | "moat"

export interface CompareData {
  stock1: StockData
  stock2: StockData
  winner: Record<WinnerKey, "stock1" | "stock2" | "tie">
  overall_winner: "stock1" | "stock2" | "tie"
  stock1_wins: number
  stock2_wins: number
  total_metrics: number
}

const DASH = "\u2014"

function fmtINR(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return DASH
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return DASH
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`
}

function fmtMarketCap(n: number | null | undefined): string {
  if (n == null || isNaN(n) || n <= 0) return DASH
  // Backend returns market_cap in INR; canonical formatter expects Cr
  // (1 Cr = 1e7) and emits "₹x.xx Lakh Cr" for large caps.
  return formatMarketCap(n / 1e7)
}

function verdictLabel(v: string): string {
  const map: Record<string, string> = {
    undervalued: "Undervalued",
    fairly_valued: "Fairly Valued",
    overvalued: "Overvalued",
    avoid: "High Risk",
    data_limited: "Data Limited",
    unavailable: "Unavailable",
  }
  return map[v] || (v || "").replace(/_/g, " ")
}

function VerdictBadge({ v }: { v: string }) {
  const label = verdictLabel(v)
  const cls =
    v === "undervalued"
      ? "bg-green-50 text-green-700 border-green-200"
      : v === "overvalued" || v === "avoid"
        ? "bg-red-50 text-red-700 border-red-200"
        : "bg-blue-50 text-blue-700 border-blue-200"
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-xs font-bold border ${cls}`}>
      {label}
    </span>
  )
}

interface MetricRow {
  label: string
  v1: string
  v2: string
  winner: "stock1" | "stock2" | "tie" | null
}

export default function CompareClient({ data }: { data: CompareData }) {
  const { stock1: s1, stock2: s2, winner, overall_winner, stock1_wins, stock2_wins, total_metrics } = data
  const router = useRouter()
  const [t1Input, setT1Input] = useState("")
  const [t2Input, setT2Input] = useState("")

  // Per-row winners for display-only metrics (no backend cat assigned)
  const cmpHigher = (a: number | null | undefined, b: number | null | undefined): "stock1" | "stock2" | "tie" | null => {
    if (a == null || b == null || isNaN(a) || isNaN(b)) return null
    if (a > b) return "stock1"
    if (b > a) return "stock2"
    return "tie"
  }
  const cmpLower = (a: number | null | undefined, b: number | null | undefined): "stock1" | "stock2" | "tie" | null => {
    if (a == null || b == null || isNaN(a) || isNaN(b)) return null
    if (a < b) return "stock1"
    if (b < a) return "stock2"
    return "tie"
  }

  // Order per spec: Verdict, Score, Fair Value, Current Price, MoS, Moat,
  // Piotroski, ROE, D/E, EV/EBITDA, Market Cap
  const metrics: MetricRow[] = [
    {
      label: "Verdict",
      v1: verdictLabel(s1.verdict),
      v2: verdictLabel(s2.verdict),
      // Undervalued > Fairly > Overvalued/Avoid
      winner: (() => {
        const rank = (v: string) =>
          v === "undervalued" ? 3 : v === "fairly_valued" ? 2 : v === "overvalued" ? 1 : v === "avoid" ? 0 : -1
        const r1 = rank(s1.verdict), r2 = rank(s2.verdict)
        if (r1 < 0 || r2 < 0) return null
        return r1 > r2 ? "stock1" : r2 > r1 ? "stock2" : "tie"
      })(),
    },
    {
      label: "YieldIQ Score",
      v1: `${s1.score}/100`,
      v2: `${s2.score}/100`,
      winner: winner.score,
    },
    {
      label: "Fair Value",
      v1: fmtINR(s1.fair_value),
      v2: fmtINR(s2.fair_value),
      winner: null,
    },
    {
      label: "Current Price",
      v1: fmtINR(s1.current_price),
      v2: fmtINR(s2.current_price),
      winner: null,
    },
    {
      label: "Margin of Safety",
      v1: fmtPct(s1.mos),
      v2: fmtPct(s2.mos),
      winner: winner.value,
    },
    {
      label: "Moat",
      v1: s1.moat || DASH,
      v2: s2.moat || DASH,
      winner: winner.moat,
    },
    {
      label: "Piotroski F-Score",
      v1: `${s1.piotroski}/9`,
      v2: `${s2.piotroski}/9`,
      winner: winner.quality,
    },
    {
      label: "ROE",
      v1: s1.roe != null ? `${s1.roe.toFixed(1)}%` : DASH,
      v2: s2.roe != null ? `${s2.roe.toFixed(1)}%` : DASH,
      winner: cmpHigher(s1.roe, s2.roe),
    },
    {
      label: "Debt / Equity",
      v1: s1.de_ratio != null ? s1.de_ratio.toFixed(2) : DASH,
      v2: s2.de_ratio != null ? s2.de_ratio.toFixed(2) : DASH,
      // lower is better
      winner: cmpLower(s1.de_ratio, s2.de_ratio),
    },
    {
      label: "EV / EBITDA",
      v1: s1.ev_ebitda != null ? `${s1.ev_ebitda.toFixed(1)}\u00D7` : DASH,
      v2: s2.ev_ebitda != null ? `${s2.ev_ebitda.toFixed(1)}\u00D7` : DASH,
      // lower is better (cheaper)
      winner: cmpLower(s1.ev_ebitda, s2.ev_ebitda),
    },
    {
      label: "Market Cap",
      v1: fmtMarketCap(s1.market_cap),
      v2: fmtMarketCap(s2.market_cap),
      winner: null,
    },
  ]

  const overallName =
    overall_winner === "stock1" ? s1.display_ticker : overall_winner === "stock2" ? s2.display_ticker : null
  const overallWins = overall_winner === "stock1" ? stock1_wins : overall_winner === "stock2" ? stock2_wins : 0

  const handleCompare = (e: React.FormEvent) => {
    e.preventDefault()
    const a = t1Input.trim().toUpperCase().replace(/\s+/g, "")
    const b = t2Input.trim().toUpperCase().replace(/\s+/g, "")
    if (a && b && a !== b) router.push(`/compare/${a}-vs-${b}`)
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 sm:py-12">
      {/* Breadcrumb */}
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">Compare</span>
        <span>/</span>
        <span className="text-gray-600 font-medium">{s1.display_ticker} vs {s2.display_ticker}</span>
      </nav>

      {/* Header */}
      <div className="text-center mb-6">
        <h1 className="text-2xl sm:text-3xl font-black text-gray-900 mb-2">
          {s1.display_ticker} vs {s2.display_ticker}
        </h1>
        <p className="text-gray-500 text-sm">
          Head-to-head DCF comparison &middot; {s1.company_name} vs {s2.company_name}
        </p>
      </div>

      {/* Top CTA */}
      <div className="mb-8 text-center">
        <Link
          href="/auth/signup"
          className="inline-block text-sm font-semibold text-blue-600 hover:text-blue-800"
        >
          Get full interactive analysis &mdash; Sign up free &rarr;
        </Link>
      </div>

      {/* Overall winner card */}
      {overallName ? (
        <div className="bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-2xl p-6 text-center mb-8">
          <p className="text-sm text-green-700 font-semibold mb-1">Model Favors</p>
          <p className="text-xl sm:text-2xl font-black text-gray-900">
            {overallName} shows a larger model margin of safety
          </p>
          <p className="text-sm text-gray-600 mt-1">
            Leads on {overallWins} of {total_metrics} model metrics &middot; not investment advice
          </p>
        </div>
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-2xl p-6 text-center mb-8">
          <p className="text-xl font-bold text-gray-900">It&apos;s a tie</p>
          <p className="text-sm text-gray-500 mt-1">
            {s1.display_ticker} and {s2.display_ticker} are evenly matched on the {total_metrics} headline metrics.
          </p>
        </div>
      )}

      {/* Two-column header cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        {[s1, s2].map((s, idx) => {
          const isWin = overall_winner === (idx === 0 ? "stock1" : "stock2")
          return (
            <div
              key={s.ticker}
              className={`rounded-2xl p-5 border ${isWin ? "border-green-300 bg-green-50/40" : "border-gray-200 bg-white"}`}
            >
              <Link href={`/stocks/${s.display_ticker}/fair-value`} className="hover:opacity-80 transition block">
                <p className="text-lg sm:text-xl font-black text-gray-900">{s.display_ticker}</p>
                <p className="text-xs text-gray-500 truncate">{s.company_name}</p>
                <p className="text-xs text-gray-400">{s.sector || DASH}</p>
              </Link>
              <div className="mt-3 space-y-2">
                <p className="text-2xl font-black font-mono text-gray-900">{fmtINR(s.current_price)}</p>
                <VerdictBadge v={s.verdict} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Comparison table */}
      <div className="rounded-2xl border border-gray-200 overflow-hidden mb-8">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-3 font-semibold text-gray-500 uppercase tracking-wider text-xs">Metric</th>
              <th className="text-center px-4 py-3 font-semibold text-gray-900">{s1.display_ticker}</th>
              <th className="text-center px-4 py-3 font-semibold text-gray-900">{s2.display_ticker}</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(m => (
              <tr key={m.label} className="border-b border-gray-100 last:border-0">
                <td className="px-4 py-3 text-gray-600">{m.label}</td>
                <td
                  className={`px-4 py-3 text-center font-mono font-semibold ${
                    m.winner === "stock1"
                      ? "bg-green-50 text-green-700"
                      : m.winner === "stock2"
                        ? "text-red-500"
                        : "text-gray-900"
                  }`}
                >
                  {m.v1}
                </td>
                <td
                  className={`px-4 py-3 text-center font-mono font-semibold ${
                    m.winner === "stock2"
                      ? "bg-green-50 text-green-700"
                      : m.winner === "stock1"
                        ? "text-red-500"
                        : "text-gray-900"
                  }`}
                >
                  {m.v2}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Compare other stocks */}
      <form
        onSubmit={handleCompare}
        className="bg-gray-50 rounded-2xl border border-gray-200 p-6 mb-8"
      >
        <h2 className="text-sm font-bold text-gray-900 mb-3">Compare other stocks</h2>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            placeholder="e.g. ITC"
            value={t1Input}
            onChange={e => setT1Input(e.target.value)}
            className="flex-1 px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:border-blue-500"
            aria-label="First ticker"
          />
          <span className="text-gray-400 font-bold text-center self-center">vs</span>
          <input
            type="text"
            placeholder="e.g. BRITANNIA"
            value={t2Input}
            onChange={e => setT2Input(e.target.value)}
            className="flex-1 px-4 py-2.5 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:border-blue-500"
            aria-label="Second ticker"
          />
          <button
            type="submit"
            className="bg-blue-600 text-white font-semibold px-6 py-2.5 rounded-lg hover:bg-blue-700 transition text-sm"
          >
            Compare &rarr;
          </button>
        </div>
      </form>

      {/* CTA */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-8 text-center text-white mb-8">
        <h2 className="text-xl font-bold mb-2">Run the full interactive analysis</h2>
        <p className="text-blue-100 text-sm mb-4">
          DCF sliders, sensitivity tables, peer screens, watchlists &mdash; free to start.
        </p>
        <Link
          href="/auth/signup"
          className="inline-block bg-white text-blue-700 font-bold px-8 py-3 rounded-xl hover:bg-blue-50 transition"
        >
          Sign up free &rarr;
        </Link>
      </div>

      {/* Disclaimer */}
      <p className="text-[10px] text-gray-400 text-center leading-relaxed">
        Model estimates using publicly available data. Not investment advice.
        YieldIQ is not registered with SEBI as an investment adviser or research analyst.
      </p>
    </div>
  )
}

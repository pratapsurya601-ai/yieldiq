"use client"

import { useState, useEffect, useCallback } from "react"
import Link from "next/link"

interface Scenario {
  growth_rate: number
  implied_iv: number
  mos: number
}

interface ReverseDCFData {
  ticker: string
  current_price: number
  implied_growth: number | null
  converged: boolean
  iv_at_implied: number
  historical_growth: number | null
  long_run_gdp: number
  wacc: number
  terminal_g: number
  verdict_level: string
  verdict_text: string
  verdict_colour: string
  summary: string
  scenarios: Record<string, Scenario>
  years_to_justify: number | null
  payback_at_implied: number | null
  fcf_yield: number | null
  price_to_fcf: number | null
  excess_growth: number | null
  growth_premium: number | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || ""

function pct(n: number | null | undefined, decimals = 1): string {
  if (n == null || isNaN(n)) return "\u2014"
  return `${(n * 100).toFixed(decimals)}%`
}

function fmt(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "\u2014"
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function verdictBg(c: string): string {
  if (c === "green") return "bg-green-50 text-green-800 border-green-200"
  if (c === "amber") return "bg-amber-50 text-amber-800 border-amber-200"
  if (c === "red") return "bg-red-50 text-red-800 border-red-200"
  return "bg-gray-50 text-gray-800 border-gray-200"
}

function verdictDot(c: string): string {
  if (c === "green") return "bg-green-500"
  if (c === "amber") return "bg-amber-500"
  if (c === "red") return "bg-red-500"
  return "bg-gray-500"
}

export default function ReverseDCFClient({ initialData, ticker }: { initialData: ReverseDCFData; ticker: string }) {
  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  const [data, setData] = useState(initialData)
  const [wacc, setWacc] = useState(initialData.wacc)
  const [terminalG, setTerminalG] = useState(initialData.terminal_g)
  const [loading, setLoading] = useState(false)
  const [debouncedWacc, setDebouncedWacc] = useState(wacc)
  const [debouncedTerm, setDebouncedTerm] = useState(terminalG)

  // Debounce slider changes
  useEffect(() => {
    const t = setTimeout(() => setDebouncedWacc(wacc), 500)
    return () => clearTimeout(t)
  }, [wacc])
  useEffect(() => {
    const t = setTimeout(() => setDebouncedTerm(terminalG), 500)
    return () => clearTimeout(t)
  }, [terminalG])

  const refetch = useCallback(async () => {
    if (debouncedWacc === initialData.wacc && debouncedTerm === initialData.terminal_g) {
      setData(initialData)
      return
    }
    setLoading(true)
    try {
      const url = `${API_BASE}/api/v1/analysis/${ticker}/reverse-dcf?wacc=${debouncedWacc}&terminal_g=${debouncedTerm}`
      const res = await fetch(url)
      if (res.ok) {
        const d = await res.json()
        setData(d)
      }
    } catch {}
    setLoading(false)
  }, [debouncedWacc, debouncedTerm, ticker, initialData])

  useEffect(() => {
    refetch()
  }, [refetch])

  const sortedScenarios = Object.entries(data.scenarios || {}).sort(
    (a, b) => a[1].growth_rate - b[1].growth_rate
  )

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">{display}</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">Reverse DCF</span>
      </nav>

      {/* Hero */}
      <div className="mb-8">
        <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-2">Reverse DCF</p>
        <h1 className="text-2xl sm:text-3xl font-black text-gray-900 mb-2">
          What growth does the market imply for {display}?
        </h1>
        <p className="text-gray-500">
          Working backwards from the current price to find the FCF growth assumption baked in.
        </p>
      </div>

      {/* Headline result */}
      <div className={`rounded-2xl border p-6 mb-6 ${verdictBg(data.verdict_colour)}`}>
        <div className="flex items-start gap-3">
          <div className={`mt-1.5 w-3 h-3 rounded-full flex-shrink-0 ${verdictDot(data.verdict_colour)}`} />
          <div className="flex-1">
            <p className="text-xs font-bold uppercase tracking-wider opacity-70 mb-1">
              {data.verdict_level || "Result"}
            </p>
            <p className="text-3xl font-black mb-2">
              {pct(data.implied_growth)} <span className="text-lg font-medium opacity-70">implied annual FCF growth</span>
            </p>
            <p className="text-sm leading-relaxed opacity-90">{data.verdict_text}</p>
          </div>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Current Price</p>
          <p className="text-lg font-bold text-gray-900 font-mono">{fmt(data.current_price)}</p>
        </div>
        <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Historical Growth</p>
          <p className="text-lg font-bold text-gray-900">{pct(data.historical_growth)}</p>
        </div>
        <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">FCF Yield</p>
          <p className="text-lg font-bold text-gray-900">{pct(data.fcf_yield, 2)}</p>
        </div>
        <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Price / FCF</p>
          <p className="text-lg font-bold text-gray-900">{data.price_to_fcf ? `${data.price_to_fcf.toFixed(1)}x` : "\u2014"}</p>
        </div>
      </div>

      {/* Plain English Summary */}
      {data.summary && (
        <div className="bg-blue-50 border border-blue-100 rounded-2xl p-6 mb-8">
          <h2 className="text-sm font-bold text-blue-800 mb-2">Plain English</h2>
          <p className="text-sm text-blue-900 leading-relaxed whitespace-pre-line">{data.summary}</p>
        </div>
      )}

      {/* Sensitivity Sliders */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 mb-8">
        <h2 className="text-sm font-bold text-gray-900 mb-4">Adjust Assumptions {loading && <span className="text-blue-500 text-xs ml-2">recomputing...</span>}</h2>
        <div className="space-y-5">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-gray-600">WACC (Discount Rate)</label>
              <span className="text-sm font-mono font-bold text-gray-900">{pct(wacc, 1)}</span>
            </div>
            <input
              type="range"
              min={0.06}
              max={0.20}
              step={0.005}
              value={wacc}
              onChange={(e) => setWacc(parseFloat(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>6%</span><span>13%</span><span>20%</span>
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-gray-600">Terminal Growth Rate</label>
              <span className="text-sm font-mono font-bold text-gray-900">{pct(terminalG, 1)}</span>
            </div>
            <input
              type="range"
              min={0.0}
              max={0.06}
              step={0.0025}
              value={terminalG}
              onChange={(e) => setTerminalG(parseFloat(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>0%</span><span>3%</span><span>6%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Growth Scenarios Table */}
      <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden mb-8">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Growth Scenarios</h2>
          <p className="text-xs text-gray-500 mt-1">What the stock is worth at different growth assumptions</p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              <th className="text-left px-6 py-3 font-semibold text-gray-500">Scenario</th>
              <th className="text-right px-6 py-3 font-semibold text-gray-500">FCF Growth</th>
              <th className="text-right px-6 py-3 font-semibold text-gray-500">Implied IV</th>
              <th className="text-right px-6 py-3 font-semibold text-gray-500">MoS vs Price</th>
            </tr>
          </thead>
          <tbody>
            {sortedScenarios.map(([label, sc]) => (
              <tr key={label} className="border-b border-gray-100">
                <td className="px-6 py-3 font-medium text-gray-900">{label}</td>
                <td className="px-6 py-3 text-right font-mono">{pct(sc.growth_rate, 1)}</td>
                <td className="px-6 py-3 text-right font-mono text-gray-900">{fmt(sc.implied_iv)}</td>
                <td className={`px-6 py-3 text-right font-mono font-bold ${sc.mos >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {sc.mos >= 0 ? "+" : ""}{(sc.mos * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* DCF Horizon at Historical Growth */}
      {data.historical_growth != null && data.scenarios?.Historical && (
        <div className="bg-amber-50 border border-amber-100 rounded-xl p-5 mb-8">
          <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">At Historical Growth Rate</p>
          <p className="text-sm text-amber-900">
            DCF horizon: <span className="font-bold">10 years</span>. At {pct(data.historical_growth)} growth, the model values {display} at <span className="font-bold">{fmt(data.scenarios.Historical.implied_iv)}</span>, {data.scenarios.Historical.implied_iv >= data.current_price ? "above" : "below"} today&apos;s {fmt(data.current_price)}.
          </p>
        </div>
      )}

      {/* CTA */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-center text-white mb-8">
        <h2 className="text-lg font-bold mb-1">See full DCF analysis</h2>
        <p className="text-blue-100 text-sm mb-4">Bear/base/bull scenarios, sensitivity heatmap, reverse DCF, and more.</p>
        <Link
          href={`/analysis/${ticker}`}
          className="inline-block bg-white text-blue-700 font-bold px-6 py-2.5 rounded-xl hover:bg-blue-50 transition text-sm"
        >
          Run Full Analysis &rarr;
        </Link>
      </div>

      <p className="text-[10px] text-gray-400 text-center">
        This is an analytical tool, not investment advice. Implied growth is a mathematical inversion of the DCF model
        and depends on WACC and terminal growth assumptions. YieldIQ is not registered with SEBI as an investment adviser.
      </p>
    </div>
  )
}

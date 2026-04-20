import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface RiskStats {
  ticker: string
  volatility_pct: number
  max_drawdown_pct: number
  max_drawdown_days: number
  recovery_days: number | null
  current_drawdown_pct: number
  beta: number | null
  sharpe_proxy: number
  week52_high: number
  week52_low: number
  return_1m: number | null
  return_3m: number | null
  return_1y: number | null
  return_3y: number | null
  days_in_sample: number
  peak_date: string
  trough_date: string
}

async function getRiskStats(ticker: string): Promise<RiskStats | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/risk-stats/${ticker}?years=3`, {
      next: { revalidate: 86400 },
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  const data = await getRiskStats(ticker)
  if (!data) return { title: `${display} Risk Analysis | YieldIQ` }
  return {
    title: `${display} Risk Analysis — Volatility ${data.volatility_pct.toFixed(1)}%, Max DD ${data.max_drawdown_pct.toFixed(1)}% | YieldIQ`,
    description: `${display} risk profile: annualized volatility ${data.volatility_pct.toFixed(1)}%, max drawdown ${data.max_drawdown_pct.toFixed(1)}%, beta ${data.beta ?? "—"}. Free analysis on YieldIQ.`,
    alternates: { canonical: `https://yieldiq.in/stocks/${display}/risk-analysis` },
  }
}

function fmt(n: number): string {
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function pctColor(n: number | null | undefined, positiveGood = true): string {
  if (n == null) return "text-gray-400"
  if (positiveGood) return n >= 0 ? "text-green-600" : "text-red-600"
  return n <= 0 ? "text-green-600" : "text-red-600"
}

function dateShort(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-IN", { month: "short", year: "2-digit" })
  } catch {
    return iso
  }
}

export default async function RiskAnalysisPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const data = await getRiskStats(ticker)
  if (!data) notFound()

  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  const priceInRange = data.week52_high > 0
    ? ((data.week52_high - data.week52_low) / data.week52_low * 100).toFixed(0)
    : "—"

  // Volatility regime
  const volRegime = data.volatility_pct < 20 ? "Low" : data.volatility_pct < 35 ? "Moderate" : data.volatility_pct < 50 ? "High" : "Extreme"
  const volColor = data.volatility_pct < 20 ? "text-green-600 bg-green-50 border-green-200"
    : data.volatility_pct < 35 ? "text-blue-600 bg-blue-50 border-blue-200"
    : data.volatility_pct < 50 ? "text-amber-600 bg-amber-50 border-amber-200"
    : "text-red-600 bg-red-50 border-red-200"

  // Beta regime
  const betaLabel = data.beta == null ? "—"
    : data.beta < 0.8 ? "Less volatile than market"
    : data.beta < 1.2 ? "Moves with market"
    : "More volatile than market"

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">{display}</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">Risk Analysis</span>
      </nav>

      {/* Hero */}
      <div className="mb-8">
        <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-2">Risk Analysis</p>
        <h1 className="text-2xl sm:text-3xl font-black text-gray-900 mb-2">
          {display} Risk & Volatility Profile
        </h1>
        <p className="text-gray-500 text-sm">
          Based on {data.days_in_sample} days of price history. Factual statistics, no recommendations.
        </p>
      </div>

      {/* Top-line risk cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Annualised Volatility</p>
          <p className="text-xl font-bold text-gray-900">{data.volatility_pct != null ? `${data.volatility_pct.toFixed(1)}%` : "\u2014"}</p>
          <p className="text-[10px] text-gray-400 mt-0.5">{volRegime} volatility</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Max Drawdown</p>
          <p className="text-xl font-bold text-red-600">{data.max_drawdown_pct != null ? `${data.max_drawdown_pct.toFixed(1)}%` : "\u2014"}</p>
          <p className="text-[10px] text-gray-400 mt-0.5">{data.max_drawdown_days ?? "\u2014"} days peak-to-trough</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Beta vs Nifty</p>
          <p className="text-xl font-bold text-gray-900">{data.beta != null ? data.beta.toFixed(2) : "\u2014"}</p>
          <p className="text-[10px] text-gray-400 mt-0.5 truncate">{betaLabel}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Return/Vol Ratio</p>
          <p className={`text-xl font-bold ${data.sharpe_proxy != null ? pctColor(data.sharpe_proxy) : "text-gray-400"}`}>{data.sharpe_proxy != null ? data.sharpe_proxy.toFixed(2) : "\u2014"}</p>
          <p className="text-[10px] text-gray-400 mt-0.5">Simple Sharpe proxy</p>
        </div>
      </div>

      {/* Volatility regime explainer */}
      <div className={`rounded-2xl border p-5 mb-8 ${volColor}`}>
        <p className="text-xs font-bold uppercase tracking-wider opacity-70 mb-1">Volatility Regime</p>
        <p className="text-lg font-bold mb-2">{volRegime} — {data.volatility_pct.toFixed(1)}% annualised</p>
        <p className="text-sm leading-relaxed opacity-90">
          {data.volatility_pct < 20 && `${display} shows lower-than-average volatility, typical of stable large-caps and defensive sectors.`}
          {data.volatility_pct >= 20 && data.volatility_pct < 35 && `${display} has moderate volatility consistent with a typical Indian equity.`}
          {data.volatility_pct >= 35 && data.volatility_pct < 50 && `${display} is above-average volatile. Expect larger daily swings than the broader market.`}
          {data.volatility_pct >= 50 && `${display} is highly volatile. Small-caps, cyclicals, and turnaround stories often show this pattern.`}
        </p>
      </div>

      {/* Drawdown Details */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 mb-8">
        <h2 className="text-sm font-bold text-gray-900 mb-4">Drawdown History</h2>
        <div className="grid sm:grid-cols-2 gap-6">
          <div>
            <p className="text-xs text-gray-500 mb-1">Worst Drawdown</p>
            <p className="text-2xl font-black text-red-600 mb-1">{data.max_drawdown_pct.toFixed(1)}%</p>
            <p className="text-xs text-gray-500">
              From {dateShort(data.peak_date)} to {dateShort(data.trough_date)}<br />
              {data.max_drawdown_days} days of decline
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1">Recovery</p>
            {data.recovery_days != null ? (
              <>
                <p className="text-2xl font-black text-green-600 mb-1">{data.recovery_days} days</p>
                <p className="text-xs text-gray-500">Time from trough back to previous peak</p>
              </>
            ) : (
              <>
                <p className="text-2xl font-black text-amber-600 mb-1">Not recovered</p>
                <p className="text-xs text-gray-500">Still below the previous peak</p>
              </>
            )}
          </div>
        </div>
        {Math.abs(data.current_drawdown_pct) > 1 && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <p className="text-xs text-gray-500">
              Currently {Math.abs(data.current_drawdown_pct).toFixed(1)}% below the 3-year high
            </p>
          </div>
        )}
      </div>

      {/* Returns Grid */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 mb-8">
        <h2 className="text-sm font-bold text-gray-900 mb-4">Historical Returns</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: "1 Month", value: data.return_1m },
            { label: "3 Months", value: data.return_3m },
            { label: "1 Year", value: data.return_1y },
            { label: "3 Years", value: data.return_3y },
          ].map(r => (
            <div key={r.label} className="bg-gray-50 rounded-xl p-3">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{r.label}</p>
              <p className={`text-lg font-bold font-mono ${pctColor(r.value)}`}>
                {r.value != null ? `${r.value >= 0 ? "+" : ""}${r.value.toFixed(1)}%` : "\u2014"}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* 52w Range */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 mb-8">
        <h2 className="text-sm font-bold text-gray-900 mb-4">52-Week Range</h2>
        <div className="flex items-baseline justify-between mb-2 text-sm">
          <span className="text-red-600 font-mono font-bold">{fmt(data.week52_low)}</span>
          <span className="text-xs text-gray-400">Range: {priceInRange}%</span>
          <span className="text-green-600 font-mono font-bold">{fmt(data.week52_high)}</span>
        </div>
        <div className="h-2 bg-gradient-to-r from-red-400 via-amber-400 to-green-400 rounded-full" />
      </div>

      {/* CTA */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-center text-white mb-8">
        <h2 className="text-lg font-bold mb-1">See DCF fair value for {display}</h2>
        <p className="text-blue-100 text-sm mb-4">Combine risk profile with intrinsic value estimate.</p>
        <Link
          href={`/stocks/${display}/fair-value`}
          className="inline-block bg-white text-blue-700 font-bold px-6 py-2.5 rounded-xl hover:bg-blue-50 transition text-sm"
        >
          See Fair Value &rarr;
        </Link>
      </div>

      <p className="text-[10px] text-gray-400 text-center">
        Risk statistics computed from historical price data. Past volatility does not predict future risk.
        YieldIQ is not registered with SEBI as an investment adviser.
      </p>
    </div>
  )
}

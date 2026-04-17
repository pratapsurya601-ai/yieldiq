import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface Period {
  period_end: string
  fy: string
  revenue_cr: number
  pat_cr: number
  total_assets_cr: number
  total_equity_cr: number
  net_margin_pct: number
  asset_turnover: number
  equity_multiplier: number
  roe_pct: number
  roa_pct: number
}

interface DuPontData {
  ticker: string
  display_ticker: string
  company_name: string
  years: number
  periods: Period[]
  latest: Period
  commentary: string
}

async function getData(ticker: string): Promise<DuPontData | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/dupont/${ticker}?years=5`, {
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
  const data = await getData(ticker)
  if (!data) return { title: `${display} DuPont Analysis | YieldIQ` }
  return {
    title: `${display} DuPont Analysis \u2014 ROE ${data.latest.roe_pct.toFixed(1)}% | YieldIQ`,
    description: `${data.company_name} ROE decomposition: ${data.latest.net_margin_pct.toFixed(1)}% margin \u00D7 ${data.latest.asset_turnover.toFixed(2)}x turnover \u00D7 ${data.latest.equity_multiplier.toFixed(2)}x leverage. ${data.years}-year history.`,
    alternates: { canonical: `https://yieldiq.in/stocks/${display}/dupont` },
  }
}

function pctColor(curr: number, prev: number): string {
  if (curr > prev) return "text-green-600"
  if (curr < prev) return "text-red-600"
  return "text-gray-600"
}

export default async function DuPontPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const data = await getData(ticker)
  if (!data) notFound()

  const display = data.display_ticker
  const latest = data.latest
  const first = data.periods[0]

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">{display}</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">DuPont Analysis</span>
      </nav>

      <div className="mb-8">
        <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-2">DuPont Decomposition</p>
        <h1 className="text-2xl sm:text-3xl font-black text-gray-900 mb-2">
          Why does {display} earn its ROE?
        </h1>
        <p className="text-gray-500 text-sm">
          Breaking down Return on Equity into profitability, efficiency, and leverage.
        </p>
      </div>

      {/* Formula equation */}
      <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 mb-8 text-center">
        <p className="text-xs text-blue-700 mb-2">ROE = Net Margin &times; Asset Turnover &times; Equity Multiplier</p>
        <p className="text-2xl sm:text-3xl font-black text-blue-900 font-mono">
          {latest.roe_pct.toFixed(1)}% = {latest.net_margin_pct.toFixed(1)}% &times; {latest.asset_turnover.toFixed(2)} &times; {latest.equity_multiplier.toFixed(2)}
        </p>
        <p className="text-xs text-blue-600 mt-2">Latest: {latest.fy}</p>
      </div>

      {/* Three pillars */}
      <div className="grid sm:grid-cols-3 gap-4 mb-8">
        <div className="bg-white border border-gray-200 rounded-2xl p-5">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Profitability</p>
          <p className="text-sm text-gray-500 mb-2">Net Margin</p>
          <p className="text-3xl font-black text-gray-900 mb-1">{latest.net_margin_pct.toFixed(1)}%</p>
          {first && (
            <p className={`text-xs font-semibold ${pctColor(latest.net_margin_pct, first.net_margin_pct)}`}>
              {first.net_margin_pct.toFixed(1)}% →{latest.net_margin_pct.toFixed(1)}%
            </p>
          )}
          <p className="text-[10px] text-gray-400 mt-2">How much profit per ₹ of revenue</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-2xl p-5">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Efficiency</p>
          <p className="text-sm text-gray-500 mb-2">Asset Turnover</p>
          <p className="text-3xl font-black text-gray-900 mb-1">{latest.asset_turnover.toFixed(2)}x</p>
          {first && (
            <p className={`text-xs font-semibold ${pctColor(latest.asset_turnover, first.asset_turnover)}`}>
              {first.asset_turnover.toFixed(2)}x →{latest.asset_turnover.toFixed(2)}x
            </p>
          )}
          <p className="text-[10px] text-gray-400 mt-2">Revenue per ₹ of assets</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-2xl p-5">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Leverage</p>
          <p className="text-sm text-gray-500 mb-2">Equity Multiplier</p>
          <p className="text-3xl font-black text-gray-900 mb-1">{latest.equity_multiplier.toFixed(2)}x</p>
          {first && (
            <p className={`text-xs font-semibold ${pctColor(first.equity_multiplier, latest.equity_multiplier)}`}>
              {first.equity_multiplier.toFixed(2)}x →{latest.equity_multiplier.toFixed(2)}x
            </p>
          )}
          <p className="text-[10px] text-gray-400 mt-2">Assets funded by equity vs debt</p>
        </div>
      </div>

      {/* Commentary */}
      {data.commentary && (
        <div className="bg-gray-50 border border-gray-200 rounded-2xl p-5 mb-8">
          <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">Trend Analysis</p>
          <p className="text-sm text-gray-800 leading-relaxed">{data.commentary}</p>
        </div>
      )}

      {/* Historical Table */}
      <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden mb-8">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-900">Historical Decomposition</h2>
          <p className="text-xs text-gray-500 mt-1">Last {data.years} years</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="text-left px-4 py-3 font-semibold text-gray-500">Year</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500">Revenue</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-500">PAT</th>
                <th className="text-right px-4 py-3 font-semibold text-blue-600">Net Margin</th>
                <th className="text-right px-4 py-3 font-semibold text-blue-600">Asset TO</th>
                <th className="text-right px-4 py-3 font-semibold text-blue-600">Leverage</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-900">ROE</th>
              </tr>
            </thead>
            <tbody>
              {data.periods.map(p => (
                <tr key={p.period_end} className="border-b border-gray-100">
                  <td className="px-4 py-3 font-medium text-gray-900">{p.fy}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">₹{p.revenue_cr.toLocaleString("en-IN")}Cr</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">₹{p.pat_cr.toLocaleString("en-IN")}Cr</td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-blue-700">{p.net_margin_pct.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-blue-700">{p.asset_turnover.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-blue-700">{p.equity_multiplier.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right font-mono font-bold text-gray-900">{p.roe_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Learn */}
      <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 mb-8">
        <p className="text-xs font-bold text-blue-700 uppercase tracking-wider mb-2">How to read DuPont</p>
        <ul className="text-xs text-blue-900 space-y-1.5 leading-relaxed">
          <li>&bull; <b>Rising ROE from margin</b> = pricing power, operational improvement (good)</li>
          <li>&bull; <b>Rising ROE from turnover</b> = better asset utilization (good)</li>
          <li>&bull; <b>Rising ROE from leverage</b> = more debt, amplified risk (caution)</li>
          <li>&bull; <b>Falling ROE across all three</b> = structural deterioration (red flag)</li>
        </ul>
      </div>

      {/* CTA */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-center text-white mb-8">
        <h2 className="text-lg font-bold mb-1">See DCF fair value for {display}</h2>
        <p className="text-blue-100 text-sm mb-4">Combine financial quality with intrinsic value.</p>
        <Link href={`/stocks/${display}/fair-value`} className="inline-block bg-white text-blue-700 font-bold px-6 py-2.5 rounded-xl hover:bg-blue-50 transition text-sm">
          See Fair Value &rarr;
        </Link>
      </div>

      <p className="text-[10px] text-gray-400 text-center">
        DuPont decomposition from audited annual financials. Factual analysis, not investment advice.
      </p>
    </div>
  )
}

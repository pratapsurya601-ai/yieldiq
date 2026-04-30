"use client"

import { useState } from "react"
import Link from "next/link"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

interface Trade {
  ticker: string
  quantity: number
  buy_date: string
  sell_date: string
  buy_price: number
  sell_price: number
  cost_basis: number
  proceeds: number
  gain: number
  holding_days: number
  category: "STCG" | "LTCG"
  fy: string
  error?: string
}

interface FYSummary {
  stcg_gain: number
  stcg_loss: number
  stcg_net: number
  stcg_taxable: number
  stcg_tax: number
  ltcg_gain: number
  ltcg_loss: number
  ltcg_net: number
  ltcg_exemption_applied: number
  ltcg_taxable: number
  ltcg_tax: number
  total_tax: number
  trade_count: number
  stcg_trades: Trade[]
  ltcg_trades: Trade[]
}

interface TaxSummary {
  by_fy: Record<string, FYSummary>
  overall: {
    total_stcg_net: number
    total_ltcg_net: number
    total_tax: number
    trade_count: number
    error_count: number
  }
  trades: Trade[]
  rules: {
    fy_applicable: string
    stcg_rate_pct: number
    ltcg_rate_pct: number
    ltcg_exemption_rs: number
    holding_period_days: number
  }
}

// sebi-allow: buy, sell
const CSV_PLACEHOLDER = "Symbol, Quantity, Buy Date, Buy Price, Sell Date, Sell Price"

// sebi-allow: buy, sell
const ZERODHA_EXAMPLE = `Symbol,Quantity,Buy Date,Buy Price,Sell Date,Sell Price
RELIANCE,10,15-03-2023,2450,20-09-2024,2943
ITC,50,10-01-2024,430,05-02-2025,460
TCS,5,22-11-2022,3100,18-12-2024,3850
HDFCBANK,20,04-07-2024,1580,12-10-2024,1720`

function fmtRs(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  return `${sign}\u20B9${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function fmtRsCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}\u20B9${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}\u20B9${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}\u20B9${(abs / 1_000).toFixed(1)}K`
  return `${sign}\u20B9${abs.toFixed(0)}`
}

export default function TaxReportPage() {
  const [csvText, setCsvText] = useState("")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TaxSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showTrades, setShowTrades] = useState<string | null>(null)
  const tier = useAuthStore(s => s.tier)

  const handleCompute = async () => {
    if (!csvText.trim()) {
      setError("Paste your trades CSV first")
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.post("/api/v1/tax/import", { csv_text: csvText, broker: "zerodha" })
      setResult(res.data)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string }; status?: number } }
      const detail = err.response?.data?.detail || "Could not compute tax"
      const status = err.response?.status
      if (status === 402) {
        setError(`${detail}`)
      } else {
        setError(detail)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleExportCSV = async () => {
    if (!result) return
    try {
      const res = await api.post("/api/v1/tax/export-csv", { trades: result.trades }, { responseType: "blob" })
      const blob = new Blob([res.data], { type: "text/csv" })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "yieldiq_capital_gains.csv"
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string }; status?: number } }
      const status = err.response?.status
      if (status === 402) {
        setError("CSV export requires Analyst tier (₹799/mo).")
      } else {
        setError("Export failed. Try again.")
      }
    }
  }

  const fyEntries = result ? Object.entries(result.by_fy).sort(([a], [b]) => b.localeCompare(a)) : []

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 pb-20">
      {/* Header */}
      <div className="mb-6">
        <Link href="/portfolio" className="text-xs text-gray-500 hover:text-gray-900 mb-3 inline-flex items-center gap-1">
          &larr; Back to portfolio
        </Link>
        <h1 className="text-2xl font-black text-gray-900 mb-1">Capital Gains Tax Report</h1>
        <p className="text-sm text-gray-500">India FY 2025-26 &middot; STCG 20% &middot; LTCG 12.5% above &#8377;1.25L</p>
      </div>

      {/* Tier gate */}
      {tier === "free" && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 mb-6">
          <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">Analyst Feature</p>
          <p className="text-sm text-amber-900 mb-3">
            Capital gains tax computation + ITR-ready CSV export is an Analyst (&#8377;799/mo) feature.
          </p>
          <Link href="/pricing" className="inline-block bg-amber-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-amber-700 transition">
            See pricing &rarr;
          </Link>
        </div>
      )}

      {/* Input section */}
      {!result && (
        <>
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wider">Paste Trades CSV</label>
              <button onClick={() => setCsvText(ZERODHA_EXAMPLE)} className="text-xs text-blue-600 hover:underline font-semibold">
                Load example
              </button>
            </div>
            <textarea
              value={csvText}
              onChange={e => setCsvText(e.target.value)}
              placeholder={CSV_PLACEHOLDER}
              rows={8}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs font-mono bg-white resize-y"
            />
          </div>

          <button
            onClick={handleCompute}
            disabled={loading || tier === "free" || !csvText.trim()}
            className="w-full py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition disabled:opacity-50"
          >
            {loading ? "Computing..." : "Compute Tax"}
          </button>

          {error && (
            <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-4">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          {/* Help */}
          <div className="mt-8 bg-gray-50 border border-gray-200 rounded-xl p-5">
            <h3 className="text-sm font-bold text-gray-900 mb-2">How to get your trades CSV from Zerodha</h3>
            <ol className="text-xs text-gray-600 space-y-1 list-decimal list-inside">
              <li>Log in to <a href="https://console.zerodha.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">Zerodha Console</a></li>
              <li>Reports &rarr; Tax P&amp;L &rarr; Select FY</li>
              {/* sebi-allow: buy, sell */}
              <li>Download Equity &mdash; gives FIFO-matched buy/sell pairs</li>
              <li>Paste the CSV contents here</li>
            </ol>
            <p className="text-[10px] text-gray-400 mt-3 leading-relaxed">
              We apply FY 2025-26 rules: STCG 20% on gains held &lt;12mo, LTCG 12.5% above &#8377;1.25L exemption.
              STCL is set off against LTCG where applicable. Grandfathering (pre-Feb 2018) is not computed here &mdash;
              use broker&apos;s Tax P&amp;L which already applies FMV rule.
            </p>
          </div>
        </>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Headline */}
          <div className="bg-gradient-to-br from-blue-600 to-cyan-500 rounded-2xl p-6 text-white mb-6">
            <p className="text-xs font-bold uppercase tracking-wider opacity-80 mb-1">Total Tax Liability</p>
            <p className="text-4xl font-black mb-3">{fmtRsCompact(result.overall.total_tax)}</p>
            <div className="grid grid-cols-3 gap-4 text-xs">
              <div>
                <p className="opacity-80">Net STCG</p>
                <p className="font-bold text-base">{fmtRsCompact(result.overall.total_stcg_net)}</p>
              </div>
              <div>
                <p className="opacity-80">Net LTCG</p>
                <p className="font-bold text-base">{fmtRsCompact(result.overall.total_ltcg_net)}</p>
              </div>
              <div>
                <p className="opacity-80">Trades</p>
                <p className="font-bold text-base">{result.overall.trade_count}</p>
              </div>
            </div>
          </div>

          {/* Per-FY breakdown */}
          <div className="space-y-4 mb-6">
            {fyEntries.map(([fy, s]) => (
              <div key={fy} className="bg-white border border-gray-200 rounded-2xl p-5">
                <div className="flex items-baseline justify-between mb-4">
                  <h2 className="text-lg font-bold text-gray-900">{fy}</h2>
                  <p className="text-xs text-gray-400">{s.trade_count} trades</p>
                </div>

                {/* STCG */}
                <div className="mb-4">
                  <div className="flex items-baseline justify-between mb-2">
                    <h3 className="text-sm font-bold text-gray-700">STCG (Short-term, &lt;12mo)</h3>
                    <p className={`text-xs font-bold ${s.stcg_net >= 0 ? "text-gray-900" : "text-green-600"}`}>
                      Net: {fmtRs(s.stcg_net)}
                    </p>
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-xs">
                    <div className="bg-gray-50 rounded-lg p-3">
                      <p className="text-gray-400">Gains</p>
                      <p className="font-mono font-semibold text-gray-900">{fmtRs(s.stcg_gain)}</p>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-3">
                      <p className="text-gray-400">Losses</p>
                      <p className="font-mono font-semibold text-red-600">{fmtRs(-s.stcg_loss)}</p>
                    </div>
                    <div className="bg-blue-50 rounded-lg p-3">
                      <p className="text-blue-700">Tax @20%</p>
                      <p className="font-mono font-bold text-blue-900">{fmtRs(s.stcg_tax)}</p>
                    </div>
                  </div>
                </div>

                {/* LTCG */}
                <div className="mb-4">
                  <div className="flex items-baseline justify-between mb-2">
                    <h3 className="text-sm font-bold text-gray-700">LTCG (Long-term, &ge;12mo)</h3>
                    <p className={`text-xs font-bold ${s.ltcg_net >= 0 ? "text-gray-900" : "text-green-600"}`}>
                      Net: {fmtRs(s.ltcg_net)}
                    </p>
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-xs">
                    <div className="bg-gray-50 rounded-lg p-3">
                      <p className="text-gray-400">Gains</p>
                      <p className="font-mono font-semibold text-gray-900">{fmtRs(s.ltcg_gain)}</p>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-3">
                      <p className="text-gray-400">Exemption Used</p>
                      <p className="font-mono font-semibold text-green-600">{fmtRs(s.ltcg_exemption_applied)}</p>
                    </div>
                    <div className="bg-blue-50 rounded-lg p-3">
                      <p className="text-blue-700">Tax @12.5%</p>
                      <p className="font-mono font-bold text-blue-900">{fmtRs(s.ltcg_tax)}</p>
                    </div>
                  </div>
                  {s.ltcg_net > 0 && s.ltcg_exemption_applied < result.rules.ltcg_exemption_rs && (
                    <p className="text-[10px] text-amber-700 mt-1">
                      You&apos;ve used &#8377;{s.ltcg_exemption_applied.toLocaleString("en-IN")} of the &#8377;1,25,000 annual exemption.
                    </p>
                  )}
                </div>

                {/* Total tax */}
                <div className="pt-4 border-t border-gray-100 flex items-center justify-between">
                  <p className="text-sm font-bold text-gray-900">FY Total Tax</p>
                  <p className="text-xl font-black text-gray-900">{fmtRs(s.total_tax)}</p>
                </div>

                {/* Show trades */}
                <button
                  onClick={() => setShowTrades(showTrades === fy ? null : fy)}
                  className="mt-3 text-xs text-blue-600 hover:underline font-semibold"
                >
                  {showTrades === fy ? "Hide" : "Show"} {s.trade_count} trades &rarr;
                </button>

                {showTrades === fy && (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-gray-200 text-gray-500">
                          <th className="text-left py-2 font-semibold">Ticker</th>
                          <th className="text-right py-2 font-semibold">Qty</th>
                          {/* sebi-allow: buy, sell */}
                          <th className="text-right py-2 font-semibold" title="Your transaction history">Buy</th>
                          {/* sebi-allow: buy, sell */}
                          <th className="text-right py-2 font-semibold" title="Your transaction history">Sell</th>
                          <th className="text-right py-2 font-semibold">Gain</th>
                          <th className="text-center py-2 font-semibold">Type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...s.stcg_trades, ...s.ltcg_trades].sort((a, b) => b.sell_date.localeCompare(a.sell_date)).map((t, i) => (
                          <tr key={i} className="border-b border-gray-50">
                            <td className="py-2 font-semibold text-gray-900">{t.ticker}</td>
                            <td className="py-2 text-right font-mono">{t.quantity}</td>
                            <td className="py-2 text-right font-mono text-gray-600">{fmtRsCompact(t.buy_price)}</td>
                            <td className="py-2 text-right font-mono text-gray-600">{fmtRsCompact(t.sell_price)}</td>
                            <td className={`py-2 text-right font-mono font-bold ${t.gain >= 0 ? "text-green-600" : "text-red-600"}`}>
                              {fmtRsCompact(t.gain)}
                            </td>
                            <td className="py-2 text-center">
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${t.category === "LTCG" ? "bg-blue-50 text-blue-700" : "bg-amber-50 text-amber-700"}`}>
                                {t.category}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-3 mb-6">
            <button
              onClick={handleExportCSV}
              disabled={tier !== "analyst"}
              className="flex-1 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition disabled:opacity-50"
            >
              {tier === "analyst" ? "Download ITR-ready CSV" : "Export CSV (Analyst tier)"}
            </button>
            <button
              onClick={() => { setResult(null); setCsvText(""); }}
              className="flex-1 py-3 bg-white border border-gray-200 text-gray-700 rounded-xl font-semibold hover:bg-gray-50 transition"
            >
              Start Over
            </button>
          </div>

          {tier !== "analyst" && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4">
              <p className="text-sm text-blue-900">
                <b>Upgrade to Analyst (&#8377;799/mo)</b> for ITR-ready CSV export.{" "}
                <Link href="/pricing" className="underline font-semibold">See pricing &rarr;</Link>
              </p>
            </div>
          )}

          {/* Disclaimer */}
          <p className="text-[10px] text-gray-400 text-center mt-6 leading-relaxed">
            Calculations apply post-Budget-2024 rules: LTCG threshold &#8377;1.25L, holding period changes,
            and buyback-as-dividend treatment for trades on/after 1 Oct 2024.
            This is an estimate &mdash; consult a CA for ITR filing.
            YieldIQ is not a tax advisor. Figures assume listed equity with STT paid.
          </p>
        </>
      )}
    </div>
  )
}

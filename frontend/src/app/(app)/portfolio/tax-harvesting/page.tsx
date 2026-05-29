"use client"

// Day-90 (2026-05-22): Tax-loss harvesting calculator.
// This is a TAX CALCULATOR, not investment advice. SEBI-sensitive
// copy throughout — see backend/services/analysis/sebi_filter.py
// for banned vocabulary. Use "candidate", "could offset",
// "estimated tax saved" instead.

import { useEffect, useState } from "react"
import Link from "next/link"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

interface TLHSuggestion {
  ticker: string
  qty: number
  avg_cost: number
  current_price: number
  unrealized_loss: number
  holding_period_months: number
  tax_bucket: "ST" | "LT"
  estimated_tax_saved: number
  rationale: string
  acquired_known: boolean
}

interface TLHResult {
  as_of: string
  fy: string
  suggestions: TLHSuggestion[]
  totals: {
    candidate_count: number
    gross_unrealized_loss: number
    estimated_tax_saved: number
  }
  context: {
    realized_stcg_this_fy: number
    realized_ltcg_this_fy: number
    ltcg_exemption_rs: number
    stcg_rate_pct: number
    ltcg_rate_pct: number
    caveats: string[]
    acquired_on_source?: string
  }
}

function fmtRs(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function fmtCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

export default function TaxHarvestingPage() {
  const tier = useAuthStore(s => s.tier)
  const token = useAuthStore(s => s.token)
  const [stcg, setStcg] = useState<string>("0")
  const [ltcg, setLtcg] = useState<string>("0")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TLHResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isGated = tier === "free"

  const handleCompute = async () => {
    if (isGated) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.post("/api/v1/portfolio/tlh-suggestions", {
        realized_stcg_this_fy: parseFloat(stcg) || 0,
        realized_ltcg_this_fy: parseFloat(ltcg) || 0,
      })
      setResult(res.data)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: { message?: string } | string }; status?: number } }
      const detail = err.response?.data?.detail
      const msg = typeof detail === "string" ? detail : detail?.message || "Could not load suggestions"
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  // Auto-load on mount for Analyst+ users with a saved portfolio.
  useEffect(() => {
    if (token && !isGated) {
      handleCompute()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, isGated])

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 pb-20">
      <div className="mb-6">
        <Link href="/portfolio" className="text-xs text-caption hover:text-gray-900 mb-3 inline-flex items-center gap-1">
          &larr; Back to portfolio
        </Link>
        <h1 className="text-2xl font-black text-ink mb-1">Tax-Loss Harvesting Calculator</h1>
        <p className="text-sm text-caption">
          Identify positions with unrealized losses that could offset realized gains in the current FY.
          Tax calculator &middot; not investment advice.
        </p>
      </div>

      {/* Explainer */}
      <details className="mb-6 bg-blue-50 border border-blue-200 rounded-xl p-4" open>
        <summary className="text-sm font-bold text-blue-900 cursor-pointer">
          How tax-loss harvesting works (Indian rules)
        </summary>
        <div className="mt-3 text-xs text-blue-900 space-y-2 leading-relaxed">
          <p>
            <span className="font-bold">Short-term (retained &lt; 12 months):</span> gains taxed at 20%. A short-term loss
            could offset BOTH short-term and long-term gains.
          </p>
          <p>
            <span className="font-bold">Long-term (retained &ge; 12 months):</span> gains taxed at 12.5% above the
            &#8377;1,25,000 per-FY exemption. A long-term loss could offset ONLY long-term gains.
          </p>
          <p>
            <span className="font-bold">Carry-forward:</span> unused losses can be carried forward up to 8 assessment
            years per the Income Tax Act.
          </p>
          <p>
            <span className="font-bold">No wash-sale rule in India:</span> unlike the US, you can repurchase the same
            security immediately after realizing a loss.
          </p>
        </div>
      </details>

      {/* Free-tier gate with sample preview */}
      {isGated && (
        <>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6">
            <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">
              Analyst Feature
            </p>
            <p className="text-sm text-amber-900 mb-3">
              The tax-loss harvesting calculator is an Analyst (&#8377;799/mo) tool. Upgrade to see
              ranked candidates from your own portfolio.
            </p>
            <Link
              href="/pricing"
              className="inline-block bg-amber-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-amber-700 transition"
            >
              See pricing &rarr;
            </Link>
          </div>

          <div className="bg-bg dark:bg-surface border border-border rounded-xl p-4 mb-6">
            <p className="text-xs font-bold text-caption uppercase tracking-wider mb-3">
              Sample preview
            </p>
            <SamplePreview />
          </div>
        </>
      )}

      {/* Inputs */}
      {!isGated && (
        <div className="bg-bg dark:bg-surface border border-border rounded-xl p-4 mb-6">
          <p className="text-xs font-bold text-caption uppercase tracking-wider mb-3">
            Realized FY gains so far (optional)
          </p>
          <p className="text-xs text-caption mb-3 leading-relaxed">
            Enter the net realized gains you&apos;ve booked in the current FY. Leave at zero if
            you don&apos;t have the figures handy &mdash; we&apos;ll model every loss as a
            carry-forward candidate instead.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-caption">Realized STCG (&#8377;)</label>
              <input
                type="number"
                value={stcg}
                onChange={e => setStcg(e.target.value)}
                className="mt-1 w-full px-3 py-2 border border-border rounded-lg text-sm bg-bg dark:bg-surface"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-caption">Realized LTCG (&#8377;)</label>
              <input
                type="number"
                value={ltcg}
                onChange={e => setLtcg(e.target.value)}
                className="mt-1 w-full px-3 py-2 border border-border rounded-lg text-sm bg-bg dark:bg-surface"
              />
            </div>
          </div>
          <button
            onClick={handleCompute}
            disabled={loading}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition disabled:opacity-50"
          >
            {loading ? "Computing…" : "Recompute"}
          </button>
        </div>
      )}

      {error && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {/* Results */}
      {!isGated && result && (
        <>
          <div className="bg-gradient-to-br from-emerald-600 to-teal-500 rounded-2xl p-6 text-white mb-6">
            <p className="text-xs font-bold uppercase tracking-wider opacity-80 mb-1">
              Estimated tax saved this {result.fy}
            </p>
            <p className="text-4xl font-black mb-3">
              {fmtCompact(result.totals.estimated_tax_saved)}
            </p>
            <div className="grid grid-cols-3 gap-4 text-xs">
              <div>
                <p className="opacity-80">Candidates</p>
                <p className="font-bold text-base">{result.totals.candidate_count}</p>
              </div>
              <div>
                <p className="opacity-80">Gross loss available</p>
                <p className="font-bold text-base">
                  {fmtCompact(result.totals.gross_unrealized_loss)}
                </p>
              </div>
              <div>
                <p className="opacity-80">As of</p>
                <p className="font-bold text-base">{result.as_of}</p>
              </div>
            </div>
          </div>

          {result.context.caveats.length > 0 && (
            <div className="mb-6 bg-amber-50 border border-amber-200 rounded-xl p-4">
              <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-2">
                Caveats
              </p>
              <ul className="text-xs text-amber-900 space-y-1 list-disc list-inside">
                {result.context.caveats.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}

          {result.suggestions.length === 0 ? (
            <div className="bg-bg dark:bg-surface border border-border rounded-xl p-8 text-center">
              <p className="text-sm font-bold text-ink mb-1">No harvesting candidates today</p>
              <p className="text-xs text-caption">
                None of your saved positions show an unrealized loss right now.
              </p>
            </div>
          ) : (
            <div className="bg-bg dark:bg-surface border border-border rounded-xl overflow-hidden mb-6">
              <table className="w-full text-xs">
                <thead className="bg-bg dark:bg-surface border-b border-border">
                  <tr className="text-caption">
                    <th className="text-left px-3 py-2 font-semibold">Ticker</th>
                    <th className="text-right px-3 py-2 font-semibold">Qty</th>
                    <th className="text-right px-3 py-2 font-semibold">Avg cost</th>
                    <th className="text-right px-3 py-2 font-semibold">Current</th>
                    <th className="text-right px-3 py-2 font-semibold">Unrealized loss</th>
                    <th className="text-center px-3 py-2 font-semibold">Bucket</th>
                    <th className="text-right px-3 py-2 font-semibold">Est. tax saved</th>
                  </tr>
                </thead>
                <tbody>
                  {result.suggestions.map(s => (
                    <tr key={s.ticker} className="border-b border-border last:border-0 align-top">
                      <td className="px-3 py-3 font-semibold text-ink">
                        {s.ticker.replace(".NS", "").replace(".BO", "")}
                        <div className="text-[10px] text-caption font-normal mt-0.5">
                          {s.holding_period_months}mo retained
                          {!s.acquired_known && " (date unknown)"}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right font-mono">{s.qty}</td>
                      <td className="px-3 py-3 text-right font-mono">{fmtRs(s.avg_cost)}</td>
                      <td className="px-3 py-3 text-right font-mono">{fmtRs(s.current_price)}</td>
                      <td className="px-3 py-3 text-right font-mono text-red-600">
                        {fmtRs(-s.unrealized_loss)}
                      </td>
                      <td className="px-3 py-3 text-center">
                        <span className={
                          "inline-block px-2 py-0.5 rounded text-[10px] font-bold " +
                          (s.tax_bucket === "ST"
                            ? "bg-orange-100 text-orange-800"
                            : "bg-violet-100 text-violet-800")
                        }>
                          {s.tax_bucket}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right font-mono font-bold text-emerald-700">
                        {fmtRs(s.estimated_tax_saved)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="bg-bg dark:bg-surface border-t border-border px-3 py-3">
                <p className="text-[11px] text-caption leading-relaxed">
                  <span className="font-bold">Rationale per candidate:</span>
                </p>
                <ul className="text-[11px] text-caption mt-1 space-y-1">
                  {result.suggestions.map(s => (
                    <li key={s.ticker}>
                      <span className="font-bold">
                        {s.ticker.replace(".NS", "").replace(".BO", "")}:
                      </span>{" "}
                      {s.rationale}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </>
      )}

      {/* Disclaimer */}
      <div className="mt-8 bg-bg dark:bg-surface border border-border rounded-xl p-4">
        <p className="text-[10px] text-caption leading-relaxed">
          <span className="font-bold">Disclaimer.</span> This is a tax calculation tool. Estimates are based on the
          rules of the Income Tax Act, 1961 as applicable to FY 2025-26 (listed equity with STT:
          STCG 20%, LTCG 12.5% above &#8377;1,25,000 exemption). Not all positions may be eligible
          for tax-loss harvesting based on individual circumstances, including grandfathering rules,
          STT applicability, scrip type (equity/MF/bond), and prior carry-forward losses. Acquisition
          dates are inferred from when each holding was saved to your YieldIQ portfolio, which may
          differ from the actual broker transaction date. Consult a tax adviser. YieldIQ is not a
          SEBI-registered investment adviser or tax adviser.
        </p>
      </div>
    </div>
  )
}

function SamplePreview() {
  const sample = [
    { ticker: "PAYTM", qty: 50, loss: 20000, bucket: "ST" as const, saved: 4000 },
    { ticker: "ZOMATO", qty: 100, loss: 8000, bucket: "LT" as const, saved: 1000 },
  ]
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-caption">
          <th className="text-left py-1">Ticker</th>
          <th className="text-right py-1">Qty</th>
          <th className="text-right py-1">Unrealized loss</th>
          <th className="text-center py-1">Bucket</th>
          <th className="text-right py-1">Est. tax saved</th>
        </tr>
      </thead>
      <tbody>
        {sample.map(s => (
          <tr key={s.ticker} className="border-t border-border">
            <td className="py-2 font-semibold">{s.ticker}</td>
            <td className="py-2 text-right font-mono">{s.qty}</td>
            <td className="py-2 text-right font-mono text-red-600">{fmtRs(-s.loss)}</td>
            <td className="py-2 text-center">
              <span className={
                "inline-block px-2 py-0.5 rounded text-[10px] font-bold " +
                (s.bucket === "ST"
                  ? "bg-orange-100 text-orange-800"
                  : "bg-violet-100 text-violet-800")
              }>
                {s.bucket}
              </span>
            </td>
            <td className="py-2 text-right font-mono font-bold text-emerald-700">
              {fmtRs(s.saved)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

"use client"
import { useParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { getAnalysis } from "@/lib/api"
import ConvictionRing from "@/components/analysis/ConvictionRing"
import VerdictChip from "@/components/analysis/VerdictChip"
import BlurredValue from "@/components/ui/BlurredValue"
import LearnTip from "@/components/ui/LearnTip"
import AISummary from "@/components/analysis/AISummary"
import ActionBar from "@/components/analysis/ActionBar"
import TransparencyStrip from "@/components/analysis/TransparencyStrip"
import InsightCards from "@/components/analysis/InsightCards"
import LoadingSteps from "@/components/ui/LoadingSteps"
import { formatCurrency, formatPct } from "@/lib/utils"

export default function AnalysisPage() {
  const params = useParams<{ ticker: string }>()
  const ticker = params?.ticker ?? ""

  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) return <LoadingSteps />
  if (error) return (
    <div className="max-w-md mx-auto px-4 py-16 text-center">
      <p className="text-4xl mb-4">&#9888;&#65039;</p>
      <p className="text-lg font-medium text-gray-900 mb-2">Could not load {ticker}</p>
      <p className="text-sm text-gray-500 mb-4">Data provider may be temporarily unavailable. Try again in a moment.</p>
      <button onClick={() => window.location.reload()} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium">Retry</button>
    </div>
  )
  if (!data) return null

  const { company, valuation, quality, insights } = data

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
      {/* Data confidence badge */}
      {data.data_confidence !== "high" && (
        <div className={`text-xs font-medium px-3 py-1 rounded-full inline-block ${data.data_confidence === "medium" ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700"}`}>
          Data: {data.data_confidence} confidence
        </div>
      )}

      {/* LAYER 1 -- Instant Verdict */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">{company.company_name}</h1>
            <p className="text-xs text-gray-400">{company.ticker} &middot; {company.sector}</p>
          </div>
          <p className="text-xl font-semibold text-gray-900 font-mono">
            {formatCurrency(valuation.current_price, company.currency)}
          </p>
        </div>

        <div className="flex items-center gap-5">
          <ConvictionRing score={quality.yieldiq_score} confidence={valuation.confidence_score} />
          <div className="flex-1 space-y-2">
            <VerdictChip verdict={valuation.verdict} size="lg" />
            <LearnTip tipKey="mos" />
            <BlurredValue value={valuation.fair_value} currency={company.currency} label="Fair value estimate" />
            <p className="text-sm text-gray-500">Margin of safety: {formatPct(valuation.margin_of_safety)}</p>
          </div>
        </div>

        <AISummary summary={data.ai_summary} ticker={ticker} />

        <TransparencyStrip
          wacc={valuation.wacc} waccMin={valuation.wacc_industry_min} waccMax={valuation.wacc_industry_max}
          fcfGrowth={valuation.fcf_growth_rate} fcfGrowthHistAvg={valuation.fcf_growth_historical_avg}
          confidence={data.data_confidence}
        />

        <ActionBar ticker={ticker} currentPrice={valuation.current_price} />
      </div>

      {/* LAYER 2 -- The Story (Insight Cards) */}
      <InsightCards quality={quality} insights={insights} valuation={valuation} currency={company.currency} />

      {/* LAYER 3 -- Scenarios */}
      {data.scenarios && (
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Scenario Analysis</h2>
          <div className="grid grid-cols-3 gap-3">
            {(["bear", "base", "bull"] as const).map((key) => {
              const sc = data.scenarios[key]
              const label = key === "bear" ? "Bear" : key === "base" ? "Base" : "Bull"
              const color = key === "bear" ? "text-red-600" : key === "bull" ? "text-green-600" : "text-blue-700"
              return (
                <div key={key} className="text-center p-3 rounded-xl bg-gray-50">
                  <p className="text-xs text-gray-400 mb-1">{label} case</p>
                  <p className={`text-lg font-bold font-mono ${color}`}>
                    {formatCurrency(sc.iv, company.currency)}
                  </p>
                  <p className="text-xs text-gray-400">MoS: {formatPct(sc.mos_pct)}</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-[10px] text-gray-400 text-center leading-relaxed px-4">
        All outputs are model estimates using publicly available data. Not investment advice.
        YieldIQ is not registered with SEBI as an investment adviser.
      </p>
    </div>
  )
}

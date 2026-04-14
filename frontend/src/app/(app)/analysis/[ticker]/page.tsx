"use client"
import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { getAnalysis, getChartData } from "@/lib/api"
import ConvictionRing from "@/components/analysis/ConvictionRing"
import VerdictChip from "@/components/analysis/VerdictChip"
import BlurredValue from "@/components/ui/BlurredValue"
import LearnTip from "@/components/ui/LearnTip"
import AISummary from "@/components/analysis/AISummary"
import ActionBar from "@/components/analysis/ActionBar"
import TransparencyStrip from "@/components/analysis/TransparencyStrip"
import InsightCards from "@/components/analysis/InsightCards"
import PriceChart from "@/components/analysis/PriceChart"
import FinancialBars from "@/components/analysis/FinancialBars"
import { formatCurrency, formatPct, formatCompanyName } from "@/lib/utils"
import { trackStockAnalysed } from "@/lib/analytics"
import Link from "next/link"

/* ------------------------------------------------------------------ */
/*  Skeleton that mirrors the real analysis layout — shown while       */
/*  the API call is in flight. Matches card structure so there is      */
/*  zero layout shift when real content replaces it.                   */
/* ------------------------------------------------------------------ */
function AnalysisSkeleton() {
  return (
    <div className="max-w-2xl md:max-w-3xl lg:max-w-5xl mx-auto px-4 py-6 space-y-5 pb-20 animate-pulse">
      {/* Card 1 skeleton — verdict */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4">
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <div className="h-5 w-40 bg-gray-200 rounded" />
            <div className="h-3 w-24 bg-gray-100 rounded" />
          </div>
          <div className="h-6 w-20 bg-gray-200 rounded" />
        </div>
        <div className="flex items-center gap-5">
          {/* Ring placeholder */}
          <div className="w-[100px] h-[100px] rounded-full bg-gray-100 border-4 border-gray-200" />
          <div className="flex-1 space-y-3">
            <div className="h-6 w-28 bg-gray-200 rounded-full" />
            <div className="h-4 w-36 bg-gray-100 rounded" />
            <div className="h-4 w-24 bg-gray-100 rounded" />
          </div>
        </div>
      </div>

      {/* Card 2 skeleton — AI summary */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
        <div className="h-4 w-24 bg-gray-200 rounded" />
        <div className="space-y-2">
          <div className="h-3 w-full bg-gray-100 rounded" />
          <div className="h-3 w-3/4 bg-gray-100 rounded" />
        </div>
        <div className="flex gap-2">
          <div className="h-10 flex-1 bg-gray-100 rounded-xl" />
          <div className="h-10 flex-1 bg-gray-100 rounded-xl" />
          <div className="h-10 flex-1 bg-gray-100 rounded-xl" />
          <div className="h-10 flex-1 bg-gray-100 rounded-xl" />
        </div>
      </div>

      {/* Insight cards skeleton */}
      <div className="grid grid-cols-2 gap-3">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-100 p-4 space-y-2">
            <div className="h-3 w-20 bg-gray-100 rounded" />
            <div className="h-5 w-16 bg-gray-200 rounded" />
            <div className="h-3 w-24 bg-gray-100 rounded" />
          </div>
        ))}
      </div>

      {/* Chart skeleton */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5">
        <div className="h-4 w-28 bg-gray-200 rounded mb-3" />
        <div className="h-[200px] bg-gray-50 rounded-xl" />
      </div>
    </div>
  )
}

export default function AnalysisPage() {
  const params = useParams<{ ticker: string }>()
  const ticker = params?.ticker ?? ""

  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
  })

  const { data: chartData } = useQuery({
    queryKey: ["chart-data", ticker, "1m"],
    queryFn: () => getChartData(ticker, "1m"),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
  })

  /* Staggered reveal removed — was causing white gaps (opacity-0 sections).
     Content now renders immediately. Skeleton handles the loading state. */

  // Dynamic SEO meta tags — must be before any conditional returns (Rules of Hooks)
  useEffect(() => {
    if (data) {
      const displayTicker = data.ticker.replace(".NS", "").replace(".BO", "")
      const verdict = data.valuation.verdict.replace("_", " ")
      document.title = `${displayTicker} — ${verdict} | YieldIQ`

      const desc = `${data.company.company_name} (${data.ticker}) fair value ₹${data.valuation.fair_value.toFixed(0)} vs price ₹${data.valuation.current_price.toFixed(0)}. YieldIQ Score: ${data.quality.yieldiq_score}/100. ${data.quality.moat} moat.`
      const metaDesc = document.querySelector('meta[name="description"]')
      if (metaDesc) {
        metaDesc.setAttribute("content", desc)
      } else {
        const meta = document.createElement("meta")
        meta.name = "description"
        meta.content = desc
        document.head.appendChild(meta)
      }
      // Track stock analysis in GA4
      trackStockAnalysed(
        data.ticker,
        data.valuation.verdict,
        data.quality.yieldiq_score
      )
    }
  }, [data])

  if (isLoading) return <AnalysisSkeleton />
  if (error) {
    const is429 = (error as { message?: string })?.message?.includes("Daily analysis limit reached")
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-gray-900 mb-2">
          {is429 ? "Daily limit reached" : `Could not load ${ticker}`}
        </p>
        <p className="text-sm text-gray-500 mb-4">
          {is429
            ? "You've used all your free analyses for today. Upgrade to Pro for unlimited access."
            : "Data provider may be temporarily unavailable. Try again in a moment."}
        </p>
        {is429 ? (
          <a href="/pricing" className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium inline-block">Upgrade</a>
        ) : (
          <button onClick={() => window.location.reload()} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium">Retry</button>
        )}
      </div>
    )
  }
  if (!data) return (
    <div className="max-w-md mx-auto px-4 py-16 text-center">
      <div className="bg-gray-50 border border-gray-100 rounded-xl p-4 text-center">
        <p className="text-sm text-gray-400">No analysis data available</p>
      </div>
    </div>
  )

  if (data.valuation.verdict === "unavailable") {
    const displayTicker = data.ticker.replace(".NS", "").replace(".BO", "")
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-gray-900 mb-2">
          Price data unavailable for {displayTicker}
        </p>
        <p className="text-sm text-gray-500 mb-4">
          {data.data_issues?.[0] || "Market data could not be fetched. This is usually temporary."}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium"
        >
          Retry in 60 seconds
        </button>
      </div>
    )
  }

  const { company, valuation, quality, insights } = data

  return (
    <div className="max-w-2xl md:max-w-3xl lg:max-w-5xl mx-auto px-4 py-6 space-y-5 pb-20">
      {/* Data confidence badge */}
      {data.data_confidence !== "high" && (
        <div className={`text-xs font-medium px-3 py-1 rounded-full inline-block ${data.data_confidence === "medium" ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700"}`}>
          Data: {data.data_confidence} confidence
        </div>
      )}

      {/* CARD 1 -- Compact Verdict (conviction ring + fair value + MoS) */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">{formatCompanyName(company.company_name)}</h1>
            <p className="text-xs text-gray-400">{company.ticker} &middot; {company.sector}</p>
          </div>
          <p className="text-xl font-semibold text-gray-900 font-mono">
            {formatCurrency(valuation.current_price, company.currency)}
          </p>
        </div>

        <div className="flex items-center gap-5">
          <ConvictionRing score={quality.yieldiq_score} confidence={valuation.confidence_score} />
          <div className="flex-1 space-y-1.5">
            <VerdictChip verdict={valuation.verdict} size="lg" />
            <BlurredValue value={valuation.fair_value} currency={company.currency} label="Fair value estimate" />
            <p className={`text-sm font-medium ${valuation.margin_of_safety >= 0 ? "text-blue-600" : "text-amber-600"}`}>
              MoS: {valuation.margin_of_safety > 80 ? "+80%+" : formatPct(valuation.margin_of_safety)}
              <LearnTip tipKey="mos" />
            </p>
          </div>
        </div>

        {valuation.margin_of_safety > 80 && (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
            Model shows significant undervaluation. Verify assumptions before acting on this signal.
          </div>
        )}

        {company.sector && /banking|insurance|financial services|nbfc|finance/i.test(company.sector) && (
          <div className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
            <span className="font-semibold">Note:</span> DCF less reliable for banking stocks. Use book value and P/E alongside.
          </div>
        )}
      </div>

      {/* CARD 2 -- AI Summary + Transparency + Actions */}
      <div className="">
        <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
          <AISummary
            summary={data.ai_summary}
            ticker={ticker}
            marginOfSafety={valuation.margin_of_safety}
            moat={quality.moat}
            confidence={valuation.confidence_score}
            fairValue={valuation.fair_value}
            currentPrice={valuation.current_price}
          />

          <div className="h-px bg-gray-100" />

          <TransparencyStrip
            wacc={valuation.wacc} waccMin={valuation.wacc_industry_min} waccMax={valuation.wacc_industry_max}
            fcfGrowth={valuation.fcf_growth_rate} fcfGrowthHistAvg={valuation.fcf_growth_historical_avg}
            confidence={data.data_confidence}
            fcfDataSource={valuation.fcf_data_source}
          />

          <ActionBar
            ticker={ticker}
            currentPrice={valuation.current_price}
            companyName={company.company_name}
            sector={company.sector}
            currency={company.currency}
            fairValue={valuation.fair_value}
            mos={valuation.margin_of_safety}
            verdict={valuation.verdict}
            score={quality.yieldiq_score}
            grade={quality.grade}
            piotroski={quality.piotroski_score}
            moat={quality.moat}
            moatScore={quality.moat_score}
            wacc={valuation.wacc}
            fcfGrowth={valuation.fcf_growth_rate}
            confidence={valuation.confidence_score}
            bearCase={data.scenarios?.bear?.iv ?? valuation.bear_case}
            baseCase={data.scenarios?.base?.iv ?? valuation.base_case}
            bullCase={data.scenarios?.bull?.iv ?? valuation.bull_case}
            bearMos={data.scenarios?.bear?.mos_pct ?? 0}
            bullMos={data.scenarios?.bull?.mos_pct ?? 0}
          />

          <Link href={`/compare?stock1=${ticker}`} className="text-xs text-blue-600 hover:underline">
            Compare with another stock &rarr;
          </Link>
        </div>
      </div>

      {/* LAYER 2 -- The Story (Insight Cards) */}
      <div className="">
        <InsightCards quality={quality} insights={insights} valuation={valuation} currency={company.currency} />
      </div>

      {/* Price Chart + Financial Bars */}
      <div className="space-y-5">
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Price History</h2>
          <PriceChart
            ticker={ticker}
            currentPrice={valuation.current_price}
            fairValue={valuation.fair_value}
            currency={company.currency}
          />
        </div>

        {/* Divider */}
        <div className="h-px bg-gray-100 mx-2" />

        {/* Financial Bars */}
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Financial Overview</h2>
          <FinancialBars
            ticker={ticker}
            currency={company.currency}
            revenue={chartData?.financials?.revenue}
            fcf={chartData?.financials?.fcf}
          />
        </div>
      </div>

      {/* LAYER 3 -- Scenarios */}
      <div className="space-y-5">
        {/* Divider */}
        <div className="h-px bg-gray-100 mx-2" />
        {data.scenarios ? (
          <div className="bg-white rounded-2xl border border-gray-100 p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Scenario Analysis</h2>
            <div className="grid grid-cols-3 gap-3">
              {(["bear", "base", "bull"] as const).map((key) => {
                const sc = data.scenarios[key]
                const label = key === "bear" ? "Bear" : key === "base" ? "Base" : "Bull"
                const color = key === "bear" ? "text-red-600" : key === "bull" ? "text-green-600" : "text-blue-700"
                const bgGradient = key === "bear"
                  ? "bg-gradient-to-b from-red-50 to-white"
                  : key === "bull"
                    ? "bg-gradient-to-b from-green-50 to-white"
                    : "bg-gradient-to-b from-blue-50 to-white"
                return (
                  <div key={key} className={`text-center p-3 rounded-xl border border-gray-100 ${bgGradient}`}>
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
        ) : (
          <div className="bg-gray-50 border border-gray-100 rounded-xl p-4 text-center">
            <p className="text-sm text-gray-400">Scenario analysis unavailable</p>
          </div>
        )}

        {/* Disclaimer */}
        <p className="text-[10px] text-gray-400 text-center leading-relaxed px-4">
          All outputs are model estimates using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </div>
    </div>
  )
}

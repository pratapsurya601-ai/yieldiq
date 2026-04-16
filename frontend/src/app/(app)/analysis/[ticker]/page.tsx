"use client"
import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { getAnalysis, getChartData, getFVHistory, getPeers, getFinancials } from "@/lib/api"
import ConvictionRing from "@/components/analysis/ConvictionRing"
import VerdictChip from "@/components/analysis/VerdictChip"
import BlurredValue from "@/components/ui/BlurredValue"
import LearnTip from "@/components/ui/LearnTip"
import AISummary from "@/components/analysis/AISummary"
import ActionBar from "@/components/analysis/ActionBar"
import TransparencyStrip from "@/components/analysis/TransparencyStrip"
import InsightCards from "@/components/analysis/InsightCards"
import RedFlagInsights from "@/components/analysis/RedFlagInsights"
import QualityRatios from "@/components/analysis/QualityRatios"
import DividendTracker from "@/components/analysis/DividendTracker"
import LoadingSteps from "@/components/ui/LoadingSteps"
import PriceChart from "@/components/analysis/PriceChart"
import FinancialBars from "@/components/analysis/FinancialBars"
import FairValueHistory from "@/components/analysis/FairValueHistory"
import FinancialStatements from "@/components/analysis/FinancialStatements"
import PeerComparison from "@/components/analysis/PeerComparison"
import { formatCurrency, formatPct, formatCompanyName } from "@/lib/utils"
import { trackStockAnalysed } from "@/lib/analytics"
import Link from "next/link"

/* ------------------------------------------------------------------ */
/*  Skeleton that mirrors the real analysis layout — shown while       */
/*  the API call is in flight. Matches card structure so there is      */
/*  zero layout shift when real content replaces it.                   */
/* ------------------------------------------------------------------ */
// LoadingSteps is used as the loading state — shows skeleton + animated progress steps

export default function AnalysisPage() {
  const params = useParams<{ ticker: string }>()
  const ticker = params?.ticker ?? ""

  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: (failureCount, err) => {
      // Don't retry 404 (ticker not found) or 429 (rate limit) —
      // neither will become a 200 on re-request.
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404 || status === 429) return false
      return failureCount < 1
    },
  })

  const { data: chartData } = useQuery({
    queryKey: ["chart-data", ticker, "1m"],
    queryFn: () => getChartData(ticker, "1m"),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
  })

  // ── Parallel warmup of sub-queries ────────────────────────────
  // Child components (FairValueHistory, PeerComparison,
  // FinancialStatements) each run their own useQuery. Firing those
  // same queryKeys here at page level makes them start in parallel
  // with the main analysis call instead of waiting for it to resolve
  // and the children to mount. Shared React Query cache means the
  // children's queries become instant cache hits. Results ignored —
  // this block is purely for side-effect warming.
  useQuery({
    queryKey: ["fv-history", ticker, 3],
    queryFn: () => getFVHistory(ticker, 3),
    enabled: !!ticker,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
  useQuery({
    queryKey: ["peers", ticker],
    queryFn: () => getPeers(ticker),
    enabled: !!ticker,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })
  useQuery({
    queryKey: ["financials", ticker, "annual"],
    queryFn: () => getFinancials(ticker, "annual", 5),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
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

  if (isLoading) return <LoadingSteps />
  if (error) {
    const msg = (error as { message?: string })?.message ?? ""
    const is429 = msg.includes("Daily analysis limit reached")
    const is404 = msg.includes("Ticker not found")
    // Backend attaches a per-ticker note for known-broken upstream
    // symbols (e.g. TATAMOTORS data-provider gap). Prefer that text
    // over the generic 404 message when present.
    const backendNote = (error as {
      response?: { data?: { detail?: { note?: string } | string } }
    })?.response?.data?.detail
    const note =
      typeof backendNote === "object" && backendNote !== null
        ? backendNote.note
        : undefined
    const displayTicker = ticker.replace(".NS", "").replace(".BO", "")
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-gray-900 mb-2">
          {is429 ? "Daily limit reached"
            : is404 ? "Ticker not found"
            : `Could not load ${ticker}`}
        </p>
        <p className="text-sm text-gray-500 mb-4">
          {is429
            ? "You've used all your free analyses for today. Upgrade to Pro for unlimited access."
            : is404
              ? (note ?? `We couldn\u2019t find \u201c${displayTicker}\u201d on any data provider. Please check the symbol and try again.`)
              : "Data provider may be temporarily unavailable. Try again in a moment."}
        </p>
        {is429 ? (
          <a href="/pricing" className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium inline-block">Upgrade</a>
        ) : is404 ? (
          <a href="/search" className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium inline-block">Search again</a>
        ) : (
          <button onClick={() => window.location.reload()} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium">Retry</button>
        )}
      </div>
    )
  }
  if (!data) {
    // Previously this path rendered a bare "No analysis data available"
    // with no affordance. Replaced with a full retry UI that matches
    // the error-branch pattern so users can recover.
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-gray-900 mb-2">
          Could not load {ticker}
        </p>
        <p className="text-sm text-gray-500 mb-4">
          Analysis data was empty. This is usually a transient
          data-provider hiccup.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium"
        >
          Retry
        </button>
      </div>
    )
  }

  // Defensive degenerate-response guard — catches the case where the
  // backend returned a 200 with a valid-looking verdict but every
  // monetary value is 0. Happens occasionally with stale/renamed
  // tickers where yfinance serves a cached price but no fundamentals.
  const isDegenerate =
    (!data.valuation.current_price || data.valuation.current_price < 1) ||
    (data.valuation.fair_value === 0 &&
      data.valuation.bear_case === 0 &&
      data.valuation.bull_case === 0 &&
      data.quality.yieldiq_score === 0)

  if (data.valuation.verdict === "unavailable" || isDegenerate) {
    const displayTicker = data.ticker.replace(".NS", "").replace(".BO", "")
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center pb-20">
        <p className="text-4xl mb-4">&#9888;&#65039;</p>
        <p className="text-lg font-medium text-gray-900 mb-2">
          Data unavailable for {displayTicker}
        </p>
        <p className="text-sm text-gray-500 mb-4">
          {data.data_issues?.[0] ||
            "We couldn\u2019t fetch reliable financial data for this ticker. It may be delisted, renamed, or temporarily unavailable."}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium"
        >
          Try again in a moment
        </button>
      </div>
    )
  }

  const { company, valuation, quality, insights } = data

  // Ticker-rename banner — triggers when backend silently aliased the
  // requested symbol to its canonical name (e.g. ZOMATO.NS → ETERNAL.NS).
  const requestedTicker = ticker.toUpperCase()
  const canonicalTicker = data.ticker.toUpperCase()
  const wasAliased = requestedTicker !== canonicalTicker
  const requestedDisplay = requestedTicker.replace(".NS", "").replace(".BO", "")
  const canonicalDisplay = canonicalTicker.replace(".NS", "").replace(".BO", "")

  return (
    <div className="max-w-2xl md:max-w-3xl lg:max-w-5xl mx-auto px-4 py-6 space-y-5 pb-20">
      {/* Rename banner — shown when URL ticker was aliased server-side */}
      {wasAliased && (
        <div className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
          <span className="font-semibold">{requestedDisplay}</span> has been renamed to{" "}
          <span className="font-semibold">{canonicalDisplay}</span>. Showing {canonicalDisplay} data.
        </div>
      )}

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

        {/* Extreme valuation explanation — shown when MoS > ±50% */}
        {valuation.margin_of_safety < -50 && valuation.current_price > 0 && valuation.fair_value > 0 && (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 leading-relaxed">
            <span className="font-semibold">Why the large gap?</span>{" "}
            {formatCompanyName(company.company_name)} trades at a significant premium to our DCF model
            (P/E {quality.roe && quality.roe > 0 ? `with ${quality.roe.toFixed(0)}% ROE` : ""}). The market values its
            brand strength, growth potential, and management quality — factors our quantitative model
            may not fully capture. Consider this estimate alongside qualitative analysis.
          </div>
        )}
        {valuation.margin_of_safety > 80 && (
          <div className="text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 leading-relaxed">
            <span className="font-semibold">Large undervaluation detected.</span>{" "}
            Our model shows significant upside, but verify: is the stock temporarily beaten down
            (opportunity) or is there a fundamental issue the model doesn&apos;t see? Check red flags
            and recent news before acting.
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
        <QualityRatios quality={quality} insights={insights} />
        <RedFlagInsights flags={insights?.red_flags_structured ?? []} />
        <DividendTracker dividend={insights?.dividend ?? null} currency={company.currency} />
      </div>

      {/* Historical Fair Value Chart — placed ABOVE price history per Phase 1 spec */}
      <FairValueHistory
        ticker={ticker}
        companyName={formatCompanyName(company.company_name)}
        currency={company.currency}
      />

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

        {/* Peer comparison table — sector-grouped */}
        <PeerComparison ticker={ticker} currency={company.currency} />

        {/* Full financial statements (Income / Balance Sheet / Cash Flow) */}
        <FinancialStatements ticker={ticker} currency={company.currency} />
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

        {/* Share Report Card CTA */}
        <div className="bg-gradient-to-r from-blue-50 to-cyan-50 border border-blue-100 rounded-xl p-4 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-gray-900">Share this analysis</p>
            <p className="text-xs text-gray-500">Beautiful report card for WhatsApp &amp; Twitter</p>
          </div>
          <a
            href={`/report/${ticker}`}
            className="bg-blue-600 text-white text-xs font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition whitespace-nowrap"
          >
            View Report Card →
          </a>
        </div>

        {/* Disclaimer */}
        <p className="text-[10px] text-gray-400 text-center leading-relaxed px-4">
          All outputs are model estimates using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </div>
    </div>
  )
}

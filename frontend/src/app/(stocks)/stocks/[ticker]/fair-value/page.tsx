import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import { validateAnalysisData } from "@/lib/validators"
import DataQualityBanner from "@/components/analysis/DataQualityBanner"
import DataUnderReview from "@/components/DataUnderReview"
import ValuationGrid from "@/components/analysis/ValuationGrid"
import HistoricFinancialsTable from "@/components/analysis/HistoricFinancialsTable"
import RatioSparklines from "@/components/analysis/RatioSparklines"
import PeerComparisonCard from "@/components/analysis/PeerComparisonCard"
import DividendHistorySparkline from "@/components/analysis/DividendHistorySparkline"
import SegmentRevenueTable from "@/components/analysis/SegmentRevenueTable"
import { getHistoricalFinancials, getRatiosHistory, getPublicPeers, getDividendHistory } from "@/lib/api"
import { timeAgo } from "@/lib/dataFreshness"
import ExcelExportButton from "@/components/analysis/ExcelExportButton"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface StockSummary {
  ticker: string
  company_name: string
  sector: string
  industry: string
  exchange: string
  currency: string
  fair_value: number
  current_price: number
  mos: number
  verdict: string
  score: number
  grade: string
  moat: string
  piotroski: number
  bear_case: number
  base_case: number
  bull_case: number
  wacc: number
  confidence: number
  roe: number | null
  de_ratio: number | null
  // Phase 2.1 ratios — all nullable, render "—" when missing
  roce: number | null
  debt_ebitda: number | null
  interest_coverage: number | null
  current_ratio: number | null
  asset_turnover: number | null
  revenue_cagr_3y: number | null
  revenue_cagr_5y: number | null
  ev_ebitda: number | null
  market_cap: number
  ai_summary_snippet: string | null
  last_updated: string | null
}

interface UnderReviewPayload {
  status: "under_review"
  ticker: string
  message: string
  last_validated_at: string
  reason: string
  issue_count: number
}

type StockResponse = StockSummary | UnderReviewPayload

function isUnderReview(d: StockResponse): d is UnderReviewPayload {
  return (d as UnderReviewPayload).status === "under_review"
}

// Last-line-of-defense sanity check — even if the backend gate missed
// something, we won't render impossible numbers. Mirrors the server
// bounds: WACC 0.02–0.30, |ROE| ≤ 200, FV/CMP 0.2–5x.
function clientSanityFail(d: StockSummary): boolean {
  if (d.wacc != null && (d.wacc > 0.30 || d.wacc < 0.02)) return true
  if (d.roe != null && Math.abs(d.roe) > 200) return true
  if (d.fair_value && d.current_price) {
    const r = d.fair_value / d.current_price
    if (r > 5 || r < 0.2) return true
  }
  return false
}

async function getStockData(ticker: string): Promise<StockResponse | null> {
  try {
    // 300s time-based fallback. Real freshness comes from on-demand
    // revalidation: backend/services/analysis_cache_service.save_cached
    // POSTs /api/revalidate after every successful cache write, so the
    // SEO page typically refreshes within seconds of a re-analysis.
    // The 5-minute TTL is just the safety net for when the on-demand
    // hook is unavailable (env var missing, network blip, etc.).
    const res = await fetch(`${API_BASE}/api/v1/public/stock-summary/${ticker}`, {
      next: { revalidate: 300 },
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

function fmt(n: number | null | undefined, currency = "INR"): string {
  if (n == null || isNaN(n)) return "\u2014"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(n)
}

function pct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "\u2014"
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`
}

function verdictLabel(v: string): string {
  if (!v) return ""
  // SEBI-safe: map 'avoid' to 'High Risk' (descriptive, not advice)
  const map: Record<string, string> = {
    undervalued: "Undervalued",
    fairly_valued: "Fairly valued",
    overvalued: "Overvalued",
    avoid: "High Risk",
    data_limited: "Data Limited",
    unavailable: "Unavailable",
  }
  if (map[v]) return map[v]
  return v.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
}

function verdictColor(v: string) {
  if (v === "undervalued") return { bg: "bg-green-50", text: "text-green-700", border: "border-green-200" }
  if (v === "overvalued") return { bg: "bg-red-50", text: "text-red-700", border: "border-red-200" }
  if (v === "avoid") return { bg: "bg-red-100", text: "text-red-800", border: "border-red-300" }
  return { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200" }
}

function scoreColor(s: number): string {
  if (s >= 75) return "text-green-600"
  if (s >= 55) return "text-blue-600"
  if (s >= 35) return "text-amber-600"
  return "text-red-600"
}

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const data = await getStockData(ticker)

  if (!data) {
    return { title: `${ticker.toUpperCase()} Stock Analysis | YieldIQ` }
  }

  const display = ticker.toUpperCase()

  if (isUnderReview(data)) {
    return {
      title: `${display} — Data Under Review | YieldIQ`,
      description: `Analysis for ${display} is being recalibrated. Check back shortly.`,
      robots: { index: false, follow: true },
    }
  }

  const vText = verdictLabel(data.verdict)
  // SEO-2026-04-21: rewrite for "X share price" intent.
  // GSC showed 225 impressions / 0 clicks — we ranked but didn't get
  // clicks. Top real-user queries: "acc share", "indus towers latest
  // news", "bluestar share price", "biocon latest news" — all
  // "<ticker> [share|price|news]" patterns we didn't match in our title.
  // New title leads with "Share Price <price>" so the SERP snippet
  // hits the keyword users actually type, then differentiates with
  // fair value (our moat).
  const priceText = data.current_price ? fmt(data.current_price) : ""
  const fvText = data.fair_value ? fmt(data.fair_value) : ""
  const mosText = data.mos != null
    ? `${data.mos > 0 ? "+" : ""}${data.mos.toFixed(1)}% MoS`
    : ""
  // Format e.g. "HDFCBANK Share Price ₹1,815 — Fair Value ₹1,892 (+4.2% MoS) | YieldIQ"
  const titleParts: string[] = [`${display} Share Price`]
  if (priceText) titleParts.push(priceText)
  let title = titleParts.join(" ")
  if (fvText) {
    title += ` \u2014 Fair Value ${fvText}`
    if (mosText) title += ` (${mosText})`
  } else {
    title += ` \u2014 ${vText}`
  }
  title += " | YieldIQ"

  return {
    title,
    description: `${data.company_name} share price ${priceText || "live"}. DCF fair value ${fvText || "n/a"}, margin of safety ${pct(data.mos)}, YieldIQ Score ${data.score}/100. Free DCF analysis on YieldIQ.`,
    openGraph: {
      title: `${display} Share Price ${priceText} \u2014 Fair Value ${fvText} | YieldIQ`,
      description: `${data.company_name} fair value ${fvText} vs ${priceText}. Score: ${data.score}/100. Moat: ${data.moat}.`,
      url: `https://yieldiq.in/stocks/${display}/fair-value`,
      siteName: "YieldIQ",
      type: "article",
      images: [
        {
          url: `https://yieldiq.in/api/og/${data.ticker}`,
          width: 1200,
          height: 630,
          alt: `${display} Fair Value Analysis`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: `${display} Share Price ${priceText} | YieldIQ`,
      description: `Fair value ${fvText} vs ${priceText}. Score: ${data.score}/100.`,
      images: [`https://yieldiq.in/api/og/${data.ticker}`],
    },
    alternates: { canonical: `https://yieldiq.in/stocks/${display}/fair-value` },
  }
}

export default async function StockFairValuePage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  // Fetch the hero summary and the three SEO-block payloads in parallel.
  // Each of the three auxiliary fetchers returns `null` on 503/network error
  // and the child components render a graceful placeholder in that case —
  // they never block the rest of the page from rendering.
  const [data, financials, ratios, peers, dividends] = await Promise.all([
    getStockData(ticker),
    getHistoricalFinancials(ticker, 10, "annual"),
    getRatiosHistory(ticker, 10, "annual"),
    getPublicPeers(ticker, 5),
    getDividendHistory(ticker, 10),
  ])
  if (!data) notFound()

  const display = ticker.toUpperCase()

  // Server said "under review" — never render numbers from this payload.
  if (isUnderReview(data)) {
    return (
      <DataUnderReview
        symbol={display}
        lastValidatedAt={data.last_validated_at}
        reason={data.reason}
      />
    )
  }

  // Last-line-of-defense: if the server missed something, still don't ship.
  if (clientSanityFail(data)) {
    return <DataUnderReview symbol={display} reason="client_sanity_fail" />
  }

  const vc = verdictColor(data.verdict)
  const mosSign = data.mos >= 0 ? "+" : ""

  // JSON-LD structured data
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "FinancialProduct",
    name: `${data.company_name} (${display})`,
    description: `DCF fair value analysis of ${data.company_name}`,
    provider: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <div className="max-w-4xl mx-auto px-4 py-8 sm:py-12">
        {/* Breadcrumb */}
        <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
          <Link href="/" className="hover:text-gray-600">Home</Link>
          <span>/</span>
          <Link href="/nifty50" className="hover:text-gray-600">Stocks</Link>
          <span>/</span>
          <span className="text-gray-600 font-medium">{display}</span>
        </nav>

        {/* Data quality gate — runs server-side */}
        {(() => {
          const valResult = validateAnalysisData({
            valuation: {
              fair_value: data.fair_value,
              current_price: data.current_price,
              margin_of_safety: data.mos,
              wacc: data.wacc,
              confidence_score: data.confidence,
            },
            quality: {
              yieldiq_score: data.score,
              roe: data.roe,
              de_ratio: data.de_ratio,
              piotroski_score: data.piotroski,
              moat: data.moat,
            },
          })
          return valResult.ok ? null : <DataQualityBanner result={valResult} ticker={display} />
        })()}

        {/* Hero Section */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden mb-8">
          <div className="p-6 sm:p-8">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
              <div>
                <h1 className="text-2xl sm:text-3xl font-black text-gray-900">
                  {data.company_name}
                </h1>
                <p className="text-gray-500 text-sm mt-1">
                  {display} &middot; {data.sector} &middot; {data.exchange}
                </p>
              </div>
              <div className="text-left sm:text-right">
                <p className="text-3xl font-black text-gray-900 font-mono">
                  {fmt(data.current_price)}
                </p>
                <p className="text-sm text-gray-400">Current Market Price</p>
              </div>
            </div>

            {/* Verdict + Fair Value + MoS */}
            <div className="flex flex-wrap gap-4 items-center">
              <span className={`px-4 py-2 rounded-full text-sm font-bold capitalize ${vc.bg} ${vc.text} ${vc.border} border`}>
                {verdictLabel(data.verdict)}
              </span>
              <div className="flex gap-6">
                <div>
                  <p className="text-xs text-gray-400">Fair Value (DCF)</p>
                  <p className="text-xl font-bold text-gray-900 font-mono">{fmt(data.fair_value)}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">Margin of Safety</p>
                  <p className={`text-xl font-bold font-mono ${data.mos >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {mosSign}{data.mos.toFixed(1)}%
                  </p>
                </div>
              </div>
            </div>
            {/* Freshness badge — server-rendered "Updated N ago" relative
                to the cached AnalysisResponse.timestamp. Omitted when the
                payload has no timestamp (per Trust-Surface spec — never
                fabricate a freshness signal). Value is fixed for the
                lifetime of an ISR slice (~5 min revalidate on this route),
                which is acceptable given the page's freshness budget. */}
            {(() => {
              const ago = timeAgo(data.last_updated)
              return ago ? (
                <p className="mt-3 text-[11px] text-gray-400">
                  <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-gray-50 border border-gray-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500" aria-hidden />
                    Updated {ago}
                  </span>
                </p>
              ) : null
            })()}
            {/* Power-user actions: deep-dive sensitivity heatmap + offline Excel.
                Kept in the hero so they're discoverable without competing with
                the primary verdict copy. */}
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Link
                href={`/stocks/${display}/fair-value/sensitivity`}
                className="inline-flex items-center gap-1.5 rounded-xl border bg-white px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 transition"
                style={{ borderColor: "var(--color-border, #E2E8F0)" }}
              >
                DCF Sensitivity →
              </Link>
              <ExcelExportButton ticker={display} />
            </div>
          </div>
        </div>

        {/* Key Metrics Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          {[
            { label: "YieldIQ Score", value: `${data.score}/100`, color: scoreColor(data.score) },
            { label: "Piotroski F-Score", value: `${data.piotroski}/9`, color: data.piotroski >= 7 ? "text-green-600" : data.piotroski >= 4 ? "text-blue-600" : "text-red-600" },
            { label: "Economic Moat", value: data.moat, color: data.moat === "Wide" ? "text-green-600" : data.moat === "Narrow" ? "text-blue-600" : "text-gray-600" },
            { label: "Confidence", value: `${data.confidence}%`, color: data.confidence >= 70 ? "text-green-600" : "text-amber-600" },
            { label: "ROE", value: data.roe != null ? `${data.roe.toFixed(1)}%` : "\u2014", color: "text-gray-900" },
            { label: "Debt/Equity", value: data.de_ratio != null ? data.de_ratio.toFixed(2) : "\u2014", color: "text-gray-900" },
            { label: "WACC", value: `${(data.wacc * 100).toFixed(1)}%`, color: "text-gray-900" },
            { label: "Market Cap", value: data.market_cap ? `\u20B9${(data.market_cap / 1e10).toFixed(0)}K Cr` : "\u2014", color: "text-gray-900" },
          ].map(m => (
            <div key={m.label} className="bg-gray-50 rounded-xl p-4 border border-gray-100">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{m.label}</p>
              <p className={`text-lg font-bold ${m.color}`}>{m.value}</p>
            </div>
          ))}
        </div>

        {/* Quality & Valuation ratios — Phase 2.1
            Neutral monochrome; factual descriptors; "—" when data missing.
            NO buy/sell color coding. */}
        {(data.roce != null || data.ev_ebitda != null || data.debt_ebitda != null ||
          data.interest_coverage != null || data.current_ratio != null ||
          data.asset_turnover != null || data.revenue_cagr_3y != null) && (
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
            <h2 className="text-lg font-bold text-gray-900 mb-1">Quality &amp; Valuation</h2>
            <p className="text-xs text-gray-400 mb-4">Neutral model outputs &mdash; no recommendations.</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              {[
                { label: "ROCE", value: data.roce != null ? `${data.roce.toFixed(1)}%` : "\u2014", note: "Return on capital employed" },
                { label: "EV / EBITDA", value: data.ev_ebitda != null ? `${data.ev_ebitda.toFixed(1)}\u00D7` : "\u2014", note: "Enterprise multiple" },
                { label: "Debt / EBITDA", value: data.debt_ebitda != null ? `${data.debt_ebitda.toFixed(1)}\u00D7` : "\u2014", note: "Leverage vs earnings" },
                { label: "Interest Coverage", value: data.interest_coverage != null ? `${data.interest_coverage.toFixed(1)}\u00D7` : "\u2014", note: "EBIT covers interest" },
                { label: "Current Ratio", value: data.current_ratio != null ? `${data.current_ratio.toFixed(2)}\u00D7` : "\u2014", note: "Short-term liquidity" },
                { label: "Asset Turnover", value: data.asset_turnover != null ? `${data.asset_turnover.toFixed(2)}\u00D7` : "\u2014", note: "Revenue per \u20B9 of assets" },
                { label: "Revenue CAGR (3Y)", value: data.revenue_cagr_3y != null ? `${(data.revenue_cagr_3y * 100).toFixed(1)}%` : "\u2014", note: "3-year revenue growth" },
                { label: "Revenue CAGR (5Y)", value: data.revenue_cagr_5y != null ? `${(data.revenue_cagr_5y * 100).toFixed(1)}%` : "\u2014", note: "5-year revenue growth" },
              ].map(r => (
                <div key={r.label} className="border-l-2 border-gray-200 pl-3 py-1">
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider">{r.label}</p>
                  <p className="text-lg font-bold text-gray-900 font-mono">{r.value}</p>
                  <p className="text-[10px] text-gray-400">{r.note}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* DCF Scenarios — shared with the authed analysis page via
            <ValuationGrid />. Per-scenario MoS is derived from CMP since
            the public stock-summary payload only carries the raw bear/
            base/bull fair-value figures (the canonical AnalysisResponse
            ScenariosOutput is not yet exposed on this endpoint). */}
        <div className="mb-8">
          <ValuationGrid
            bear={{
              fair_value: data.bear_case,
              mos_pct: data.current_price > 0
                ? ((data.bear_case - data.current_price) / data.bear_case) * 100
                : 0,
            }}
            base={{
              fair_value: data.base_case,
              mos_pct: data.current_price > 0
                ? ((data.base_case - data.current_price) / data.base_case) * 100
                : 0,
            }}
            bull={{
              fair_value: data.bull_case,
              mos_pct: data.current_price > 0
                ? ((data.bull_case - data.current_price) / data.bull_case) * 100
                : 0,
            }}
            currentPrice={data.current_price}
            currency={data.currency}
          />
        </div>

        {/* SEO blocks — each renders a graceful placeholder on null payload
            (503 under_review / network error). Order is ratio-trends first
            as a visual "quality story", then the full financials table,
            then peers for competitive context. */}
        <RatioSparklines ticker={display} data={ratios} />
        <HistoricFinancialsTable ticker={display} data={financials} />
        <PeerComparisonCard ticker={display} data={peers} />
        <DividendHistorySparkline
          ticker={display}
          data={dividends}
          currentPrice={data.current_price ?? null}
        />

        {/* Segment-level revenue (renders nothing if company doesn't disclose). */}
        <SegmentRevenueTable ticker={display} years={5} />

        {/* AI Summary */}
        {data.ai_summary_snippet && (
          <div className="bg-blue-50 border border-blue-100 rounded-2xl p-6 mb-8">
            <h2 className="text-sm font-bold text-blue-800 mb-2">AI Analysis Summary</h2>
            <p className="text-sm text-blue-700 leading-relaxed">{data.ai_summary_snippet}</p>
            <Link
              href={`/analysis/${data.ticker}`}
              className="text-blue-600 text-sm font-semibold mt-3 inline-block hover:underline"
            >
              Read full AI analysis &rarr;
            </Link>
          </div>
        )}

        {/* Related tools */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <Link
            href={`/stocks/${display}/reverse-dcf`}
            className="block bg-white border-2 border-blue-100 hover:border-blue-300 rounded-2xl p-5 transition group"
          >
            <p className="text-xs font-bold text-blue-600 uppercase tracking-wider mb-1">Reverse DCF</p>
            <h3 className="font-bold text-gray-900 mb-1 group-hover:text-blue-700 transition">Market-implied growth</h3>
            <p className="text-xs text-gray-500">What FCF growth is priced in &rarr;</p>
          </Link>
          <Link
            href={`/stocks/${display}/risk-analysis`}
            className="block bg-white border-2 border-blue-100 hover:border-blue-300 rounded-2xl p-5 transition group"
          >
            <p className="text-xs font-bold text-blue-600 uppercase tracking-wider mb-1">Risk Analysis</p>
            <h3 className="font-bold text-gray-900 mb-1 group-hover:text-blue-700 transition">Volatility & drawdown</h3>
            <p className="text-xs text-gray-500">Risk profile of {display} &rarr;</p>
          </Link>
          <Link
            href={`/stocks/${display}/dupont`}
            className="block bg-white border-2 border-blue-100 hover:border-blue-300 rounded-2xl p-5 transition group"
          >
            <p className="text-xs font-bold text-blue-600 uppercase tracking-wider mb-1">DuPont</p>
            <h3 className="font-bold text-gray-900 mb-1 group-hover:text-blue-700 transition">ROE decomposition</h3>
            <p className="text-xs text-gray-500">Why ROE is what it is &rarr;</p>
          </Link>
          <Link
            href={`/stocks/${display}/technicals`}
            className="block bg-white border-2 border-blue-100 hover:border-blue-300 rounded-2xl p-5 transition group"
          >
            <p className="text-xs font-bold text-blue-600 uppercase tracking-wider mb-1">Technicals</p>
            <h3 className="font-bold text-gray-900 mb-1 group-hover:text-blue-700 transition">RSI, MACD, MAs</h3>
            <p className="text-xs text-gray-500">Reference indicators &rarr;</p>
          </Link>
        </div>
        <div className="grid sm:grid-cols-2 gap-4 mb-8">
          <Link
            href={`/stocks/${display}/news`}
            className="block bg-white border-2 border-blue-100 hover:border-blue-300 rounded-2xl p-5 transition group"
          >
            <p className="text-xs font-bold text-blue-600 uppercase tracking-wider mb-1">News & Filings</p>
            <h3 className="font-bold text-gray-900 mb-1 group-hover:text-blue-700 transition">Recent activity</h3>
            <p className="text-xs text-gray-500">BSE filings + news for {display} &rarr;</p>
          </Link>
          <Link
            href={`/compare/${display}-vs-RELIANCE`}
            className="block bg-white border-2 border-blue-100 hover:border-blue-300 rounded-2xl p-5 transition group"
          >
            <p className="text-xs font-bold text-blue-600 uppercase tracking-wider mb-1">Compare</p>
            <h3 className="font-bold text-gray-900 mb-1 group-hover:text-blue-700 transition">Head-to-head with peers</h3>
            <p className="text-xs text-gray-500">Compare {display} side by side &rarr;</p>
          </Link>
        </div>

        {/* CTA */}
        <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-8 text-center text-white mb-8">
          <h2 className="text-xl font-bold mb-2">Run Full Interactive Analysis</h2>
          <p className="text-blue-100 text-sm mb-4">
            Interactive DCF sliders, sensitivity heatmap, peer comparison, and more.
          </p>
          <Link
            href={`/analysis/${data.ticker}`}
            className="inline-block bg-white text-blue-700 font-bold px-8 py-3 rounded-xl hover:bg-blue-50 transition"
          >
            Analyse {display} Now &rarr;
          </Link>
        </div>

        {/* Disclaimer */}
        <p className="text-[10px] text-gray-400 text-center leading-relaxed">
          Model estimates using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser or research analyst.
          Past performance does not guarantee future results.
        </p>
      </div>
    </>
  )
}

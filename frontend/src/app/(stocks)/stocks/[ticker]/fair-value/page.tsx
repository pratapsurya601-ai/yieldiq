import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"

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
  market_cap: number
  ai_summary_snippet: string | null
  last_updated: string | null
}

async function getStockData(ticker: string): Promise<StockSummary | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/stock-summary/${ticker}`, {
      next: { revalidate: 3600 },
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
  const vText = verdictLabel(data.verdict)

  return {
    title: `${data.company_name} (${display}) Fair Value \u2014 ${vText} | YieldIQ`,
    description: `${data.company_name} DCF valuation: Fair value ${fmt(data.fair_value)} vs price ${fmt(data.current_price)}. Margin of Safety ${pct(data.mos)}. YieldIQ Score: ${data.score}/100. Free analysis.`,
    openGraph: {
      title: `${display} \u2014 ${vText} | YieldIQ Fair Value`,
      description: `${data.company_name} fair value ${fmt(data.fair_value)} vs ${fmt(data.current_price)}. Score: ${data.score}/100. Moat: ${data.moat}.`,
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
      title: `${display} \u2014 ${vText} | YieldIQ`,
      description: `Fair value ${fmt(data.fair_value)} vs ${fmt(data.current_price)}. Score: ${data.score}/100.`,
      images: [`https://yieldiq.in/api/og/${data.ticker}`],
    },
    alternates: { canonical: `https://yieldiq.in/stocks/${display}/fair-value` },
  }
}

export default async function StockFairValuePage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const data = await getStockData(ticker)
  if (!data) notFound()

  const display = ticker.toUpperCase()
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

        {/* DCF Scenarios */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
          <h2 className="text-lg font-bold text-gray-900 mb-4">DCF Scenario Analysis</h2>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "Bear Case", value: data.bear_case, color: "border-red-200 bg-red-50", textColor: "text-red-700" },
              { label: "Base Case", value: data.base_case, color: "border-blue-200 bg-blue-50", textColor: "text-blue-700" },
              { label: "Bull Case", value: data.bull_case, color: "border-green-200 bg-green-50", textColor: "text-green-700" },
            ].map(s => (
              <div key={s.label} className={`rounded-xl p-4 text-center border ${s.color}`}>
                <p className="text-xs text-gray-500 mb-1">{s.label}</p>
                <p className={`text-xl font-bold font-mono ${s.textColor}`}>{fmt(s.value)}</p>
              </div>
            ))}
          </div>
        </div>

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

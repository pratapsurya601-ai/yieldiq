"use client"
import { useParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { getAnalysis } from "@/lib/api"
import { formatCurrency, formatCompanyName } from "@/lib/utils"
import Link from "next/link"

function gradeColor(grade: string) {
  if (grade === "A") return "bg-green-500"
  if (grade === "B") return "bg-blue-500"
  if (grade === "C") return "bg-yellow-500"
  return "bg-red-500"
}

function verdictColor(v: string) {
  if (v === "undervalued") return "text-green-700 bg-green-50"
  if (v === "fairly_valued") return "text-blue-700 bg-blue-50"
  if (v === "overvalued") return "text-red-700 bg-red-50"
  return "text-gray-700 bg-gray-50"
}

export default function ReportPage() {
  const params = useParams<{ ticker: string }>()
  const ticker = params?.ticker ?? ""

  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis", ticker],
    queryFn: () => getAnalysis(ticker),
    enabled: !!ticker,
    staleTime: 15 * 60 * 1000,
  })

  if (isLoading) return (
    <div className="max-w-md mx-auto px-4 py-20 text-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent mx-auto" />
      <p className="text-sm text-gray-400 mt-4">Generating report...</p>
    </div>
  )

  if (error || !data) return (
    <div className="max-w-md mx-auto px-4 py-20 text-center">
      <p className="text-gray-500">Could not generate report for {ticker}</p>
      <Link href={`/analysis/${ticker}`} className="text-blue-600 text-sm mt-2 inline-block">Try full analysis →</Link>
    </div>
  )

  const { company, valuation, quality } = data
  const displayTicker = ticker.replace(".NS", "").replace(".BO", "")
  const verdict = valuation.verdict.replace("_", " ")
  const mosSign = valuation.margin_of_safety >= 0 ? "+" : ""

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white pb-20">
      <div className="max-w-md mx-auto px-4 py-8">
        {/* Report Card */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-lg overflow-hidden">

          {/* Header gradient */}
          <div className="bg-gradient-to-r from-blue-600 to-cyan-500 px-5 py-4 text-white">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-lg font-bold">{formatCompanyName(company.company_name)}</h1>
                <p className="text-blue-100 text-xs">{displayTicker} &middot; {company.sector}</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold font-mono">{formatCurrency(valuation.current_price, company.currency)}</p>
              </div>
            </div>
          </div>

          {/* Score + Verdict */}
          <div className="px-5 py-4 flex items-center gap-4 border-b border-gray-100">
            <div className="flex-shrink-0">
              <div className={`w-14 h-14 rounded-full flex items-center justify-center text-white font-bold text-xl ${gradeColor(quality.grade)}`}>
                {quality.yieldiq_score}
              </div>
              <p className="text-[10px] text-gray-400 text-center mt-1">YieldIQ</p>
            </div>
            <div className="flex-1">
              <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold capitalize ${verdictColor(valuation.verdict)}`}>
                {verdict}
              </span>
              <div className="mt-2 flex gap-4 text-xs text-gray-600">
                <div>
                  <span className="text-gray-400">Fair Value</span>
                  <p className="font-semibold font-mono">{formatCurrency(valuation.fair_value, company.currency)}</p>
                </div>
                <div>
                  <span className="text-gray-400">MoS</span>
                  <p className={`font-semibold ${valuation.margin_of_safety >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {mosSign}{valuation.margin_of_safety.toFixed(1)}%
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Key Metrics Grid */}
          <div className="grid grid-cols-3 divide-x divide-gray-100 border-b border-gray-100">
            <div className="px-3 py-3 text-center">
              <p className="text-[10px] text-gray-400 uppercase">Piotroski</p>
              <p className="text-lg font-bold text-gray-900">{quality.piotroski_score}/9</p>
            </div>
            <div className="px-3 py-3 text-center">
              <p className="text-[10px] text-gray-400 uppercase">Moat</p>
              <p className="text-lg font-bold text-gray-900">{quality.moat}</p>
            </div>
            <div className="px-3 py-3 text-center">
              <p className="text-[10px] text-gray-400 uppercase">Confidence</p>
              <p className="text-lg font-bold text-gray-900">{valuation.confidence_score}%</p>
            </div>
          </div>

          {/* Scenario Strip */}
          {data.scenarios && (
            <div className="grid grid-cols-3 divide-x divide-gray-100 border-b border-gray-100">
              {(["bear", "base", "bull"] as const).map(key => {
                const sc = data.scenarios[key]
                const label = key === "bear" ? "Bear" : key === "bull" ? "Bull" : "Base"
                const color = key === "bear" ? "text-red-600" : key === "bull" ? "text-green-600" : "text-blue-700"
                return (
                  <div key={key} className="px-3 py-2 text-center">
                    <p className="text-[10px] text-gray-400">{label} case</p>
                    <p className={`text-sm font-bold font-mono ${color}`}>
                      {formatCurrency(sc.iv, company.currency)}
                    </p>
                  </div>
                )
              })}
            </div>
          )}

          {/* AI Summary */}
          {data.ai_summary && (
            <div className="px-5 py-3 border-b border-gray-100">
              <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">
                {data.ai_summary}
              </p>
            </div>
          )}

          {/* Footer CTA */}
          <div className="px-5 py-4 bg-gray-50 flex items-center justify-between">
            <div>
              <p className="text-[10px] text-gray-400">Powered by</p>
              <p className="text-sm font-bold text-gray-900">YieldIQ</p>
            </div>
            <Link
              href={`/analysis/${ticker}`}
              className="bg-blue-600 text-white text-xs font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition"
            >
              See full analysis →
            </Link>
          </div>
        </div>

        {/* Share buttons */}
        <div className="mt-6 flex gap-3 justify-center">
          <a
            href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(`${formatCompanyName(company.company_name)} (${displayTicker}) — ${verdict}\n\nFair Value: ${formatCurrency(valuation.fair_value, company.currency)} vs Price: ${formatCurrency(valuation.current_price, company.currency)}\nYieldIQ Score: ${quality.yieldiq_score}/100\n\nFree analysis at yieldiq.in/analysis/${ticker}`)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 bg-black text-white text-xs font-semibold px-4 py-2 rounded-lg hover:bg-gray-800 transition"
          >
            Share on X
          </a>
          <a
            href={`https://wa.me/?text=${encodeURIComponent(`${formatCompanyName(company.company_name)} — ${verdict}\n\nPrice: ${formatCurrency(valuation.current_price, company.currency)}\nFair Value: ${formatCurrency(valuation.fair_value, company.currency)}\nMoS: ${mosSign}${valuation.margin_of_safety.toFixed(1)}%\nScore: ${quality.yieldiq_score}/100\n\nSee full analysis: https://yieldiq.in/analysis/${ticker}`)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 bg-green-600 text-white text-xs font-semibold px-4 py-2 rounded-lg hover:bg-green-700 transition"
          >
            Share on WhatsApp
          </a>
        </div>

        {/* Disclaimer */}
        <p className="text-[10px] text-gray-400 text-center mt-6 px-4">
          Model estimate using publicly available data. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </div>
    </div>
  )
}

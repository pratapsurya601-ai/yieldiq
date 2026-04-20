"use client"

import { useState } from "react"
import Link from "next/link"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import ConcallEmpty from "@/components/empty-states/ConcallEmpty"

interface GuidanceItem {
  topic: string
  guidance: string
  quote: string
}

interface QATheme {
  theme: string
  summary: string
}

interface ConcallAnalysis {
  executive_summary: string
  financial_highlights: string[]
  forward_guidance: GuidanceItem[]
  strategic_priorities: string[]
  q_and_a_themes: QATheme[]
  concerns_raised: string[]
  sentiment: "positive" | "neutral" | "cautious" | "negative"
  sentiment_rationale: string
  ticker: string
  quarter: string
  analyzed_at: string
  cached: boolean
}

const SAMPLE_TRANSCRIPT = `Good morning everyone, and welcome to ABC Limited's Q3 FY26 earnings call. I'm pleased to report another strong quarter.

Revenue grew 12% year-over-year to Rs 8,500 crore, driven primarily by 18% growth in our consumer segment. EBITDA margin expanded by 120 basis points to 23.4%, reflecting operating leverage and pricing actions taken last quarter.

Looking ahead to FY27, we expect revenue growth in the 14-16% range, with margin expansion of another 50-80 bps as our new capacity comes online in Q2.

Our key priorities remain capacity expansion at the Hyderabad facility, deeper rural distribution, and the upcoming launch of three new products in the premium category.

[Q&A Section]
Analyst 1: Can you comment on raw material inflation impact?
CFO: We've seen a 4-5% increase in input costs this quarter. Our pricing actions in October are recovering most of this with a one-quarter lag.

Analyst 2: How do you see the rural slowdown impacting Q4?
CEO: Rural is showing initial signs of recovery. We expect normal monsoons next year to drive a stronger H2 FY27.`

function sentimentColor(s: string): string {
  if (s === "positive") return "bg-green-50 text-green-800 border-green-200"
  if (s === "negative") return "bg-red-50 text-red-800 border-red-200"
  if (s === "cautious") return "bg-amber-50 text-amber-800 border-amber-200"
  return "bg-blue-50 text-blue-800 border-blue-200"
}

export default function ConcallPage() {
  const tier = useAuthStore(s => s.tier)
  const [transcript, setTranscript] = useState("")
  const [ticker, setTicker] = useState("")
  const [quarter, setQuarter] = useState("Q3 FY26")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ConcallAnalysis | null>(null)

  const handleAnalyze = async () => {
    if (!transcript.trim() || transcript.length < 200) {
      setError("Paste the transcript first (at least 200 characters)")
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.post("/api/v1/concall/analyze", {
        transcript,
        ticker: ticker.trim().toUpperCase(),
        quarter: quarter.trim(),
        save: true,
      })
      setResult(res.data)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string }; status?: number } }
      const status = err.response?.status
      const detail = err.response?.data?.detail || "Analysis failed"
      setError(status === 402 ? `${detail}` : detail)
    } finally {
      setLoading(false)
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    if (file.name.toLowerCase().endsWith(".pdf")) {
      setError("PDF parsing isn't supported yet. Open the PDF in a viewer, copy all text (Ctrl+A, Ctrl+C), and paste here.")
      return
    }
    try {
      const text = await file.text()
      setTranscript(text)
    } catch {
      setError("Could not read file")
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 pb-20">
      <div className="mb-6">
        <Link href="/portfolio" className="text-xs text-gray-500 hover:text-gray-900 mb-3 inline-flex items-center gap-1">
          &larr; Back
        </Link>
        <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-1">AI Summary</p>
        <h1 className="text-2xl font-black text-gray-900 mb-1">Concall Transcript Analysis</h1>
        <p className="text-sm text-gray-500">Paste an earnings call transcript &mdash; get structured insights in 10 seconds.</p>
      </div>

      {/* Tier gate */}
      {tier === "free" && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 mb-6">
          <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">Pro Feature</p>
          <p className="text-sm text-amber-900 mb-3">
            AI concall analysis is a Pro (&#8377;299/mo) feature. Upgrade to extract guidance, financial highlights,
            and Q&amp;A themes from any earnings call.
          </p>
          <Link href="/pricing" className="inline-block bg-amber-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-amber-700 transition">
            See pricing &rarr;
          </Link>
        </div>
      )}

      {!result && (
        <>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1 block">Ticker (optional)</label>
              <input
                type="text"
                placeholder="e.g. RELIANCE"
                value={ticker}
                onChange={e => setTicker(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
              />
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1 block">Quarter</label>
              <input
                type="text"
                placeholder="e.g. Q3 FY26"
                value={quarter}
                onChange={e => setQuarter(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
              />
            </div>
          </div>

          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-bold text-gray-500 uppercase tracking-wider">Transcript</label>
              <div className="flex gap-3 text-xs">
                <button onClick={() => setTranscript(SAMPLE_TRANSCRIPT)} className="text-blue-600 hover:underline font-semibold">
                  Load sample
                </button>
                <label className="text-blue-600 hover:underline font-semibold cursor-pointer">
                  Upload .txt
                  <input type="file" accept=".txt,.pdf" onChange={handleFileUpload} className="hidden" />
                </label>
              </div>
            </div>
            <textarea
              value={transcript}
              onChange={e => setTranscript(e.target.value)}
              placeholder="Paste the full earnings call transcript here. Open the PDF in any viewer, select all (Ctrl+A), copy (Ctrl+C), and paste here..."
              rows={12}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs font-mono bg-white resize-y"
            />
            <p className="text-[10px] text-gray-400 mt-1">{transcript.length.toLocaleString()} characters &middot; minimum 200 required</p>
          </div>

          <button
            onClick={handleAnalyze}
            disabled={loading || tier === "free" || transcript.length < 200}
            className="w-full py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed mb-4"
          >
            {loading ? "Analyzing... (~10s)" : "Analyze Transcript"}
          </button>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          {transcript.length === 0 ? (
            <div className="bg-gray-50 border border-gray-200 rounded-2xl">
              <ConcallEmpty />
            </div>
          ) : (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-5">
              <h3 className="text-sm font-bold text-gray-900 mb-2">How to get a transcript</h3>
              <ol className="text-xs text-gray-600 space-y-1 list-decimal list-inside">
                <li>Visit company&apos;s investor relations page or BSE/NSE filings</li>
                <li>Look for &ldquo;Q3 FY26 Earnings Call Transcript&rdquo; (usually a PDF)</li>
                <li>Open the PDF, select all text (Ctrl+A), copy (Ctrl+C)</li>
                <li>Paste here, click Analyze</li>
              </ol>
            </div>
          )}
        </>
      )}

      {/* Results */}
      {result && (
        <>
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm text-gray-500">
              Analyzed {result.ticker || "stock"} {result.quarter ? `\u2014 ${result.quarter}` : ""}
              {result.cached && <span className="ml-2 text-[10px] bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">cached</span>}
            </p>
            <button onClick={() => { setResult(null); setTranscript("") }} className="text-xs text-blue-600 hover:underline font-semibold">
              Analyze another &rarr;
            </button>
          </div>

          {/* Sentiment Card */}
          <div className={`rounded-2xl border p-5 mb-4 ${sentimentColor(result.sentiment)}`}>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-bold uppercase tracking-wider opacity-70">Tone of the call</p>
              <span className="text-sm font-bold capitalize">{result.sentiment}</span>
            </div>
            <p className="text-sm font-medium leading-relaxed">{result.executive_summary}</p>
            {result.sentiment_rationale && (
              <p className="text-xs italic mt-2 opacity-80">{result.sentiment_rationale}</p>
            )}
          </div>

          {/* Financial Highlights */}
          {result.financial_highlights.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl p-5 mb-4">
              <h2 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 bg-green-500 rounded-full"></span>
                Financial Highlights
              </h2>
              <ul className="space-y-2 text-sm text-gray-800">
                {result.financial_highlights.map((h, i) => (
                  <li key={i} className="flex gap-2"><span className="text-green-600">&bull;</span><span>{h}</span></li>
                ))}
              </ul>
            </div>
          )}

          {/* Forward Guidance */}
          {result.forward_guidance.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl p-5 mb-4">
              <h2 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
                Forward Guidance
              </h2>
              <div className="space-y-3">
                {result.forward_guidance.map((g, i) => (
                  <div key={i} className="border-l-2 border-blue-200 pl-3">
                    <p className="text-xs font-bold text-blue-700 uppercase">{g.topic}</p>
                    <p className="text-sm text-gray-900 mt-0.5">{g.guidance}</p>
                    {g.quote && (
                      <p className="text-xs italic text-gray-500 mt-1">&ldquo;{g.quote}&rdquo;</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Strategic Priorities */}
          {result.strategic_priorities.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl p-5 mb-4">
              <h2 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 bg-purple-500 rounded-full"></span>
                Strategic Priorities
              </h2>
              <ul className="space-y-2 text-sm text-gray-800">
                {result.strategic_priorities.map((p, i) => (
                  <li key={i} className="flex gap-2"><span className="text-purple-600">&bull;</span><span>{p}</span></li>
                ))}
              </ul>
            </div>
          )}

          {/* Q&A Themes */}
          {result.q_and_a_themes.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl p-5 mb-4">
              <h2 className="text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 bg-cyan-500 rounded-full"></span>
                What Analysts Asked About
              </h2>
              <div className="space-y-3">
                {result.q_and_a_themes.map((q, i) => (
                  <div key={i} className="bg-gray-50 rounded-lg p-3">
                    <p className="text-sm font-bold text-gray-900 mb-1">{q.theme}</p>
                    <p className="text-xs text-gray-600">{q.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Concerns Raised */}
          {result.concerns_raised.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 mb-4">
              <h2 className="text-sm font-bold text-amber-900 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 bg-amber-500 rounded-full"></span>
                Concerns Raised
              </h2>
              <ul className="space-y-2 text-sm text-amber-900">
                {result.concerns_raised.map((c, i) => (
                  <li key={i} className="flex gap-2"><span>&bull;</span><span>{c}</span></li>
                ))}
              </ul>
            </div>
          )}

          {/* Disclaimer */}
          <p className="text-[10px] text-gray-400 text-center mt-6">
            AI-generated summary from your transcript. May contain inaccuracies. Verify against the original transcript.
            Not investment advice. YieldIQ is not registered with SEBI.
          </p>
        </>
      )}
    </div>
  )
}

import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import Prism from "@/components/prism/Prism"
import type { PrismData, PillarKey } from "@/components/prism/types"
import { PRISM_PILLAR_ORDER, adaptPrismResponse } from "@/lib/prism"
import ShareBar from "./ShareBar"
import PrismCompareInput from "./PrismCompareInput"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const revalidate = 3600

const PILLAR_LABEL: Record<PillarKey, string> = {
  pulse: "Pulse",
  quality: "Quality",
  moat: "Moat",
  safety: "Safety",
  growth: "Growth",
  value: "Value",
}

const PILLAR_BLURB: Record<PillarKey, string> = {
  pulse:
    "Pulse tracks recent momentum in price, analyst revisions, and news sentiment. Higher means stronger near-term tailwinds.",
  quality:
    "Quality captures profitability, return on capital, and earnings consistency. Higher means a better business.",
  moat:
    "Moat estimates durable competitive advantages — brand, scale, switching costs. Higher means more defensible.",
  safety:
    "Safety looks at balance-sheet strength, leverage, and cash generation. Higher means lower financial risk.",
  growth:
    "Growth reflects revenue and earnings expansion over recent years. Higher means faster compounding.",
  value:
    "Value measures whether the stock is cheap relative to its intrinsic worth. Higher is cheaper.",
}

function withSuffix(t: string): string {
  const up = t.toUpperCase()
  if (up.endsWith(".NS") || up.endsWith(".BO")) return up
  return `${up}.NS`
}

function display(t: string): string {
  return t.toUpperCase().replace(/\.(NS|BO)$/i, "")
}

async function getPrism(ticker: string): Promise<PrismData | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/prism/${encodeURIComponent(withSuffix(ticker))}`,
      { next: { revalidate: 3600 } }
    )
    if (!res.ok) return null
    return adaptPrismResponse(await res.json(), ticker)
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const disp = display(ticker)
  const data = await getPrism(ticker)

  const company = data?.company_name || disp
  const verdict = data?.verdict_label || "6-pillar profile"
  const overall = typeof data?.overall === "number" ? data.overall.toFixed(1) : "\u2014"

  const title = `${company} (${disp}) Prism \u2014 YieldIQ`
  const description = `6-pillar fundamental profile for ${disp}: ${verdict}. Composite score ${overall}/10. Model estimate.`
  const canonical = `https://yieldiq.in/prism/${disp}`
  const ogUrl = `https://yieldiq.in/api/og/prism/${disp}`

  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      title: `${disp} Prism \u2014 YieldIQ`,
      description: verdict,
      url: canonical,
      siteName: "YieldIQ",
      type: "article",
      images: [
        {
          url: ogUrl,
          width: 1200,
          height: 1200,
          alt: `${disp} Prism \u2014 6-pillar profile`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: `${disp} Prism \u2014 YieldIQ`,
      description: verdict,
      images: [ogUrl],
    },
    robots: data ? { index: true, follow: true } : { index: false, follow: true },
  }
}

function scoreClass(s: number): string {
  if (s >= 7) return "text-green-600 border-green-200 bg-green-50"
  if (s >= 4) return "text-amber-600 border-amber-200 bg-amber-50"
  return "text-red-600 border-red-200 bg-red-50"
}

export default async function PrismPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const data = await getPrism(ticker)
  if (!data) notFound()

  const disp = display(data.ticker || ticker)
  const canonical = `https://yieldiq.in/prism/${disp}`
  const ogUrl = `https://yieldiq.in/api/og/prism/${disp}`
  const overall = Math.max(0, Math.min(10, data.overall))

  const pillarByKey = new Map<PillarKey, (typeof data.pillars)[number]>()
  for (const p of data.pillars) pillarByKey.set(p.key, p)

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "FinancialProduct",
    name: `${disp} Prism Profile`,
    description: `6-pillar fundamental profile of ${disp}: ${data.verdict_label}. Model estimate, not advice.`,
    url: canonical,
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
          <span className="text-gray-600 font-medium">{disp} Prism</span>
        </nav>

        {/* Hero */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 sm:p-8 mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
            <div>
              <h1 className="text-3xl sm:text-4xl font-serif font-black text-gray-900">
                {data.company_name}
              </h1>
              <div className="flex items-center gap-3 mt-2">
                <span className="text-sm font-mono text-gray-500">{disp}</span>
                <span className="text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  {data.verdict_label}
                </span>
              </div>
              <p className="text-gray-500 text-sm mt-3">
                A 6-pillar fundamental profile. Each pillar scored 0&ndash;10.
              </p>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-5xl font-black text-blue-600 font-mono tabular-nums">
                  {overall.toFixed(1)}
                </span>
                <span className="text-gray-400 font-medium">/10 composite</span>
              </div>
            </div>
            <div className="flex justify-center">
              <Prism data={data} size={420} defaultMode="signature" />
            </div>
          </div>
        </div>

        {/* Pillar cards */}
        <div className="grid sm:grid-cols-2 gap-4 mb-8">
          {PRISM_PILLAR_ORDER.map((key) => {
            const pillar = pillarByKey.get(key)
            if (!pillar) return null
            const hasScore = typeof pillar.score === "number"
            const score = hasScore ? Math.max(0, Math.min(10, pillar.score as number)) : 0
            const color = hasScore ? scoreClass(score) : "text-gray-600 border-gray-200 bg-gray-50"
            return (
              <div key={key} className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-lg font-bold text-gray-900">{PILLAR_LABEL[key]}</h2>
                  <span className={`text-sm font-bold px-3 py-1 rounded-full border ${color}`}>
                    {hasScore ? score.toFixed(1) : "\u2014"} &middot; {pillar.label}
                  </span>
                </div>
                {pillar.why && (
                  <p className="text-sm text-gray-700 leading-relaxed">{pillar.why}</p>
                )}
                <p className="text-xs text-gray-400 mt-2 leading-relaxed">
                  {PILLAR_BLURB[key]}
                </p>
                {pillar.data_limited && (
                  <p className="text-[11px] text-amber-600 mt-2">
                    Data limited &mdash; score may be incomplete.
                  </p>
                )}
              </div>
            )
          })}
        </div>

        {/* Compare input */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
          <h2 className="text-lg font-bold text-gray-900 mb-1">Compare with another stock</h2>
          <p className="text-xs text-gray-500 mb-4">
            Overlay {disp}'s prism against a peer.
          </p>
          <PrismCompareInput base={disp} />
        </div>

        {/* Share */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
          <h2 className="text-lg font-bold text-gray-900 mb-3">Share this prism</h2>
          <ShareBar ticker={disp} url={canonical} ogUrl={ogUrl} verdictLabel={data.verdict_label} />
        </div>

        {/* CTA — full analysis */}
        <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-8 text-center text-white mb-8">
          <h2 className="text-xl font-bold mb-2">Get the full analysis</h2>
          <p className="text-blue-100 text-sm mb-4">
            Interactive DCF, sensitivity, peer comparison, and AI summary for {disp}.
          </p>
          <Link
            href={`/analysis/${disp}`}
            className="inline-block bg-white text-blue-700 font-bold px-8 py-3 rounded-xl hover:bg-blue-50 transition"
          >
            Full analysis &rarr;
          </Link>
        </div>

        {/* Disclaimer */}
        <p className="text-[10px] text-gray-400 text-center leading-relaxed">
          Model estimate. Not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser or research analyst.
          Past performance does not guarantee future results.
        </p>
      </div>
    </>
  )
}

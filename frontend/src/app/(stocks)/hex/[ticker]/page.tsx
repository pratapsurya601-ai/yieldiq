import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import Hex from "@/components/hex/Hex"
import {
  HEX_AXIS_BLURB,
  HEX_AXIS_ORDER,
  type HexAxisKey,
  type HexResponse,
} from "@/lib/hex"
import HexShareBar from "./HexShareBar"
import HexCompareInput from "./HexCompareInput"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const AXIS_LABEL: Record<HexAxisKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

function withSuffix(t: string): string {
  const up = t.toUpperCase()
  if (up.endsWith(".NS") || up.endsWith(".BO")) return up
  return `${up}.NS`
}

function display(t: string): string {
  return t.toUpperCase().replace(/\.(NS|BO)$/i, "")
}

async function getHex(ticker: string): Promise<HexResponse | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/hex/${encodeURIComponent(withSuffix(ticker))}`,
      { next: { revalidate: 3600 } }
    )
    if (!res.ok) return null
    return (await res.json()) as HexResponse
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ ticker: string }> }
): Promise<Metadata> {
  const { ticker } = await params
  const disp = display(ticker)
  const data = await getHex(ticker)

  const company = disp
  const title = `${company} Hex \u2014 Fundamental + Market Profile | YieldIQ`
  const description = `6-axis health visualization for ${disp}: value, quality, growth, moat, safety, pulse. Model estimate.`
  const canonical = `https://yieldiq.in/hex/${disp}`
  const ogUrl = `https://yieldiq.in/api/og/hex/${disp}`

  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      title,
      description,
      url: canonical,
      siteName: "YieldIQ",
      type: "article",
      images: [
        {
          url: ogUrl,
          width: 1200,
          height: 1200,
          alt: `${disp} Hex \u2014 6-axis profile`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [ogUrl],
    },
    robots: data ? { index: true, follow: true } : { index: false, follow: true },
  }
}

export default async function HexPage(
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const data = await getHex(ticker)
  if (!data) notFound()

  const disp = display(data.ticker || ticker)
  const canonical = `https://yieldiq.in/hex/${disp}`

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "FinancialProduct",
    name: `${disp} Hex Profile`,
    description: `6-axis fundamental and market profile of ${disp}: value, quality, growth, moat, safety, pulse. Model estimate, not advice.`,
    url: canonical,
    provider: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
  }

  const overall = Math.max(0, Math.min(10, data.overall))

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
          <span className="text-gray-600 font-medium">{disp} Hex</span>
        </nav>

        {/* Hero */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 sm:p-8 mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
            <div>
              <h1 className="text-3xl sm:text-4xl font-black text-gray-900">
                {disp} <span className="text-gray-400 font-medium">Hex</span>
              </h1>
              <p className="text-gray-500 text-sm mt-2">
                A 6-axis fundamental and market profile. Each axis scored 0&ndash;10.
              </p>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="text-5xl font-black text-blue-600 font-mono tabular-nums">
                  {overall.toFixed(1)}
                </span>
                <span className="text-gray-400 font-medium">/10 overall</span>
              </div>
            </div>
            <div className="flex justify-center">
              <Hex data={data} size={320} />
            </div>
          </div>
        </div>

        {/* Axis cards */}
        <div className="grid sm:grid-cols-2 gap-4 mb-8">
          {HEX_AXIS_ORDER.map((key) => {
            const axis = data.axes[key]
            const score = Math.max(0, Math.min(10, axis.score))
            const color =
              score >= 7
                ? "text-green-600 border-green-200 bg-green-50"
                : score >= 4
                  ? "text-amber-600 border-amber-200 bg-amber-50"
                  : "text-red-600 border-red-200 bg-red-50"
            return (
              <div key={key} className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-lg font-bold text-gray-900">{AXIS_LABEL[key]}</h2>
                  <span className={`text-sm font-bold px-3 py-1 rounded-full border ${color}`}>
                    {score.toFixed(1)} &middot; {axis.label}
                  </span>
                </div>
                {axis.why && (
                  <p className="text-sm text-gray-700 leading-relaxed">{axis.why}</p>
                )}
                <p className="text-xs text-gray-400 mt-2 leading-relaxed">
                  {HEX_AXIS_BLURB[key]}
                </p>
                {axis.data_limited && (
                  <p className="text-[11px] text-amber-600 mt-2">
                    Data limited &mdash; score may be incomplete.
                  </p>
                )}
              </div>
            )
          })}
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

        {/* Compare input */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
          <h2 className="text-lg font-bold text-gray-900 mb-1">Compare with another stock</h2>
          <p className="text-xs text-gray-500 mb-4">
            Overlay {disp}'s hex against a peer.
          </p>
          <HexCompareInput base={disp} />
        </div>

        {/* Share */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
          <h2 className="text-lg font-bold text-gray-900 mb-3">Share this hex</h2>
          <HexShareBar ticker={disp} url={canonical} />
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
